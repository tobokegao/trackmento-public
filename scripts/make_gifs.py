"""`promo/gif_windows.mjs` が撮ったコマを GIF にまとめる。

    PYTHONUTF8=1 .venv/Scripts/python scripts/make_gifs.py <コマのディレクトリ> [横幅]

note に貼る前提なので、**横 720px・色 96 色**まで落とす（1 本 1〜2MB に収める）。
コマの間隔は 100ms（10 コマ/秒）。最後のコマだけ少し長く止める。
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(sys.argv[1])
WIDTH = int(sys.argv[2]) if len(sys.argv) > 2 else 720
COLORS = 96
MS = 100
LAST_MS = 900


def build(dirpath: pathlib.Path) -> None:
    files = sorted(dirpath.glob("f*.png"))
    if not files:
        return
    frames: list[Image.Image] = []
    for f in files:
        im = Image.open(f).convert("RGB")
        if im.width != WIDTH:
            im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
        # **1 枚目の色で全部を塗る**。コマごとに色を作り直すと、地の色がちらついて見える
        frames.append(im)
    # **色は全コマから作る**。1 枚目だけで作ると、その時点に無い色（ジャケットの色など）が
    # 近い色に潰れ、全体が別の色味になる（茶色い画像になっていた）
    step = max(1, len(frames) // 12)
    sample = frames[::step]
    montage = Image.new("RGB", (frames[0].width, frames[0].height * len(sample)))
    for i, f in enumerate(sample):
        montage.paste(f, (0, frames[0].height * i))
    base = montage.quantize(colors=COLORS, method=Image.MEDIANCUT)
    conv = [f.quantize(palette=base, dither=Image.FLOYDSTEINBERG) for f in frames]
    out = ROOT.parent / f"gif-{dirpath.name}.gif"
    durations = [MS] * (len(conv) - 1) + [LAST_MS]
    conv[0].save(out, save_all=True, append_images=conv[1:], duration=durations,
                 loop=0, optimize=True, disposal=2)
    kb = out.stat().st_size / 1024
    print(f"{out.name}  {len(conv)} コマ  {conv[0].width}x{conv[0].height}  {kb:.0f} KB")


for d in sorted(p for p in ROOT.iterdir() if p.is_dir()):
    build(d)
