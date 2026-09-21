"""運用ボード（claude.ai の artifact）に流し込む数字を metrics/series.jsonl から組み立てる。

使い方:
  PYTHONUTF8=1 .venv/Scripts/python scripts/board_data.py [--out board.json] [--limit 0]
                                    [--r2-gb 30.3 --r2-note "..." --r2-counted "09-21 09:10 に一覧して数えた"]

  ログ確認（`gh workflow run render-check.yml` → `git pull`）のあとに回す。書き出した JSON を
  ArtifactData の set で `board/metrics` に入れると、ボードの「いまの状況」「推移」「外へ出した要求」が
  そのまま置き換わる（ボード側は scripts/board/index.html。db が読めないときは作り付けの控えが出る）。

出すもの:
  latest … いちばん新しい点検 1 回ぶん（タイルの元）
  series … 推移の図の元。窓の長さが違う回は 2 時間に直す
  out    … 外へ出した要求のホスト別。画像かどうかで色を分ける
  r2     … R2 の使用量。--r2-gb を渡したときだけ入れる（series.jsonl には無いので手で数える）
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERIES_PATH = ROOT / "metrics" / "series.jsonl"
R2_PATH = ROOT / "metrics" / "r2.jsonl"              # 毎日の掃除（r2_prune.py --append）が書く。種類ごとの内訳つき
R2_HISTORY_PATH = ROOT / "metrics" / "r2_history.jsonl"   # scripts/r2_history.py が GraphQL から引く合計だけの履歴

# 推移の図で使う種類のまとめ方。9 種類そのままだと帯が細かすぎて読めない
KIND_GROUPS = [
    ("共有", ("共有（本体画像）", "共有（カード用）", "共有（並び）")),
    ("画像キャッシュ", ("imgcache/",)),
    ("アップロード", ("uploads/",)),
    ("その他", ("fonts/", "searchcache/", "listed/", "app/")),
]

FREE_GB = 10.0      # R2 の無料枠
PER_GB = 0.015      # 超過 1GB あたりの月額（USD）

# 画像を取りに行くホスト。ここに当たらないものは API への問い合わせ扱いにする。
IMG_HOST = re.compile(
    r"ytimg|nimg\.jp|sndcdn|bcbits|hdslb|cdn\.otodb|coverartarchive|mzstatic|scdn\.co|i\.scdn"
)


def rows(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out   # まだ 1 度も書かれていない記録（r2_history.jsonl など）は空として扱う
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
    """窓の長さが違う回を 2 時間に直す。図の点をそろえるため。"""
    if value is None:
        return 0
    h = float(hours or 2) or 2.0
    return value * 2.0 / h


def build(data: list[dict], limit: int) -> dict:
    if not data:
        raise SystemExit("metrics/series.jsonl が空。先に点検を回す")

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


def img_index_max() -> int:
    """`backend/main.py` の `IMAGE_INDEX_MAX` の既定値。

    数字を 2 か所に書かないため、コードから読む（本番が環境変数で上書きしていれば実際はそちら。
    上書きは今のところしていない）。読めなければ 0 を返し、呼び出し側が imgcache の行を出さない。
    """
    try:
        src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        m = re.search(r'IMAGE_INDEX_MAX",\s*"(\d+)"', src)
        return int(m.group(1)) if m else 0
    except OSError:
        return 0


def watch_items(latest: dict) -> list:
    """点検の数字から組み立てる「見ているもの」。**手で書かない**（書いた数字は次の点検で古くなる）。

    それぞれ {t: 見出し, d: 中身, level: "ok" か "watch"}。閾値を越えたものだけ watch にして、
    平常時は黙っている。閾値はここが唯一の置き場所。
    """
    out = []

    # 画像キャッシュの索引。上限を超えると索引が打ち切られ、302 に戻せなくなる
    imax = img_index_max()
    kinds = (rows(R2_PATH)[-1].get("kinds") if rows(R2_PATH) else None) or {}
    icount = (kinds.get("imgcache/") or [0, 0])[0]
    if imax and icount:
        pct = icount / imax * 100
        out.append({
            "t": f"imgcache の索引: {icount:,} 件（上限 {imax:,} の {pct:.0f}%）",
            "d": "上限を超えると索引が打ち切られ、R2 にある画像へ 302 で戻せなくなる。"
                 "増えたら上限を上げるより、索引の期限を絞るほうが先",
            "level": "watch" if pct >= 80 else "ok",
        })

    # フォントが間に合わずサーバー描画へ落ちた数
    ff = (latest.get("client") or {}).get("font_fail", 0)
    out.append({
        "t": f"font_fail: {ff} 件 / {latest.get('hours', 2)} 時間",
        "d": "フォントを 25 秒待っても揃わず、ブラウザ描画をあきらめてサーバー描画に落ちた数。"
             "CPU に余裕があるうちは実害が小さいが、増えるなら断片の数か待ち方を見直す",
        "level": "watch" if ff >= 20 else "ok",
    })

    # 検索結果の控え（R2）の当たり率。デプロイで cache.sqlite3 が消えたあとの効き目を見る
    for src, label in (("vocadb", "VocaDB"), ("otodb", "otoDB")):
        v = (latest.get("srch") or {}).get(src)
        if not v or len(v) < 3:
            continue
        sq, r2c, net = v[0], v[1], v[2]
        total = sq + r2c + net
        if not total:
            continue
        out.append({
            "t": f"{label} の控えの当たり率: {(sq + r2c) / total * 100:.0f}%（うち R2 の控え {r2c}）",
            "d": f"{total} 回のうち覚えていた {sq + r2c}・外へ聞いた {net}。"
                 "cache.sqlite3 はデプロイで消えるので、R2 の控えが効いているかはここで見る",
            "level": "watch" if (sq + r2c) / total < 0.1 else "ok",
        })

    # インスタンスを下げる判断
    rss, mem_limit = latest.get("rss"), 2048
    if rss:
        pct = rss / mem_limit * 100
        out.append({
            "t": f"メモリの使いみち: 最大 {rss}MB / {mem_limit}MB（{pct:.0f}%）",
            "d": f"CPU は最大 {latest.get('cpu')}（割当 1.0）。"
                 + ("上限に近い。下げてはいけない" if pct >= 80 else
                    "余っている。1 段下げるなら、下の段のメモリに最大値が収まるかを先に見る"),
            "level": "watch" if pct >= 80 else "ok",
        })

    return out


def storage_series() -> list:
    """R2 の使用量の推移。1 日 1 点で [日付, 合計 GB, {まとめた種類: GB} または None]。

    元が 2 つある:
      - `metrics/r2_history.jsonl` … GraphQL から引いた**合計だけ**の履歴（過去 31 日ぶん）
      - `metrics/r2.jsonl` … 毎日の掃除が残す**種類ごとの内訳**（2026-09-21 から）
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


