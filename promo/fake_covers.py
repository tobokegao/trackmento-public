"""X 向けの短い動画（promo/x_clips.mjs）で使う、架空のジャケットと曲名を作る。

    PYTHONUTF8=1 .venv/Scripts/python promo/fake_covers.py

**動画に実在のジャケットを映さない**ため（2026-09-25、利用者の指定「サムネの画像は全て架空の絵に」）。
- 正方形のジャケット 24 枚と、動画サイトのサムネ風の 16:9 を 12 枚、図形と色だけで描く
  （色で並べ替えが映えるよう色相を散らし、白黒も 3 枚混ぜる）
- 絵は手元の `uploads/`（git の外）に置く。サーバーは R2 に無いアップロード画像を手元から読むので、
  **本番の R2 には上げない**（uploads.read_bytes の手元への逃げ道）。名前は uploads の形（16 進 16 桁）で、頭を fa4e にしてある
- 白黒のジャケット 16 枚（明るさを段階的に。色で並べ替えの場面用）
- 曲の一覧は `promo/public/fake-tracks.json`・`fake-tracks-wide.json`・`fake-tracks-mono.json`（x_clips.mjs と台本が読む）
- 背景の画像の場面の見本 `promo/public/x-bg-sample.jpg`（メッシュグラデーション）も作る
何度回しても同じ絵になる（乱数の種を固定）。
"""
from __future__ import annotations

import colorsys
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads"
OUT = ROOT / "promo" / "public"
FONT = ROOT / "fonts" / "IBMPlexSansJP-Bold.ttf"

SQUARE = [
    ("夜明けのシグナル", "ミナトリ"), ("ガラスの海辺", "Kaede Loop"), ("三月の電波塔", "ねむり工房"),
    ("ソーダ水の惑星", "ハルノ"), ("迷子の自販機", "トタン楽団"), ("Night Parade", "moca//"),
    ("白い坂道", "ユキミ"), ("はんぶんこの月", "こもれび通信"), ("Paper Rocket", "Tsubame"),
    ("ひまわり配達人", "サンカク"), ("雨宿りのワルツ", "しずく堂"), ("Lemon Circuit", "8bit Garden"),
    ("深海ラジオ", "アオイロ"), ("すずらん通り", "ポロン"), ("Violet Hour", "Nagi"),
    ("朝焼けエスカレーター", "カラクリ座"), ("ミントの約束", "ふたば"), ("Orange Tape", "Hiro Sato"),
    ("星座のない夜", "ルル"), ("こはく色の街", "ユウグレ"), ("Blue Envelope", "Akane"),
    ("ねこじゃらし", "まるいち"), ("灰色のキャンバス", "モノクロ舎"), ("Snow Signal", "Kuro"),
]
# 白黒のジャケット（明るさを段階的に変える）。色で並べ替えの場面で、明るい順に並ぶのを見せる
# （カラフルな絵だと色相の順は伝わりにくい、と利用者。白黒のジャケットは明るい順に並ぶ決まり）
MONO = [
    ("影のワルツ", "ヨル"), ("炭の街", "スミ"), ("鉄の鳥", "Grey Harbor"), ("雨の音階", "しとしと"),
    ("鉛筆の夢", "エンピツ"), ("霧の駅", "Mist"), ("石畳", "カタコト"), ("曇り空", "くもり堂"),
    ("銀の鈴", "Silver"), ("雪明かり", "ユキノ"), ("白いノート", "Paper"), ("朝もや", "アサギ"),
    ("月の砂", "Luna"), ("紙飛行機", "カミ"), ("まっしろ", "しろくま"), ("光の粒", "Hikari"),
]
WIDE = [
    ("踊ってみた【夏まつり】", "こはる"), ("ピアノで弾いてみた", "ゆびさき"), ("自作シンセで1曲", "ラボ32"),
    ("ゲーム実況 #12", "たぬき"), ("散歩しながら作曲", "ふらっと"), ("歌ってみた【春】", "みずほ"),
    ("音MAD：夜の商店街", "カセット"), ("ドラム叩いてみた", "リズム堂"), ("作業用BGM 1時間", "ねこまち"),
    ("MV：空の手紙", "ソラノ"), ("ライブ映像【初ワンマン】", "トビウオ"), ("絵を描きながら歌う", "えのぐ"),
]


def palette(i: int, n: int, rng: random.Random) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """色相を n 等分して i 番目の色の組（地・図形・文字）。最後の 3 つは白黒"""
    if i >= n - 3:
        v = [0.12, 0.55, 0.93][i - (n - 3)]
        g = int(v * 255)
        fg = 255 - g if abs(g - 128) > 40 else 20
        return (g, g, g), (fg, fg, fg), (fg, fg, fg)
    h = (i / (n - 3) + rng.uniform(-0.02, 0.02)) % 1.0
    bg = tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, rng.uniform(0.55, 0.85), rng.uniform(0.75, 0.95)))
    fg = tuple(int(c * 255) for c in colorsys.hsv_to_rgb((h + rng.choice([0.08, 0.5, -0.08])) % 1, rng.uniform(0.4, 0.9), rng.uniform(0.3, 1.0)))
    ink = (20, 20, 24) if sum(bg) > 420 else (250, 248, 240)
    return bg, fg, ink


