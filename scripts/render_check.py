"""Render のログ・イベント・メトリクスを API で取り、直近の状態を要約する（定期点検用）。

使い方:
  .venv/Scripts/python scripts/render_check.py [--hours 2] [--strict] [--out summary.md] [--json]

  RENDER_API_KEY（必須）を環境変数か .env から読む。サービスは RENDER_SERVICE_NAME（既定 trackmento）で探す。
  --strict は異常があれば終了コード 2（GitHub Actions で失敗扱いにして通知を出す）。

見るもの:
  - イベント: デプロイ、再起動（server_failed / server_restarted）、停止（service_suspended）
  - ログ: [stats]（経路ごとの件数・5xx）、[health] rss、[error]／Traceback、[loop] lag、[share] budget／quota、共有数の復元
  - メトリクス: 帯域（1 時間ごと）、メモリ・CPU の最大
判定の閾値は環境変数で変えられる（CHECK_BW_GB_PER_HOUR など。下の THRESHOLDS 参照）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://api.render.com/v1"
ROOT = Path(__file__).resolve().parent.parent

THRESHOLDS = {
    "bw_gb_per_hour": float(os.getenv("CHECK_BW_GB_PER_HOUR", "1.0")),   # 1 時間の転送量がこれを超えたら異常
    "rss_mb": float(os.getenv("CHECK_RSS_MB", "400")),                    # [health] rss の最大
    "memory_gb": float(os.getenv("CHECK_MEMORY_GB", "0.45")),             # メトリクスのメモリ最大（インスタンス 512MB）
    "5xx_total": int(os.getenv("CHECK_5XX_TOTAL", "20")),                 # 期間内の 5xx 合計
    "5xx_share": int(os.getenv("CHECK_5XX_SHARE", "5")),                  # /share と /share/upload の 5xx 合計
    "errors": int(os.getenv("CHECK_ERRORS", "10")),                       # [error]／Traceback の行数
    "lag_lines": int(os.getenv("CHECK_LAG_LINES", "10")),                 # [loop] lag の行数
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


def _get(path: str, params: dict | None = None, key: str = "") -> object:
    qs = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
    url = f"{API}{path}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:
                # /logs は 30 回/分。Ratelimit-Reset（UTC 秒）まで待つ。無ければ指数的に待つ
                reset = e.headers.get("Ratelimit-Reset") or e.headers.get("RateLimit-Reset")
                wait = max(1.0, float(reset) - time.time() + 1) if reset and reset.isdigit() else float(e.headers.get("Retry-After") or 5 * (attempt + 1))
                wait = min(wait, 90.0)
                print(f"[warn] 429 {path}: limit={e.headers.get('Ratelimit-Limit')} remaining={e.headers.get('Ratelimit-Remaining')} → {wait:.0f} 秒待つ", file=sys.stderr)
                time.sleep(wait)
                continue
            body = e.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(f"Render API {e.code} {path}: {body}") from e
    raise RuntimeError(f"Render API 429 が続く: {path}")


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jst(s: str) -> str:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M")
    except Exception:
        return s


# ---- 取得 ----

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


LOG_TEXT = ["[stats]*", "[health]*", "[error]*", "[loop]*", "[share]*", "[search]*", "Traceback*", "ERROR:*"]


def fetch_logs(key: str, owner: str, sid: str, start: datetime, end: datetime, max_pages: int = 25) -> list[dict]:
    """古い順に読む（100 行ずつ。hasMore の間 nextStartTime/nextEndTime で続きを取る）。
    /logs は 30 回/分の制限があるので、要約に使う印付きの行だけ text で絞る（トレースバックの本文は取らない）。"""
    out: list[dict] = []
    s, e = _iso(start), _iso(end)
    for _ in range(max_pages):
        page = _get("/logs", {"ownerId": owner, "resource": sid, "startTime": s, "endTime": e, "limit": 100, "direction": "forward", "text": LOG_TEXT}, key)
        out.extend(page.get("logs", []))
        if not page.get("hasMore"):
            break
        s, e = page.get("nextStartTime") or s, page.get("nextEndTime") or e
    return out


def fetch_metric(key: str, kind: str, sid: str, start: datetime, end: datetime, resolution: int, method: str | None = None) -> list[tuple[str, float]]:
    params = {"resource": sid, "startTime": _iso(start), "endTime": _iso(end), "resolutionSeconds": resolution}
    if method:
        params["aggregationMethod"] = method
    try:
        series = _get(f"/metrics/{kind}", params, key)
    except RuntimeError as ex:
        print(f"[warn] metrics/{kind}: {ex}", file=sys.stderr)
        return []
    vals: list[tuple[str, float]] = []
    for ts in series or []:
        for v in ts.get("values", []):
            vals.append((v.get("timestamp", ""), float(v.get("value") or 0)))
    return vals


# ---- ログの読み取り ----

STATS_RE = re.compile(r"(\S+?):(\d+)件/([\d.]+)s/max([\d.]+)s(?:/5xx(\d+))?")
HEALTH_RE = re.compile(r"\[health\] rss=(\d+)MB uptime=(\d+)s")
LAG_RE = re.compile(r"\[loop\] lag=([\d.]+)s")
RESTORE_RE = re.compile(r"本日の共有数を復元: (\d+) 件")


def analyze_logs(logs: list[dict]) -> dict:
    per_path: dict[str, dict] = defaultdict(lambda: {"count": 0, "5xx": 0, "max_s": 0.0, "peak_per_min": 0})
    rss: list[tuple[str, int]] = []
    errors: list[str] = []
    lags: list[float] = []
    budget_lines: list[str] = []
    search_fail = 0
    restored: list[tuple[str, int]] = []
    uptime_resets = 0
    last_uptime = None
    for lg in logs:
        m, ts = lg.get("message", ""), lg.get("timestamp", "")
        if m.startswith("[stats]"):
            for path, cnt, total, mx, e5 in STATS_RE.findall(m):
                p = per_path[path]
                p["count"] += int(cnt)
                p["5xx"] += int(e5 or 0)
                p["max_s"] = max(p["max_s"], float(mx))
                p["peak_per_min"] = max(p["peak_per_min"], int(cnt))
        elif (h := HEALTH_RE.search(m)):
            r, up = int(h.group(1)), int(h.group(2))
            rss.append((ts, r))
            if last_uptime is not None and up < last_uptime:
                uptime_resets += 1
            last_uptime = up
        elif (lm := LAG_RE.search(m)):
            lags.append(float(lm.group(1)))
        elif m.startswith("[error]") or m.startswith("Traceback") or m.startswith("ERROR:"):
            errors.append(f"{_jst(ts)} {m[:160]}")
        elif "[share] budget" in m or "[share] quota" in m:
            budget_lines.append(f"{_jst(ts)} {m[:160]}")
        elif "[search]" in m and "failed" in m:
            search_fail += 1
        elif (rm := RESTORE_RE.search(m)):
            restored.append((ts, int(rm.group(1))))
    return {
        "lines": len(logs),
        "per_path": dict(per_path),
        "rss": rss,
        "errors": errors,
        "lags": lags,
        "budget_lines": budget_lines,
        "search_fail": search_fail,
        "restored": restored,
        "uptime_resets": uptime_resets,
    }


# ---- 要約 ----

def summarize(svc: dict, hours: float, events: list[dict], la: dict, bw: list[tuple[str, float]], mem: list[tuple[str, float]], cpu: list[tuple[str, float]]) -> tuple[str, list[str]]:
    T = THRESHOLDS
    problems: list[str] = []
    lines: list[str] = []
    now_jst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    lines.append(f"## Render 点検: {svc.get('name')}（直近 {hours:g} 時間、{now_jst}）")

    # イベント
    ev_counts: dict[str, int] = defaultdict(int)
    for ev in events:
        ev_counts[ev.get("type", "?")] += 1
    bad_ev = {k: v for k, v in ev_counts.items() if k in ("server_failed", "server_restarted", "server_hardware_failure", "service_suspended")}
    deploys = ev_counts.get("deploy_ended", 0)
    lines.append(f"- イベント: デプロイ {deploys} 回" + (f"、**再起動・障害 {sum(bad_ev.values())} 回**（{', '.join(f'{k} {v}' for k, v in bad_ev.items())}）" if bad_ev else "、再起動・障害なし"))
    if bad_ev:
        problems.append(f"再起動・障害イベント {sum(bad_ev.values())} 回: {', '.join(f'{k} {v}' for k, v in bad_ev.items())}")
    if la["uptime_resets"] > max(deploys, 0):
        problems.append(f"uptime のリセットがデプロイ回数より多い（{la['uptime_resets']} 回 > デプロイ {deploys} 回）→ 想定外の再起動")

    # 帯域（1 時間刻み。値の単位は API の unit に従う。GB/h に換算）
    if bw:
        # Render の bandwidth は bytes を返す（時間帯ごとの合計）
        per_hour = [(ts, v / (1024 ** 3)) for ts, v in bw]
        mx = max(per_hour, key=lambda x: x[1])
        total = sum(v for _, v in per_hour)
        lines.append(f"- 帯域: 合計 {total:.2f} GB、最大 {mx[1]:.2f} GB/時（{_jst(mx[0])}）")
        if mx[1] > T["bw_gb_per_hour"]:
            problems.append(f"帯域 {mx[1]:.2f} GB/時 が閾値 {T['bw_gb_per_hour']} GB/時 を超過（{_jst(mx[0])}）")
    else:
        lines.append("- 帯域: 取得できず")

    # メモリ・CPU
    if mem:
        mmax = max(v for _, v in mem)
        lines.append(f"- メモリ（メトリクス）: 最大 {mmax * 1024:.0f} MB")
        if mmax > T["memory_gb"]:
            problems.append(f"メモリ最大 {mmax * 1024:.0f} MB が閾値 {T['memory_gb'] * 1024:.0f} MB を超過")
    if cpu:
        lines.append(f"- CPU: 最大 {max(v for _, v in cpu):.2f}（0.1 vCPU の割当に対する使用量）")
    if la["rss"]:
        rs = [r for _, r in la["rss"]]
        lines.append(f"- [health] rss: 最小 {min(rs)} / 最大 {max(rs)} / 最新 {rs[-1]} MB（{len(rs)} 点）")
        if max(rs) > T["rss_mb"]:
            problems.append(f"[health] rss 最大 {max(rs)} MB が閾値 {T['rss_mb']:.0f} MB を超過")

    # 経路
    pp = la["per_path"]
    total_5xx = sum(p["5xx"] for p in pp.values())
    share_5xx = sum(p["5xx"] for k, p in pp.items() if k in ("/share", "/share/upload"))
    top = sorted(pp.items(), key=lambda kv: kv[1]["count"], reverse=True)[:8]
    lines.append(f"- 要求（[stats] {la['lines']} 行から集計）: 5xx 合計 {total_5xx}、共有の 5xx {share_5xx}")
    for k, p in top:
        lines.append(f"  - `{k}` {p['count']} 件、最大 {p['max_s']:.1f} 秒、ピーク {p['peak_per_min']} 件/分" + (f"、5xx {p['5xx']}" if p["5xx"] else ""))
    if total_5xx > T["5xx_total"]:
        problems.append(f"5xx 合計 {total_5xx} が閾値 {T['5xx_total']} を超過")
    if share_5xx > T["5xx_share"]:
        problems.append(f"共有の 5xx {share_5xx} が閾値 {T['5xx_share']} を超過")

    # エラー・lag・予算
    lines.append(f"- エラー行: {len(la['errors'])}、[loop] lag: {len(la['lags'])} 行（最大 {max(la['lags']) if la['lags'] else 0:.1f} 秒）、検索失敗: {la['search_fail']}")
    for e in la["errors"][:5]:
        lines.append(f"  - {e}")
    if len(la["errors"]) > T["errors"]:
        problems.append(f"エラー行 {len(la['errors'])} が閾値 {T['errors']} を超過")
    if len(la["lags"]) > T["lag_lines"]:
        problems.append(f"[loop] lag が {len(la['lags'])} 行（閾値 {T['lag_lines']}）")
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
        events = fetch_events(key, sid, start, end)
        logs = fetch_logs(key, owner, sid, start, end)
        la = analyze_logs(logs)
        bw = fetch_metric(key, "bandwidth", sid, start.replace(minute=0, second=0, microsecond=0), end, 3600)
        mem = fetch_metric(key, "memory", sid, start, end, 300, "MAX")
        cpu = fetch_metric(key, "cpu", sid, start, end, 300, "MAX")
        text, problems = summarize(svc, args.hours, events, la, bw, mem, cpu)
    except Exception as ex:   # API 側の失敗も「異常」として要約に残す（点検が黙って止まらないように）
        problems = [f"点検自体が失敗: {type(ex).__name__}: {ex}"]
        text = "\n".join([f"## Render 点検: {name}（直近 {args.hours:g} 時間）", "", "### 判定: **異常あり**", f"- {problems[0]}"])
        la = {"per_path": {}, "rss": []}
        events = []
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({"problems": problems, "per_path": la["per_path"], "rss": la["rss"][-5:], "events": [e.get("type") for e in events]}, ensure_ascii=False))
    return 2 if (problems and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
