"""R2 に何がどれだけ置いてあるかを種類ごとに数える（運用ボードの「R2 の使用量」を直すとき用）。

使い方:
  PYTHONUTF8=1 .venv/Scripts/python scripts/r2_count.py

  `.env` の R2 の鍵を読む。**揃っていないと黙ってローカルの `shares/` を数える**ので、
  出だしの「保存先: r2」を必ず確かめる。読むだけで、消したり書いたりはしない。

数え方:
  共有は 1 件につき 3 つある（`<id>.jpg`／`.png` の本体・`<id>-og.jpg` のカード用・`<id>.json` の並び）。
  件数は `.json` を数える（本体は jpg と png に分かれ、og と混ざるので当てにならない）。

Class A（一覧）を 1,000 件につき 1 回使う。21 万件なら 210 回ほど。数え直すときだけ回す。
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import storage  # noqa: E402

FREE_GB = 10.0          # R2 の無料枠
PER_GB = 0.015          # 超過 1GB あたりの月額（USD）


def bucket_of(key: str) -> str:
    """キー → 数える単位の名前。直下（共有）は役割ごとに分ける。"""
    if "/" in key:
        return key.split("/", 1)[0] + "/"
    if key.endswith("-og.jpg"):
        return "共有（カード用）"
    if key.endswith(".json"):
        return "共有（並び）"
    return "共有（本体画像）"


def main() -> int:
    st = storage.get_storage()
    print(f"保存先: {st.name}")
    if st.name != "r2":
        print("※ R2 を見ていない。.env の R2_* が揃っているか確かめる")

    n: collections.Counter[str] = collections.Counter()
    b: collections.Counter[str] = collections.Counter()
    for key, size, _modified in st.list_objects():
        k = bucket_of(key)
        n[k] += 1
        b[k] += size

    for k in sorted(n, key=lambda x: -b[x]):
        print(f"  {k:<18} {n[k]:>8,} 件  {b[k] / 1024**3:7.3f} GB")

    total_n, total_b = sum(n.values()), sum(b.values())
    gb = total_b / 1024**3
    over = max(0.0, gb - FREE_GB)
    print(f"  {'合計':<18} {total_n:>8,} 件  {gb:7.3f} GB")
    print(f"\n無料 {FREE_GB:.0f}GB ＋ 超過 {over:.1f}GB ＝ 月 ${over * PER_GB:.2f}")
    print(f"共有の件数: {n['共有（並び）']:,}（.json を数えたもの）")
    print("\nボードに入れるなら:")
    print(f'  --r2-gb {gb:.1f} --r2-note "無料 {FREE_GB:.0f}GB ＋ 超過 {over:.1f}GB ＝ 月 ${over * PER_GB:.2f}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
