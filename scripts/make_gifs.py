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
# **色数はけちらない**。96 色では中間色が潰れて**全体がくすんで見える**（利用者から 3 回報告）。
# 特に、暗い覆い（モーダルやシートの背景）が写る場面は、そちらに色を取られて紙の色が灰色に寄る。
# GIF は 256 色まで使えるので、200 を既定にして、色の変化そのものが主題の場面はさらに上げる
COLORS = 200
HI_COLOR = {"palette": 240, "touchbar": 240, "sheet": 240, "custom": 224}
NO_DITHER = {"options", "touchbar", "drag"}   # custom は色の帯が段になるのでディザを残す。写真の場面でもディザ無しのほうが 2 割小さい（drag 3.7MB → 3.0MB）
MS = 100
LAST_MS = 900
# **縦に長いものは横幅も落とす**。スマホの画面を丸ごと撮った場面は 720px 幅だと高さが
# 1600px になり、1 本で 4MB を超える（記事に十数本貼るので効いてくる）
MAX_H = 1100


def build(dirpath: pathlib.Path) -> None:
    files = sorted(dirpath.glob("f*.png"))
    if not files:
        return
    with Image.open(files[0]) as probe:
        w0, h0 = probe.size
    width = min(WIDTH, round(w0 * MAX_H / h0)) if h0 * WIDTH / w0 > MAX_H else WIDTH
    frames: list[Image.Image] = []
    for f in files:
        im = Image.open(f).convert("RGB")
        if im.width != width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        # **1 枚目の色で全部を塗る**。コマごとに色を作り直すと、地の色がちらついて見える
        frames.append(im)
    # **色は全コマから作る**。1 枚目だけで作ると、その時点に無い色（ジャケットの色など）が
    # 近い色に潰れ、全体が別の色味になる（茶色い画像になっていた）
    step = max(1, len(frames) // 12)
    sample = frames[::step]
    montage = Image.new("RGB", (frames[0].width, frames[0].height * len(sample)))
    for i, f in enumerate(sample):
        montage.paste(f, (0, frames[0].height * i))
    base = montage.quantize(colors=HI_COLOR.get(dirpath.name, COLORS), method=Image.MEDIANCUT)
    # **カーソルが動く場面はディザを切る**。ディザは同じ場所でも点の並びが揺れるので、
    # コマごとの差分が大きくなって GIF が太る（options が 3.9MB → 下の実測）。
    # 色数を 200 以上にしてあるので、ディザ無しでも階調の段は目立たない
    dither = Image.NONE if dirpath.name in NO_DITHER else Image.FLOYDSTEINBERG
    conv = [f.quantize(palette=base, dither=dither) for f in frames]
    out = ROOT.parent / f"gif-{dirpath.name}.gif"
    durations = [MS] * (len(conv) - 1) + [LAST_MS]
    conv[0].save(out, save_all=True, append_images=conv[1:], duration=durations,
                 loop=0, optimize=True, disposal=2)
    kb = out.stat().st_size / 1024
    print(f"{out.name}  {len(conv)} コマ  {conv[0].width}x{conv[0].height}  {kb:.0f} KB")


for d in sorted(p for p in ROOT.iterdir() if p.is_dir()):
    build(d)