def draw_art(w: int, h: int, bg, fg, style: int, rng: random.Random) -> Image.Image:
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    s = min(w, h)
    if style == 0:      # 同心円
        cx, cy = rng.uniform(0.3, 0.7) * w, rng.uniform(0.3, 0.6) * h
        for k, r in enumerate(range(int(s * 0.55), 0, -int(s * 0.07))):
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fg if k % 2 == 0 else bg)
    elif style == 1:    # 斜めの縞
        step = int(s * rng.uniform(0.08, 0.14))
        for x in range(-h, w + h, step * 2):
            d.polygon([(x, 0), (x + step, 0), (x + step - h, h), (x - h, h)], fill=fg)
    elif style == 2:    # 升目
        n = rng.choice([3, 4, 5])
        cw, ch = w / n, h / n
        for r in range(n):
            for c in range(n):
                if rng.random() < 0.45:
                    d.rectangle((c * cw + 4, r * ch + 4, (c + 1) * cw - 4, (r + 1) * ch - 4), fill=fg)
    elif style == 3:    # 大きな三角と円
        d.polygon([(0, h), (w * rng.uniform(0.3, 0.7), h * 0.15), (w, h)], fill=fg)
        r = s * 0.16
        cx, cy = w * rng.uniform(0.2, 0.8), h * 0.25
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(min(255, c + 60) for c in bg))
    else:               # 横の帯
        y = 0
        while y < h:
            bh = int(h * rng.uniform(0.05, 0.16))
            if rng.random() < 0.5:
                d.rectangle((0, y, w, y + bh), fill=fg)
            y += bh
    return im


def label(im: Image.Image, title: str, ink, bg) -> None:
    """題を左下に小さく入れる（ジャケットらしく見せる。架空の題）。縞の上でも読めるよう、後ろに地の色の帯を敷く"""
    d = ImageDraw.Draw(im)
    size = max(14, int(min(im.size) * 0.075))
    f = ImageFont.truetype(str(FONT), size)
    pad = int(min(im.size) * 0.06)
    x0, y0, x1, y1 = d.textbbox((pad, im.height - pad), title, font=f, anchor="ls")
    m = int(size * 0.35)
    d.rectangle((x0 - m, y0 - m, x1 + m, y1 + m), fill=bg)
    d.text((pad, im.height - pad), title, font=f, fill=ink, anchor="ls")


def _srgb_to_oklab(rgb):
    """sRGB（0〜1）→ OKLab。色を混ぜるのはこの空間で行う（sRGB のまま混ぜると、境目が灰色に濁る）"""
    import numpy as np
    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566], [0.0883024619, 0.2817188376, 0.6299787005]])
    lms = np.cbrt(c @ m1.T)
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099], [0.0259040371, 0.7827717662, -0.8086757660]])
    return lms @ m2.T


