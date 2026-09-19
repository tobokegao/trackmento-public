"""サイトのリンクカード（frontend/og.png）のワードマークを、ロゴ用フォント（TrackmentoMark）で描き直す。

    PYTHONUTF8=1 .venv/Scripts/python scripts/build_og.py

og.png の図と説明文は 2026-09-10 に作ったものをそのまま使い、右下のワードマークと下の色帯だけを消して描き直す
（何度回しても同じ絵になる）。位置は元の絵から測った値: 字面の右端 1124px・上端 482px、84px、
色帯は字面から左右に 11px はみ出し、上端 550px・高さ 17px。
ロゴの M を変えたら scripts/build_logo_font.py → これ、の順に回す。
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
OG = ROOT / "frontend" / "og.png"
FONT = ROOT / "fonts" / "TrackmentoMark-Bold.ttf"

PAPER = (246, 245, 243)
INK = (18, 23, 27)
STRIPE = [(230, 183, 49), (0, 139, 199), (229, 70, 44), (175, 158, 228), (128, 226, 185), (245, 148, 195)]

SIZE = 84
RIGHT, TOP = 1124, 482          # 字面の右端・上端
BAND_OVER, BAND_TOP, BAND_H = 11, 550, 17
LEAD_W, LEAD_GAP = 15, 6         # 線の頭に離して置く小さな四角（線の太さの 0.88 倍・すき間 0.35 倍。2026-09-19、利用者が気に入った形）
CLEAR = (340, 460, 1160, 590)    # 消す範囲（図と説明文にはかからない）


def main() -> int:
    im = Image.open(OG).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle(CLEAR, fill=PAPER)
    f = ImageFont.truetype(str(FONT), SIZE)
    # getbbox は送り幅まで含むので、実際に描いた字面で測る
    probe = Image.new("L", (2000, 300), 0)
    ImageDraw.Draw(probe).text((0, 0), "TRACKMENTO", font=f, fill=255)
    x0, y0, x1, y1 = probe.point(lambda v: 255 if v >= 128 else 0).getbbox()
    ox, oy = RIGHT - x1, TOP - y0
    d.text((ox, oy), "TRACKMENTO", font=f, fill=INK)
    left, right = ox + x0 - BAND_OVER, RIGHT + BAND_OVER
    d.rectangle((left - LEAD_GAP - LEAD_W, BAND_TOP, left - LEAD_GAP - 1, BAND_TOP + BAND_H - 1), fill=STRIPE[0])
    w = (right - left) / len(STRIPE)
    for i, c in enumerate(STRIPE):
        d.rectangle((round(left + i * w), BAND_TOP, round(left + (i + 1) * w) - 1, BAND_TOP + BAND_H - 1), fill=c)
    im.save(OG, optimize=True)
    print(f"書き出し: {OG.relative_to(ROOT)}（字面 {ox + x0}〜{RIGHT}px × {oy + y0}〜{oy + y1}px）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