def r2_from_prune() -> dict | None:
    """毎日の掃除が残した `metrics/r2.jsonl` の最後の行から、R2 の使用量タイルを組む。

    掃除はどのみちバケット全体を一覧するので、ここに相乗りすれば数え直しに Class A を足さずに済む。
    ファイルがまだ無いとき（初回）は None を返し、呼び出し側が `--r2-gb` で渡す。
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
    shares = (kinds.get("共有（並び）") or [0])[0]       # 共有は .json を数える（画像は本体とカード用で 2 倍になる）
    return {
        "gb": round(gb, 1),
        "note": f"無料 {FREE_GB:.0f}GB ＋ 超過 {over:.1f}GB ＝ 月 ${over * PER_GB:.2f}",
        "counted": f"{last.get('jst', '')} JST の掃除で数えた",
        # 共有の総数。以前は起動時にバケットを 1 周して「本日の共有」を数えていたが、
        # 全体の上限を使っていないとその数はどこにも使われないので 2026-09-21 にやめた（Class A 214 回／起動）
        "shares": shares,
        "kept_days": 30,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="書き出し先。省略すると標準出力")
    ap.add_argument("--limit", type=int, default=0, help="推移に載せる点検の数（0 で全部）")
    ap.add_argument("--r2-gb", type=float, help="R2 の使用量（GB）。渡したときだけタイルに出る")
    ap.add_argument("--r2-note", default="", help="R2 タイルの補足（料金など）")
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
    doc["watch"] = watch_items(doc["latest"])

    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.out} に書いた（点検 {len(doc['series'])} 回ぶん、最新 {doc['latest']['jst']}）")
    else:
        print(text)


if __name__ == "__main__":
    main()
