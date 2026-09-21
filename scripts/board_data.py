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
R2_PATH = ROOT / "metrics" / "r2.jsonl"      # 毎日の掃除（r2_prune.py --append）が書く

FREE_GB = 10.0      # R2 の無料枠
PER_GB = 0.015      # 超過 1GB あたりの月額（USD）

# 画像を取りに行くホスト。ここに当たらないものは API への問い合わせ扱いにする。
IMG_HOST = re.compile(
    r"ytimg|nimg\.jp|sndcdn|bcbits|hdslb|cdn\.otodb|coverartarchive|mzstatic|scdn\.co|i\.scdn"
)


def rows(path: Path) -> list[dict]:
    out = []
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
    }
    return {"latest": latest, "series": series, "out": out}


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
        "counted": f"{last.get('jst', '')} JST の掃除で数えた（共有 {shares:,} 件）",
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

    text = json.dumps(doc, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.out} に書いた（点検 {len(doc['series'])} 回ぶん、最新 {doc['latest']['jst']}）")
    else:
        print(text)


if __name__ == "__main__":
    main()