def _oklab_to_srgb(lab):
    import numpy as np
    m2i = np.array([[1.0, 0.3963377774, 0.2158037573], [1.0, -0.1055613458, -0.0638541728], [1.0, -0.0894841775, -1.2914855480]])
    lms = (lab @ m2i.T) ** 3
    m1i = np.array([[4.0767416621, -3.3077115913, 0.2309699292], [-1.2684380046, 2.6097574011, -0.3413193965], [-0.0041960863, -0.7034186147, 1.7076147010]])
    c = np.clip(lms @ m1i.T, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def _smooth_noise(w: int, h: int, cells: int, rng) -> "object":
    """なめらかなノイズ（粗い乱数の升目を拡大して補間）。-1〜1"""
    import numpy as np
    small = Image.fromarray(((rng.random((cells, max(2, int(cells * w / h)))) * 255)).astype("uint8"), "L")
    return np.asarray(small.resize((w, h), Image.BICUBIC), dtype=float) / 127.5 - 1


def mesh_gradient(w: int, h: int, points, grain: float = 0.018, seed: int = 7, warp: float = 0.07) -> Image.Image:
    """メッシュグラデーション（2026-09-25。色の塊をぼかしただけの版は濁って美しくない、と利用者）。
    - 色は **OKLab で混ぜる**（点からの距離のガウスで重みを付けた平均）。境目がくすまず、明るさがなめらかにつながる
    - **細かい粒を足す**（±grain）。なめらかな面は JPEG で縞（階段）が出るので、粒でならす
    - **座標をなめらかなノイズでゆらす**（warp。After Effects のタービュレントディスプレイスと同じ考え。
      色が四隅から直線的に移るだけだと単調なので、境目を少しずつずらして自然に混ぜる。利用者が挙げた作例から）
    - 離れた色（黄と青など）を隣に置くときは、**あいだに中間色の点を置く**（直接つなぐと濁る。同じく作例から）
    points は (x 0〜1, y 0〜1, (r, g, b), 広がり 0〜1)"""
    import numpy as np
    ys, xs = np.mgrid[0:h, 0:w]
    u, v = xs / w, ys / h * (h / w)   # 縦横比をそろえた座標
    rng0 = np.random.default_rng(seed + 1)
    # ゆらぎは粗いものから細かいものまで 4 段を重ねる（フラクタルノイズ）。1 段だけだと大きくうねるだけで、
    # 水彩や雲のような「大小のむら」にならない（利用者が挙げた「液体系」のグラデーション背景の作例から）
    fbm = lambda: sum(a * _smooth_noise(w, h, c, rng0) for c, a in ((3, 0.5), (6, 0.25), (12, 0.15), (24, 0.1)))
    u = u + warp * fbm()
    v = v + warp * fbm()
    acc = np.zeros((h, w, 3)); wsum = np.zeros((h, w, 1)); chroma = np.zeros((h, w, 1))
    for (px, py, rgb, spread) in points:
        d2 = (u - px) ** 2 + (v - py * h / w) ** 2
        wt = np.exp(-d2 / (2 * spread ** 2))[..., None]
        lab = _srgb_to_oklab(np.array(rgb, dtype=float) / 255)
        acc += wt * lab
        chroma += wt * np.hypot(lab[1], lab[2])
        wsum += wt
    mix = acc / np.maximum(wsum, 1e-9)
    # **鮮やかさは別に平均して保つ**（a・b をそのまま平均すると、反対どうしの色が打ち消し合って真ん中が灰色になる）
    c_now = np.hypot(mix[..., 1:2], mix[..., 2:3])
    # 持ち上げは 1.35 倍まで（上限が無いと、混ぜた色の向きが入れ替わる所に筋が出る）。**色は色相の近いものどうしで組む**こと
    mix[..., 1:] *= np.minimum((chroma / np.maximum(wsum, 1e-9)) / np.maximum(c_now, 1e-6), 1.35)
    rgb = _oklab_to_srgb(mix)
    rng = np.random.default_rng(seed)
    rgb = np.clip(rgb + rng.normal(0, grain, (h, w, 1)), 0, 1)
    return Image.fromarray((rgb * 255 + 0.5).astype("uint8"), "RGB")


def make_mono(items, size: int, tag: str, rng: random.Random) -> list[dict]:
    """白黒のジャケット。地の明るさを暗い → 明るいに等分し、図形は少しだけ明るさを変える（色を入れない）"""
    out = []
    n = len(items)
    for i, (title, artist) in enumerate(items):
        g = int(20 + (235 - 20) * i / (n - 1))
        bg = (g, g, g)
        f = g + (28 if g < 128 else -28)
        fg = (f, f, f)
        ink = (245, 245, 245) if g < 128 else (20, 20, 20)
        im = draw_art(size, size, bg, fg, i % 5, rng)
        label(im, title, ink, bg)
        name = f"fa4e{tag}{i:010x}.jpg"
        im.save(UPLOADS / name, quality=90)
        url = f"/uploads/{name}"
        out.append({"source": "manual", "title": title, "artist": artist, "image": url, "thumb": url, "external_url": None})
    return out


def make(items, w: int, h: int, tag: str, rng: random.Random) -> list[dict]:
    out = []
    for i, (title, artist) in enumerate(items):
        bg, fg, ink = palette(i, len(items), rng)
        im = draw_art(w, h, bg, fg, i % 5, rng)
        label(im, title, ink, bg)
        name = f"fa4e{tag}{i:010x}.jpg"   # uploads の名前の形（16 進 16 桁）
        im.save(UPLOADS / name, quality=90)
        url = f"/uploads/{name}"
        out.append({"source": "manual", "title": title, "artist": artist, "image": url, "thumb": url, "external_url": None})
    return out


def main() -> None:
    UPLOADS.mkdir(exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20260925)
    square = make(SQUARE, 600, 600, "01", rng)
    wide = make(WIDE, 640, 360, "02", rng)
    mono = make_mono(MONO, 600, "03", rng)
    # 背景の画像の見本（穏やかなメッシュグラデーション。にぎやかさが低いので、濃さ 5 割で見本にも見える）
    mesh_gradient(1600, 900, [
        # 色相の近い並び（青緑 → 緑 → 若草 → クリーム）。反対どうしの色を隣に置くと、境目が濁るか筋になる
        (0.05, 0.85, (40, 170, 170), 0.20), (0.30, 0.55, (110, 210, 190), 0.18), (0.55, 0.20, (160, 230, 170), 0.20),
        (0.85, 0.35, (200, 240, 185), 0.18), (0.95, 0.90, (250, 245, 205), 0.22), (0.20, 0.10, (150, 225, 200), 0.18),
        (0.60, 0.80, (90, 195, 175), 0.16),
    ], warp=0.16).save(OUT / "x-bg-sample.jpg", quality=92)
    (OUT / "fake-tracks-mono.json").write_text(json.dumps(mono, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "fake-tracks.json").write_text(json.dumps(square, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "fake-tracks-wide.json").write_text(json.dumps(wide, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"正方形 {len(square)} 枚・16:9 {len(wide)} 枚・白黒 {len(mono)} 枚 → uploads/、一覧 → {OUT}")


if __name__ == "__main__":
    main()
