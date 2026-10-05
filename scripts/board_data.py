"""運用ボード（claude.aiのartifact）に流し込む数字をmetrics/series.jsonlから組み立てる。

使い方:
  PYTHONUTF8=1 .venv/Scripts/python scripts/board_data.py [--out board.json] [--limit 0]
                                    [--r2-gb 30.3 --r2-note "..." --r2-counted "09-21 09:10に一覧して数えた"]

  ログ確認（`gh workflow run render-check.yml` → `git pull`）のあとに回す。書き出したJSONを
  ArtifactDataのsetで `board/metrics` に入れると、ボードの「いまの状況」「推移」「外へ出した要求」が
  そのまま置き換わる（ボード側はscripts/board/index.html。dbが読めないときは作り付けの控えが出る）。

出すもの:
  latest … いちばん新しい点検1回ぶん（タイルの元）
  series … 推移の図の元。窓の長さが違う回は2時間に直す
  out    … 外へ出した要求のホスト別。画像かどうかで色を分ける
  services … 相手ごとの「1日に直すと何回か」（多い日の値）。外部サービスの表の実測列
  r2     … R2の使用量。--r2-gbを渡したときだけ入れる（series.jsonlには無いので手で数える）
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERIES_PATH = ROOT / "metrics" / "series.jsonl"
R2_PATH = ROOT / "metrics" / "r2.jsonl"              # 毎日の掃除（r2_prune.py --append）が書く。種類ごとの内訳つき
R2_HISTORY_PATH = ROOT / "metrics" / "r2_history.jsonl"   # scripts/r2_history.pyがGraphQLから引く合計だけの履歴
STATUS_PATH = ROOT / "scripts" / "board" / "status.json"  # 人が書く欄（やること・外部サービスの状態）
STALE_DAYS = 3      # 人が書く欄をこれより長く見直していなければ警告する

# 推移の図で使う種類のまとめ方。9種類そのままだと帯が細かすぎて読めない
KIND_GROUPS = [
    ("共有", ("共有（本体画像）", "共有（カード用）", "共有（並び）")),
    ("画像キャッシュ", ("imgcache/",)),
    ("アップロード", ("uploads/",)),
    ("その他", ("fonts/", "searchcache/", "listed/", "app/")),
]

FREE_GB = 10.0      # R2の無料枠
PER_GB = 0.015      # 超過1GBあたりの月額（USD）
# 月の見込み（円）。数字の出どころはdocs/ops.md「帯域とR2の操作回数」とボードの「お金」（2026-09-24）
RENDER_INSTANCE_USD = 25.0   # Standardインスタンス
RENDER_FREE_BW_GB = 5.0      # Hobbyプランの込みの帯域（月）
RENDER_BW_PER_GB = 0.15      # 超過1GBあたり（USD）
BW_DAYS = 7                  # 帯域の見込みに使う直近の日数
FX_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=JPY"   # 欧州中央銀行の参照レート（鍵なし）
FX_CACHE = Path(__file__).resolve().parent.parent / "metrics" / "fx.json"   # 取れなかったときの控え

# 画像を取りに行くホスト。ここに当たらないものはAPIへの問い合わせ扱いにする。
IMG_HOST = re.compile(
    r"ytimg|nimg\.jp|sndcdn|bcbits|hdslb|cdn\.otodb|coverartarchive|mzstatic|scdn\.co|i\.scdn"
)

# 「外部サービスの使い方と上限」の表に出す実測。相手ごとにドメインをまとめる（2026-09-21）。
# 以前は表の数字を手で書いていて、いつの値か分からなくなっていた（iTunesの264は
# 14回の点検のうち1回だけ出た値だった）。ここからdbに入れて、表はそれを読む。
# 画像かAPIかは `IMG_HOST` が分ける（cdn.otodb.netとotodb.netのように同じ相手で分かれる）
SERVICE_DOMAINS = {
    "itunes": ("itunes.apple.com", "mzstatic.com"),
    "musicbrainz": ("musicbrainz.org",),
    "coverart": ("coverartarchive.org",),
    "vocadb": ("vocadb.net",),
    "otodb": ("otodb.net",),
    "youtube": ("youtube.com", "ytimg.com", "googleapis.com"),
    "niconico": ("nicovideo.jp", "nimg.jp"),
    "bandcamp": ("bandcamp.com", "bcbits.com"),
    "spotify": ("spotify.com", "scdn.co", "spotifycdn.com"),
    "soundcloud": ("soundcloud.com", "sndcdn.com"),
    "bilibili": ("bilibili.com", "hdslb.com"),
    "discogs": ("discogs.com",),
}


def rows(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out   # まだ1度も書かれていない記録（r2_history.jsonlなど）は空として扱う
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue   # 途中で切れた行は飛ばす（点検が落ちた回に出る）
    return out


def to_2h(value, hours):
    """窓の長さが違う回を2時間に直す。図の点をそろえるため。"""
    if value is None:
        return 0
    h = float(hours or 2) or 2.0
    return value * 2.0 / h


def build(data: list[dict], limit: int) -> dict:
    if not data:
        raise SystemExit("metrics/series.jsonlが空。先に点検を回す")

    last = data[-1]
    series = []
    for r in data[-limit:] if limit else data:
        jst = str(r.get("jst", ""))[5:]            # 年を落として "MM-DD HH:MM"
        req = round(to_2h(r.get("req"), r.get("hours")))
        gb = round(to_2h(r.get("gb"), r.get("hours")), 3)
        series.append([jst, req, gb])

    out_hosts = sorted((last.get("out") or {}).items(), key=lambda kv: -kv[1])
    out = [[host, n, "img" if IMG_HOST.search(host) else "api"] for host, n in out_hosts]

    latest = {
        "jst": last.get("jst"),
        "hours": last.get("hours") or 2,
        "ng": last.get("ng") or 0,
        "fivexx": last.get("fivexx") or 0,
        "rss": last.get("rss"),
        "cpu": last.get("cpu"),
        "mem_mb": last.get("mem_mb"),
        "shares": last.get("shares"),
        "out_total": sum((last.get("out") or {}).values()),
        "client": last.get("client") or {},
        "img": last.get("img") or {},
        "srch": last.get("srch") or {},
    }
    return {"latest": latest, "series": series, "out": out}


def _service_of(host: str) -> str | None:
    """ホスト名から相手を決める。いちばん長く一致したドメインを採る
    （`cdn.otodb.net` は `otodb.net` に、`i.ytimg.com` は `ytimg.com` に当たる）。"""
    h = host.lower()
    best: tuple[str, int] | None = None
    for name, domains in SERVICE_DOMAINS.items():
        for d in domains:
            if (h == d or h.endswith("." + d)) and (best is None or len(d) > best[1]):
                best = (name, len(d))
    return best[0] if best else None


def services(data: list[dict]) -> dict | None:
    """相手ごとの「1日に直すと何回か」。表の実測列に出す。

    **多い日の値（最大）を出す。** 上限を守れているかを見る表なので、平均ではなくピークで比べる。
    `out`（外へ出した要求）は2026-09-20に入った記録なので、それが空の回は数に入れない。
    """
    seen = [r for r in data if r.get("out")]
    if not seen:
        return None
    peak: dict[str, dict[str, float]] = {}
    for r in seen:
        per_day = 24 / float(r.get("hours") or 2)
        here: dict[str, dict[str, float]] = {}
        for host, n in r["out"].items():
            name = _service_of(host)
            if not name:
                continue
            kind = "img" if IMG_HOST.search(host) else "api"
            here.setdefault(name, {"api": 0.0, "img": 0.0})[kind] += n * per_day
        for name, got in here.items():
            cur = peak.setdefault(name, {"api": 0.0, "img": 0.0, "seen": 0})
            cur["api"] = max(cur["api"], got["api"])
            cur["img"] = max(cur["img"], got["img"])
            if got["api"] or got["img"]:
                cur["seen"] += 1
    return {
        "of": len(seen),
        "from": str(seen[0].get("jst", ""))[5:],
        "to": str(seen[-1].get("jst", ""))[5:],
        "peak": {k: {"api": round(v["api"]), "img": round(v["img"]), "seen": int(v["seen"])}
                 for k, v in sorted(peak.items())},
    }


def img_index_max() -> int:
    """`backend/main.py` の `IMAGE_INDEX_MAX` の既定値。

    数字を2か所に書かないため、コードから読む（本番が環境変数で上書きしていれば実際はそちら。
    上書きは今のところしていない）。読めなければ0を返し、呼び出し側がimgcacheの行を出さない。
    """
    try:
        src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        m = re.search(r'IMAGE_INDEX_MAX",\s*"(\d+)"', src)
        return int(m.group(1)) if m else 0
    except OSError:
        return 0


def watch_items(latest: dict) -> list:
    """点検の数字から組み立てる「見ているもの」。**手で書かない**（書いた数字は次の点検で古くなる）。

    それぞれ{t: 見出し, d: 中身, level: "ok" か "watch"}。閾値を越えたものだけwatchにして、
    平常時は黙っている。閾値はここが唯一の置き場所。
    """
    out = []

    # サーバー代の棒（backend/support.py）の月。月が変わったら数字を入れ直す（2026-09-26、利用者の希望）
    sp = ROOT / "backend" / "support.py"
    stext = sp.read_text(encoding="utf-8") if sp.exists() else ""
    mm = re.search(r'^MONTH = "(\d{4}-\d{2})"', stext, re.M)
    if mm:
        from datetime import datetime, timedelta, timezone
        stale = mm.group(1) != datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m")

        def _num(name: str) -> int:
            # 「388 + 104」のような足し算の式もあるので、コメントより前の整数を足す
            m = re.search(rf"^{name} = ([^#\n]*)", stext, re.M)
            return sum(int(x) for x in re.findall(r"\d+", m.group(1))) if m else 0

        cost, got, ppl = _num("COST_JPY"), _num("RECEIVED_JPY"), _num("SUPPORTERS")
        out.append({
            "t": f"サーバー代の棒: {mm.group(1)}は{got:,}円・{ppl}人（見込み{cost:,}円の{got / cost * 100 if cost else 0:.0f}%）"
                 + ("（月が変わった。直す）" if stale else ""),
            "d": "月が変わったらbackend/support.pyのMONTHを進め、COST_JPYをmoney() の見込みに、"
                 "RECEIVED_JPYとSUPPORTERSを0に戻してデプロイする。Bandcamp・PayPalで届いたら、そのつど額と人数を足す",
            "level": "watch" if stale else "ok",
        })

    # 画像キャッシュの索引。上限を超えると索引が打ち切られ、302に戻せなくなる
    imax = img_index_max()
    kinds = (rows(R2_PATH)[-1].get("kinds") if rows(R2_PATH) else None) or {}
    icount = (kinds.get("imgcache/") or [0, 0])[0]
    if imax and icount:
        pct = icount / imax * 100
        out.append({
            "t": f"imgcacheの索引: {icount:,}件（上限{imax:,}の{pct:.0f}%）",
            "d": "上限を超えると索引が打ち切られ、R2にある画像へ302で戻せなくなる。"
                 "増えたら上限を上げるより、索引の期限を絞るほうが先",
            "level": "watch" if pct >= 80 else "ok",
        })

    # フォントが間に合わずサーバー描画へ落ちた数
    ff = (latest.get("client") or {}).get("font_fail", 0)
    out.append({
        "t": f"font_fail: {ff}件 / {latest.get('hours', 2)}時間",
        "d": "フォントを25秒待っても揃わず、ブラウザ描画をあきらめてサーバー描画に落ちた数。"
             "CPUに余裕があるうちは実害が小さいが、増えるなら断片の数か待ち方を見直す",
        "level": "watch" if ff >= 20 else "ok",
    })

    # 検索結果の控え（R2）の当たり率。デプロイでcache.sqlite3が消えたあとの効き目を見る
    for src, label in (("vocadb", "VocaDB"), ("otodb", "otoDB")):
        v = (latest.get("srch") or {}).get(src)
        if not v or len(v) < 3:
            continue
        sq, r2c, net = v[0], v[1], v[2]
        total = sq + r2c + net
        if not total:
            continue
        out.append({
            "t": f"{label}の控えの当たり率: {(sq + r2c) / total * 100:.0f}%（うちR2の控え{r2c}）",
            "d": f"{total}回のうち覚えていた{sq + r2c}・外へ聞いた{net}。"
                 "cache.sqlite3はデプロイで消えるので、R2の控えが効いているかはここで見る",
            "level": "watch" if (sq + r2c) / total < 0.1 else "ok",
        })

    # インスタンスを下げる判断
    rss, mem_limit = latest.get("rss"), 2048
    if rss:
        pct = rss / mem_limit * 100
        out.append({
            "t": f"メモリの使いみち: 最大{rss}MB / {mem_limit}MB（{pct:.0f}%）",
            "d": f"CPUは最大{latest.get('cpu')}（割当1.0）。"
                 + ("上限に近い。下げてはいけない" if pct >= 80 else
                    "余っている。1段下げるなら、下の段のメモリに最大値が収まるかを先に見る"),
            "level": "watch" if pct >= 80 else "ok",
        })

    return out


def storage_series() -> list:
    """R2の使用量の推移。1日1点で [日付, 合計GB, {まとめた種類: GB}またはNone]。

    元が2つある:
      - `metrics/r2_history.jsonl` … GraphQLから引いた**合計だけ**の履歴（過去31日ぶん）
      - `metrics/r2.jsonl` … 毎日の掃除が残す**種類ごとの内訳**（2026-09-21から）
    同じ日に両方あれば内訳のほうを採る（内訳の合計＝合計なので食い違わない）。
    """
    by_date: dict[str, tuple[float, dict | None]] = {}

    for r in rows(R2_HISTORY_PATH):
        d = str(r.get("date", ""))[:10]
        if d:
            by_date[d] = (r.get("bytes", 0) / 1024**3, None)

    for r in rows(R2_PATH):
        d = str(r.get("jst", ""))[:10]
        if not d:
            continue
        kinds = r.get("kinds") or {}
        grouped = {}
        for label, members in KIND_GROUPS:
            b = sum((kinds.get(m) or [0, 0])[1] for m in members)
            if b:
                grouped[label] = round(b / 1024**3, 3)
        by_date[d] = (r.get("total_bytes", 0) / 1024**3, grouped or None)

    return [[d[5:], round(gb, 2), kinds] for d, (gb, kinds) in sorted(by_date.items())]


def usd_jpy() -> dict | None:
    """USD→JPYのレート。取れれば控え（metrics/fx.json）を更新し、取れなければ控えを使う。"""
    import urllib.request
    try:
        req = urllib.request.Request(FX_URL, headers={"User-Agent": "trackmento-board/1.0"})   # UAが無いと403
        with urllib.request.urlopen(req, timeout=10) as r:
            got = json.loads(r.read().decode())
        fx = {"rate": float(got["rates"]["JPY"]), "date": got["date"]}
        FX_CACHE.write_text(json.dumps(fx, ensure_ascii=False) + "\n", encoding="utf-8")
        return fx
    except Exception:
        if FX_CACHE.exists():
            return json.loads(FX_CACHE.read_text(encoding="utf-8"))
        return None


def money(series: list, r2: dict | None) -> dict | None:
    """月の合計の見込み（USDと円）。Renderのインスタンス＋帯域の超過（直近BW_DAYS日の2時間あたりの平均から）＋R2の保存の超過。
    R2の操作回数（Class A/B）は無料枠の中なので0とする。"""
    fx = usd_jpy()
    recent = [r for r in series if r[2] is not None]
    if recent:
        days = sorted({r[0][:5] for r in recent})
        keep = set(days[-BW_DAYS:])
        recent = [r for r in recent if r[0][:5] in keep]
    gb2h = sum(r[2] for r in recent) / len(recent) if recent else 0.0
    bw_gb = gb2h * 12 * 30
    bw_usd = max(0.0, bw_gb - RENDER_FREE_BW_GB) * RENDER_BW_PER_GB
    r2_usd = float((r2 or {}).get("cost") or 0)
    total = RENDER_INSTANCE_USD + bw_usd + r2_usd
    out = {
        "instance_usd": RENDER_INSTANCE_USD, "bw_gb": round(bw_gb, 1), "bw_usd": round(bw_usd, 2),
        "r2_usd": round(r2_usd, 2), "total_usd": round(total, 2), "bw_days": BW_DAYS,
    }
    if fx:
        out.update({"jpy": round(total * fx["rate"]), "rate": fx["rate"], "rate_date": fx["date"]})
    return out


def r2_from_prune() -> dict | None:
    """毎日の掃除が残した `metrics/r2.jsonl` の最後の行から、R2の使用量タイルを組む。

    掃除はどのみちバケット全体を一覧するので、ここに相乗りすれば数え直しにClass Aを足さずに済む。
    ファイルがまだ無いとき（初回）はNoneを返し、呼び出し側が `--r2-gb` で渡す。
    """
    if not R2_PATH.exists():
        return None
    data = rows(R2_PATH)
    if not data:
        return None
    last = data[-1]
    gb = last.get("total_bytes", 0) / 1024**3
    over = max(0.0, gb - FREE_GB)
    kinds = last.get("kinds") or {}
    shares = (kinds.get("共有（並び）") or [0])[0]       # 共有は .jsonを数える（画像は本体とカード用で2倍になる）
    share_gb = sum((kinds.get(k) or [0, 0])[1] for k in ("共有（本体画像）", "共有（カード用）", "共有（並び）")) / 1024**3
    # 掃除で実際に消えた記録。「まだ一度も減っていない」の注記をボードが自分で出し分ける
    applied = [r for r in data if r.get("applied")]
    first_del = next((r.get("jst", "")[:10] for r in applied if r.get("deleted")), None)
    return {
        "gb": round(gb, 1),
        "note": f"無料{FREE_GB:.0f}GB＋ 超過{over:.1f}GB＝ 月${over * PER_GB:.2f}",
        "counted": f"{last.get('jst', '')} JSTの掃除で数えた",
        # 共有の総数。以前は起動時にバケットを1周して「本日の共有」を数えていたが、
        # 全体の上限を使っていないとその数はどこにも使われないので2026-09-21にやめた（Class A 214回／起動）
        "shares": shares,
        "kept_days": 30,
        # 覚え書きの「データの置き場所」と「お金」の欄（以前は手で書いていて古くなった。2026-09-22）
        "share_gb": round(share_gb, 1),
        "img_n": (kinds.get("imgcache/") or [0])[0],
        "img_gb": round((kinds.get("imgcache/") or [0, 0])[1] / 1024**3, 1),
        "search_n": (kinds.get("searchcache/") or [0])[0],
        "cost": round(over * PER_GB, 2),
        "deleted_total": sum(r.get("deleted", 0) for r in applied),
        "first_deleted": first_del,
    }


def shares_series() -> list:
    """1日の共有数。毎日の掃除が残す `shares_by_day`（残っている共有を作られた日ごとに数えたもの）の
    いちばん新しい行から [MM-DD, 件数] を作る。共有は30日残るので、1行で30日ぶんが揃う（2026-09-22）。
    最後の日はその日の途中までなので、呼び出し側（ボード）で断り書きを出す。"""
    for r in reversed(rows(R2_PATH)):
        by_day = r.get("shares_by_day")
        if by_day:
            return [[d[5:], n] for d, n in sorted(by_day.items())]
    return []


# 「文書の置き場所」の表の推定トークン数。字数 × この比で見積もる。
# 2026-09-20に分けたときCLAUDE.mdが17,980字で8.0kと見積もった比（日本語が主なので1字 ≒ 0.44トークン）
TOKENS_PER_CHAR = 8000 / 17980
DOC_FILES = {
    "claude": ("CLAUDE.md",),
    "layout": ("docs/layout.md",),
    "ui": ("docs/ui.md",),
    "ops": ("docs/ops.md",),
    "gotchas": ("docs/gotchas.md",),
    "sources": ("docs/sources.md",),
    "terms": ("docs/services-terms.md",),
    "history": ("docs/history.md",),
    "cli": ("docs/cli.md",),
    "misc": ("docs/share.md", "docs/env.md", "docs/promo.md", "docs/setup.md", "docs/writing.md"),
}
# メモリの索引はリポジトリの外。手元で回したときだけ数える
MEMORY_INDEX = Path.home() / ".claude" / "projects" / "C--Users-amisi-musicgrid-local" / "memory" / "MEMORY.md"


def doc_sizes() -> dict:
    """文書ごとの推定トークン数（千単位）。毎セッション読み込まれる土台＝CLAUDE.md＋ メモリの索引。"""
    def k(paths):
        chars = sum(len(p.read_text(encoding="utf-8")) for p in paths if p.exists())
        return round(chars * TOKENS_PER_CHAR / 1000, 1)
    out = {key: k([ROOT / f for f in files]) for key, files in DOC_FILES.items()}
    if MEMORY_INDEX.exists():
        out["memory"] = k([MEMORY_INDEX])
    out["base"] = round(out["claude"] + out.get("memory", 0), 1)
    return out


def load_status(today) -> tuple[dict, list[str]]:
    """人が書く欄（scripts/board/status.json）を読み、古くなっていそうなものを挙げる。

    点検の記録からは出せない状況（外からの返事・投稿したもの）はここにしか無い。
    2026-09-22に「紹介動画を公開するか」が投稿後も残っていたので、見直した日を持たせて警告する。"""
    from datetime import date
    if not STATUS_PATH.exists():
        return {}, [f"{STATUS_PATH.name}が無い"]
    st = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    warn = []
    def age(d):
        try:
            return (today - date.fromisoformat(d)).days
        except (TypeError, ValueError):
            return 999
    for t in st.get("todos", []):
        if age(t.get("reviewed")) > STALE_DAYS:
            warn.append(f"やること「{t['t']}」: {age(t.get('reviewed'))}日見直していない")
        w = t.get("when") or ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", w) and age(w) >= 0:
            warn.append(f"やること「{t['t']}」: 期限{w}を過ぎた（今日を含む）")
    svc = st.get("services", {})
    if age(svc.get("reviewed")) > STALE_DAYS:
        warn.append(f"外部サービスの状態: {age(svc.get('reviewed'))}日見直していない")
    return {"todos": st.get("todos", []), "services": {k: v for k, v in svc.items() if not k.startswith("_")}}, warn


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="書き出し先。省略すると標準出力")
    ap.add_argument("--limit", type=int, default=0, help="推移に載せる点検の数（0で全部）")
    ap.add_argument("--r2-gb", type=float, help="R2の使用量（GB）。渡したときだけタイルに出る")
    ap.add_argument("--r2-note", default="", help="R2タイルの補足（料金など）")
    ap.add_argument("--r2-counted", default="", help="いつ数えたか（脚注に出る）")
    args = ap.parse_args()

    doc = build(rows(SERIES_PATH), args.limit)
    r2 = r2_from_prune()
    if args.r2_gb is not None:      # 手で渡したほうが強い
        r2 = {"gb": args.r2_gb, "note": args.r2_note, "counted": args.r2_counted}
    if r2:
        doc["r2"] = r2
    storage = storage_series()
    if storage:
        doc["storage"] = storage
    svc = services(rows(SERIES_PATH))
    if svc:
        doc["services"] = svc
    doc["watch"] = watch_items(doc["latest"])
    shares = shares_series()
    if shares:
        doc["shares"] = shares
    doc["docs"] = doc_sizes()
    m = money(doc["series"], doc.get("r2"))
    if m:
        doc["money"] = m
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone(timedelta(hours=9))).date()
    status, warn = load_status(today)
    if status:
        doc["status"] = status

    # 人が書く欄は自動では新しくならない。毎回ここで見直す合図を出す（stderrなので --outなしでもJSONを汚さない）
    import sys
    print(f"[人が書く欄] {STATUS_PATH.relative_to(ROOT)}をメモリの進捗（project-status-tasks-done）と突き合わせる", file=sys.stderr)
    for w in warn:
        print(f"  ! {w}", file=sys.stderr)

    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.out}に書いた（点検{len(doc['series'])}回ぶん、最新{doc['latest']['jst']}）")
    else:
        print(text)


if __name__ == "__main__":
    main()
