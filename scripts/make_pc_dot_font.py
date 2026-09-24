"""PC の操作部品に使う日本語のドット字（Galmuri14 を 2 目下げたもの）を作る。

  python scripts/make_pc_dot_font.py <Galmuri14.ttf>     # fonts/Galmuri14-Down2.ttf を書く

元: Galmuri 2.40.3 の dist/Galmuri14.ttf（https://cdn.jsdelivr.net/npm/galmuri@2.40.3/dist/Galmuri14.ttf、
OFL 1.1・予約名なし、fonts/OFL-Galmuri.txt）。15px で 1 目 = 1px の字（名前は 14 だが升目は 15）。

2026-09-24、利用者が見本で決めた組み合わせ:
- PC だけ操作部品の字を 15px に大きくする。日本語は Galmuri14、英数字は東雲ゴシック 14（fonts/JF-Dot-Shinonome14.ttf を
  size-adjust で 14px に縮めて使う。build_fonts.py の SOURCES）。東雲 14 だけだと はね・はらいが明朝寄りに見え、
  Galmuri14 だけだと英字がプロポーショナルで背が高く浮いて見えた
- 同じ行ではどちらのフォントも同じ基準線に乗るので、CSS では片方だけ上下に動かせない。描いた点で数えると
  （基準線から上へ）Galmuri の漢字は 14〜2 目、東雲の英数字は 10〜1 目で、英数字が沈んで見えた。
  英数字を 2 目上げると上下の余りが 2 目・1 目で釣り合い、さらに「全体を 2 目下げたい」（ラジオの丸・チェックの箱に対して
  字が高い）と言われたので、**英数字は元のまま・日本語だけ 2 目下げる**（同じ見た目になる）
- ハングルは外す（操作部品に出ない。断片の数と R2 への書き込みを減らす）
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools import subset
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fonts" / "Galmuri14-Down2.ttf"
DOTS_DOWN = 2          # 下げる目の数
GRID_PX = 15           # Galmuri14 の升目（1 目 = unitsPerEm / 15）
FAMILY = "TM Dot PC JA"   # 改変版なので元の名前で名乗らない
HANGUL = [(0x1100, 0x11FF), (0x3130, 0x318F), (0xA960, 0xA97F), (0xAC00, 0xD7AF), (0xD7B0, 0xD7FF)]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    font = TTFont(sys.argv[1])
    cps = [cp for cp in font.getBestCmap() if not any(lo <= cp <= hi for lo, hi in HANGUL)]
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    opts.hinting = False
    sub = subset.Subsetter(options=opts)
    sub.populate(unicodes=cps)
    sub.subset(font)

    dy = -round(font["head"].unitsPerEm / GRID_PX * DOTS_DOWN)
    glyphs = font.getGlyphSet()
    glyf = font["glyf"]
    for name in font.getGlyphOrder():
        g = glyf[name]
        if g.isComposite() or g.numberOfContours == 0:
            continue   # 複合グリフは部品が動くので二重に動かさない
        pen = TTGlyphPen(glyphs)
        glyphs[name].draw(TransformPen(pen, (1, 0, 0, 1, 0, dy)))
        glyf[name] = pen.glyph()

    for rec in font["name"].names:
        if rec.nameID in (1, 4, 16):
            rec.string = FAMILY
        elif rec.nameID == 6:
            rec.string = FAMILY.replace(" ", "")
    font.save(OUT)
    print(f"{OUT.relative_to(ROOT)}  {OUT.stat().st_size / 1024:.0f} KB  {len(cps)} 字  {DOTS_DOWN} 目下げ（{dy} units）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
