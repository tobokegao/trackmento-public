"""`promo/x_clips.mjs` が撮ったコマを、X に載せる 16:9 の MP4 と GIF に組む。

    PYTHONUTF8=1 .venv/Scripts/python scripts/make_x_clips.py <コマのディレクトリ> [id ...] [--no-gif] [--no-mp4]

出力は <コマのディレクトリ>/../x/<id>.mp4 と <id>.gif（1280x720）。

- **地はサイトの地の模様**（撮るときに窓をすべて隠して撮った desk.png を敷き詰める）。
  切り取った窓は真ん中に置く。大きさは画面に収まる範囲で、**2 倍（撮った解像度そのまま）まで**拡大する
- スマホの画面は黒い縁と右下の影を付けて、端末の画面に見せる（OS 9 風の影は真っ黒を右下にずらす）
- MP4 は X に載せる本命（画質がよく軽い）。GIF は note など MP4 を貼れない所向け。
  X の GIF の上限は 15MB なので、超えたら知らせる
- MP4 の書き出しには Remotion に付いてくる ffmpeg を使う（別に入れなくて済む）
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

from PIL import Image, ImageDraw

W, H = 1280, 720
MARGIN = 40          # 窓のまわりに残す地の幅（出力の px）
MAX_SCALE = 2.0      # 1 CSS px を何 px まで大きくするか（撮った解像度が 2 倍なので、それ以上はぼやける）
GRAIN = 6            # 地の粒の間隔（CSS px。body の background-size と同じ）
FPS = 10
LAST_HOLD = 9        # 最後のコマを何コマぶん止めるか（0.9 秒。繰り返し再生の切れ目を見せる）
GIF_COLORS = 200
GIF_LIMIT = 15 * 1024 * 1024
FFMPEG = pathlib.Path("promo/node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe")


def desk(dirpath: pathlib.Path, dpr: float) -> Image.Image:
    """地の模様で 1280x720 を埋める。粒の周期に合わせて切ってから敷き詰める（継ぎ目が出ないように）"""
    src = Image.open(dirpath / "desk.png").convert("RGB")
    one = src.resize((round(src.width / dpr), round(src.height / dpr)), Image.LANCZOS)
    tile = one.crop((0, 0, one.width // GRAIN * GRAIN, one.height // GRAIN * GRAIN))
    out = Image.new("RGB", (W, H))
    for y in range(0, H, tile.height):
        for x in range(0, W, tile.width):
            out.paste(tile, (x, y))
    return out


def compose(dirpath: pathlib.Path) -> list[Image.Image]:
    meta = json.loads((dirpath / "meta.json").read_text(encoding="utf-8"))
    dpr = meta["dpr"]
    files = sorted(dirpath.glob("f*.png"))
    frames = [Image.open(f).convert("RGB") for f in files]
    if meta["full"] and meta["device"] == "pc":
        return [f.resize((W, H), Image.LANCZOS) for f in frames]
    base = desk(dirpath, dpr)
    phone = meta["device"] == "phone"
    # 大きさは**いちばん大きいコマ**で決め、全コマ同じ倍率・同じ左上に置く（窓がコマごとに跳ねないように）
    wc = max(f.width for f in frames) / dpr
    hc = max(f.height for f in frames) / dpr
    border = 3 if phone else 0
    s = min((W - 2 * MARGIN - 2 * border) / wc, (H - 2 * MARGIN - 2 * border) / hc, MAX_SCALE)
    bw, bh = round(wc * s), round(hc * s)
    x0, y0 = (W - bw) // 2, (H - bh) // 2
    out = []
    for f in frames:
        im = base.copy()
        if phone:
            d = ImageDraw.Draw(im)
            d.rectangle((x0 - border + 6, y0 - border + 6, x0 + bw + border + 5, y0 + bh + border + 5), fill=(0, 0, 0))
            d.rectangle((x0 - border, y0 - border, x0 + bw + border - 1, y0 + bh + border - 1), fill=(0, 0, 0))
        im.paste(f.resize((round(f.width / dpr * s), round(f.height / dpr * s)), Image.LANCZOS), (x0, y0))
        out.append(im)
    return out


def write_mp4(frames: list[Image.Image], out: pathlib.Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        seq = frames + [frames[-1]] * LAST_HOLD
        for i, f in enumerate(seq):
            f.save(f"{tmp}/c{i:04d}.png")
        # **30 コマ/秒で書く**（撮ったのは 10 コマ/秒。低いコマ数の動画は受け付けない所があるので、同じコマを重ねて上げる。Remotion の ffmpeg には fps フィルタが無いので -r で）
        subprocess.run([str(FFMPEG), "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", f"{tmp}/c%04d.png",
                        "-vf", "format=yuv420p", "-r", "30", "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                        "-movflags", "+faststart", str(out)], check=True)


def write_gif(frames: list[Image.Image], out: pathlib.Path) -> None:
    # 色は全コマから作る（1 枚目だけだと、途中で出るジャケットの色が潰れる。make_gifs.py と同じ）
    step = max(1, len(frames) // 12)
    sample = frames[::step]
    montage = Image.new("RGB", (W, H * len(sample)))
    for i, f in enumerate(sample):
        montage.paste(f, (0, H * i))
    pal = montage.quantize(colors=GIF_COLORS, method=Image.MEDIANCUT)
    conv = [f.quantize(palette=pal, dither=Image.NONE) for f in frames]
    conv[0].save(out, save_all=True, append_images=conv[1:], duration=[1000 // FPS] * (len(conv) - 1) + [1000 // FPS * (LAST_HOLD + 1)],
                 loop=0, optimize=True, disposal=2)


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    root = pathlib.Path(args[0])
    only = set(args[1:])
    dest = root.parent / "x"
    dest.mkdir(parents=True, exist_ok=True)
    if "--no-mp4" not in flags and not FFMPEG.exists():
        sys.exit(f"ffmpeg が見つからない: {FFMPEG}（promo で npm install を）")
    for d in sorted(p for p in root.iterdir() if (p / "meta.json").exists()):
        if only and d.name not in only:
            continue
        frames = compose(d)
        line = f"{d.name:<24} {len(frames):>3} コマ"
        if "--no-mp4" not in flags:
            mp4 = dest / f"{d.name}.mp4"
            write_mp4(frames, mp4)
            line += f"  mp4 {mp4.stat().st_size / 1024:>6.0f} KB"
        if "--no-gif" not in flags:
            gif = dest / f"{d.name}.gif"
            write_gif(frames, gif)
            size = gif.stat().st_size
            line += f"  gif {size / 1024:>6.0f} KB" + ("  ← X の上限 15MB を超えている" if size > GIF_LIMIT else "")
        print(line)


if __name__ == "__main__":
    main()
