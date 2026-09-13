"""サイトのアイコン画像を作る（frontend/ に書き出す）。

  .venv/Scripts/python scripts/build_icons.py

作るもの:
  frontend/no-cover.png … ジャケットが無い曲のマスに使う 600x600。サイトのアイコン（3x3 の色ブロック）と
                          同じ意匠で、左下だけ粗い市松にして「画像が無い」ことを示す。
                          600px は書き出しのマスの大きさ（render.py / index.html の CELL_PX）。

色は frontend/apple-touch-icon.png から取ったもの。意匠を変えるときはここを直して再実行する。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "no-cover.png"
SIZE = 600
CHECKER_N = 4          # 左下の市松の分割数（粗さ）
INK = "#12171B"        # サイトの色トークン --color-ink 相当
PAPER_3 = "#DCDBD7"
WHITE = "#FFFFFF"
# 3x3 の並び。None の位置は市松にする
BLOCKS = [["#E6B731", "#008BC7", "#E5462C"],
          ["#AF9EE4", "#80E2B9", "#F594C3"],
          [None,      PAPER_3,   WHITE]]


def main() -> int:
    im = Image.new("RGB", (SIZE, SIZE), WHITE)
    dr = ImageDraw.Draw(im)
    c = SIZE // 3
    for r in range(3):
        for col in range(3):
            x, y = col * c, r * c
            fill = BLOCKS[r][col]
            if fill:
                dr.rectangle([x, y, x + c - 1, y + c - 1], fill=fill)
                continue
            s = c // CHECKER_N
            dr.rectangle([x, y, x + c - 1, y + c - 1], fill=WHITE)
            for rr in range(CHECKER_N):
                for cc in range(CHECKER_N):
                    if (rr + cc) % 2 == 0:
                        dr.rectangle([x + cc * s, y + rr * s, x + cc * s + s - 1, y + rr * s + s - 1], fill=INK)
    im.save(OUT, optimize=True)
    print(f"{OUT.relative_to(ROOT)} を作りました（{SIZE}x{SIZE}, {OUT.stat().st_size / 1024:.1f} KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
