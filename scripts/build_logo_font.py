"""ロゴ用のフォントを作る。Silkscreen Bold の M だけを描き替えたもの（2026-09-19）。

    PYTHONUTF8=1 .venv/Scripts/python scripts/build_logo_font.py [--variant A|B] [--out fonts/TrackmentoMark-Bold]

Silkscreen Bold の M は中の 2 段が塗りつぶされていて、ロゴでは H に見える（利用者の指摘）。
Micro 5 の M（上に横線・その下に 3 本の脚）の雰囲気に寄せ、線の太さは Silkscreen に合わせて 2 ドットにする。
- A … 脚 3 本とも 2 ドット（幅 8 ドット）
- B … 外の脚 2 ドット・真ん中 1 ドット（幅 7 ドット）
- C … A の右上の角を 1 ドット欠く（小文字の m らしく、H・N とさらに見分けやすい。利用者の提案）

Silkscreen は SIL OFL 1.1（Reserved Font Name なし）。描き替えたものは別名（TrackmentoMark）にして、
元の Silkscreen と取り違えないようにする。ライセンス文は fonts/OFL-Silkscreen.txt をそのまま同梱する。
"""
from __future__ import annotations

import argparse
import pathlib

from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "fonts" / "Silkscreen-Bold.ttf"
PX = 125          # Silkscreen の 1 ドット（unitsPerEm 1000、大文字の高さ 5 ドット）
FAMILY = "TrackmentoMark"

# 上の行が 5 段目（いちばん上）。"#" が塗り
VARIANTS = {
    "A": ["########",
          "##.##.##",
          "##.##.##",
          "##.##.##",
          "##.##.##"],
    "C": ["#######.",
          "##.##.##",
          "##.##.##",
          "##.##.##",
          "##.##.##"],
    "B": ["#######",
          "##.#.##",
          "##.#.##",
          "##.#.##",
          "##.#.##"],
}


def draw_m(rows: list[str]):
    pen = TTGlyphPen(None)
    h = len(rows)
    for r, line in enumerate(rows):
        y0 = (h - 1 - r) * PX
        c = 0
        while c < len(line):
            if line[c] != "#":
                c += 1
                continue
            start = c
            while c < len(line) and line[c] == "#":
                c += 1
            x0, x1 = (start + 1) * PX, (c + 1) * PX   # 左に 1 ドットの余白（ほかの字と同じ）
            # TrueType の外側の輪郭は時計回り
            pen.moveTo((x0, y0))
            pen.lineTo((x0, y0 + PX))
            pen.lineTo((x1, y0 + PX))
            pen.lineTo((x1, y0))
            pen.closePath()
    width = (len(rows[0]) + 2) * PX   # 左右に 1 ドットずつ
    return pen.glyph(), width


def build(variant: str, out: pathlib.Path) -> None:
    f = TTFont(SRC)
    # **小文字の m も同じ形にする**（2026-09-20）。Silkscreen の m は大文字と同じ高さ・同じ形なので、
    # 「trackmento.com」のような小文字の表示でも H に見えていた
    for ch in ("M", "m"):
        gname = f.getBestCmap()[ord(ch)]
        glyph, width = draw_m(VARIANTS[variant])
        f["glyf"][gname] = glyph
        f["hmtx"][gname] = (width, PX)
        f["glyf"][gname].recalcBounds(f["glyf"])
    for rec in f["name"].names:
        if rec.nameID in (1, 4, 16):
            rec.string = FAMILY if rec.nameID != 4 else f"{FAMILY} Bold"
        elif rec.nameID == 6:
            rec.string = f"{FAMILY}-Bold"
        elif rec.nameID == 3:
            rec.string = f"{FAMILY}-Bold;M-{variant}"
    out.parent.mkdir(parents=True, exist_ok=True)
    f.save(out.with_suffix(".ttf"))
    f.flavor = "woff2"
    f.save(out.with_suffix(".woff2"))
    print(f"書き出し: {out.with_suffix('.ttf').name} / .woff2（M = 案 {variant}）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A", choices=sorted(VARIANTS))
    ap.add_argument("--out", default=str(ROOT / "fonts" / "TrackmentoMark-Bold"))
    a = ap.parse_args()
    build(a.variant, pathlib.Path(a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
