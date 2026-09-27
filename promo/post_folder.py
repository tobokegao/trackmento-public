"""Instagram・TikTok に投稿する縦の短い動画を、投稿順に番号を付けて promo/out/post/ に写す。

投稿順は post_order.json（投稿の本文のボードの db `order/main` と同じ並び。ボードを直したらこちらも直す）。
動画は out/tall/<id>-sp.mp4（スマホで撮り直したもの）、無ければ out/tall/<id>.mp4（もとからスマホの sp-*）。

  PYTHONUTF8=1 ../.venv/Scripts/python post_folder.py     # promo/ で実行
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out" / "post"


def main() -> None:
    order = json.loads((HERE / "post_order.json").read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.mp4"):
        f.unlink()
    missing = []
    for n, i in enumerate(order, 1):
        src = next((p for p in (HERE / "out" / "tall" / f"{i}-sp.mp4", HERE / "out" / "tall" / f"{i}.mp4") if p.exists()), None)
        if src is None:
            missing.append(i)
            continue
        shutil.copy(src, OUT / f"{n:02d}-{i}.mp4")
    print(f"{len(order) - len(missing)} 本を out/post に写した" + (f"（動画が無い: {' '.join(missing)}）" if missing else ""))


if __name__ == "__main__":
    main()
