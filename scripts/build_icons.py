"""サイトのアイコン画像を作る（frontend/ に書き出す）。

  .venv/Scripts/python scripts/build_icons.py

作るもの:
  frontend/no-cover.png … ジャケットが無い曲のマスに使う 600x600。サイトのアイコン（3x3 の色ブロック）と
                          同じ意匠で、左下だけ粗い市松にして「画像が無い」ことを示す。
                          600px は書き出しのマスの大きさ（render.py / index.html の CELL_PX）。
  frontend/icon-192.png, icon-512.png … ホーム画面に置いたときのアイコン（manifest.webmanifest から指す。
                          2026-09-24、Android の「共有」から URL を受け取る Web Share Target のため）。
                          apple-touch-icon.png（180px）と同じ意匠: 3x3 の色ブロックの間を透明にあけ、左下は 7x7 の市松。

  frontend/bg-mark.png … 背景色の「画像」の既定（2026-09-25、利用者の案）。TRACKMENTO のロゴ（TrackmentoMark 書体＋リソの 6 色の線）を
                          紙の地に互い違いに敷き詰めた 1600x900。まだ画像を選んでいないときに敷く。

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


def app_icon(size: int, block: int, gap: int) -> Image.Image:
    """3 * block + 2 * gap = size。apple-touch-icon.png は block 56・gap 6 で 180"""
    assert 3 * block + 2 * gap == size
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    for r in range(3):
        for col in range(3):
            x, y = col * (block + gap), r * (block + gap)
            fill = BLOCKS[r][col]
            if fill:
                dr.rectangle([x, y, x + block - 1, y + block - 1], fill=fill)
                continue
            dr.rectangle([x, y, x + block - 1, y + block - 1], fill=WHITE)
            edges = [round(block * i / 7) for i in range(8)]
            for rr in range(7):
                for cc in range(7):
                    if (rr + cc) % 2 == 0:
                        dr.rectangle([x + edges[cc], y + edges[rr], x + edges[cc + 1] - 1, y + edges[rr + 1] - 1], fill=INK)
    return im


BAR = ["#E6B731", "#008BC7", "#E5462C", "#AF9EE4", "#80E2B9", "#F594C3"]   # ロゴの下の線（マスタード〜ピンク。index.html の .wordmark .mark）
PAPER = "#F6F5F2"


def bg_mark() -> Image.Image:
    """ロゴ 1 つを描き、1600x900 に互い違いに敷き詰める（index.html の .wordmark .mark と同じ形: 字の下に 6 色の線、線の頭に四角）"""
    from PIL import ImageFont
    font = ImageFont.truetype(str(ROOT / "fonts" / "TrackmentoMark-Bold.ttf"), 64)
    text = "TRACKMENTO"
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    u = 4                                   # 1 目（ロゴの線の太さ・四角の大きさの単位。サイトの 5px に当たる）
    bar_h, gap = 3 * u, 3 * u
    w, h = tw + 7 * u + 2 * u, th + gap + bar_h
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.text((7 * u - bbox[0], -bbox[1]), text, font=font, fill=INK)
    y = th + gap
    d.rectangle([0, y, bar_h - 1, y + bar_h - 1], fill=BAR[0])   # 線の頭の四角
    x0, x1 = 7 * u - u, w
    step = (x1 - x0) / 6
    for i, c in enumerate(BAR):
        d.rectangle([round(x0 + i * step), y, round(x0 + (i + 1) * step) - 1, y + bar_h - 1], fill=c)
    W, H = 1600, 900
    im = Image.new("RGB", (W, H), PAPER)
    gx, gy = w + 90, h + 70
    for r, yy in enumerate(range(-h // 2, H, gy)):
        off = (gx // 2) * (r % 2) - gx // 3
        for xx in range(off, W, gx):
            im.paste(tile, (xx, yy), tile)
    return im


def main() -> int:
    out = ROOT / "frontend" / "bg-mark.png"
    bg_mark().save(out, optimize=True)
    print(f"{out.relative_to(ROOT)} を作りました（{out.stat().st_size / 1024:.1f} KB）")

    for size, block, gap in ((192, 60, 6), (512, 160, 16)):
        out = ROOT / "frontend" / f"icon-{size}.png"
        app_icon(size, block, gap).save(out, optimize=True)
        print(f"{out.relative_to(ROOT)} を作りました（{out.stat().st_size / 1024:.1f} KB）")

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
