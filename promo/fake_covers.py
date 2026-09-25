"""X 向けの短い動画（promo/x_clips.mjs）で使う、架空のジャケットと曲名を作る。

    PYTHONUTF8=1 .venv/Scripts/python promo/fake_covers.py

**動画に実在のジャケットを映さない**ため（2026-09-25、利用者の指定「サムネの画像は全て架空の絵に」）。
- 正方形のジャケット 24 枚と、動画サイトのサムネ風の 16:9 を 12 枚、図形と色だけで描く
  （色で並べ替えが映えるよう色相を散らし、白黒も 3 枚混ぜる）
- 絵は手元の `uploads/`（git の外）に置く。サーバーは R2 に無いアップロード画像を手元から読むので、
  **本番の R2 には上げない**（uploads.read_bytes の手元への逃げ道）。名前は uploads の形（16 進 16 桁）で、頭を fa4e にしてある
- 白黒のジャケット 16 枚（明るさを段階的に。色で並べ替えの場面用）
- 曲の一覧は `promo/public/fake-tracks.json`・`fake-tracks-wide.json`・`fake-tracks-mono.json`（x_clips.mjs と台本が読む）
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
    (OUT / "fake-tracks-mono.json").write_text(json.dumps(mono, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "fake-tracks.json").write_text(json.dumps(square, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "fake-tracks-wide.json").write_text(json.dumps(wide, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"正方形 {len(square)} 枚・16:9 {len(wide)} 枚・白黒 {len(mono)} 枚 → uploads/、一覧 → {OUT}")


if __name__ == "__main__":
    main()
