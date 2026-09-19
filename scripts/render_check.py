"""Render のログ・イベント・メトリクスを API で取り、直近の状態を要約する（定期点検用）。

使い方:
  .venv/Scripts/python scripts/render_check.py [--hours 2] [--strict] [--out summary.md] [--json]

  RENDER_API_KEY（必須）を環境変数か .env から読む。サービスは RENDER_SERVICE_NAME（既定 trackmento）で探す。
  --strict は異常があれば終了コード 2（GitHub Actions で失敗扱いにして通知を出す）。

見るもの:
  - イベント: デプロイ、再起動（server_failed / server_restarted）、停止（service_suspended）
  - ログ: [stats]（経路ごとの件数・5xx）、[ua]（経路ごとの UA 種別）、[src]（`?src=` の内訳）、[health] rss、[error]／Traceback、[loop] lag、[share] budget／quota、共有数の復元
  - メトリクス: 帯域（1 時間ごと）、メモリ・CPU の最大
判定の閾値は環境変数で変えられる（CHECK_BW_GB_PER_HOUR など。下の THRESHOLDS 参照）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.render.com/v1"
ROOT = Path(__file__).resolve().parent.parent

# インスタンスの種類 → (vCPU, メモリ MB)。メモリの閾値はここから出すので、種類を変えたら点検も自動で追随する。
# API が返すのは "1c_2g"（1 vCPU / 2GB）のような形式で、これは _PLAN_RE で解く。下は名前で返る分。
PLAN_SPECS = {
    "free": (0.1, 512), "starter": (0.5, 512), "standard": (1.0, 2048),
    "pro": (2.0, 4096), "pro_plus": (4.0, 8192), "pro_max": (4.0, 16384), "pro_ultra": (8.0, 32768),
}
# "1c_2g" / "0_5c_512m" のような形式。c の前が vCPU、その後ろが g(GB) か m(MB)
_PLAN_RE = re.compile(r"^(\d+)(?:_(\d+))?c_(\d+)([gm])$")
_FALLBACK_MEM_MB = 512   # 種類が取れなかったときに使う（いちばん小さい構成に合わせて、見逃すより誤検知する側に倒す）


def spec_of(plan: str) -> tuple[float | None, int]:
    """インスタンスの種類 → (vCPU, メモリ MB)。読めなければ (None, 512)。"""
    if plan in PLAN_SPECS:
        return PLAN_SPECS[plan]
    m = _PLAN_RE.match(plan)
    if not m:
        return None, _FALLBACK_MEM_MB
    cpu = float(f"{m.group(1)}.{m.group(2)}") if m.group(2) else float(m.group(1))
    mem = int(m.group(3)) * (1024 if m.group(4) == "g" else 1)
    return cpu, mem

THRESHOLDS = {
    "bw_gb_per_hour": float(os.getenv("CHECK_BW_GB_PER_HOUR", "1.0")),   # 1 時間の転送量がこれを超えたら異常
    "rss_mb": float(os.getenv("CHECK_RSS_MB", "0")) or 0.0,               # [health] rss の最大。0 なら種類から出す
    "memory_gb": float(os.getenv("CHECK_MEMORY_GB", "0")) or 0.0,         # メトリクスのメモリ最大。0 なら種類から出す
    "5xx_total": int(os.getenv("CHECK_5XX_TOTAL", "20")),                 # 期間内の 5xx 合計
    "5xx_share": int(os.getenv("CHECK_5XX_SHARE", "5")),                  # /share と /share/upload の 5xx 合計
    # /image-proxy の 5xx は**配信元都合**（消えた画像の 404）が大半で、こちらでは直せない。
    # 合計に混ぜると「異常あり」のメールがそればかりになって、直すべきものが埋もれる。
    # 別枠にして、要求のうち何割かで見る（うちのバグで全部 404 になるような壊れ方は拾える）
    "5xx_proxy_ratio": float(os.getenv("CHECK_5XX_PROXY_RATIO", "0.10")),
    "5xx_proxy_min": int(os.getenv("CHECK_5XX_PROXY_MIN", "50")),
    "errors": int(os.getenv("CHECK_ERRORS", "10")),                       # [error]／Traceback の行数
    "lag_lines": int(os.getenv("CHECK_LAG_LINES", "5")),                  # 2 秒以上の [loop] lag の行数（1 秒前後は描画の待ちで普段から出る）
}


def _load_dotenv() -> None:
    p = ROOT / ".env"
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


# Render の API は経路ごとにレート制限がある（`/logs` は 30 回/分。応答の Ratelimit-* に出る）。
# **こちらから間隔を空けて出す**（2026-09-20）。長い窓（`--hours 12`）だとページ数が増えて上限に当たり、
# 点検そのものが「異常あり」で落ちていた。上限に当たってから待つだけでは足りない（下の 429 の扱いも直した）
_RATE_WINDOW = 60.0
_RATE_MAX = 28          # 30 のうち 2 件は余裕として残す
_calls: dict[str, list[float]] = {}


def _pace(path: str) -> None:
    """同じ経路への要求が 1 分に `_RATE_MAX` を超えないように、必要なら待つ"""
    now = time.time()
    hist = [t for t in _calls.get(path, []) if now - t < _RATE_WINDOW]
    if len(hist) >= _RATE_MAX:
        wait = _RATE_WINDOW - (now - hist[0]) + 0.5
        if wait > 0:
            time.sleep(wait)
            now = time.time()
            hist = [t for t in hist if now - t < _RATE_WINDOW]
    hist.append(now)
    _calls[path] = hist


def _get(path: str, params: dict | None = None, key: str = "") -> object:
    qs = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
    url = f"{API}{path}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    _pace(path)
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 7:
                # /logs は 30 回/分。**Ratelimit-Reset は「あと何秒か」で返る**（UTC の時刻ではない。
                # 時刻として読んでいたため `float(reset) - time.time()` が大きな負になり、毎回 1 秒しか
                # 待たずに 6 回とも 429 で落ちていた。2026-09-19 21:14 の点検がこれで「異常あり」になった）。
                # 大きい値なら時刻として解釈する（仕様が変わっても壊れないように）
                reset = e.headers.get("Ratelimit-Reset") or e.headers.get("RateLimit-Reset")
                if reset and reset.isdigit():
                    n = float(reset)
                    wait = n - time.time() + 1 if n > 10 ** 9 else n + 1
                else:
                    wait = float(e.headers.get("Retry-After") or 5 * (attempt + 1))
                wait = min(max(wait, 1.0), 90.0)
                print(f"[warn] 429 {path}: limit={e.headers.get('Ratelimit-Limit')} remaining={e.headers.get('Ratelimit-Remaining')} → {wait:.0f} 秒待つ", file=sys.stderr)
                time.sleep(wait)
                continue
            body = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Render API {e.code} {path}: {body}") from e
    raise RuntimeError(f"Render API 429 が続く: {path}")


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


RESTART_WINDOW_S = 300   # この秒数内に続く uptime の戻りは、同じ入れ替え（新旧の並走）とみなす


def _dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _jst(s: str) -> str:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M")
    except Exception:
        return s


# ---- 取得 ----

def plan_of(svc: dict) -> str:
    """サービスのインスタンス種類（free / starter / standard …）。取れなければ空文字。"""
    d = svc.get("serviceDetails") or {}
    raw = d.get("plan") or svc.get("plan") or ""
    return str(raw).strip().lower().replace(" ", "_").replace("-", "_")


def thresholds_for(plan: str) -> tuple[dict, float | None, int]:
    """インスタンスの種類に合わせた閾値と (vCPU, メモリ MB) を返す。

    メモリ系の閾値は種類から出す（環境変数で指定があればそちら）。Free と Standard では
    上限が 512MB と 2GB で 4 倍違うので、固定値のままだと種類を変えた後に誤検知が続く。
    """
    cpu_alloc, mem_mb = spec_of(plan)
    T = dict(THRESHOLDS)
    T["memory_gb"] = T["memory_gb"] or mem_mb * 0.90 / 1024   # 上限の 90%
    T["rss_mb"] = T["rss_mb"] or mem_mb * 0.78                # 上限の 78%（残りは描画中の一時的な山に充てる）
    return T, cpu_alloc, mem_mb


def find_service(key: str, name: str) -> dict:
    items = _get("/services", {"name": name, "limit": 20}, key)
    svcs = [it["service"] for it in items if it.get("service", {}).get("name") == name]
    if not svcs:
        raise RuntimeError(f"サービス '{name}' が見つかりません（RENDER_SERVICE_NAME を確認）")
    web = [s for s in svcs if s.get("type") == "web_service"]
    return (web or svcs)[0]


def fetch_events(key: str, sid: str, start: datetime, end: datetime) -> list[dict]:
    items = _get(f"/services/{sid}/events", {"startTime": _iso(start), "endTime": _iso(end), "limit": 100}, key)
    return [it["event"] for it in items]


LOG_TEXT = ["[stats]*", "[ua]*", "[src]*", "[ref]*", "[health]*", "[error]*", "[5xx]*", "[loop]*", "[share]*", "[search]*", "[srch]*", "[out]*", "[vocadb]*", "[client]*", "[upload]*", "Traceback*", "ERROR:*"]


# 1 時間あたりに読むページ数の見込み（1 ページ 100 行）。印付きの行は実測で 1 時間 600〜800 行ほど
# （[stats] と [ua] が経路ごとに 60 秒おき、[health] も 60 秒おき）。多めに見積もり、読み切れなければ要約に出す
PAGES_PER_HOUR = 12
MAX_PAGES = 600          # 50 時間ぶん。/logs は 30 回/分なので、これで 20 分ほど


def fetch_logs(key: str, owner: str, sid: str, start: datetime, end: datetime,
               max_pages: int | None = None) -> tuple[list[dict], str | None]:
    """古い順に読む（100 行ずつ。hasMore の間 nextStartTime/nextEndTime で続きを取る）。
    /logs は 30 回/分の制限があるので、要約に使う印付きの行だけ text で絞る（トレースバックの本文は取らない）。
    **ページ数の上限は窓の長さから決める**（2026-09-19）。以前は 25 ページ（2,500 行）固定で、10 時間の点検だと
    窓の前半しか集計していなかった。それでも読み切れなければ、どこまで読んだか（最後の行の時刻）を返す"""
    if max_pages is None:
        hours = (end - start).total_seconds() / 3600
        max_pages = min(MAX_PAGES, max(25, math.ceil(hours * PAGES_PER_HOUR)))
    out: list[dict] = []
    s, e = _iso(start), _iso(end)
    for _ in range(max_pages):
        page = _get("/logs", {"ownerId": owner, "resource": sid, "startTime": s, "endTime": e, "limit": 100, "direction": "forward", "text": LOG_TEXT}, key)
        out.extend(page.get("logs", []))
        if not page.get("hasMore"):
            return out, None
        s, e = page.get("nextStartTime") or s, page.get("nextEndTime") or e
    return out, (out[-1].get("timestamp") if out else s)


def fetch_tracebacks(key: str, owner: str, sid: str, at: list[str], most: int = 3) -> list[tuple[str, list[str]]]:
    """Traceback の本文を取り直す。ふだんは印付きの行だけ text で絞って読むので、本文（`File …` の行や
    例外の名前）が取れず、「Traceback が 5 件」としか分からなかった（2026-09-19）。
    時刻の近いものは 1 つにまとめ、最初の `most` 件だけ、その時刻から 3 秒ぶんを絞らずに読む"""
    out: list[tuple[str, list[str]]] = []
    last = None
    for ts in at:
        t = _dt(ts)
        if t is None or (last is not None and (t - last).total_seconds() < 5):
            continue
        last = t
        try:
            page = _get("/logs", {"ownerId": owner, "resource": sid, "startTime": _iso(t), "endTime": _iso(t + timedelta(seconds=3)),
                                  "limit": 60, "direction": "forward"}, key)
        except RuntimeError as ex:
            out.append((ts, [f"（取れなかった: {ex}）"]))
        else:
            body = [(it.get("message") or "")[:200] for it in page.get("logs", [])]
            body = [b for b in body if not b.startswith(("[stats]", "[ua]", "[health]", "[src]", "[ref]"))]
            # 頭（何の例外か）と尻（例外の名前と中身）だけ残す。間の `File …` の行はライブラリの奥が大半
            out.append((ts, body if len(body) <= 12 else body[:3] + ["…"] + body[-8:]))
        if len(out) >= most:
            break
    return out


def fetch_metric(key: str, kind: str, sid: str, start: datetime, end: datetime, resolution: int, method: str | None = None) -> tuple[str, list[tuple[str, float]]]:
    """(unit, [(timestamp, value), …])。unit は API が返すもの（bytes / MB / GB など。空なら不明）。"""
    params = {"resource": sid, "startTime": _iso(start), "endTime": _iso(end), "resolutionSeconds": resolution}
    if method:
        params["aggregationMethod"] = method
    try:
        series = _get(f"/metrics/{kind}", params, key)
    except RuntimeError as ex:
        print(f"[warn] metrics/{kind}: {ex}", file=sys.stderr)
        return "", []
    unit = ""
    vals: list[tuple[str, float]] = []
    for ts in series or []:
        unit = unit or str(ts.get("unit") or "")
        for v in ts.get("values", []):
            unit = unit or str(v.get("unit") or "")
            vals.append((v.get("timestamp", ""), float(v.get("value") or 0)))
    return unit, vals


def _to_gb(value: float, unit: str) -> float:
    """API の unit を見て GB に直す（bytes / KB / MB / GB / bytes per second など）。不明なら bytes とみなす。"""
    u = (unit or "").lower()
    if u.startswith("gb") or u.startswith("gib"):
        return value
    if u.startswith("mb") or u.startswith("mib"):
        return value / 1024
    if u.startswith("kb") or u.startswith("kib"):
        return value / 1024 ** 2
    return value / 1024 ** 3


# ---- ログの読み取り ----

STATS_RE = re.compile(r"(\S+?):(\d+)件/([\d.]+)s/max([\d.]+)s(?:/5xx(\d+))?(?:/h([\d.]+))?")
# 待ち時間の区切り（秒）。backend/main.py の LAT_BUCKETS と同じ。[stats] と [srch] の `/h` は区切りごとの件数
LAT_BUCKETS = (0.25, 0.5, 1, 2, 5, 10, 20)
ALWAYS_PATHS = ("/share/upload", "/share", "/from-url", "/from-playlist", "/hiccup")
# [srch] vocadb:db3/r2/net5/fail1/max8.0s/h… の 1 ソースぶん（ソースごとの検索。backend/main.py の _srch_stats）
SRCH_RE = re.compile(r"(\S+?):db(\d+)/r2(\d+)/net(\d+)/fail(\d+)/max([\d.]+)s/h([\d.]+)")


def _add_hist(acc: list[int], h: str) -> None:
    for i, n in enumerate(h.split(".")[: len(acc)]):
        acc[i] += int(n or 0)


def _pct(hist: list[int], q: float) -> str:
    """区切りごとの件数から「q の割合がこれ以内」を出す（区切りの上端で答える。「≤ 2 秒」の形）"""
    total = sum(hist)
    if not total:
        return "—"
    run = 0
    for i, n in enumerate(hist):
        run += n
        if run >= total * q:
            return f"≤ {LAT_BUCKETS[i]:g} 秒" if i < len(LAT_BUCKETS) else f"> {LAT_BUCKETS[-1]:g} 秒"
    return "—"
# [ua] /s/*:人=60,プレビュー=80 /image-proxy:人=300 … の 1 経路ぶん
UA_RE = re.compile(r"(\S+?):((?:[^\s=,]+=\d+)(?:,[^\s=,]+=\d+)*)")
HEALTH_RE = re.compile(r"\[health\] rss=(\d+)MB uptime=(\d+)s")
LAG_RE = re.compile(r"\[loop\] lag=([\d.]+)s")
RESTORE_RE = re.compile(r"本日の共有数を復元: (\d+) 件")
# [5xx] <件数> <status> <パス種別> <理由>。HTTPException で返した 5xx の内訳。
# backend/main.py の _log_5xx が理由ごとに数え、_load_monitor が [stats] と同じ 60 秒窓で出す
FIVEXX_RE = re.compile(r"^\[5xx\] (\d+) (\d{3}) (\S+) (.*)$")


def analyze_logs(logs: list[dict]) -> dict:
    per_path: dict[str, dict] = defaultdict(lambda: {"count": 0, "5xx": 0, "max_s": 0.0, "peak_per_min": 0,
                                                     "hist": [0] * (len(LAT_BUCKETS) + 1)})
    per_src: dict[str, dict] = defaultdict(lambda: {"db": 0, "r2": 0, "net": 0, "fail": 0, "max_s": 0.0,
                                                    "hist": [0] * (len(LAT_BUCKETS) + 1)})
    client: Counter[str] = Counter()   # [client] ブラウザ側で起きた失敗の種類 → 件数
    vocadb: Counter[str] = Counter()   # [vocadb] VocaDB へ聞いた回数と、覚えていて聞かずに済んだ回数
    out: Counter[str] = Counter()      # [out] 外へ出した要求のホスト → 件数
    upload = {"n": 0, "recv_max": 0.0, "save_max": 0.0, "cut": 0, "busy": 0, "kb": [],
              "recv_h": [0] * (len(LAT_BUCKETS) + 1)}   # [upload] 共有の送信の内訳
    ua_by_path: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    rss: list[tuple[str, int]] = []
    errors: list[str] = []
    fivexx: dict[str, int] = defaultdict(int)   # "status パス種別 理由" → 件数（省略分を含む）
    lags: list[float] = []
    budget_lines: list[str] = []
    search_fail = 0
    tb_at: list[str] = []    # Traceback の時刻（本文を取り直すため）
    search_fail_by: dict[str, int] = defaultdict(int)   # "ソース 理由" → 件数（省略分を含む）
    restored: list[tuple[str, int]] = []
    uptime_resets = 0        # 入れ替え単位にまとめた回数（判定に使う）
    uptime_reset_lines = 0   # 生の「戻り」行数（並走で膨らむ）
    uptime_reset_at: list[str] = []
    last_reset_at = None
    last_uptime = None
    src_counts: Counter[str] = Counter()
    ref_counts: Counter[str] = Counter()   # Referer のホスト名
    for lg in logs:
        m, ts = lg.get("message", ""), lg.get("timestamp", "")
        if m.startswith("[stats]"):
            for path, cnt, total, mx, e5, h in STATS_RE.findall(m):
                p = per_path[path]
                p["count"] += int(cnt)
                p["5xx"] += int(e5 or 0)
                p["max_s"] = max(p["max_s"], float(mx))
                p["peak_per_min"] = max(p["peak_per_min"], int(cnt))
                if h:
                    _add_hist(p["hist"], h)
        elif m.startswith("[srch]"):
            for src, db, r2, net, fail, mx, h in SRCH_RE.findall(m):
                p = per_src[src]
                for k, v in (("db", db), ("r2", r2), ("net", net), ("fail", fail)):
                    p[k] += int(v)
                p["max_s"] = max(p["max_s"], float(mx))
                _add_hist(p["hist"], h)
        elif m.startswith("[upload]"):
            kv = dict(x.split("=", 1) for x in m[len("[upload]"):].split() if "=" in x)
            upload["n"] += int(kv.get("n", 0))
            upload["recv_max"] = max(upload["recv_max"], float(kv.get("recv_max", "0s").rstrip("s")))
            upload["save_max"] = max(upload["save_max"], float(kv.get("save_max", "0s").rstrip("s")))
            upload["cut"] += int(kv.get("cut", 0))
            upload["busy"] += int(kv.get("busy", 0))
            if kv.get("kb_med"):
                upload["kb"].append(float(kv["kb_med"]))
            if kv.get("recv_h"):
                _add_hist(upload["recv_h"], kv["recv_h"])
        elif m.startswith("[client]"):
            for pair in m[len("[client]"):].split():
                k, _, n = pair.rpartition("=")
                if k and n.isdigit():
                    client[k] += int(n)
        elif m.startswith("[out]"):
            for pair in m[len("[out]"):].split():
                k, _, n = pair.rpartition("=")
                if k and n.isdigit():
                    out[k] += int(n)
        elif m.startswith("[vocadb]"):
            for pair in m[len("[vocadb]"):].split():
                k, _, n = pair.rpartition("=")
                if k and n.isdigit():
                    vocadb[k] += int(n)
        elif m.startswith("[ref]"):
            for pair in m[len("[ref]"):].split():
                k, _, n = pair.rpartition("=")
                if k and n.isdigit():
                    ref_counts[k] += int(n)
        elif m.startswith("[src]"):
            # どこから来たか（`?src=…`）。貼る側が付けた印を数えるだけ
            for pair in m[len("[src]"):].split():
                name, _, n = pair.partition("=")
                if n.isdigit():
                    src_counts[name] += int(n)
        elif m.startswith("[ua]"):
            for path, kinds in UA_RE.findall(m[len("[ua]"):]):
                for pair in kinds.split(","):
                    kind, _, n = pair.partition("=")
                    ua_by_path[path][kind] += int(n)
        elif (h := HEALTH_RE.search(m)):
            r, up = int(h.group(1)), int(h.group(2))
            rss.append((ts, r))
            if last_uptime is not None and up < last_uptime:
                # 入れ替え中は新旧のプロセスが並走し、両方の [health] が交互に出るので
                # 1 回の入れ替えが 2〜3 行の「戻り」として現れる。近い時刻のものは 1 回にまとめる
                t = _dt(ts)
                if last_reset_at is None or t is None or (t - last_reset_at).total_seconds() > RESTART_WINDOW_S:
                    uptime_resets += 1
                    if len(uptime_reset_at) < 8:
                        uptime_reset_at.append(f"{_jst(ts)} {last_uptime}→{up}s")
                uptime_reset_lines += 1
                last_reset_at = t or last_reset_at
            last_uptime = up
        elif (lm := LAG_RE.search(m)):
            lags.append(float(lm.group(1)))
        elif (fm := FIVEXX_RE.match(m)):
            fivexx[f"{fm.group(2)} {fm.group(3)} {fm.group(4)}"] += int(fm.group(1))
        elif m.startswith("[error]") or m.startswith("Traceback") or m.startswith("ERROR:"):
            errors.append(f"{_jst(ts)} {m[:160]}")
            if m.startswith("Traceback"):
                tb_at.append(ts)
        elif "[share] budget" in m or "[share] quota" in m:
            budget_lines.append(f"{_jst(ts)} {m[:160]}")
        elif "[search]" in m and "failed" in m:
            # 「[search] vocadb failed: TimeoutError（ほか 3 件を省略）」。どのソースが何で落ちたかを数える
            sm = re.search(r"\[search\] (\S+) failed: (.*?)(?:（ほか (\d+) 件を省略）)?$", m)
            n = 1 + int(sm.group(3) or 0) if sm else 1
            search_fail += n
            if sm:
                search_fail_by[f"{sm.group(1)} {sm.group(2)[:80]}"] += n
        elif (rm := RESTORE_RE.search(m)):
            restored.append((ts, int(rm.group(1))))
    return {
        "lines": len(logs),
        "per_path": dict(per_path),
        "per_src": dict(per_src),
        "client": dict(client),
        "vocadb": dict(vocadb),
        "out": dict(out),
        "upload": upload,
        "ua_by_path": {k: dict(v) for k, v in ua_by_path.items()},
        "src_counts": dict(src_counts),
        "ref_counts": dict(ref_counts),
        "rss": rss,
        "errors": errors,
        "fivexx": dict(fivexx),
        "lags": lags,
        "budget_lines": budget_lines,
        "search_fail": search_fail,
        "search_fail_by": dict(search_fail_by),
        "tb_at": tb_at,
        "restored": restored,
        "uptime_resets": uptime_resets,
        "uptime_reset_lines": uptime_reset_lines,
        "uptime_reset_at": uptime_reset_at,
    }


# ---- 要約 ----

def summarize(svc: dict, hours: float, events: list[dict], la: dict, bw: tuple[str, list], mem: tuple[str, list], cpu: tuple[str, list]) -> tuple[str, list[str]]:
    plan = plan_of(svc)
    T, cpu_alloc, mem_mb = thresholds_for(plan)
    problems: list[str] = []
    lines: list[str] = []
    now_jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    lines.append(f"## Render 点検: {svc.get('name')}（直近 {hours:g} 時間、{now_jst}）")
    lines.append(f"- インスタンス: {plan or '不明'}"
                 + (f"（{cpu_alloc:g} vCPU / {mem_mb} MB）" if cpu_alloc else f"（種類が読めないので {mem_mb} MB として判定）"))

    # イベント
    ev_counts: dict[str, int] = defaultdict(int)
    for ev in events:
        ev_counts[ev.get("type", "?")] += 1
    bad_ev = {k: v for k, v in ev_counts.items() if k in ("server_failed", "server_restarted", "server_hardware_failure", "service_suspended")}
    deploys = ev_counts.get("deploy_ended", 0)
    lines.append(f"- イベント: デプロイ {deploys} 回（窓の 20 分前から数える）" + (f"、**再起動・障害 {sum(bad_ev.values())} 回**（{', '.join(f'{k} {v}' for k, v in bad_ev.items())}）" if bad_ev else "、再起動・障害なし"))
    if bad_ev:
        problems.append(f"再起動・障害イベント {sum(bad_ev.values())} 回: {', '.join(f'{k} {v}' for k, v in bad_ev.items())}")
    if la["uptime_resets"]:
        detail = "、".join(la["uptime_reset_at"]) + ("…" if la["uptime_resets"] > len(la["uptime_reset_at"]) else "")
        lines.append(f"- [health] uptime のリセット: {la['uptime_resets']} 回"
                     + (f"（戻りの行は {la['uptime_reset_lines']}。入れ替え中の新旧並走を 1 回にまとめた）" if la["uptime_reset_lines"] > la["uptime_resets"] else "")
                     + f": {detail}")
    if la["uptime_resets"] > max(deploys, 0):
        problems.append(f"uptime のリセットがデプロイ回数より多い（{la['uptime_resets']} 回 > デプロイ {deploys} 回）→ 想定外の再起動")

    # 帯域（1 時間刻み。値の単位は API の unit に従って GB/時 に換算）
    bw_unit, bw_vals = bw
    if bw_vals:
        per_hour = [(ts, _to_gb(v, bw_unit)) for ts, v in bw_vals]
        mx = max(per_hour, key=lambda x: x[1])
        total = sum(v for _, v in per_hour)
        lines.append(f"- 帯域: 合計 {total:.2f} GB、最大 {mx[1]:.2f} GB/時（{_jst(mx[0])}、API の単位: {bw_unit or '不明'}）")
        if mx[1] > T["bw_gb_per_hour"]:
            problems.append(f"帯域 {mx[1]:.2f} GB/時 が閾値 {T['bw_gb_per_hour']} GB/時 を超過（{_jst(mx[0])}）")
    else:
        lines.append("- 帯域: 取得できず")

    # メモリ・CPU
    mem_unit, mem_vals = mem
    if mem_vals:
        mmax = _to_gb(max(v for _, v in mem_vals), mem_unit)
        lines.append(f"- メモリ（メトリクス）: 最大 {mmax * 1024:.0f} MB（API の単位: {mem_unit or '不明'}）")
        if mmax > T["memory_gb"]:
            problems.append(f"メモリ最大 {mmax * 1024:.0f} MB が閾値 {T['memory_gb'] * 1024:.0f} MB を超過")
    cpu_unit, cpu_vals = cpu
    if cpu_vals:
        alloc = f"割当は {cpu_alloc} vCPU" if cpu_alloc else "割当は不明"
        lines.append(f"- CPU: 最大 {max(v for _, v in cpu_vals):.3f}（単位: {cpu_unit or '不明'}。{alloc}）")
    if la["rss"]:
        rs = [r for _, r in la["rss"]]
        lines.append(f"- [health] rss: 最小 {min(rs)} / 最大 {max(rs)} / 最新 {rs[-1]} MB（{len(rs)} 点）")
        if max(rs) > T["rss_mb"]:
            problems.append(f"[health] rss 最大 {max(rs)} MB が閾値 {T['rss_mb']:.0f} MB を超過")

    # 経路
    pp = la["per_path"]
    # **`/image-proxy` は合計から外す**（配信元都合の 404 が大半。下で別に見る）
    total_5xx = sum(p["5xx"] for k, p in pp.items() if k != "/image-proxy")
    share_5xx = sum(p["5xx"] for k, p in pp.items() if k in ("/share", "/share/upload"))
    proxy = pp.get("/image-proxy") or {"count": 0, "5xx": 0}
    top = sorted(pp.items(), key=lambda kv: kv[1]["count"], reverse=True)[:8]
    # 件数が少なくても必ず出す経路（共有と URL からの取得。件数順の上位 8 に入らず見落としていた。2026-09-19）
    for k in ALWAYS_PATHS:
        if k in pp and all(k != t for t, _ in top):
            top.append((k, pp[k]))
    if la.get("cut_at"):
        # 読み切れなかったことを黙らない（件数・最大値・5xx はここまでの分しか入っていない）
        lines.append(f"- **ログを読み切れなかった**: {_jst(la['cut_at'])} までの {la['lines']} 行で集計"
                     f"（上限 {MAX_PAGES} ページ。窓を短くするか PAGES_PER_HOUR を見直す）")
    lines.append(f"- 要求（ログ {la['lines']} 行から集計）: 5xx 合計 {total_5xx}"
                 f"（`/image-proxy` を除く）、共有の 5xx {share_5xx}"
                 + (f"、`/image-proxy` の 5xx {proxy['5xx']}／{proxy['count']} 件"
                    f"（{proxy['5xx'] / proxy['count'] * 100:.1f}%）" if proxy["count"] else ""))
    for k, p in top:
        # p50 / p95 は区切りごとの件数から出す（入れる前のログには無いので、その窓では「—」）
        lat = f"、半分が {_pct(p['hist'], 0.5)}・95% が {_pct(p['hist'], 0.95)}" if sum(p["hist"]) else ""
        lines.append(f"  - `{k}` {p['count']} 件、最大 {p['max_s']:.1f} 秒{lat}、ピーク {p['peak_per_min']} 件/分" + (f"、5xx {p['5xx']}" if p["5xx"] else ""))
    fx = la.get("fivexx") or {}
    if fx:
        lines.append("  - 5xx の内訳（[5xx] 行。HTTPException で返したもの）:")
        for k, n in sorted(fx.items(), key=lambda kv: -kv[1])[:6]:
            lines.append(f"    - {n} 件 `{k}`")
    if proxy["count"] and proxy["5xx"] >= T["5xx_proxy_min"] and proxy["5xx"] / proxy["count"] > T["5xx_proxy_ratio"]:
        problems.append(f"`/image-proxy` の 5xx が {proxy['5xx']} 件（要求の "
                        f"{proxy['5xx'] / proxy['count'] * 100:.1f}%）。配信元都合ではなく、"
                        f"こちらの組み立てが壊れている可能性がある")
    if total_5xx > T["5xx_total"]:
        problems.append(f"5xx 合計 {total_5xx} が閾値 {T['5xx_total']} を超過")
    if share_5xx > T["5xx_share"]:
        problems.append(f"共有の 5xx {share_5xx} が閾値 {T['5xx_share']} を超過")

    # User-Agent の内訳（robots.txt で減らせるぶんと、減らしてはいけないぶんを分けて見る）
    ua = la.get("ua_by_path") or {}
    if ua:
        total: dict[str, int] = {}
        for kinds in ua.values():
            for k, n in kinds.items():
                total[k] = total.get(k, 0) + n
        grand = sum(total.values()) or 1
        lines.append("- User-Agent: " + "、".join(
            f"{k} {n} 件（{n * 100 // grand}%）" for k, n in sorted(total.items(), key=lambda kv: -kv[1])))
        for path, kinds in sorted(ua.items(), key=lambda kv: -sum(kv[1].values()))[:5]:
            sub = sum(kinds.values()) or 1
            human = kinds.get("人", 0) + kinds.get("不明", 0)
            lines.append(f"  - `{path}` " + "、".join(
                f"{k} {n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
                + f"（人以外 {(sub - human) * 100 // sub}%）")

    # どこから来たか（`?src=…`）。投稿に貼ったリンクの印を数えるだけで、人は特定しない
    ref = la.get("ref_counts") or {}
    if ref:
        lines.append("- どこから来たか（Referer のホスト）: " + "、".join(
            f"{k} {n} 件" for k, n in sorted(ref.items(), key=lambda kv: -kv[1])[:10]))
    src = la.get("src_counts") or {}
    if src:
        lines.append("- 流入の印（`?src=`）: " + "、".join(
            f"{k} {n} 件" for k, n in sorted(src.items(), key=lambda kv: -kv[1])))

    # エラー・lag・予算
    lines.append(f"- エラー行: {len(la['errors'])}、[loop] lag: {len(la['lags'])} 行（最大 {max(la['lags']) if la['lags'] else 0:.1f} 秒）、検索失敗: {la['search_fail']}")
    for e in la["errors"][:5]:
        lines.append(f"  - {e}")
    for k, n in sorted((la.get("search_fail_by") or {}).items(), key=lambda kv: -kv[1])[:8]:
        lines.append(f"  - 検索失敗 {n} 件 `{k}`")
    # ソースごとの検索（覚えていた / 外へ聞いた / 失敗 と、外へ聞いた時間）
    for src, p in sorted((la.get("per_src") or {}).items(), key=lambda kv: -(kv[1]["db"] + kv[1]["r2"] + kv[1]["net"] + kv[1]["fail"])):
        n = p["db"] + p["r2"] + p["net"] + p["fail"]
        hit = (p["db"] + p["r2"]) / n * 100 if n else 0
        lines.append(f"  - 検索 `{src}` {n} 回: 覚えていた {p['db'] + p['r2']}（うち R2 の控え {p['r2']}、{hit:.0f}%）、"
                     f"外へ {p['net']}、失敗 {p['fail']}。外へ聞いた時間は半分が {_pct(p['hist'], 0.5)}・"
                     f"95% が {_pct(p['hist'], 0.95)}・最大 {p['max_s']:.1f} 秒")
    up = la.get("upload") or {}
    if up.get("n") or up.get("cut") or up.get("busy"):
        kb = sorted(up["kb"])[len(up["kb"]) // 2] if up["kb"] else 0
        lines.append(f"- 共有の送信の内訳: {up['n']} 件。本文の受け取りは半分が {_pct(up['recv_h'], 0.5)}・95% が "
                     f"{_pct(up['recv_h'], 0.95)}・最大 {up['recv_max']:.1f} 秒、検査と保存は最大 {up['save_max']:.1f} 秒、"
                     f"大きさはおよそ {kb:.0f}KB、途中で切れた {up['cut']}、混雑で断った {up['busy']}")
    ob = la.get("out") or {}
    if ob:
        # 外へ出した要求（ホストごと）。各サービスの規約の上限（1 分・1 日）と見比べるための数字
        rows = sorted(ob.items(), key=lambda kv: -kv[1])
        lines.append(f"- 外へ出した要求: 合計 {sum(ob.values())} 件（1 日に直すと約 {sum(ob.values()) / max(hours, 0.01) * 24:,.0f}）")
        for h, n in rows[:12]:
            lines.append(f"  - `{h}` {n} 件（1 日約 {n / max(hours, 0.01) * 24:,.0f}、1 分あたり平均 {n / max(hours * 60, 0.01):.1f}）")
    vd = la.get("vocadb") or {}
    if vd:
        # VocaDB へ聞いた回数（種類ごと）。「1 日数千件には事前の許可が要る」とされているので、窓の長さから 1 日に直して出す
        net = sum(n for k, n in vd.items() if k in ("search", "pv", "title"))
        kept = sum(n for k, n in vd.items() if k.endswith(("_mem", "_r2")))
        per_day = net / max(hours, 0.01) * 24
        lines.append(f"- VocaDB へ聞いた回数: {net}（1 日に直すと約 {per_day:.0f}）。覚えていて聞かずに済んだ {kept}。"
                     + "内訳 " + "、".join(f"`{k}` {n}" for k, n in sorted(vd.items(), key=lambda kv: -kv[1])))
    cl = la.get("client") or {}
    if cl:
        # ブラウザ側で起きた失敗（画面が /hiccup に送る種類と回数）。サーバーのログには他に何も残らない
        lines.append("- ブラウザ側の失敗: " + "、".join(f"`{k}` {n}" for k, n in sorted(cl.items(), key=lambda kv: -kv[1])))
    for at, body in (la.get("tb_body") or [])[:3]:
        lines.append(f"  - Traceback の本文（{_jst(at)}）:")
        lines.append("    ```")
        lines.extend(f"    {b}" for b in body)
        lines.append("    ```")
    if len(la["errors"]) > T["errors"]:
        problems.append(f"エラー行 {len(la['errors'])} が閾値 {T['errors']} を超過")
    slow = [l for l in la["lags"] if l >= 2.0]
    if len(slow) > T["lag_lines"]:
        problems.append(f"[loop] lag 2 秒以上が {len(slow)} 行（閾値 {T['lag_lines']}、最大 {max(slow):.1f} 秒）→ イベントループの停止（ヘルスチェック落ちの前兆）")
    if la["budget_lines"]:
        problems.append(f"[share] budget／quota が {len(la['budget_lines'])} 行（容量上限か回数上限に到達）")
        for b in la["budget_lines"][:3]:
            lines.append(f"  - {b}")
    if la["restored"]:
        ts, n = la["restored"][-1]
        lines.append(f"- 本日の共有数（最後の復元値）: {n} 件（{_jst(ts)}）")

    lines.append("")
    lines.append("### 判定: " + ("**異常あり**" if problems else "正常"))
    for p in problems:
        lines.append(f"- {p}")
    return "\n".join(lines), problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours", type=float, default=2.0, help="さかのぼる時間（既定 2）")
    ap.add_argument("--strict", action="store_true", help="異常があれば終了コード 2")
    ap.add_argument("--out", help="要約（Markdown）を書き出すファイル")
    ap.add_argument("--json", action="store_true", help="集計結果を JSON でも標準出力に出す")
    args = ap.parse_args()

    _load_dotenv()
    key = os.getenv("RENDER_API_KEY", "").strip()
    if not key:
        print("RENDER_API_KEY がありません（.env か環境変数に設定）", file=sys.stderr)
        return 1
    name = os.getenv("RENDER_SERVICE_NAME", "trackmento").strip()

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=args.hours)
    try:
        svc = find_service(key, name)
        sid, owner = svc["id"], svc["ownerId"]
        # **イベントは窓の 20 分前から取る**。デプロイの直後にプロセスが入れ替わるので、
        # 窓の開始直前に終わったデプロイだと「uptime のリセットはあるのにデプロイが無い」ことになり、
        # 想定外の再起動として誤検知する（2026-09-14 23:30 の点検で実際に出た）
        events = fetch_events(key, sid, start - timedelta(minutes=20), end)
        logs, cut_at = fetch_logs(key, owner, sid, start, end)
        la = analyze_logs(logs)
        la["cut_at"] = cut_at
        la["tb_body"] = fetch_tracebacks(key, owner, sid, la.get("tb_at") or [])
        bw = fetch_metric(key, "bandwidth", sid, start.replace(minute=0, second=0, microsecond=0), end, 3600)
        mem = fetch_metric(key, "memory", sid, start, end, 300, "MAX")
        cpu = fetch_metric(key, "cpu", sid, start, end, 300, "MAX")
        text, problems = summarize(svc, args.hours, events, la, bw, mem, cpu)
    except Exception as ex:   # API 側の失敗も「異常」として要約に残す（点検が黙って止まらないように）
        problems = [f"点検自体が失敗: {type(ex).__name__}: {ex}"]
        text = "\n".join([f"## Render 点検: {name}（直近 {args.hours:g} 時間）", "", "### 判定: **異常あり**", f"- {problems[0]}"])
        la = {"per_path": {}, "rss": []}
        events = []
        bw = mem = cpu = ("", [])
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({"problems": problems, "per_path": la["per_path"], "rss": la["rss"][-5:], "events": [e.get("type") for e in events]}, ensure_ascii=False))
    return 2 if (problems and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
