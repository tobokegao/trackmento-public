"""Pillow によるサーバー側 PNG 描画。CLI からも /render からも使う。

レイアウト計算はフロント（frontend/index.html の layout()）と同じ式にしてあるので、
Web で「画像を作る」とサーバーで作ったものが同じ寸法・配置になる。
色は CSS の oklch トークンを sRGB に変換して使う。
"""
from __future__ import annotations

import io
import math
from typing import NamedTuple
import unicodedata
import os
import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from backend import imgtools, names, netguard, uploads
from backend.cache import cache
from backend.logutil import brief
from backend.grids import GridDoc
from backend.models import NO_COVER, Track

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
OUTPUTS = ROOT / "outputs"

# マスの寸法（論理 px）。**形を変えても幅は変えない**ので、幅から決まる式（タイトルの大きさ・
# 余白・サイドバーの幅）はそのまま効く。高さから決まる式（塊の高さ・曲名リストの段の送り）だけ
# `cell_h()` を見る。どの式がどちらを見るかは docs/layout.md の表
CELL_W = 600
# 16:9 は 600×337.5 の小数を避けるための丸め（実比 16:9.01、誤差 0.15%。見た目には分からない）
CELL_H_BY_RATIO = {"1:1": 600, "16:9": 338}
CELL_PX = CELL_W          # 旧名。幅から決まる式が読む
GAP_PX = 12
MAX_SIDE = 8000
RATIOS: dict[str, float | None] = {"1:1": 1.0, "16:9": 16 / 9, "4:5": 4 / 5, "9:16": 9 / 16, "free": None}
IMAGE_MAX_BYTES = 15 * 1024 * 1024
UA = "Mozilla/5.0 (compatible; trackmento/0.1)"
Image.MAX_IMAGE_PIXELS = 24_000_000   # 展開爆弾対策（超えると DecompressionBombError。約 4900×4900）。ジャケット用途には十分
IMAGE_HOSTS = ("mzstatic.com", "coverartarchive.org", "archive.org", "discogs.com", "bcbits.com", "bandcamp.com",
               "sndcdn.com", "ytimg.com", "nimg.jp", "nicovideo.jp", "hdslb.com", "scdn.co", "spotifycdn.com", "otodb.net")


def rnd(x: float) -> int:
    """JS の Math.round と同じ丸め（.5 は切り上げ）。Python の round は偶数丸めで 1px ずれる。"""
    return math.floor(x + 0.5)


# ---------- 色（CSS トークンと同じ oklch 値） ----------
def _oklch_to_hex(L: float, C: float, H: float) -> str:
    a = C * math.cos(math.radians(H))
    b = C * math.sin(math.radians(H))
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s

    def gamma(x: float) -> int:
        x = max(0.0, min(1.0, x))
        x = 1.055 * x ** (1 / 2.4) - 0.055 if x > 0.0031308 else 12.92 * x
        return max(0, min(255, round(x * 255)))

    return "#{:02x}{:02x}{:02x}".format(gamma(r), gamma(g), gamma(bl))


TOKENS = {
    "paper": _oklch_to_hex(0.97, 0.003, 95),
    "paper-2": _oklch_to_hex(0.93, 0.004, 95),
    "paper-3": _oklch_to_hex(0.89, 0.005, 95),
    "ink": _oklch_to_hex(0.20, 0.012, 250),
    "ink-2": _oklch_to_hex(0.28, 0.012, 250),
    "muted": _oklch_to_hex(0.46, 0.012, 250),
    "rule": _oklch_to_hex(0.76, 0.012, 250),
    "mustard": _oklch_to_hex(0.80, 0.150, 88),
    "cerulean": _oklch_to_hex(0.60, 0.140, 235),
    "lavender": _oklch_to_hex(0.74, 0.100, 295),
    "vermilion": _oklch_to_hex(0.62, 0.200, 32),
    "mint": _oklch_to_hex(0.84, 0.110, 165),
    "pink": _oklch_to_hex(0.78, 0.130, 350),
    # もう 1 組のパレット（2026-09-15 に追加）。リソグラフ寄りの上の 6 色より彩度が高い。
    # **この 6 色は実際の色見本から取った値なので oklch ではなく生の 16 進で持つ**
    # （frontend/index.html の TOKENS_RGB と POP_PALETTE にも同じ値がある。片方だけ変えない）
    # 3 つ目の組「ナイト」（2026-09-16）。**地が暗い組**。画面も暗い側のプラチナに入れ替わる
    "night": "#14181d",
    "chalk": "#f2f0ec",
    "amber": "#ffb43d",
    "azure": "#58a6ff",
    "flare": "#ff6b6b",
    "violet": "#b18cff",
    "jade": "#3ddc97",
    "magenta": "#ff5ec4",
    # ポップの地と文字（2026-09-16）。**パレットは 8 色ひと組**になり、クリームと黒も組ごとに変わる
    "ivory": "#fdf4e6",
    "charcoal": "#1b2430",
    "lemon": "#fbd743",
    "ultramarine": "#4878da",
    "coral": "#f0535a",
    "sky": "#87d4ff",
    "leaf": "#52a555",
    "rose": "#f2418f",   # コーラル（357°）と紛らわしかったので色相を 343° → 334° に振った（324° は紫に寄りすぎた）
}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _is_light(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.55


# ---------- フォント ----------
# **大きさごとに FreeType の face を 1 つ持つので、1 つ 0.3MB ほど食う**。割り付けを探すあいだに
# 1px 刻みで何百通りも作るので、上限を付けないと本番のプロセスに溜まり続ける
# （2026-09-19 に調べた。手元で 60 通り組むと 1,317 個・+380MB。本番の rss が 632MB まで伸びていた原因）。
# 使った順に並べ、上限を超えたら古いものから捨てる
FONT_CACHE_MAX = int(os.getenv("FONT_CACHE_MAX", "160"))
_font_cache: "OrderedDict[tuple[str, int], ImageFont.FreeTypeFont]" = OrderedDict()

# 字幅の控え。1 件は小さいが、利用者の曲名の字 × 大きさで際限なく増えるので、上限で丸ごと捨てる
CHAR_W_CACHE_MAX = int(os.getenv("CHAR_W_CACHE_MAX", "200000"))
_char_w_cache: dict[tuple[str, int, str], float] = {}


def char_w(kind: str, size: int, ch: str) -> float:
    """1 字の幅（1px に丸めたもの）。**流し込みは同じ字を何度も測る**ので控えておく
    （21x12 のような大きな並びだと、割り付けを探すあいだに数十万回になる）。"""
    key = (kind, size, ch)
    w = _char_w_cache.get(key)
    if w is None:
        if len(_char_w_cache) >= CHAR_W_CACHE_MAX:
            _char_w_cache.clear()
        w = _char_w_cache[key] = float(rnd(font(kind, size).getlength(ch)))
    return w


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    """kind: 'bold' | 'regular' | 'pixel'（Silkscreen Bold）"""
    key = (kind, size)
    f = _font_cache.get(key)
    if f is not None:
        _font_cache.move_to_end(key)
        return f
    name = {"bold": "IBMPlexSansJP-Bold.ttf", "regular": "IBMPlexSansJP-Regular.ttf", "pixel": "Silkscreen-Bold.ttf"}[kind]
    p = FONTS / name
    try:
        f = _font_cache[key] = ImageFont.truetype(str(p), size)
    except OSError as e:
        raise RuntimeError(f"フォントが見つかりません: {p}") from e
    while len(_font_cache) > FONT_CACHE_MAX:
        _font_cache.popitem(last=False)
    return f
    if True:
        name = {"bold": "IBMPlexSansJP-Bold.ttf", "regular": "IBMPlexSansJP-Regular.ttf", "pixel": "Silkscreen-Bold.ttf"}[kind]
        p = FONTS / name
        try:
            f = _font_cache[key] = ImageFont.truetype(str(p), size)
        except OSError as e:
            raise RuntimeError(f"フォントが見つかりません: {p}") from e
        while len(_font_cache) > FONT_CACHE_MAX:
            _font_cache.popitem(last=False)
    return f


_cmap_cache: set[int] | None = None


def _cmap() -> set[int]:
    """サイドバー用フォント（IBM Plex Sans JP）が持つコードポイント。無い文字は豆腐（□）になるので描画前に落とす"""
    global _cmap_cache
    if _cmap_cache is None:
        from fontTools.ttLib import TTFont
        cps: set[int] = set()
        for name in ("IBMPlexSansJP-Regular.ttf", "IBMPlexSansJP-Bold.ttf"):
            with TTFont(str(FONTS / name), lazy=True) as tt:
                cps |= set(tt.getBestCmap().keys())
        _cmap_cache = cps
    return _cmap_cache


def _drawable(s: str) -> str:
    """フォントに無い文字を、互換分解（NFKC: 𝓒→C、㈱→(株) など）で置き換え、それでも無ければ落とす。
    装飾文字や私用領域（キャリア絵文字）が入ったアーティスト名が豆腐で並ぶのを防ぐ"""
    cmap = _cmap()
    out: list[str] = []
    for ch in s:
        if ord(ch) in cmap or ch == " ":
            out.append(ch)
            continue
        alt = unicodedata.normalize("NFKC", ch)
        if alt != ch and all(ord(c) in cmap for c in alt):
            out.append(alt)
    return "".join(out)


def _one_line(s: str | None) -> str:
    """改行・タブを空白に。Pillow は改行入りの文字列を 1 行として測れない（ValueError）ので、描画前に必ず通す。
    フォントに無い文字もここで落とす。

    **まず NFC で合成する**。濁点・半濁点が結合文字（U+3099 / U+309A）で入っている題があり
    （利用者の「人生を歩む上で…」）、Pillow は合成せずに素の「て」と濁点を別々に置くので
    **「上て」「及ひ」と濁点が消えて見える**。Canvas は合成するので、直さないと両描画がずれる
    （字幅も変わるので折り返す位置まで変わり、突き合わせで 7.7% の差になっていた）"""
    return " ".join(_drawable(unicodedata.normalize("NFC", s or "")).split())


TITLE_SHRINK = (0.92, 0.86, 0.8)   # 折った最後の行が少しはみ出すときに縮める段階（frontend の TITLE_SHRINK と同じ）
TITLE_ROWS3 = 1 + 1 / TITLE_SHRINK[-1]   # 2.25 … 1 行＋0.8 に縮めた 1 行に入る題の幅の上限（段の幅の何倍か）。超えたら 3 行
TITLE_CLIP = 2 + 1 / TITLE_SHRINK[-1]    # 3.25 … 3 段（2 行＋0.8 に縮めた 1 行）に入る上限。超える題は「…」で切れる
# **アーティスト名も 2 行まで折る**（2026-09-18）。iTunes は「ピノキオピー feat. 初音ミク Append (Dark),
# 初音ミク Append (Sweet)」のように歌声の種類まで並べて返すので、2 列でも 1 行には入らない
# （利用者の 5x5・16:9・25 曲で 3 曲が「…」になっていた）。曲名と同じ順序で「縮める → 折る → 切る」
ARTIST_ROWS1 = 1 / TITLE_SHRINK[-1]      # 1.25 … 0.8 に縮めれば 1 行に入る上限。ここまでは行を増やさない
ARTIST_CLIP = 1 + 1 / TITLE_SHRINK[-1]   # 2.25 … 2 行（1 行＋0.8 に縮めた 1 行）に入る上限。超える名前は「…」で切れる


def _shrink_font(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, font_s: int, max_w: float,
                 kind: str = "bold") -> ImageFont.FreeTypeFont:
    """text が max_w に入るまで TITLE_SHRINK の順に字を縮める。縮めても入らなければ最後の大きさを返す（描くときは「…」で切る）。"""
    for k in TITLE_SHRINK:
        if d.textlength(text, font=f) <= max_w:
            break
        f = font(kind, max(8, rnd(font_s * k)))
    return f


def _fits_shrunk(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, font_s: int, max_w: float) -> bool:
    return d.textlength(text, font=_shrink_font(d, text, f, font_s, max_w)) <= max_w


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_w: float) -> str:
    if draw.textlength(text, font=f) <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid] + "…", font=f) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


# ---------- 画像取得（キャッシュ → HTTP） ----------
def fetch_image_bytes(url: str) -> bytes:
    if url == "/bg-mark.png":   # 背景色の「画像」の既定（同梱）
        return (ROOT / "frontend" / "bg-mark.png").read_bytes()
    if url == NO_COVER:   # ジャケットが無い曲に使ううちの画像。同梱しているのでそのまま読む
        p = ROOT / "frontend" / "no-cover.png"
        if not p.is_file():
            raise ValueError("no-cover.png がありません（python scripts/build_icons.py で作れます）")
        return p.read_bytes()
    if uploads.is_upload_url(url):
        got = uploads.read_bytes(url)
        if got is None:
            raise ValueError(f"アップロード画像がありません: {url}")
        return got[0]
    hit = cache.get_image(url)
    if hit:
        return hit[1]
    # 私設アドレス宛てやリダイレクト先の内部ホストは netguard が拒否する（SSRF 対策）
    # 上限は短め。共有は 1 リクエストで全マスを取りに行くので、遅い配信元（archive.org など）で長く待つと
    # プロキシ側のタイムアウト（HTML の 502/504 が返り、ブラウザが JSON として読めない）になる
    r = netguard.safe_get_sync(url, allowlist=IMAGE_HOSTS, timeout=12, headers={"User-Agent": UA, "Accept": "image/*,*/*;q=0.8"})
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").split(";")[0].strip()
    if not ctype.startswith("image/"):
        # Content-Type を付けない配信元がある（otoDB の CDN）。中身の先頭で確かめる（/image-proxy と同じ）
        ctype = imgtools.sniff_image_type(r.content) or ctype
    if not ctype.startswith("image/") or len(r.content) > IMAGE_MAX_BYTES:
        raise ValueError(f"画像として扱えません: {ctype} {len(r.content)} bytes")
    data = r.content
    if imgtools.is_video_thumb(url):
        # 動画のサムネイルは黒帯を切ってから保存する。/image-proxy も同じキャッシュを返すので、
        # どちらの経路が先に保存しても内容が同じになる（ブラウザ描画とサーバー描画の切り抜きが揃う）
        data, ctype = imgtools.trim_letterbox_bytes(data, ctype)
    cache.set_image(url, ctype, data)
    return data


def load_cover(t: Track, w: int = CELL_W, h: int | None = None, fit: str = "crop") -> Image.Image | None:
    """ジャケットを取得し、マスの大きさ（w × h）に収めて返す。
    原寸の画像を持ち続けないこと（64 枚 × 数千 px で GB 単位になる）。JPEG は draft で縮小デコードする。
    高解像度（image）が取れないときはサムネイル（thumb）で代用する（Cover Art Archive の 500、YouTube の maxres 欠落など）。"""
    urls = [t.image] + ([t.thumb] if t.thumb and t.thumb != t.image else [])
    for url in urls:
        try:
            return _load_cover_from(url, t, w, h if h is not None else w, fit)
        except Exception as e:  # 1枚の失敗で全体を止めない
            timed_out = isinstance(e, httpx.TimeoutException)
            retry = url != urls[-1] and not timed_out   # 配信元が応答しないときはサムネイルも同じ配信元なので待たない
            print(f"[render] image failed ({brief(e)}): {t.title} / {t.artist}" + ("（サムネイルで再試行）" if retry else ""))
            if not retry:
                break
    return None


def _load_cover_from(url: str, t: Track, w: int, h: int, fit: str = "crop") -> Image.Image:
    data = fetch_image_bytes(url)
    with Image.open(io.BytesIO(data)) as src:
        if src.format == "JPEG":
            src.draft("RGB", (w, h))   # マスの大きさ以上で最も小さい 1/2・1/4・1/8 スケールでデコード（デコードが描画 CPU の大半）
        im = src.convert("RGB")
    if imgtools.is_video_thumb(url) or t.source in ("youtube", "nicovideo", "bilibili", "otodb"):
        im = imgtools.trim_letterbox(im)   # 動画サムネイルの黒帯を落としてから切り抜く
    # **「ぼかして埋める」を選んだマスだけ切らずに収める**。既定は今までどおり中央で切る。
    # 文字の入ったジャケットは切ると読めなくなるので、そこだけ利用者が選ぶ（docs/ui.md）。
    # 正方形のマスでも効く（16:9 のサムネを左右を切らずに入れる。2026-09-21）
    fitted = (_cover_blur_pad(im, w, h) if fit == "blur" and abs(im.width / im.height - w / h) > 0.01
              else _cover_fit(im, w, h))
    im.close()
    return fitted


def lower_thread_priority() -> None:
    """呼び出したスレッドの優先度を下げる（Linux のみ）。0.1 vCPU の無料ホストでは描画中に他の処理（/health）が
    CPU を取れず再起動されるため、描画スレッドはイベントループより後回しにする。"""
    try:
        os.setpriority(os.PRIO_PROCESS, 0, 10)   # Linux では who=0 が呼び出しスレッド自身
    except (AttributeError, OSError):
        pass


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """a を b の方へ t（0〜1）だけ寄せた色。"""
    return tuple(rnd(x + (y - x) * t) for x, y in zip(a, b))   # type: ignore[return-value]


def _cover_fit(img: Image.Image, w: int, h: int) -> Image.Image:
    """CSS object-fit: cover 相当（中央トリミング）。"""
    s = max(w / img.width, h / img.height)
    # 浮動小数の誤差で sw/sh が画像より僅かに大きくなり、box の座標が負になって
    # "box offset can't be negative" で落ちることがある（ほぼ正方形の JPEG を draft で縮小したとき）。画像内に収める
    sw, sh = min(w / s, img.width), min(h / s, img.height)
    sx, sy = max((img.width - sw) / 2, 0.0), max((img.height - sh) / 2, 0.0)
    return img.resize((w, h), Image.LANCZOS, box=(sx, sy, sx + sw, sy + sh))


BLUR_RADIUS = 0.06    # 下地のぼかし半径（マスの高さに対する比）。**論理 px ではなく出力 px の高さに掛ける**
# 背景の画像の濃さは並びの `bgImageAlpha`（ブラウザが画像のにぎやかさから決める。0.2〜0.5）。
# 背景色（画像の平均の色を字と反対の側へ寄せたもの）の上に、この割合で画像を重ねる


def _paint_bg_image(im: Image.Image, url: str, bg: tuple[int, int, int], alpha: float) -> None:
    """背景の画像を枠いっぱいに切り抜いて敷く（背景色の上に alpha の濃さ）。
    取れなければ背景色のまま（共有を止めない）。frontend の renderShareCanvas と同じ式"""
    try:
        data = fetch_image_bytes(url)
        with Image.open(io.BytesIO(data)) as src:
            if src.format == "JPEG":
                src.draft("RGB", im.size)
            pic = src.convert("RGB")
        fitted = _cover_fit(pic, im.width, im.height)
        pic.close()
        im.paste(Image.blend(Image.new("RGB", im.size, bg), fitted, alpha))
        fitted.close()
    except Exception as e:
        print(f"[render] background image failed ({brief(e)})")


def blur_margin(h: int) -> int:
    """下地を作るときにマスの外へ広げる幅。**frontend の `blurMargin` と同じ式**"""
    return max(1, round(max(1.0, h * BLUR_RADIUS) * 3))


def _cover_blur_pad(img: Image.Image, w: int, h: int) -> Image.Image:
    """**絵を切らずに**マスいっぱいに収める。余る側は、同じ絵を cover で広げてぼかした下地で埋める
    （YouTube の再生画面と同じやり方）。**frontend の `coverBlurPad` と対で直すこと**。

    16:9 のマスに正方形のジャケットが来たときに使う。中央で切ると、アルバムアートは
    中央に絵があるので損なう。
    """
    r = max(1.0, h * BLUR_RADIUS)
    # **下地はマスより広く作ってから切り取る**。マスちょうどで作ってぼかすと、端に外側の色が無いぶん
    # 縁がにじんで四角の枠がぼやける（ブラウザの `blur()` は範囲の外を透明として扱うのでなおさら）。
    # 広げる幅は半径の 3 倍（ガウスぼかしが実質届く範囲）。**frontend の `coverBlurPad` と同じ式にすること**
    m = blur_margin(h)
    base = _cover_fit(img, w + m * 2, h + m * 2).filter(ImageFilter.GaussianBlur(r)).crop((m, m, m + w, m + h))
    f = min(w / img.width, h / img.height)                  # contain
    fw, fh = max(1, round(img.width * f)), max(1, round(img.height * f))
    base.paste(img.resize((fw, fh), Image.LANCZOS), ((w - fw) // 2, (h - fh) // 2))
    return base


# ---------- レイアウト ----------
@dataclass
class Layout:
    W: int; H: int; scale: float; ox: int; oy: int
    gw: int; gh: int
    title: str; title_size: int; title_h: int
    side: str; sb_w: int; sb_h: int; sb_cols: int; line_h: int; font_s: int; sb_gap: int; sb_flow: bool
    sb_plan: tuple[int, ...] = ()   # 曲ごとの行数（1〜4）。曲名 1〜3 行＋アーティスト名 1〜2 行
    sb_arows: tuple[int, ...] = ()  # 曲ごとのアーティスト名の行数（0〜2）。**割り付けを決めた字で数えたもの**。
                                    # 描くときに数え直すと、そのあと行の高さを取り直した分だけずれ、
                                    # 曲名に回る行数が変わって「REALITY」が「REA / LITY」に割れた（2026-09-18）
    # 回り込み（マスの塊を中央に置き、まわりの余白に曲名を流し込む）
    wrap: bool = False
    wrap_pad: int = 0                                   # 四辺の余白
    wrap_top: int = 0                                   # タイトルの帯の上端（余り分を上下に分けて下げる）
    wrap_segs: tuple[tuple[int, int, int], ...] = ()    # 行ごとの (x, y, 幅)。左段 → 右段の順
    wrap_rows: bool = False                             # 段が 1 曲ずつ（マスの横に並べる）
    sb_inline: bool = False                             # 1 行型（曲名の右端にアーティスト名を右寄せ。`_inline_one_line`）
    wrap_tx: int = 0                                    # タイトルの左端（0 なら wrap_pad）。比率なしの「マスごと」は右の列の上
    wrap_inline: bool = False                           # マスごとの 1 行型（`_slab_rows` の inline）
    sb_top: int = 0                                     # 曲名リストの頭を下げる量（表の行間に上限を掛けて余った高さの半分。`TABLE_LH_CAP`）


# 曲が多いと 1 曲 1 行では文字が小さくなりすぎる（16×16 で出力 8px）。そこで曲名を
# 続けて流し込み、幅で折り返す。区切りの記号は置かない。番号がピクセルフォントで
# 本文と書体も色も違うので、それ自体が切れ目になる
class FlowRow(NamedTuple):
    parts: list[tuple[str, str]]   # ("num"|"title"|"artist", 文字列)
    width: float                   # 文字と曲間の送りで使った幅
    gaps: int                      # 曲の切れ目の数（余った幅をここに配る）


FLOW_MIN_FONT = 20        # 1 曲 1 行のとき、出力でこれより小さくなるなら流し込み（や回り込み）を試す
FLOW_KEEP_FONT = 14       # 試した結果が流し込みなら、1 曲 1 行が出力でこれ以上あるかぎり 1 曲 1 行を残す（16 から下げた。2026-09-21）
# 行の中心からベースラインまでの下向きの量（字の大きさに対する比）。**実測せず固定比にする**。
# PIL の字面（getbbox）と Canvas の actualBoundingBox は数 px 違い、実測で決めると
# 小さい文字ほど食い違いが目立つ。IBM Plex Sans JP の「あ」で 10〜128px を測ると 0.375〜0.406、
# 平均 0.38。両者で同じ式を使えば必ず同じ位置になる
BASELINE = 0.38
# 回り込み（正方形以下の比率で曲が多いとき）。マスの塊を中央に置き、左上から右下へ文字を流す。
# 塊にぶつかる行は「左の段 → 塊の向こう側の右の段」と続ける
WRAP_GAP_EM = 0.5         # マスの塊と文字（字面）のあいだ。文字の大きさに対する割合（0.75 は広すぎると指摘があった）
WRAP_MIN_SEG = 20         # 段の最小幅（文字の大きさの何倍か＝だいたい何字入るか）。
                          # これ未満の隙間には流さない。**8 字だと曲名が数文字ごとに折れて読めない**
                          # （実測で 8x12・9:16 の左右が 8 字ぶんしかなかった）。
                          # 上げてもマスはほとんど小さくならない（全組み合わせの中央値で 96px → 91px）
WRAP_GRID_MAX = 0.96      # マスの塊は枠のこの割合まで（詰まっているほうの辺で見る）。
                          # 細い隙間は WRAP_MIN_SEG が弾き、半端な左右はコの字にまとめるので、
                          # ここは余白ぶん空けば足りる。0.72 に絞っていたときはマスが無駄に
                          # 小さかった（全組み合わせのマスの中央値 91px → 108px）
WRAP_GRID_MIN = 0.45      # 逆に、塊が枠のこの割合を下回るなら文字のほうを小さくする。
                          # **文字を優先しすぎるとジャケットが豆粒になる**（21x12 を 16:9 で 30% だった）
WRAP_MAX_PCT = 400        # 枠をマスの塊の何 % まで広げてよいか
# 出力での文字の大きさ（px）。上から順に試し、**入る中でいちばん大きいもの**を使う。
# 曲が多くて比率が横長（21x12 を 16:9 など）だと、20px ではどう組んでも入らない
# （2400x1350 に 30px 行間で 45 行しか置けない）。そこだけ落とす
WRAP_TARGET_PX = (FLOW_MIN_FONT, 18, 16, 14, 12)
# 入る大きさが見つかったあと、**余っている余地で文字を大きくする**。大きくすると枠も少し
# 大きく（＝マスが少し小さく）なるので、**マスが WRAP_CELL_KEEP を割らない範囲まで**にする
# 上限を 72 で止めていたため、枠が縦長で文字の場所が広いときに埋まりきらなかった
WRAP_TARGET_UP = (22, 24, 26, 28, 32, 36, 40, 44, 48, 56, 64, 72, 84, 96, 112, 128)
WRAP_CELL_KEEP = 0.85
# **マスがもともと小さいときは守る意味が薄い**ので、文字を大きくする許容を緩める。
# 守りすぎると文字が途中で尽きて、マスの脇と下が大きく空く（1x32 を 16:9 にすると埋まり 32%）
WRAP_CELL_OK = 40         # 出力でのマスの大きさ（px）。これ以上なら今までどおり守る
WRAP_CELL_KEEP_SMALL = 0.6
# 逆に、**文字を 1〜2 段落とすとマスが大きく取れる**ことがある。塊の形と枠の比率が食い違うと、
# 大きい文字のままでは塊を横いっぱいにできず、左右に使えない空白が残る（32x7 を 9:16 にすると
# 塊が枠の 66% の幅で、左右に 182px ずつ死んでいた）。この倍率以上大きくなるなら落とす
WRAP_CELL_GAIN = 1.25
WRAP_TARGET_FLOOR = 14    # ただし、マスのために文字をここまでしか落とさない
WRAP_FINE_STEPS = 24      # 枠を決めたあと、字を 1 論理 px ずつ大きくして余りを埋める回数の上限
WRAP_LAST_FILL = 0.8      # 最後の行がこの割合まで埋まっている候補を優先する（数語だけの行で終わると「惜しい」見た目になる）
WRAP_SWITCH_PX = 12       # 出力での文字がこれを下回るなら回り込みに切り替える
WRAP_SWITCH_GAIN = 1.3    # 文字がこの倍率以上大きくなるなら、マスが少し小さくなっても切り替える
WRAP_TITLE_SCALE = 4.0    # タイトルは本文の何倍か
WRAP_TITLE_MAX = 0.3      # ただしタイトルの高さは「塊を除いた高さ」のこの割合まで
TITLE_MIN_SCALE = 1.6     # 曲名リストに対するタイトルの最低倍率（回り込み以外の組み方）
# タイトルの大きさの天井（枠の短い辺に対する割合）。どの組み方でも共通
WRAP_TITLE_FRAME = 0.06
WRAP_TITLE_MIN = 1.6      # **タイトルは本文の最低これだけ倍**。上限に当たってこれを割るなら、
                          # その枠は使わない（枠を広げて取り直す）。曲名リストのほうが大きいと逆さま

# 入る限り大きく。曲が少ないほど大きな字になる（流し込みに切り替わるのは曲が多いときだけ）
FLOW_FONT_STEPS = (132, 120, 108, 96, 84, 72, 64, 56, 48, 42, 36, 30, 26, 22, 18)
# 右に置くときは**出力での大きさ**（px）で選ぶ。枠が先に決まるのでこちらのほうが素直
FLOW_TARGET_PX = (56, 48, 40, 34, 28, 24, 20, 18, 16, 14, 12)
FLOW_FINE_STEPS = 16      # 右に置く流し込みで、入った段から字を 1 論理 px ずつ大きくする回数の上限
# **流し込みで語の尻尾だけが次の行へこぼれるなら、語ごと次の行へ送る**（2026-09-20、利用者の指摘。
# 「ビリー・アイリッシ／ュ」「La／ur」）。こぼれるのが FLOW_TAIL 字以下で、行に置いた頭が FLOW_WORD_MAX 字以下のときだけ。
# 語の区切りは空白と記号（FLOW_WORD_SEP）。長い漢字の並びのように語が長いものは今までどおり字の途中で折る
FLOW_TAIL = 2
FLOW_WORD_MAX = 12
FLOW_WORD_SEP = frozenset(" \u3000・･/／-‐–—_,，、。.．&＆×()（）[]［］【】「」『』<>〈〉《》!！?？~〜～:：;；\"'’“”*＊+＋=|｜")


# 曲名の末尾の「(feat. …)」。**ここだけは 2 段目に落とせる**（曲名の本体とアーティスト名を守るため）。
# 全角の括弧と、feat / ft / featuring の表記ゆれを見る。括弧が閉じていないもの（途中で切れた題）は対象外
_FEAT_RE = re.compile(r"\s*[（(\[]\s*(?:feat|ft|featuring)[.\s][^）)\]]*[）)\]]\s*$", re.IGNORECASE)


# **曲名をマスに重ねる**（2026-09-18、利用者の要望）。マスの下に「下から上へ薄くなる黒い帯」を敷き、
# 白い字で曲名 → その下にアーティスト名を載せる。大きさはマスに対する割合で決まる（割り付けは変えない）。
# 入らなければ TITLE_SHRINK の順に縮め、それでも入らなければ「…」。frontend の OVERLAY_* と同じ値
OVERLAY_SHADE = 0.52      # 帯の高さ（マスに対する割合）
OVERLAY_ALPHA = 0.82      # 帯のいちばん下の濃さ
OVERLAY_TITLE = 0.085     # 曲名の字の大きさ（マスに対する割合。600px のマスで 51px）
OVERLAY_ARTIST = 0.066    # アーティスト名の字の大きさ
OVERLAY_PAD = 0.055       # 字とマスの縁のあいだ（左右と下）
OVERLAY_LEAD = 1.3        # 曲名のベースラインから、アーティスト名のベースラインまで（アーティスト名の字に対する倍率）
OVERLAY_MIN_PX = 12       # 出力での曲名の字がこれを割る並びでは重ねない（読めない）
OVERLAY_TEXT = (255, 255, 255)
OVERLAY_SUB = (214, 218, 224)


def cell_h(doc: GridDoc) -> int:
    """マスの高さ（論理 px）。`cellRatio` から決まる。幅は `CELL_W` で固定"""
    return CELL_H_BY_RATIO.get(doc.options.cellRatio, CELL_W)


def cell_short(doc: GridDoc) -> int:
    """マスの短いほうの辺。**帯や番号バッジを出すかの判定はこちらを見る**
    （幅で見ると、16:9 のマスが実際より大きく見積もられて潰れた帯が出る）"""
    return min(CELL_W, cell_h(doc))


def overlay_ok(scale: float, short: int = CELL_W) -> bool:
    """この縮尺で曲名を重ねて読めるか（frontend の overlayOk と同じ）。
    **マスの短辺で見る**（16:9 は高さが短いので、幅で見ると潰れた帯が出る）"""
    return rnd(short * OVERLAY_TITLE * scale) >= OVERLAY_MIN_PX


def _split_feat(title: str) -> tuple[str, str]:
    """曲名を「本体」と「(feat. …)」に分ける。無ければ (曲名, "")。"""
    m = _FEAT_RE.search(title)
    if not m or not m.start():   # 丸ごと feat. だけの題は分けない
        return title, ""
    return title[:m.start()].rstrip(), title[m.start():].strip()


# 曲名リスト（1 曲 1 行ではないほう）の作り。**曲名とアーティスト名を上下 2 行に分ける**。
# 横に並べると長い曲名でアーティストが押し出されるが、行を分ければ必ず読める。
# 曲が増えたら列を増やして、1 列あたりの行数を減らす（行間と文字を大きく保つため）
# **行の高さはマスの段の送りの約数に寄せる**（Vignelli Canon「type と illustration が
# 同じ格子に乗るよう、モジュールに合う行送りを決める」）。曲名の行とジャケットの上下の端が
# そろい、絵が引き締まる。**寄せられる値が近くに無ければ動かさない**（無理に寄せると
# 文字が小さくなるだけで損）。実測（3x3 16:9）では行 93 → 88px（マスの送り 616 の 7 分の 1）
SNAP_LEAD_TOL = 0.15


# **外側の余白もモジュールの目盛りに乗せる**（Gerstner の「決めた比率でどの並びでも通す」考え方）。
# マスの送り `u = CELL_PX + 間隔` の `1/MOD_PAD_DIV` 刻みに**切り上げる**。切り下げないのは、
# 3.5% の下限（絵が枠に貼り付いて見えるのを防ぐためのもの）を割ってしまうため。
# **刻みが粗いほどマスが小さくなる**（実測で 1/4 は中央値 -2.1%・最悪 -15.9%、1/8 は -1.6%・-6.9%、
# 1/16 は -0.6%・-2.1%）。読み取れる粗さと代償の釣り合いで 1/8 を採った
MOD_PAD_DIV = 8

# **外側の余白の下限（内容の短い辺に対する割合）を 3 段から選ぶ**（2026-09-24、利用者の判断。frontend の `PAD_FRAC` と同じ値）。
# 前は「余白」のスライダー（px）だったが、下限の 3.5% と比率合わせの余りに隠れて、動かしても書き出しが変わらないことが多かった
# （3x3 で下限が約 64、16x16 では約 340 になり、スライダーの上限 160 では届かない）。割合なら並びの大きさによらず差が出る。
# `margin`（px）はそのまま残り、下限より大きければ効く（CLI の --margin と古い並び）
PAD_FRAC = {"normal": 0.035, "wide": 0.07, "xwide": 0.12}


def _pad_frac(doc: GridDoc) -> float:
    return PAD_FRAC.get(getattr(doc.options, "pad", "normal"), PAD_FRAC["normal"])


def _mod_pad(pad: int, gap: int) -> int:
    """余白をモジュールの 1/MOD_PAD_DIV 刻みに切り上げる。"""
    step = (CELL_PX + gap) / MOD_PAD_DIV
    return max(pad, rnd(math.ceil(pad / step) * step))


def _snap_lead(lh: int, pitch: int, max_lh: int = 0) -> int:
    """`lh` を `pitch` の約数に寄せる。`max_lh` を超える値は選ばない（0 なら上にも寄せる）。

    候補が `SNAP_LEAD_TOL`（15%）の範囲に無ければ `lh` をそのまま返す。
    **大きいほうから選ぶ**（同じそろい方なら文字は大きいほうがよい）。
    """
    if lh <= 0 or pitch <= 0:
        return lh
    lo, hi = lh * (1 - SNAP_LEAD_TOL), lh * (1 + SNAP_LEAD_TOL)
    best = 0
    k = 1
    while k <= pitch:
        if pitch % k == 0:
            d = pitch // k
            if d < lo:
                break
            if d <= hi and (max_lh <= 0 or d <= max_lh):
                best = max(best, d)
        k += 1
    return best or lh


LIST_MIN_COL = 640        # 1 列の最小幅（論理 px）。これを割るなら列を増やさない
LEAD_PITCH_DIV = 4        # 曲名の行の高さの上限は「マスの送りの 1/4」。96px で頭打ちにしていたときは、
                          # 曲が少ないと高さが余ってもリストが縮こまり、4x4・16:9 で出力 24px・下が 4 割空いていた
LIST_COMFY_FONT = 26      # 出力での曲名の大きさ（px）。これ未満なら列を増やす（下限は FLOW_MIN_FONT）
LIST_MAX_COLS = 3
LIST_COL_GAP = GAP_PX * 5   # 列と列のあいだ。マスの間隔と同じでは隣の曲名と近すぎて、どちらの列か迷う
LIST_COL_GAIN = 1.02        # 下に置くとき、列を増やしてこの倍率以上大きくならないならやめる
ARTIST_SCALE = 0.78       # アーティスト名は曲名より小さく、薄い色で
LIST_COL_TIDY_GAIN = 1.15   # 右に置くとき、列を増やして「崩れる曲」が増えるなら、文字がこの倍率以上大きくならない限り増やさない
ROWS_SQUEEZE = 0.75       # 曲の順番で列の行数が見込みを超えたとき、行の高さを詰めてよい下限（見込みに対する割合。`_plan_need`）
FLOW_SQUEEZE = 1.2        # 流し込みの行が見込みより増えたとき、行の高さを字のこの倍まで詰めてよい（ふだんは 1.5 倍）
CLIP_MAX_RATIO = 0.15     # 下に置くとき、「…」で名前が消える曲がこの割合を超えて増えるなら、マスが大きくなっても列を増やさない
                          # （2026-09-18。一律に禁止すると、下に置く並びでマスが 22% 小さくなった＝3x3・1:1 で 496 → 388px）
CLIP_GAIN = 0.35          # 右に置くとき、名前が消える曲が 1 つ増えるごとに、列を増やすのに要る「字の大きさの倍率」をこれだけ厳しくする
                          # （1 曲なら 1.50 倍、2 曲なら 1.85 倍、8 曲なら 3.95 倍。実測で、利用者の 5x5・25 曲は 1.16 倍・
                          # 6x6・36 曲は 1.39 倍しか大きくならないので両方とも増やさない）


def _songs(doc: GridDoc) -> list[Track]:
    """曲の入ったマスだけを、マスの順（左上から右へ、次の段）に並べたもの。
    **書き出しの番号はこの並びの序数**（01・02・03…。空きマスの番号は飛ばして詰める。2026-09-25、利用者の決定）。
    マスの位置と結びつかない曲名リスト（サイドバー・表・1 行型・流し込み・縦一列）はこれで組み、
    空きマスの行を作らない。frontend の listCells と同じ"""
    return [t for t in doc.cells if t]


def _canon_key(t: Track) -> tuple[str, str]:
    return (t.title or "", t.artist or "")


def _canon(doc: GridDoc) -> GridDoc:
    """**組み方を決めるための並び**（2026-09-25）。曲の入ったマスの位置はそのままで、曲だけを
    曲名 → アーティスト名の順（文字の符号位置で比べる）に並べ替えた写しを返す。frontend の canonCells と同じ。

    同じ 49 曲（7x7・16:9）でも、「色で並べ替え」で順番を変えるだけで、書き出しが「右に 3 列の表・2400px」から
    「流し込み・2000px」に変わっていた（利用者の報告）。列の高さ（2 行に折れる曲がどの列に集まるか）や
    流し込みの行数（どこで折り返すか）が曲の順番で 1〜2 行変わり、それが境目の判定をまたいでいた。
    **組み方・出力の大きさ・字の大きさ・列数はこの並びで決め**、描くときは曲の順のまま
    （`layout()` の最後で、実際の並びに合わせて行の高さや段の位置だけを直す）
    """
    songs = _songs(doc)
    order = sorted(songs, key=_canon_key)
    if all(a is b for a, b in zip(order, songs)):
        return doc
    it = iter(order)
    return doc.model_copy(update={"cells": [next(it) if t else t for t in doc.cells]})


def _num_w(font_s: int) -> float:
    """番号（2 桁）とその後ろの空きの幅。**字ごとに 1px へ丸めて測る**（PIL と Canvas で食い違わない）"""
    return char_w("pixel", rnd(font_s * 0.8), "0") * 2 + rnd(font_s * 0.8)


def _artist_rows(artist: str, font_s: int, avail: float) -> int:
    """アーティスト名に要る行数（0〜2）。**割り付け（_row_plan）と描画で必ず同じ値を使う**。
    片方だけで数え直すと、曲名に回る行数がずれて「REALITY」が「REA / LITY」に割れた（2026-09-18）"""
    if not artist:
        return 0
    aw = sum(char_w("regular", max(8, rnd(font_s * ARTIST_SCALE)), ch) for ch in artist)
    return 1 if aw <= max(1.0, avail) * ARTIST_ROWS1 else 2


def _list_damage(doc: GridDoc, font_s: int, max_w: float) -> tuple[int, int]:
    """その列の幅で崩れる曲の数を **(折れる, 途切れる)** で返す。

    列を増やすかどうかを文字の大きさだけで決めていたとき、利用者の 5x5・16:9・25 曲（ボカロ曲で
    「作者 feat. 歌声」の長いアーティスト名）が 3 列になり、**曲名 14 曲が 2 段に折れ、アーティスト名
    13 曲が「…」で途切れた**（2026-09-17）。2 列なら文字は 7% 小さくなるだけで、折れも途切れも 0。
    幅は `_row_plan` の 3 行判定と同じく**字ごとに 1px に丸めた和**で見る（PIL と Canvas で食い違わない）

    **2 つを分けて数える**（2026-09-18）。「折れる」は行が増えるだけで**読める**が、「途切れる」は
    「…」で**文字が消える**。同じ 1 件として足していたため、利用者の 6x6・16:9・36 曲（KAITO の曲で
    「作者 feat. カイトV3 (Straight)」の長い名前）が、字が 1.39 倍になるのと引き換えに 3 列になり、
    アーティスト名 8 曲が消えていた。消えるほうは字の大きさと釣り合わない
    """
    # **番号の幅も字ごとに 1px へ丸めて測る**（2026-09-18）。まとめて測ると PIL と Canvas で 1px 違い、
    # 「入る・入らない」の境目の曲で数が割れて、列の選び方がサーバーとブラウザで食い違った
    avail = max(1.0, max_w - _num_w(font_s))
    fb, fa = max(12, font_s), max(8, rnd(font_s * ARTIST_SCALE))
    folded = clipped = 0
    for t in doc.cells:
        if not t:
            continue
        tw = sum(char_w("bold", fb, ch) for ch in _one_line(t.title))
        if tw > avail:
            # 曲名は 3 段まで折れる（最後の段は TITLE_SHRINK まで縮める）。それでも入らなければ「…」
            if tw > avail * TITLE_CLIP:
                clipped += 1
            else:
                folded += 1
        aw = sum(char_w("regular", fa, ch) for ch in _one_line(t.artist))
        if aw > avail * ARTIST_CLIP:
            clipped += 1        # 2 行に折っても入らない名前は「…」で切れる
        elif aw > avail * ARTIST_ROWS1:
            folded += 1         # 2 行に折れば読める（行が 1 つ増えるだけ）
    return folded, clipped


# **1 行型**（2026-09-18）。右に置く曲名リストで、曲名とアーティスト名を 1 行に並べ、アーティスト名を
# 列の右端にそろえる。3x3・16:9 では曲名＋アーティストの 2 行 × 9 曲で高さを使い切り、字が出力 28px に
# 止まって**右の 4 割が空いていた**（利用者の画像で指摘）。1 行にすれば行数が半分になって字が大きくなり、
# 左端（番号）と右端（アーティスト名）の両方がそろう。利用者が「左右の端をそろえたい」と選んだ形
INLINE_GAIN = 1.15        # 1 行型に切り替えるのは、字がこの倍率以上大きくなるとき
INLINE_GAP_EM = 1.0       # 曲名とアーティスト名のあいだの最低の空き（字の大きさに対する割合）
# **1 行型の表**（2026-09-20、利用者が選んだ形）。細い並び（1〜3 列）を横長の比率に入れると、マスが小さすぎて
# 曲名を横に並べられず、段落のような流し込みになっていた（1x32・16:9 の共有で指摘）。流し込みの代わりに、
# 1 行型（番号・曲名・右端にアーティスト名）を 2〜3 列の表に組む。**全曲が 1 行に入る大きさまで字を下げる**
# （「…」で切らない）。字が FLOW_KEEP_FONT を割るなら流し込みのまま。行の間に細い線を引く
TABLE_FONT = 0.5          # 1 行の高さに対する字の大きさ
TABLE_MAX_COLS = 3
TABLE_RULE = 0.86         # 行の間の線の色（文字の色を地の色へこれだけ寄せる）
LIST_VEIL = 0.8           # 背景が画像・グラデーションのとき、曲名リストの後ろに敷く地の濃さ（背景色をこの割合で重ねる）。
                          # 模様の上に字が直に乗って読みづらかった（2026-09-26、利用者の指摘）。frontend の LIST_VEIL と同じ
TABLE_LH_CAP = 2.5        # 表の 1 行の高さの上限（字の大きさに対する倍率。ふつうは 1 / TABLE_FONT = 2.0）。
                          # 行の高さは「リストの高さ ÷ 1 列の曲数」で決まるので、曲が少ないと字は幅で止まったまま行だけ広がり、
                          # 行と行が間延びしていた（2026-09-26、利用者の共有 3x8・7 曲）。余った高さはリストの上下に半分ずつ回す
TABLE_GAP_LH = 1.0        # 列と列のあいだ（1 行の高さに対する割合）。LIST_COL_GAP（マスの間隔の 5 倍）だと、
                          # マスが小さい並びでは出力 3px しかなく、左の列のアーティスト名が右の列の番号にくっついた


def _inline_one_line(doc: GridDoc, font_s: int, col_w: float) -> bool:
    """1 行型で**全曲が 1 行に並ぶか**（曲名 ＋ 1 字ぶんの空き ＋ 右端のアーティスト名）。
    幅は `_row_plan` と同じく字ごとに 1px へ丸めた和で見る（PIL と Canvas で食い違わない）"""
    avail = max(1.0, col_w - _num_w(font_s))
    fb, fa = max(12, font_s), max(8, rnd(font_s * ARTIST_SCALE))
    gap = rnd(font_s * INLINE_GAP_EM)
    for t in doc.cells:
        if not t:
            continue
        tw = sum(char_w("bold", fb, ch) for ch in _one_line(t.title))
        aw = sum(char_w("regular", fa, ch) for ch in _one_line(t.artist))
        if tw + (gap + aw if aw else 0) > avail:
            return False
    return True


def _row_plan(doc: GridDoc, font_s: int, max_w: float) -> tuple[int, ...]:
    """曲ごとの行数を返す。

    - アーティスト名があれば **曲名の行 + アーティストの行** で 2 行（無ければ 1 行）
    - 曲名が 1 行に収まらなければ曲名を 2 行に折り、その曲だけ 1 行増える
    - **2 行に折って最後の行を縮めても入らなければ 3 行**（2026-09-16）。ニコニコの題
      （【初音ミク】…【オリジナル曲】）は 30〜40 字が普通で、右に 2 列で置くと 1 行 15 字ほどしか
      入らず、2 行では「…」になる（利用者の 4x4・16:9 で 16 曲中 5 曲）。行数の分だけ他の曲の
      文字が小さくなるので、縮めれば入る題までは増やさない
    - 判定は**字ごとに 1px に丸めた幅が段の TITLE_ROWS3（2.25）倍を超えるか**。実際に折って縮めて測る
      判定にすると、折る位置の 1 字の差で PIL と Canvas が食い違う（200 通りで 27 件ずれた）。
      2.0〜2.25 倍の題は折り方しだいで入らないことがあり、そのときは今までどおり「…」で切る
    """
    # **幅は字ごとに 1px へ丸めた和で見る**（2026-09-18）。題を 1 本の文字列として測ると PIL と Canvas で
    # 1px 未満だけ違い、境目の題で「1 行に入る・入らない」が割れて、行数から決まる文字の大きさがずれた
    # （利用者の 25 曲を 5x5・16:9 に入れた実測で、サーバー 55px・ブラウザ 57px）
    avail = max(1.0, max_w - _num_w(font_s))
    plan = []
    # **曲の入ったマスだけ**（空きマスの行を作らない。2026-09-25）。以前は空きマスにも番号だけの行を 1 つ取っていた
    for t in _songs(doc):
        # **アーティスト名も 2 行まで折る**。0.8 に縮めれば入るぶんは 1 行のまま（行を増やさない）
        rows = 1 + _artist_rows(_one_line(t.artist), font_s, avail)
        title = _one_line(t.title)
        tw = sum(char_w("bold", max(12, font_s), ch) for ch in title)
        if tw > avail:
            rows += 1
            if tw > avail * TITLE_ROWS3:
                rows += 1
        plan.append(rows)
    return tuple(plan)


# 曲名を折るときに切りたい場所。**閉じ括弧の「後ろ」で折る**ので、括弧の中身が上下に分かれない
_BREAK_AFTER = "　 ・）)］]】〉》」』"
_BREAK_BEFORE = "（([［[【〈《「『／/～-—"
# 記号の切れ目を使う条件: 1 行目が「真ん中」のこの割合に届くこと。届かないなら字の途中で折る
SPLIT_HEAD_MIN = 0.45


def _break_at(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_w: float) -> tuple[str, str]:
    """切れ目が見つからないときの保険。max_w に収まるところまで入れて、字の途中で折る。"""
    cut = len(text)
    while cut > 1 and d.textlength(text[:cut], font=f) > max_w:
        cut -= 1
    return text[:cut].rstrip(), text[cut:].lstrip()


# 行頭に来てはいけない字（長音・小書き・句読点）。ここで折ると「アンハッピ／ーリフレイン」のように読めなくなる
_NO_HEAD = "ーぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ゛゜、。，．・！？!?）)］]」』】〉》"
_LATIN = re.compile(r"[A-Za-z0-9'’]")


def _break_ok(text: str, i: int) -> bool:
    """i の手前で折ってよいか。長音・小書きの前と、英単語の途中（Child's G|arden）は避ける（frontend の breakOk と同じ）。"""
    if text[i] in _NO_HEAD:
        return False
    return not (_LATIN.match(text[i - 1]) and _LATIN.match(text[i]))


def _break_near(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont,
                max_w: float, target: float) -> tuple[str, str]:
    """字の途中で折る。**行の真ん中にいちばん近い所**を選ぶ（`_break_at` は右端まで詰める）。
    **折ってよい位置（`_break_ok`）を先に探し**、無いときだけどこでも折る（2026-09-17）。"""
    best: tuple[float, int] | None = None
    fit: tuple[float, int] | None = None     # **2 行目も収まる**位置の中でいちばん真ん中に近いもの
    best_any: tuple[float, int] | None = None
    fit_any: tuple[float, int] | None = None
    for i in range(1, len(text)):
        w1 = d.textlength(text[:i], font=f)
        if w1 > max_w:
            break
        score = abs(w1 - target)
        ok = _break_ok(text, i)
        fits = d.textlength(text[i:].lstrip(), font=f) <= max_w
        if best_any is None or score < best_any[0]:
            best_any = (score, i)
        if fits and (fit_any is None or score < fit_any[0]):
            fit_any = (score, i)
        if not ok:
            continue
        if best is None or score < best[0]:
            best = (score, i)
        if fits and (fit is None or score < fit[0]):
            fit = (score, i)
    best = fit or best or fit_any or best_any
    if best is None:
        return _break_at(d, text, f, max_w)
    i = best[1]
    return text[:i].rstrip(), text[i:].lstrip()


def _split_title3(d: ImageDraw.ImageDraw, title: str, f: ImageFont.FreeTypeFont, font_s: int,
                  max_w: float) -> tuple[str, str, str]:
    """曲名を 3 行に分ける。1/3 の所で折ってから残りを半分に折る。**最後の行が縮めても入らないなら、
    最初の折り目を記号ではなく字の途中（ちょうど 1/3）にして折り直す**。
    「【調教すげぇ】初音ミク『FREELY TOMORROW』(完成)【オリジナル曲】」を 】 で折ると 6 字＋14＋14 で
    3 行目が「…」になるが、1/3 なら 11＋11＋12 で入る。折り直しても入らなければ記号のほう"""
    l1, rest = _split_title(d, title, f, max_w, 1 / 3)
    l2, l3 = _split_title(d, rest, f, max_w)
    if l3 and not _fits_shrunk(d, l3, f, font_s, max_w):
        b1, brest = _break_near(d, title, f, max_w, d.textlength(title, font=f) / 3)
        b2, b3 = _split_title(d, brest, f, max_w)
        if not b3 or _fits_shrunk(d, b3, f, font_s, max_w):
            return b1, b2, b3
    return l1, l2, l3


def _split_title(d: ImageDraw.ImageDraw, title: str, f: ImageFont.FreeTypeFont, max_w: float,
                 frac: float = 0.5) -> tuple[str, str]:
    """曲名を 2 行に分ける。**なるべく 2 行の長さがそろう位置**で折る。

    切れ目の候補は「区切りに使える記号の前後」。そのうち**行の真ん中にいちばん近いもの**を選ぶ。
    「(feat. …)」の手前は少し優遇する（そこで折れれば曲名の本体が単独で読めるため）。
    候補が無ければ字の途中で折る。
    """
    total = d.textlength(title, font=f)
    # frac は 1 行目に入れたい割合。3 行に折るときは 1/3（真ん中で折ってから残りを半分にすると、
    # 1 行目だけ長くて 2・3 行目が単語の途中で切れる。「マザーグー／ス』」になっていた）
    target = total * frac
    head, _feat = _split_feat(title)
    feat_at = len(head) + 1 if _feat else -1   # 括弧の手前（空白を 1 つ挟む）
    best: tuple[float, int, bool] | None = None   # (真ん中からの遠さ, 位置, 「(feat. …)」の手前か)
    fit: tuple[float, int, bool] | None = None    # **2 行目も収まる**候補だけを集めたもの
    for i in range(1, len(title)):
        if not (title[i - 1] in _BREAK_AFTER or title[i] in _BREAK_BEFORE):
            continue
        w1 = d.textlength(title[:i].rstrip(), font=f)
        if w1 > max_w:
            break
        score = abs(w1 - target)
        is_feat = i == feat_at or (feat_at > 0 and abs(i - feat_at) <= 1)
        if is_feat:
            score *= 0.6   # 「(feat. …)」の手前は優遇。ちょうどよい位置なら選ばれる
        if best is None or score < best[0]:
            best = (score, i, is_feat)
        # **2 行目が収まるかも見る**。真ん中に近いだけで選ぶと、1 行目が収まっても
        # 2 行目がわずかにはみ出して「…」で切れる（`I Love Love You (Love Love Super Dimension mix)` が
        # 「Love Super Dimension…」になっていた）。収まる候補があるならそちらを使う
        if d.textlength(title[i:].lstrip(), font=f) <= max_w and (fit is None or score < fit[0]):
            fit = (score, i, is_feat)
    best = fit or best
    # **偏りすぎる切れ目は使わない**。括弧や【】が題の先頭近くにあると、そこしか候補が無いことがあり、
    # 「いき」＋「(稚拙な詩歌への…」のように 1 行目が数文字だけになる（利用者の画像で発覚）。
    # 1 行目が真ん中の `SPLIT_HEAD_MIN` に届かないなら、字の途中でも真ん中に近い所で折る
    # 「(feat. …)」の手前だけは偏っていても使う（曲名の本体が単独で読めるほうが分かりやすい）
    if best is not None and (best[2]
                             or d.textlength(title[:best[1]].rstrip(), font=f) >= target * SPLIT_HEAD_MIN):
        i = best[1]
        l1, l2 = title[:i].rstrip(), title[i:].lstrip()
        # **記号で折った 2 行目が縮めても入らないなら、字の途中で折り直す**（2026-09-16）。
        # 「【巡音ルカ】ダブルラリアット【オリジナル】」を 】 で折ると 6 字＋15 字になり 2 行目が「…」で
        # 切れる。真ん中で折れば 10 字＋11 字で全部入る。折り直しても入らないなら記号の切れ目のまま
        # （単語の途中で折るだけ損）。「(feat. …)」の手前は今までどおり（本体が単独で読めるほうを取る）
        if fit is None and not best[2] and not _fits_shrunk(d, l2, f, f.size, max_w):
            alt = _break_near(d, title, f, max_w, target)
            if alt[1] and _fits_shrunk(d, alt[1], f, f.size, max_w):
                return alt
        return l1, l2
    return _break_near(d, title, f, max_w, target)


def _clip_to(text: str, f: ImageFont.FreeTypeFont, max_w: float) -> str:
    """max_w に収まるところまで切って「…」を付ける。"""
    if f.getlength(text) <= max_w:
        return text
    while text and f.getlength(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


def _flow_rows(doc: GridDoc, font_s: int, max_w: float,
               seg_w: list[float] | None = None, max_rows: int | None = None) -> list[FlowRow]:
    """流し込んだときの各行を返す。

    `seg_w` を渡すと**行ごとに幅が変わる**（マスの塊を避ける回り込み。`_wrap_plan` から使う）。
    `max_rows` はそこまで作ったら打ち切る合図で、「入るかどうか」を試すときだけ使う。

    **折り返しは字の単位**。曲の単位で折ると行の頭がいつも番号になって、規則的に見えてしまう。
    字で折れば文章のように流れる。そのかわりサーバー（PIL）とブラウザ（Canvas）で
    折り返す位置がわずかにずれる（字幅の計り方が違うため）。内容は同じで、位置だけの違い。

    行には「使った幅」と「曲の切れ目の数」を添える。描画側が余った幅を切れ目に配って
    右端をそろえる。
    """
    sizes = {"num": ("pixel", rnd(font_s * 0.8)), "title": ("bold", font_s), "artist": ("regular", font_s)}
    fonts = {k: font(*v) for k, v in sizes.items()}
    gap = float(rnd(fonts["title"].getlength("　")))   # 曲と曲のあいだは全角空白 1 つぶん
    rows: list[FlowRow] = []
    cur: list[tuple[str, str]] = []
    x = 0.0
    gaps = 0
    # 今から埋める行の幅。回り込みでは行ごとに違う（足りなくなったら最後の幅を使い回す）
    def cw() -> float:
        if not seg_w:
            return max_w
        return seg_w[len(rows)] if len(rows) < len(seg_w) else seg_w[-1]

    def full() -> bool:
        return max_rows is not None and len(rows) >= max_rows

    def flush() -> None:
        nonlocal cur, x, gaps
        if cur:
            rows.append(FlowRow(cur, x, gaps))
        cur, x, gaps = [], 0.0, 0

    def tail_back(kind: str, chars: list[str], j: int, j0: int) -> str:
        """chars[j] で折るとき、語の尻尾だけがこぼれるなら、行に置いた語の頭を外して返す（FLOW_TAIL）"""
        nonlocal x
        if chars[j] in FLOW_WORD_SEP:
            return ""
        k = j
        while k < len(chars) and chars[k] not in FLOW_WORD_SEP:
            k += 1
        p = j
        while p > j0 and chars[p - 1] not in FLOW_WORD_SEP:
            p -= 1
        n = j - p
        if k - j > FLOW_TAIL or n == 0 or n > FLOW_WORD_MAX or (p == j0 and j0 > 0):
            return ""
        # 曲名の最初の語は送らない（番号だけが行末に取り残される）
        if kind == "title" and all(c in " 　" for c in chars[:p]):
            return ""
        if not cur or cur[-1][0] != kind or len(cur[-1][1]) < n or (len(cur) == 1 and len(cur[-1][1]) == n):
            return ""
        head = "".join(chars[p:j])
        cur[-1] = (kind, cur[-1][1][:-n])
        x -= sum(char_w(*sizes[kind], ch) for ch in head)
        # 行末に残る空白も外す（見えない字のぶん右端がそろわなくなる）
        while cur and cur[-1][1] and cur[-1][1][-1] in " \u3000":
            x -= char_w(*sizes[cur[-1][0]], cur[-1][1][-1])
            cur[-1] = (cur[-1][0], cur[-1][1][:-1])
        while cur and not cur[-1][1]:
            cur.pop()
        return head

    def put(kind: str, text: str) -> None:
        nonlocal x, cur
        chars = list(text)
        j0 = 0   # この text の中で、今の行が始まった位置（行の途中から始まったなら 0）
        for j, ch in enumerate(chars):
            if full():
                return
            # **折り返しの判定は 1px に丸めた字幅で行う**。PIL と Canvas の字幅は 1px 未満だけ違い、
            # 生の値で足していくと境目の字で折る・折らないが入れ替わり、そこから先の行が全部ずれる。
            # 丸めればほとんどの字で同じ値になり、両者が同じ位置で折る（描くときは実寸のまま）
            w = char_w(*sizes[kind], ch)
            if x + w > cw() and cur:
                moved = tail_back(kind, chars, j, j0)
                flush()
                j0 = j
                if moved and not full():
                    cur = [(kind, moved)]
                    x = float(sum(char_w(*sizes[kind], c) for c in moved))
                    j0 = j - len(moved)
                    if x + w > cw():   # 送った先の行が狭くて入らないなら、そこでまた折る
                        flush()
                        j0 = j
            if cur and cur[-1][0] == kind:
                cur[-1] = (kind, cur[-1][1] + ch)
            else:
                cur.append((kind, ch))
            x += w

    # 番号は曲の入ったマスの序数（空きマスは飛ばして詰める。2026-09-25）
    for i, t in enumerate(_songs(doc)):
        if full():
            break
        if cur:
            # 曲の切れ目。**行末に来た切れ目は数えない**（数えると、その行の幅に使っていない
            # 送りが入り、余りの配り方がずれる）
            if x + gap > cw():
                flush()
            else:
                x += gap
                gaps += 1
        num, title = f"{i + 1:02d}", _one_line(t.title)
        # **番号だけが行末に取り残されないようにする**。番号と曲名の頭 2 字が入らないなら先に折る。
        # **ここも 1 字ごとの丸めた幅で測る**。文字列まるごとの実寸で比べると PIL と Canvas で
        # 判定が入れ替わり、行数が 1 つずれる。行数は中央寄せの量に効くので、**全体がずれる**
        head = (sum(char_w(*sizes["num"], ch) for ch in num)
                + sum(char_w(*sizes["title"], ch) for ch in " " + title[:2]))
        if cur and x + head > cw():
            flush()
        put("num", num)
        put("title", " " + title)
        if t.artist:
            put("artist", " " + _one_line(t.artist))
    flush()
    return rows


def _last_fill(p: "WrapPlan") -> float:
    """流し込みの最後の行がどれだけ埋まっているか（0〜1）。frontend の lastFill と同じ。"""
    if not p.rows or not p.segs:
        return 1.0
    seg_w = p.segs[min(len(p.rows), len(p.segs)) - 1][2]
    return min(1.0, p.rows[-1].width / seg_w) if seg_w > 0 else 1.0


def _refit_flow(build, plan: "WrapPlan") -> "WrapPlan":
    """回り込み・柱・帯を、**決めた枠と字のまま、曲の順で組み直す**（2026-09-25）。frontend の refitFlow と同じ。

    枠と字は `_canon` の並びで決めてあるので、曲の順番では変わらない。流し込みの行数は順番で 1〜2 行
    変わることがあり（折り返す位置が変わる）、入りきらないときは**行の高さを字の `FLOW_SQUEEZE` 倍まで詰める**。
    それでも入らないとき（実測では起きない）だけ字を 1px ずつ下げる。描けない行を捨てるよりはよい。
    `build(lh, fs)` は行の高さ・字を差し替えて組む関数（None ならそのまま）
    """
    got = build(None, None)
    if got is not None:
        return got
    for lh in range(plan.line_h - 1, math.ceil(plan.font_s * FLOW_SQUEEZE) - 1, -1):
        got = build(lh, None)
        if got is not None:
            return got
    for fs in range(plan.font_s - 1, max(8, plan.font_s * 3 // 4), -1):
        got = build(None, fs)
        if got is not None:
            return got
    return plan


def _fills_width(p: "WrapPlan", gw: int) -> bool:
    """マスの塊が枠の横いっぱい（余白を除いた幅の 95% 以上）に入っているか。"""
    return gw >= (p.W - p.pad * 2) * 0.95


class WrapPlan(NamedTuple):
    W: int; H: int; scale: float; font_s: int; line_h: int
    title_size: int; title_h: int
    pad: int; top: int; gx: int; gy: int
    segs: tuple[tuple[int, int, int], ...]
    rows: list[FlowRow]
    use: float = 1.0      # 文字の置き場所のうち実際に使った割合（帯・柱でだけ 1 未満になる）
    rows_mode: bool = False   # 段を 1 曲ずつマスの横に並べる（柱・1 列の並びだけ）
    pct: int = 0          # 枠が塊の何 % か（回り込みで、枠を変えずに字を詰め直すときに使う）
    tx: int = 0           # タイトルの左端（0 なら pad）。比率なしの「マスごと」は右の列の上に置く
    inline: bool = False  # マスごとの 1 行型（曲名とアーティスト名を 1 行に、アーティスト名は段の右端）
    seg_fs: int = 0       # 回り込み: 段の最小幅を測った字（組み直すときに同じ段を作るため）
    target: int = 0       # 柱・帯: 出力での字の目標（組み直すときに同じ枠を作るため）


# ---- 帯・柱: マスの塊を枠の辺にぴったり付ける組み方 ----
# 塊の縦横比と枠の縦横比が極端に食い違うとき（1 列の並びを正方形に、32 列の並びを 9:16 に、など）、
# 塊を真ん中に置く回り込みでは四辺に細い余白が残り、そのぶんマスが小さくなる。
# **塊を辺にぴったり付け、残りを 1 つの大きな長方形として文字に使う**と、マスも文字も大きくできる。
#   柱（column）… 塊を左端に立て、上下も枠いっぱいに伸ばす。右の 1 本の段にタイトルと曲名リスト
#   帯（band）  … タイトルを上端に、その下に枠の横いっぱいの塊、さらにその下に曲名リスト
# **塊が片方の辺を使い切るので枠の大きさは一意に決まる**（回り込みのような二分探索が要らない）。
# 決めるのは文字の大きさだけ
SLAB_ASPECT = 4.0       # 塊と枠の縦横比がこの倍率以上ずれているときだけ使う
SLAB_MIN_FONT = 14      # 出力での曲名がこれを下回るなら使わない
SLAB_TITLE_SCALE = 2.4  # タイトルは本文の何倍か
SLAB_TITLE_MIN = 1.3    # 本文に対する下限。これを割るなら使わない
SLAB_TITLE_MAX = 0.28   # 帯のとき、タイトルは曲名リストの場所の高さのこの割合まで
# **柱のときはタイトルの帯が枠の高さをそのまま押し広げる**（塊の高さは決まっているので、
# 帯のぶんだけ枠が縦に伸び、そのぶんマスが小さくなる）。塊の高さに対する割合で頭打ちにする。
# ここを緩めると本文は大きくなるがマスが目に見えて小さくなる（1x8 を 1:1 で 273 → 213px）
SLAB_TITLE_BAND = 0.10
# **柱で 1 列の並びのときは、曲名をマス 1 つ 1 つの横に並べる**（流し込まない）。
# マスと曲名が 1 対 1 で並ぶので、どのジャケットがどの曲か一目で分かる。
# 曲名の大きさは 1 マスの送りから決め、出力で `SLAB_ROW_MIN` を下回るなら流し込みに戻す
# （マスが小さくなるほど 1 曲ぶんの高さも縮むため。1x32 を 16:9 にすると 12px になる）
SLAB_ROW_FONT = 0.30
# **1 列の並び（1xN）は 1 曲にマス 1 つぶんの高さがあるので、字を大きく取る**（2026-09-20、利用者の 1x32 の共有で指摘）。
# 0.30 だとスマホの出力（最大辺 2000px）で 17px になって下限を割り、段落のような流し込みに落ちていた。
# 0.42 で 1x32・9:16 が 24px（曲名の下にアーティスト名を置いても 1 曲ぶんの高さに収まる）
SLAB_ROW_FONT1 = 0.42
# **1 列の並びは、曲名とアーティスト名を 1 行に並べ、アーティスト名を右端にそろえる**（2026-09-20、利用者の選択）。
# 曲名の下にアーティスト名を置く形だと、4:5・1:1 で画像の右半分が空いていた。1 行に並べれば字を 1 曲ぶんの
# 高さの半分まで取れる。**全曲が 1 行に入る大きさまで下げ**、2 行の形（SLAB_ROW_FONT1）より小さくなるなら 2 行の形
SLAB_ROW_INLINE = 0.5
# 1 列の並びで、曲名（とアーティスト名）が 1 マスの高さのこの割合に収まる字まで下げる。残りが曲と曲のあいだ
# （frontend の ROW_FILL と同じ。2026-09-22、利用者の指摘で 0.94 → 0.8）
ROW_FILL = 0.8
# 3 行になる曲の行の送り（字の大きさに対する比）。1.12 では詰まって見えた（2026-09-22、利用者の指摘）
ROW3_STEP = 1.3
# **流し込みの下限（20px）より少し低くてよい**。流し込みは字を詰めるので 20px を切ると読めないが、
# マスごとは 1 曲 1 行で行間も広いため 18px でも読める。20px のままだと 3x11 を 1:1 にしたときに
# 19.5px で弾かれ、その並びだけコの字になっていた（利用者の指摘）
SLAB_ROW_MIN = 18
# **比率なしのとき**の段の幅（文字の大きさの何倍か＝だいたい何字入るか）。比率が決まっていれば
# 枠から残りが決まるが、比率なしでは決め手が無いので字数で決める。
# **文字を測って決めてはいけない**（PIL と Canvas で幅が数 px 違い、枠ごとずれる）
SLAB_ROW_SEG = 30
# ただし**段の幅は塊の高さまで**。曲が少ないと 30 字ぶんの段のほうが塊よりずっと長くなり、
# 枠が横に伸びて**マスが潰れる**（1x3 を比率なしで 600 → 223px にしていた）。
# 塊の高さで頭打ちにすると、短い並びは今までどおりの大きなマス、長い並びは広い段になる
SLAB_ROW_WIDE = 0.75
# **曲名の大きさは、段の幅にこれだけの字が入るところまで下げる**。1 曲ぶんの高さから決めるので、
# 曲が少ないと 1 曲にマス 1 つぶん（600px）が割り当たり、文字が出力 185px まで育っていた。
# 段の幅は塊の高さで頭打ちなので広がらず、曲名が 2〜3 文字で「…」に切れていた（1x1・1x2）。
# 曲名は 2 行まで折れるので、1 行 14 字あれば 28 字ぶん入る
SLAB_ROW_FIT = 14
# **この列数までは「マスごと」に並べられる**。1 段ぶんの高さに列の数だけ曲名を積むので、
# 列が増えるほど 1 曲ぶんが薄くなる（3 列で 1/3）。4 列にすると出力の文字が読めない大きさになる
SLAB_ROW_MAX_COLS = 3
# 横一列に近い並び（N×1 など）では、塊を上に敷いて曲名を 1 曲 1 行の縦一列で下に置く。
# この段数まで（段が増えると曲数が増えて縦に入らなくなる）
SLAB_STACK_MAX_ROWS = 2
# **曲がこれより多いときは縦一列にしない**。1 曲 1 行は「少ない曲の一覧」として読みやすいが、
# 30 曲を超えると単なる長い列になり、同じ 32xN のグループの中で 32x1 だけ見た目が変わってしまう
# （利用者の指摘）。多いときは今までどおり流し込んで、塊の下の場所を隅々まで使う
SLAB_STACK_MAX_SONGS = 16
SLAB_STACK_TABLE_COLS = 4  # 帯の下の表（`_slab_stack` の 2 回目）の列の上限
# **列の少ない表を優先する**（2026-09-20、利用者の選択）。字の差がこの割合以内なら列の少ないほう。
# 32x1・1:1 は 2 列（28px）より 1 列（24px）のほうが高さを使い切り、帯と表のあいだが大きく空かない
SLAB_STACK_FEW_COLS = 0.85
SLAB_STACK_LINE = 2.4      # 1 曲ぶんの高さ（曲名の行 + アーティストの行）。文字の大きさに対する倍率
# 段の中で横に並べるときの、1 曲ぶんの最小の幅（文字の大きさの何倍か＝だいたい何字入るか）
SLAB_ROW_BESIDE_SEG = 12
# 出力での曲名の大きさ。大きいほうから試して、**入る中でいちばん大きいもの**を採る
SLAB_TARGET_PX = (96, 84, 72, 64, 56, 48, 42, 36, 32, 28, 24, 20, 18, 16, 14)
# **文字の置き場所をこれだけ使えていないと、マスが同じ大きさのときは回り込みに譲る**。
# 曲が少ないうえに塊が細長いと（11x1 を 9:16 など）、比率で決まる縦長の枠に対して
# 曲名リストが短く、下に大きな空白が残る。回り込みなら塊のまわりに散らせて埋まる
SLAB_USE_MIN = 0.7
# マスが**はっきり**大きくなるとき（この倍率以上）は、置き場所が余っていても辺に付けるほうを採る。
# 1% ほどの差で選んでしまうと、見た目は同じ大きさなのに空白だけ増える
SLAB_CELL_GAIN = 1.02
# 帯・柱は回り込みよりマスがこの割合まで小さくても採る（並びのほうが分かりやすいため）
SLAB_PREFER = 0.98


def _slab_frame(fixed: int, ratio: float, m: int, vertical: bool, gap: int, frac: float = PAD_FRAC["normal"]) -> tuple[int, int, int]:
    """塊が使い切る辺の長さ `fixed` から枠と余白を出す。

    余白は「枠の短いほうの辺の `frac`（ふつうは 3.5%）」（`_frame` と同じ規則）なので、枠と余白が互いを参照する。
    余白 0 から始めて 3 回回せば十分収束する。
    `vertical` は塊が縦（高さを使い切る）か横（幅を使い切る）か。
    """
    pad = m
    for _ in range(3):
        if vertical:
            H = fixed + pad * 2
            W = rnd(H * ratio)
        else:
            W = fixed + pad * 2
            H = rnd(W / ratio)
        pad = _mod_pad(max(m, rnd(min(W, H) * frac)), gap)
    if vertical:
        H = fixed + pad * 2
        W = rnd(H * ratio)
    else:
        W = fixed + pad * 2
        H = rnd(W / ratio)
    return W, H, pad


def _title_cap(title: str, t_size: int, W: int, H: int, pad: int, floor: int = 0) -> int:
    """タイトルの大きさを枠に収まる範囲に抑える。**どの組み方でも同じ規則**。

    - 幅 … 「…」で切れない大きさまで下げる（`_title_fit`）
    - 大きさ … **枠の短い辺の `WRAP_TITLE_FRAME` まで**。タイトルは本文に連動して伸びるので、
      曲が少ないと極端に大きくなる（18x1 を 1:1 にすると出力 288px あった）。
      1:1 なら 144px、16:9 / 9:16 なら 81px が天井になる
    - ただし **`floor`（たいていは本文の何倍か）より小さくはしない**。曲が少ないと本文が大きいので、
      天井だけ当てると**タイトルが本文より小さくなる**（1x1 を 16:9 にすると本文の 0.42 倍だった）。
      幅で切れない範囲でだけ持ち上げる。天井のあとに大きさを見直す組み方（回り込み・帯）では
      `floor` を渡さず、見直しのほうに任せる
    """
    fit = _title_fit(title, t_size, W - pad * 2)
    return max(min(fit, rnd(min(W, H) * WRAP_TITLE_FRAME)), min(fit, floor))


def _title_fit(title: str, t_size: int, avail_w: int) -> int:
    """タイトルが `avail_w` に収まる最大の大きさ。

    **字幅は大きさに比例する**ので 1 回の割り算で出る。これが無いと、枠が縦長のときに
    タイトルだけ極端に大きくなって「…」で切れていた（7x1 を 9:16 にすると
    幅 1350px に対して 288px のタイトルが入り、「私を構…」になっていた）。
    """
    if not title or t_size <= 0 or avail_w <= 0:
        return t_size
    w = _title_width(title, t_size)
    return t_size if w <= avail_w else max(8, int(t_size * avail_w / w))


def _slab_rows(doc: GridDoc, gw: int, gh: int, title_h: int, ratio: float | None, m: int,
               max_side_v: int, beside: bool = False, inline: bool | None = None) -> WrapPlan | None:
    """**曲名をマスの横に、マスと同じ並び順で置く**割り付け（1〜3 列の並び）。

    塊は左端に立て、その右の段に曲名を置く。**マスの段 1 つぶんの高さに、その段のマスと
    同じ数だけ曲名を積む**（3 列なら 1・2・3 曲目、4・5・6 曲目、…）。どのジャケットが
    どの曲かが目で追える。

    枠の大きさは塊とタイトルの帯だけで決まり、曲名の大きさも 1 曲ぶんの高さから決まるので、
    探索は要らない。出力での曲名が小さくなりすぎるときだけ None を返して流し込みに戻す。
    **比率なし**（`ratio is None`）でも使える。そのときは段の幅を `SLAB_ROW_SEG` 字ぶんに取り、
    枠は中身に合わせて伸ばす（比率が無いので枠から残りを逆算できない）。
    """
    cols = doc.cols
    if cols > SLAB_ROW_MAX_COLS:
        return None
    # **1 列の並びは、まず 1 行型を試す**（SLAB_ROW_INLINE）。合わなければ 2 行の形
    if inline is None:
        if cols == 1 and not beside:
            rp = _slab_rows(doc, gw, gh, title_h, ratio, m, max_side_v, beside, True)
            if rp is not None:
                return rp
        inline = False
    pitch = cell_h(doc) + doc.options.gap      # マスの段 1 つぶんの送り（**高さ**で決まる）
    # **段の中で縦に積むか、横に並べるか**。縦に積むほうが 1 行が長く取れて読みやすいので既定。
    # ただし段が多いと 1 曲ぶんが薄くなりすぎるので（2x32 で出力 10.8px）、そのときは横に並べる
    # （マスと同じ「左から右へ、次の段へ」の順になる）
    side_by_side = beside
    per = pitch if side_by_side else rnd(pitch / cols)   # 曲名 1 曲ぶんの高さ
    font_s = rnd(per * (SLAB_ROW_INLINE if inline else SLAB_ROW_FONT1 if cols == 1 and not side_by_side else SLAB_ROW_FONT))
    # **段の幅に曲名が入らない大きさにはしない**。1 曲ぶんの高さから決めるので、曲が少ないと
    # 1 曲にマス 1 つぶん（600px）が割り当たり、文字が出力 185px まで育っていた（1x1・1x2）。
    # 段の幅は塊の高さから決まるので広がらず、曲名が数文字で「…」に切れる。
    # **段の幅に `SLAB_ROW_FIT` 字が入る大きさ**まで下げる。文字を下げると帯も枠も縮むので 3 回回す
    for _ in range(3):
        wgap = rnd(font_s * WRAP_GAP_EM)
        # タイトルの帯は塊の高さの `SLAB_TITLE_BAND` まで。**ただし本文の `SLAB_TITLE_MIN` 倍は必ず確保する**
        # （マスが少ないと 10% では足りず、短い並びだけこの組み方を使えなくなる）
        need = rnd(math.ceil(font_s * SLAB_TITLE_MIN) * 1.9)
        cap = max(rnd(gh * SLAB_TITLE_BAND), need)
        t_h = min(rnd(font_s * SLAB_TITLE_SCALE * 1.9), cap) if title_h else 0
        t_size = rnd(t_h / 1.9) if title_h else 0
        if title_h and t_size < font_s * SLAB_TITLE_MIN:
            return None
        top_h = t_h + (wgap if t_h else 0)
        if ratio is None:
            # 余白は枠の短い辺の 3.5%（`_frame` と同じ規則）で、枠と余白が互いを参照する。0 から 3 回回す
            seg_w = min(font_s * SLAB_ROW_SEG, max(LIST_MIN_COL, rnd(gh * SLAB_ROW_WIDE)))
            pad = m
            for _ in range(3):
                W, H = gw + wgap + seg_w + pad * 2, top_h + gh + pad * 2
                pad = _mod_pad(max(m, rnd(min(W, H) * _pad_frac(doc))), doc.options.gap)
            W, H = gw + wgap + seg_w + pad * 2, top_h + gh + pad * 2
        else:
            W, H, pad = _slab_frame(gh + top_h, ratio, m, True, doc.options.gap, _pad_frac(doc))
            seg_w = (W - pad) - (pad + gw + wgap)
        if W <= 0 or H <= 0:
            return None
        lim = rnd(seg_w / SLAB_ROW_FIT)
        if font_s <= lim:
            break
        font_s = max(SLAB_ROW_MIN, lim)
    scale = min(1.0, max_side_v / max(W, H))
    if font_s * scale < SLAB_ROW_MIN:          # 1 曲ぶんの高さが足りない → 流し込みに戻す
        return None
    if title_h:                                # 枠が決まったので天井を当てる
        # **本文より小さくはしない**。この組み方は天井を当てたあとに大きさを見直さないので、
        # 下限を渡さないと 1x1・16:9 で本文の 0.42 倍まで潰れる
        t_size = _title_cap(_one_line(doc.title), t_size, W, H, pad,
                            rnd(math.ceil(font_s * SLAB_TITLE_MIN)))
        t_h = rnd(t_size * 1.9)
        top_h = t_h + wgap
    gx, gy = pad, pad + top_h
    x0 = gx + gw + wgap
    if seg_w < LIST_MIN_COL:
        return None
    if inline:
        # 全曲が 1 行に入る大きさまで下げる。2 行の形より小さくなる・読めない大きさになるなら使わない
        while font_s > 8 and not _inline_one_line(doc, font_s, seg_w):
            font_s -= 1
        if font_s < rnd(per * SLAB_ROW_FONT1) or font_s * scale < SLAB_ROW_MIN:
            return None
    # **比率なしは、タイトルを右の列（曲名リスト）の上に置く**（2026-09-19、利用者の指定）。
    # 帯の高さはそのまま（マスと曲名の段のそろいを崩さない）で、置く場所と幅だけ右の列に合わせる。
    # 右の列の幅に入る大きさが本文の SLAB_TITLE_MIN 倍を割るなら、今までどおり枠の上端いっぱい
    tx = 0
    if title_h and ratio is None:
        fit = _title_fit(_one_line(doc.title), t_size, seg_w)
        if fit >= math.ceil(font_s * SLAB_TITLE_MIN):
            t_size, tx = min(t_size, fit), x0
    if side_by_side:
        # 段のマスと同じ並びで横に置く（マスと同じ「左から右へ、次の段へ」の順）
        col_w = (seg_w - wgap * (cols - 1)) // cols
        if col_w < font_s * SLAB_ROW_BESIDE_SEG:
            return None
        segs = tuple((x0 + (i % cols) * (col_w + wgap), gy + (i // cols) * pitch, col_w)
                     for i in range(len(doc.cells)))
    else:
        # 段のマスと同じ数だけ曲名を積む。余った端数は段の中で上下に分ける
        off = rnd((pitch - per * cols) / 2)
        segs = tuple((x0, gy + (i // cols) * pitch + off + (i % cols) * per, seg_w)
                     for i in range(len(doc.cells)))
    return WrapPlan(W, H, scale, font_s, per, t_size, t_h, pad, pad, gx, gy, segs, [], 1.0, True, tx=tx, inline=inline)


def _slab_stack(doc: GridDoc, gw: int, gh: int, title_h: int, ratio: float, m: int,
                max_side_v: int) -> WrapPlan | None:
    """**塊を上に敷き、曲名を 1 曲 1 行の縦一列で下に置く**割り付け（段の少ない横長の並び）。

    7x1 を 9:16 に入れたときのように、塊が横一列だと下に大きな空きが残る。曲名を流し込むと
    行が長くて読みにくいので、**1 曲 1 行で縦に積み、まとめて真ん中に置く**（利用者の提案）。
    並びは「タイトル → 塊 → 曲名リスト」。曲名の大きさは、縦に全部入って、かつ 1 行が
    `WRAP_MIN_SEG` 字ぶんの幅を持てる中でいちばん大きいものを選ぶ。
    """
    # **曲の入ったマスだけを積む**（空きマスの行を作らない。2026-09-25）。段は曲の序数で並ぶ
    n = len(_songs(doc))
    if not n or doc.rows > SLAB_STACK_MAX_ROWS:
        return None
    W, H, pad = _slab_frame(gw, ratio, m, False, doc.options.gap, _pad_frac(doc))
    if W <= 0 or H <= 0:
        return None
    scale = min(1.0, max_side_v / max(W, H))
    seg_w = W - pad * 2
    # 1 回目: 曲名の下にアーティスト名を置く縦一列（SLAB_STACK_MAX_SONGS 曲まで）。
    # 2 回目: **1 行型の表**（2026-09-20、利用者の 32x1 の共有 5 枚）。縦一列に入らない並びは、曲名が段落のように
    # 流れて読みにくかった。番号・曲名・右端にアーティスト名の 1 行を、帯の下に 1〜SLAB_STACK_TABLE_COLS 列で並べる。
    # 全曲が 1 行に入る大きさだけ使う（「…」で切らない）。**1 回目で組める並び（7x1 など）の見た目は変えない**
    if n <= SLAB_STACK_MAX_SONGS:
        plan = _slab_stack_try(doc, gh, title_h, n, W, H, pad, scale, seg_w, False)
        if plan is not None:
            return plan
    # 表: 列の数ごとにいちばん大きい字を出し、いちばん大きい字の SLAB_STACK_FEW_COLS 以上ある中で列のいちばん少ないもの
    plans = [p for k in range(1, SLAB_STACK_TABLE_COLS + 1)
             if (p := _slab_stack_try(doc, gh, title_h, n, W, H, pad, scale, seg_w, True, k)) is not None]
    if not plans:
        return None
    top = max(p.font_s for p in plans)
    return next(p for p in plans if p.font_s >= top * SLAB_STACK_FEW_COLS)


def _slab_stack_try(doc: GridDoc, gh: int, title_h: int, n: int, W: int, H: int, pad: int,
                    scale: float, seg_w: int, table: bool, k: int = 1) -> WrapPlan | None:
    for target in SLAB_TARGET_PX:
        if target < SLAB_ROW_MIN:
            break
        font_s = max(18, rnd(target / scale))
        if not table and seg_w < font_s * WRAP_MIN_SEG:      # 1 行が短すぎる
            continue
        wgap = rnd(font_s * WRAP_GAP_EM)
        # 帯ではタイトルの帯が枠の高さを押し広げない（高さは比率で決まる）ので、
        # 塊の高さではなく「文字の場所の高さ」で頭打ちにする
        cap = max(rnd((H - pad * 2 - gh) * SLAB_TITLE_MAX), rnd(math.ceil(font_s * SLAB_TITLE_MIN) * 1.9))
        t_h = min(rnd(font_s * SLAB_TITLE_SCALE * 1.9), cap) if title_h else 0
        t_size = _title_cap(_one_line(doc.title), rnd(t_h / 1.9) if title_h else 0, W, H, pad)
        t_h = rnd(t_size * 1.9) if title_h else 0
        if title_h and t_size < font_s * SLAB_TITLE_MIN:
            continue
        gy = pad + t_h + (wgap if t_h else 0)
        y0 = gy + gh + wgap
        avail = (H - pad) - y0
        if table:
            lh = rnd(font_s / TABLE_FONT)
            tgap = rnd(lh * TABLE_GAP_LH)
            rows = math.ceil(n / k)
            cw = (seg_w - tgap * (k - 1)) // k
            if rows * lh > avail or cw < font_s * WRAP_MIN_SEG / 2 or not _inline_one_line(doc, font_s, cw):
                continue
            dy = max(0, (avail - rows * lh) // 2)
            segs = tuple((pad + (i // rows) * (cw + tgap), y0 + dy + (i % rows) * lh, cw) for i in range(n))
            return WrapPlan(W, H, scale, font_s, lh, t_size, t_h, pad, pad, pad, gy,
                            segs, [], 1.0, True, inline=True)
        per = rnd(font_s * SLAB_STACK_LINE)    # 1 曲ぶんの高さ（曲名の行 + アーティストの行）
        if per * n > avail:                    # 縦に入らない → 次の（小さい）大きさ
            continue
        # **中身ごと下げて上下の余白をそろえる**（曲名だけ真ん中に置くと塊から離れて見える）
        dy = max(0, (avail - per * n) // 2)
        segs = tuple((pad, y0 + dy + i * per, seg_w) for i in range(n))
        return WrapPlan(W, H, scale, font_s, per, t_size, t_h, pad, pad, pad, gy,
                        segs, [], 1.0, True)
    return None


def _slab_plan(doc: GridDoc, gw: int, gh: int, title_h: int, ratio: float, m: int,
               max_side_v: int, refit: WrapPlan | None = None) -> WrapPlan | None:
    """塊を枠の辺にぴったり付ける割り付け（柱・帯）。合わなければ None。

    どちらも**タイトルは枠の上端いっぱい**に置き、その下に塊、という並びは同じ。
      柱 … 塊はタイトルの下から枠の下端まで。曲名リストは塊の右、塊と同じ高さの段に流す
      帯 … 塊はタイトルの下に枠の横いっぱい。曲名リストはその下の帯に流す
    """
    ga = gw / gh                       # 塊の縦横比
    if ratio / ga >= SLAB_ASPECT:      # 枠のほうがずっと横長 → 塊を縦に立てる（柱）
        vertical = True
    elif ga / ratio >= SLAB_ASPECT:    # 塊のほうがずっと横長 → 塊を横いっぱいに敷く（帯）
        vertical = False
    else:
        return None
    def build(target: int, lh: int | None = None, fs: int | None = None) -> WrapPlan | None:
        # **タイトルの帯の高さは文字の大きさから決まり、文字の大きさは枠（縮尺）から決まる**ので、
        # 帯 0 から始めて何回か回す。3 回で動かなくなる
        extra = 0
        W = H = pad = font_s = line_h = wgap = t_h = t_size = 0
        for _ in range(4):
            fixed = (gh + extra) if vertical else gw
            W, H, pad = _slab_frame(fixed, ratio, m, vertical, doc.options.gap, _pad_frac(doc))
            if W <= 0 or H <= 0:
                return None
            scale = min(1.0, max_side_v / max(W, H))
            font_s = fs or max(18, rnd(target / scale))
            line_h = lh or rnd(font_s * 1.5)
            wgap = rnd(font_s * WRAP_GAP_EM)
            # タイトルは**本文から決める**（マスの数から決めると枠に対して極端に小さくなる）。
            # ただし枠の高さの SLAB_TITLE_MAX まで
            cap = rnd(gh * SLAB_TITLE_BAND) if vertical else rnd((H - pad * 2 - gh) * SLAB_TITLE_MAX)
            t_h = min(rnd(font_s * SLAB_TITLE_SCALE * 1.9), cap) if title_h else 0
            t_size = _title_cap(_one_line(doc.title), rnd(t_h / 1.9) if title_h else 0, W, H, pad)
            t_h = rnd(t_size * 1.9) if title_h else 0
            extra = t_h + (wgap if t_h else 0)
            if not vertical:
                break
        scale = min(1.0, max_side_v / max(W, H))
        if title_h and t_size < font_s * SLAB_TITLE_MIN:
            return None
        a = rnd((line_h - rnd(font_s * 0.9)) / 2)   # 行の箱と字面のすきま（上下）
        gx, gy = pad, pad + t_h + (wgap if t_h else 0)
        ty = pad          # タイトルの帯の上端
        if vertical:
            # 柱: 塊はタイトルの下から枠の下端まで。曲名リストは塊の右、同じ高さから始める
            x0, y0, y1 = gx + gw + wgap, gy, H - pad
        else:
            # 帯: 塊はタイトルの下に横いっぱい。曲名リストはその下
            x0, y0, y1 = pad, gy + gh + wgap, H - pad
        seg_w = (W - pad) - x0
        if seg_w < font_s * WRAP_MIN_SEG or y1 - y0 < line_h:
            return None
        segs: list[tuple[int, int, int]] = []
        y = y0
        while y + line_h - a <= y1:
            segs.append((x0, y, seg_w))
            y += line_h
        if not segs:
            return None
        n_seg = len(segs)
        rows = _flow_rows(doc, font_s, 0.0, [float(sg[2]) for sg in segs], n_seg + 1)
        if len(rows) > n_seg:
            return None
        segs = segs[:len(rows)]
        # **余った高さは中身ごと下げて、上下の余白をそろえる**。文字の場所だけ動かすと、
        # 塊と曲名リストのあいだに大きな空きができて「途中で切れた」ように見える
        # （7x1 を 9:16 にしたときに、タイトル・マス・曲名が離れ離れになっていた）。
        # 帯は「タイトル → 塊 → 曲名」をひとかたまりで動かす。柱は塊が枠の高さを使い切るので動かさない
        last = segs[-1][1] + line_h - a
        dy = max(0, (y1 - last) // 2)
        if dy and not vertical:
            gy += dy
            ty += dy
            segs = [(sx, sy + dy, sw) for sx, sy, sw in segs]
        elif dy:
            segs = [(sx, sy + dy, sw) for sx, sy, sw in segs]
        return WrapPlan(W, H, scale, font_s, line_h, t_size, t_h, pad, ty, gx, gy,
                        tuple(segs), rows, len(rows) / n_seg, target=target)

    if refit is not None:
        # 曲の順のまま、決めた枠と字で組み直す（`_refit_flow`）
        return _refit_flow(lambda lh, fs: build(refit.target, lh, fs), refit)
    for target in SLAB_TARGET_PX:
        if target < SLAB_MIN_FONT:
            break
        got = build(target)
        if got:
            return got
    return None


def _wrap_plan(doc: GridDoc, gw: int, gh: int, title_h: int, ratio: float, m: int,
               max_side_v: int, refit: WrapPlan | None = None) -> WrapPlan | None:
    """**マスの塊を中央に置き、まわりの余白に曲名を流し込む**割り付けを探す。

    正方形以下の比率で曲が多いと、今までは「上にマス・下に曲名」で組んでいた。
    内容が縦長なので比率合わせで**左右にごっそり余白が残り**、そのぶんマスが小さくなる。
    まわりに流し込めば余白を使い切れるので、同じ出力サイズでマスを大きくできる。

    決め方は「**出力での文字の大きさを FLOW_MIN_FONT に固定し、入る範囲で枠をいちばん小さくする**」
    （枠が小さいほど、出力に占めるマスの塊が大きい）。枠の大きさは塊に対する % で二分探索する。
    入らなければ None を返し、呼び出し側は今までの組み方に戻す。
    """
    pad0 = _mod_pad(max(m, rnd(min(gw, title_h + gh) * _pad_frac(doc))), doc.options.gap)
    Wb, Hb = _fit(gw, title_h + gh, pad0, ratio)

    def build(pct: int, target: int, fs: int | None = None, seg_fs: int | None = None,
              lh: int | None = None) -> WrapPlan | None:
        W, H = rnd(Wb * pct / 100), rnd(Hb * pct / 100)
        scale = min(1.0, max_side_v / max(W, H))
        font_s = fs if fs else max(18, rnd(target / scale))
        # **マスの送りの約数に寄せる**（塊の左右に流れる行が、ジャケットの段とそろう）。
        # ここは枠を探しながら組むので、入らなければ探索が次の大きさへ進む
        line_h = lh or _snap_lead(rnd(font_s * 1.5), cell_h(doc) + doc.options.gap)   # マスの段にそろえる（高さ）
        pad = _mod_pad(max(m, rnd(min(W, H) * _pad_frac(doc))), doc.options.gap)
        # **左右が半端なら、塊を左端に寄せて右に 1 本の広い段を作る**（コの字に囲む）。
        # 中央に置くと左右が両方とも「文字を流すには狭い」幅になり、両方とも使えず捨てになる。
        # 片側に寄せれば 2 つぶんの幅が 1 本にまとまる。塊を左・文字を上／右／下に置くと
        # 文字の並びがちょうど「コ」の形になり、上の帯 → 右の段 → 下の帯と読める
        gx = rnd((W - gw) / 2)
        # **タイトルの大きさは本文から決める**。ふだんの規則（マスの幅の 4.5%・上限 96）は
        # マスが多いと枠に対して極端に小さくなる（16x16 で出力 14px だった）。
        # まわりを囲む文字の帯に負けない大きさにしたいので、本文の WRAP_TITLE_SCALE 倍にする
        # **ただし、塊を除いた高さの WRAP_TITLE_MAX までにする**。本文に連動して伸びるので、
        # 上限が無いと文字を大きくしたぶんタイトルも伸びて上下の余地を食い潰す（そのせいで
        # 「まだ入るのに文字を大きくできない」状態になっていた）
        t_h = min(rnd(font_s * WRAP_TITLE_SCALE * 1.9), rnd((H - pad * 2 - gh) * WRAP_TITLE_MAX)) if title_h else 0
        t_size = rnd(t_h / 1.9) if title_h else 0
        t_size = _title_cap(_one_line(doc.title), t_size, W, H, pad)
        t_h = rnd(t_size * 1.9) if title_h else 0
        if title_h and t_size < font_s * WRAP_TITLE_MIN:
            return None
        top, bot = pad + t_h, H - pad
        # **塊のまわりの余白を四辺そろえる**。行は「箱」で、字面はその中央にある（上下に a ずつ空く）。
        # 行を等間隔に並べただけだと、格子の余りが塊の上下に溜まって左右より広く見える。
        # 上の帯の行数から塊の位置を逆算し、字面から wgap だけ離れた所に塊を置く
        a = rnd((line_h - rnd(font_s * 0.9)) / 2)
        wgap = rnd(font_s * WRAP_GAP_EM)
        n_top = max(0, rnd((top + rnd((bot - top - gh) / 2) - wgap + a * 2 - top) / line_h))
        gy = top + n_top * line_h - a * 2 + wgap
        if gx < pad or gy < top or gy + gh > bot:      # 塊が枠に入らない
            return None
        # 段の最小幅。**枠を決めたあとの詰め直し（fs 指定）では、枠を決めたときの字（seg_fs）で測る**。
        # 字を 1px 大きくしただけで「20 字に 1 字足りない」と段が消え、詰め直しが 1 歩も進めなかった
        min_w = (seg_fs or font_s) * WRAP_MIN_SEG
        if gx - wgap - pad < min_w and W - pad * 2 - gw - wgap >= min_w:
            gx = pad                   # コの字（塊は左端の中央、文字は上・右・下）
        x0, x1 = pad, W - pad
        ox0, ox1 = gx - wgap, gx + gw + wgap
        # **左右に段が作れないなら、塊を上に寄せて文字を全部下に流す**
        # （タイトル → マス → 曲名リスト）。上下に分かれると 01〜13 が上・14〜20 が下になり、
        # 読み順が塊をまたいで飛ぶ（利用者から指摘）。**枠の大きさも文字の総量も変わらないので、
        # マスの大きさはそのまま**。左右のどちらかが使えるときは今までどおり（コの字・回り込み）
        stack = bool(n_top) and ox0 - x0 < min_w and x1 - ox1 < min_w
        if stack:
            n_top = 0
            # **文字の幅は塊の幅にそろえる**（2026-09-17）。塊の下に全部流すとき、枠のほうが塊より広いと
            # 文字だけ左右にはみ出して「マスと幅が合っていない」見た目になる（利用者の 7x10・9:16 で指摘）
            x0, x1 = gx, gx + gw
        n_side = (gh + a * 2) // line_h
        left_ok, right_ok = ox0 - x0 >= min_w, x1 - ox1 >= min_w

        def lay(nt: int):
            """上の帯を nt 行にしたときの (塊の y, 段の並び, 流し込んだ行)。入らなければ None"""
            gy_ = top if stack else top + nt * line_h - a * 2 + wgap
            if gy_ < top or gy_ + gh > bot:
                return None
            sg: list[tuple[int, int, int]] = [(x0, top - a + r * line_h, x1 - x0) for r in range(nt)]   # 塊の上の帯（枠いっぱい）
            # 塊の左右。**左の段をぜんぶ埋めてから右の段へ移る**（1 行ごとに左右へ飛ぶと読みにくい、
            # と実際に読んでみての指摘があった）。新聞の段組みと同じ読み方になる
            if left_ok:
                sg += [(x0, gy_ - a + r * line_h, ox0 - x0) for r in range(n_side)]
            if right_ok:
                sg += [(ox1, gy_ - a + r * line_h, x1 - ox1) for r in range(n_side)]
            y = gy_ + gh + wgap - a                       # 塊の下の帯（枠いっぱい）
            while y + line_h - a <= bot:
                sg.append((x0, y, x1 - x0))
                y += line_h
            if not sg:
                return None
            rw = _flow_rows(doc, font_s, 0.0, [float(q[2]) for q in sg], len(sg) + 1)
            return (gy_, sg, rw) if len(rw) <= len(sg) else None

        got = lay(n_top)
        if got is None:
            return None
        gy, segs, rows = got
        # **上下の帯の厚みをそろえる**（2026-09-17）。上の帯の行数は「塊を枠の中央に置く」前提で決まるので、
        # 文字が下の帯の途中で終わると上 4 行・下 2 行のように偏る（利用者の 6x9・4:5 で指摘）。
        # 下に使った行数を見て、上下が同じ行数になるまで上の帯を減らして組み直す
        n_sidef = n_side * (int(left_ok) + int(right_ok))
        for _ in range(3):
            n_bot = max(0, len(rows) - n_top - n_sidef)
            # **下の帯の最後の行は埋まっている分だけ数える**（2026-09-17）。上 3 行・下「1 行＋2 曲」を
            # 3 対 2 と見て釣り合っているとしていたが、見た目は 3 対 1.3 で下が薄い（9x18・162 曲で指摘）
            n_botf = (n_bot - 1 + _last_fill(WrapPlan(W, H, scale, font_s, line_h, t_size, t_h, pad, pad, gx, gy, tuple(segs[:len(rows)]), rows))) if n_bot else 0.0
            nt = rnd((n_top + n_botf) / 2)
            if not n_top or nt >= n_top:
                break
            got = lay(nt)
            if got is None:
                break
            n_top, (gy, segs, rows) = nt, got
        segs = segs[:len(rows)]
        # **余った高さは、上下の外側の余白と塊の上下のすきまに、それぞれの大きさに比例して配る**（2026-09-17）。
        # 行は段の数で決まるので、枠と字をどう選んでも 1 行に満たない余りは残る（段が 1 行減る所で
        # 字を大きくできなくなる）。外側の余白だけに振ると上下だけ左右より広くなり、すきまだけに
        # 振ると塊の上下だけ右より空く、とどちらも指摘があった。縦の空気を全部同じ割合で広げる
        top_ = pad
        last = (segs[-1][1] + line_h - a) if segs else gy + gh
        spare = max(0, bot - max(gy + gh, last))
        if spare:
            d_m = rnd(spare * pad / (2 * (pad + wgap)))   # 外側の余白（片側）に足すぶん
            d_g = spare // 2 - d_m                          # 塊の上下のすきま（片側）に足すぶん
            out: list[tuple[int, int, int]] = []
            for sx, sy, sw in segs:
                if sy >= gy + gh - a:            # 下の帯（塊より下）
                    out.append((sx, sy + d_m + d_g * 2, sw))
                elif sy >= gy - a:               # 塊の左右の段は塊と一緒に
                    out.append((sx, sy + d_m + d_g, sw))
                else:                            # 上の帯はタイトルと一緒に
                    out.append((sx, sy + d_m, sw))
            segs = out
            gy += d_m + d_g
            top_ += d_m
        return WrapPlan(W, H, scale, font_s, line_h, t_size, t_h, pad, top_, gx, gy, tuple(segs), rows, pct=pct,
                        seg_fs=seg_fs or font_s)

    if refit is not None:
        # 曲の順のまま、決めた枠と字で組み直す（`_refit_flow`）
        return _refit_flow(lambda lh, fs: build(refit.pct, 0, fs or refit.font_s, refit.seg_fs or refit.font_s, lh), refit)

    # 塊が枠の WRAP_GRID_MAX を超えない大きさから探し始める
    lo0 = max(100, math.ceil(100 * max(gw / Wb, (title_h + gh) / Hb) / WRAP_GRID_MAX))
    # 塊が WRAP_GRID_MIN を下回るほど枠を広げない。ここに当たったら次（小さい）文字で探し直す
    hi0 = min(WRAP_MAX_PCT, int(100 * max(gw / Wb, (title_h + gh) / Hb) / WRAP_GRID_MIN))
    def search(target: int) -> WrapPlan | None:
        """その文字の大きさで入る中の、いちばん小さい枠（＝いちばん大きいマス）。"""
        lo, hi, best = lo0, hi0, None
        while lo <= hi:
            mid = (lo + hi) // 2
            got = build(mid, target)
            if got:
                best, hi = got, mid - 1
            else:
                lo = mid + 1
        return best

    for i, target in enumerate(WRAP_TARGET_PX):
        base = search(target)
        if not base:
            continue
        best = base
        # **余地があれば文字を大きくする**。**最初に見つけた大きさ**のマスから
        # WRAP_CELL_KEEP を割ったらそこで止める（1 段ずつ比べると少しずつ縮んで歯止めが効かない）
        floor = base.scale * (WRAP_CELL_KEEP if cell_short(doc) * base.scale >= WRAP_CELL_OK
                              else WRAP_CELL_KEEP_SMALL)   # **短辺**で見る
        # **塊が横いっぱいに入っているなら、それを崩してまで文字を大きくしない**。
        # 崩すと左右に使えない空白が残る（32x5 を 9:16 にすると塊が枠の 69% の幅になっていた）
        wide = _fills_width(base, gw)
        for up in WRAP_TARGET_UP:
            if up <= target:
                continue
            got = search(up)
            if not got or got.scale < floor or (wide and not _fills_width(got, gw)):
                break
            best = got
        # **逆に、落とすとマスが大きく取れるなら落とす**（左右に使えない空白が残るのを避ける）
        for down in WRAP_TARGET_PX[i + 1:i + 3]:
            if down < WRAP_TARGET_FLOOR:
                break
            got = search(down)
            if not got or got.scale < base.scale * WRAP_CELL_GAIN:
                break
            best = got
        # **枠はそのままで、字を 1 論理 px ずつ大きくして余りを埋める**（2026-09-17）。WRAP_TARGET_UP の
        # 刻みは出力で 2〜4px あり、その間では「まだ入るのに使っていない高さ」が 1〜2 行ぶん残る。
        # 余りは塊の上下のすきまに振るので、そこだけ左右より広く見えていた（利用者の 6x9・4:5 で指摘）。
        # 枠（＝マスの大きさ）は変えないので、大きくなるのは字だけ
        # 字が大きくできなくなったら、**枠を 1% ずつ小さくする**（＝マスが大きくなる）。段の行は
        # マスの高さで数が決まるので、字だけ大きくしても「段が 1 行減って入らない」所で止まる。
        # 枠を縮めると帯の幅が減るぶん段の行が増え、また字を大きくできることがある
        seg_fs = best.font_s
        base_plan = best
        cands = [best]
        for _ in range(WRAP_FINE_STEPS):
            got = build(best.pct, 0, best.font_s + 1, seg_fs)
            if got is None and best.pct > lo0:
                got = build(best.pct - 1, 0, best.font_s, seg_fs)
            if got is None:
                break
            best = got
            cands.append(got)
        # **字を少し小さくした候補も並べる**（出力で 1px まで）。曲が多いと 1px 大きくしただけで段が 1 行減って
        # 入らず、上の詰め直しが 1 歩も進めないことがある（9x18・162 曲）。小さくするぶんには必ず入る
        base_out = base_plan.font_s * base_plan.scale
        for k in range(1, WRAP_FINE_STEPS):
            fs = seg_fs - k
            if fs < 18 or fs * base_plan.scale < base_out - 1.0:
                break
            got = build(base_plan.pct, 0, fs, seg_fs)
            if got is None:
                break
            cands.append(got)
        # **最後の行が埋まっている候補を選ぶ**（2026-09-17）。字を 1px 変えるごとに最後の行の余りが変わるので、
        # 候補の中から「最後の行が WRAP_LAST_FILL 以上埋まっている」うち字がいちばん大きいものを採る。
        # 無ければ字がいちばん大きいもの（埋まりのために字を削らない。上下の帯の釣り合いで補う）
        ok = [c for c in cands if _last_fill(c) >= WRAP_LAST_FILL]
        return max(ok, key=lambda c: (c.font_s * c.scale, c.scale)) if ok else best
    return None


def _trimmed(doc: GridDoc) -> GridDoc:
    """曲名・アーティスト名から蛇足を外した写しを返す（`trimNames` が偽ならそのまま）。

    **割り付けを決める前に通すこと**。刈ったあとの文字で行数と字の大きさを決めないと枠が縮まない。
    `layout()` と `render()` の両方の入口で呼ぶので**二重に掛かる**。`names.trim` は
    掛け直しても結果が変わらない（`scripts/check_trim.py` が確かめている）。
    """
    if not doc.options.trimNames or not any(doc.cells):
        return doc
    out = doc.model_copy(deep=True)
    for cell in out.cells:
        if cell is not None:
            cell.title, cell.artist = names.trim(cell.title or "", cell.artist or "")
    return out


def _cropped(doc: GridDoc) -> GridDoc:
    """**末尾の空き行・列を落とした写し**（書き出しだけ。2026-09-26、利用者の共有 3x8 に 7 曲で指摘）。
    空きマスを塗らなくしたので、下や右の端の空き段は何も描かれないのに、割り付けはその段込みで決まり、
    マスの塊が上に寄って下が大きく空き、曲名リストも空き段の高さまで引き延ばされていた。
    途中の空きマスはそのまま（利用者が置いた形）。曲の順は変わらない（落とすのは曲の無い段・列だけ）。
    frontend の cropGrid と同じ規則。`layout()` と `render()` の入口で呼ぶので二重に掛かるが、掛け直しても同じ"""
    cols, rows = doc.cols, doc.rows
    filled = [i for i, t in enumerate(doc.cells[:cols * rows]) if t]
    if not filled:
        return doc
    nr, nc = max(i // cols for i in filled) + 1, max(i % cols for i in filled) + 1
    if nr == rows and nc == cols:
        return doc
    return doc.model_copy(update={"cols": nc, "rows": nr, "cells": [doc.cells[r * cols + c] for r in range(nr) for c in range(nc)]})


def layout(doc: GridDoc, _title_px: int | None = None, _depth: int = 0) -> Layout:
    real = _cropped(_trimmed(doc))
    # **組み方は曲の順番に左右されない並び（`_canon`）で決める**（2026-09-25）。`doc` はその並び、
    # `real` は曲の順のまま。`real` を使うのは最後の組み直し（行の高さ・段の位置）だけ
    doc = _canon(real)
    o = doc.options
    cols, rows, n, m, g = doc.cols, doc.rows, doc.size, o.margin, o.gap
    n_tracks = max(1, sum(1 for t in doc.cells if t))   # 入っている曲の数（「消える曲」の割合を測る母数）
    title = _one_line(doc.title) if o.showTitle else ""
    gw = cols * CELL_W + (cols - 1) * g
    gh = rows * cell_h(doc) + (rows - 1) * g
    # `_title_px` は「曲名リストより十分大きく」するための組み直し（下の TITLE_MIN_SCALE を参照）
    title_size = _title_px or rnd(min(96, max(48, gw * 0.045)))
    title_h = rnd(title_size * 1.9) if title else 0
    ratio = RATIOS[o.ratio]
    # サイドバー: 横長なら右、正方形以下（1:1 / 4:5 / 9:16）ならグリッドの下。
    # 正方形で右に置くと内容が横長になり、上下の余白ばかり広がるため。
    # **比率なしのときは「マスの塊が縦長なら右・横長なら下」**。枠は内容に合わせて伸びるので、
    # 長いほうの辺にさらに足すと極端な形になる（32x1 を右に足すと出力 2400x39 だった）
    side = ("none" if not o.sidebar or o.overlay
            else ("right" if gh >= gw else "bottom") if ratio is None
            else "right" if ratio > 1 else "bottom")
    # 右サイドバーのときタイトルはサイドバーの上（曲名リストの前）に置く。グリッドの上に置くと内容が縦長になり、
    # 横長の比率（16:9）で左右の余白ばかり広がるため
    title_top_h = 0 if side == "right" else title_h
    # 1 曲は「曲名の行 + アーティストの行」の 2 行。まずその前提で行の高さを見積もる。
    # **数えるのは曲の入ったマスだけ**（空きマスの行を作らない。2026-09-25）
    songs = _songs(doc)
    base_rows = sum(2 if _one_line(t.artist) else 1 for t in songs)
    avail_h = gh - title_h
    sb_w = sb_h = 0
    sb_cols = 1
    # **マスの塊と曲名リストのすきま**。定数だと枠が大きいときに出力で 3px にしかならない
    # （1x32 を 16:9 にしたとき）。内容の高さに比例させて、出力でおよそ 25px になるようにする
    sb_gap = 0 if side == "none" else max(GAP_PX * 4, rnd((title_top_h + gh) * 0.02))
    cap = gw
    if side == "right" and ratio is not None:
        # **比率が決まっているときは、横に余る幅を先にサイドバーへ回す**。高さはグリッドで決まるので、
        # 全体の幅は比率から決まってしまい、サイドバーを狭くしたぶんは余白になって捨てられるだけ
        # **グリッド幅で下駄を履かせない**。比率から決まる幅を超えると、その分だけ上下の余白が
        # 広がるか、はみ出して描かれる（2 列にしたとき実際にはみ出した）
        w_est = rnd((title_top_h + gh + m * 2) * ratio)
        cap = max(LIST_MIN_COL, min(gw * 2, w_est - m * 2 - gw - sb_gap))

    pitch = cell_h(doc) + doc.options.gap  # マスの段 1 つぶんの送り（行をこれの約数にそろえる。**高さ**）

    def _sidebar(cols: int, rows_total: int) -> tuple[int, int, int]:
        """列数を決めたときの (行の高さ, 文字の大きさ, サイドバーの幅)。"""
        if side == "right":
            rows = max(1, math.ceil(rows_total / cols))
            # **マスの送りの約数に寄せる**（曲名の行とジャケットの段がそろう）。
            # **頭打ちを当ててから寄せる**（先に寄せると 96 で切られて寄せた意味が消える）。
            # 下へだけ動かす（上げると高さに入らないか、96 を超える）
            lh = max(30, min(pitch // LEAD_PITCH_DIV, avail_h // rows))
            lh = max(30, _snap_lead(lh, pitch, max_lh=lh))
        else:
            lh = rnd(max(52, min(108, gw * 0.05)))
        fs = rnd(lh * 0.56)
        if side != "right":
            return lh, fs, gw
        # **幅は文字を測って決めない**。文字の幅は PIL と Canvas で数 px 違い、その差がサイドバーの
        # 幅の差になって、中央寄せのグリッドまで 1〜2px ずれる（突き合わせでグリッド側に差が出ていた）。
        # 比率があるときは比率から決まる残り幅、無いときはグリッドと同じ幅。余った幅は行の余白になるだけ
        return lh, fs, max(cap, _title_width(title, title_size) if cols == 1 else 0)

    line_h, font_s, sb_w = _sidebar(1, base_rows)
    sb_h = gh if side == "right" else math.ceil(base_rows / sb_cols) * line_h

    def _frame(sbw: int, sbh: int) -> tuple[int, int, float]:
        cw = gw + sb_gap + sbw if side == "right" else gw
        ch = title_top_h + gh + (sb_gap + sbh if side == "bottom" else 0)
        # **四辺に最低でも内容の短辺の 3.5% の余白を残す**。既定の 16px は出力にすると 10px 足らずで、
        # 絵が枠に貼り付いて見える。比率合わせで余りが出る辺だけ広い、という不揃いも無くなる
        pad = _mod_pad(max(m, rnd(min(cw, ch) * _pad_frac(doc))), doc.options.gap)
        w, h = _fit(cw, ch, pad, ratio)
        if ratio is not None and (w, h) != (cw + pad * 2, ch + pad * 2):
            # 比率合わせで余りが出る辺は余白が広がる。反対の辺が狭いままだと上下（縦長なら左右）だけ
            # 極端に狭く見えるため、余りが出るときは「内容の短辺の 4%」まで引き上げる
            w, h = _fit(cw, ch, _mod_pad(max(m, rnd(min(cw, ch) * (_pad_frac(doc) + 0.005))), doc.options.gap), ratio)
        from backend.config import max_side
        return w, h, min(1.0, max_side() / max(w, h))

    W, H, scale = _frame(sb_w, sb_h)

    def _right_final(cols: int) -> tuple[int, tuple[int, int]]:
        """右に置いて cols 列にしたときの、曲名を折ったあとの (文字の大きさ, (折れる, 途切れる))。
        下の「折ったぶん高さを取り直す」と同じ式で出す"""
        _, fs, w = _sidebar(cols, base_rows)
        col_w = (w - LIST_COL_GAP * (cols - 1)) // cols
        plan = _row_plan(doc, fs, col_w)
        if sum(plan) > base_rows or _plan_need(plan, cols) > math.ceil(base_rows / cols):
            lh = max(30, min(pitch // LEAD_PITCH_DIV, avail_h // max(1, _plan_need(plan, cols))))
            fs = rnd(max(30, _snap_lead(lh, pitch, max_lh=lh)) * 0.56)
        return fs, _list_damage(doc, fs, col_w)

    # **文字が小さくなるなら、まず列を増やす**。1 列のまま縦に詰めるより、列を割って 1 列あたりの
    # 行数を減らしたほうが行間も文字も大きく取れる（25 曲で 2 列。参考にした他サービスと同じ考え方）。
    # 判断は論理 px ではなく**出力で何 px になるか**で行う（比率・余白・タイトルの有無で変わるため）
    # **下に置くときも列を増やす**（2026-09-15）。右に置くときだけ増やしていたので、正方形以下の
    # 比率では曲名リストが必ず 1 列で、**縦に長いぶん枠が縦に伸び、そのぶんマスが小さくなっていた**
    # （3x3 を 4:5 にすると左右に 340px ずつ余り、リストの右半分は空白だった）。
    # 列を割れば行数が半分になり、枠が縮んでマスも文字も大きくなる
    # **流し込みに落ちる並びでは列を増やさない**。下に置くときは列を割ると枠が縮んで縮尺が上がり、
    # 出力での文字が FLOW_MIN_FONT を超えて「1 曲 1 行」のまま残ってしまう。すると回り込みを
    # 試さなくなり、**回り込みのほうがマスを大きく取れる並び（6x6 を 1:1 で 282 → 205px）で損をする**
    flow1 = font_s * scale < FLOW_MIN_FONT
    if side != "none" and (side == "right" or not flow1):
        while sb_cols < LIST_MAX_COLS:
            # **増やす理由が右と下で違う**。右に置くときは高さがグリッドで決まるので、
            # 列を割ると 1 列あたりの行数が減って**文字が大きくなる**（だから文字が小さいときだけ増やす）。
            # 下に置くときは文字の大きさがグリッドの幅で決まるので、列を割ると**リストが縦に縮み、
            # 枠ごと小さくなってマスが大きくなる**（文字の大きさに関わらず得になる）
            if side == "right" and font_s * scale >= LIST_COMFY_FONT:
                break
            lh, fs, w = _sidebar(sb_cols + 1, base_rows)
            if (w - LIST_COL_GAP * sb_cols) // (sb_cols + 1) < LIST_MIN_COL:
                break
            sb_h2 = sb_h if side == "right" else math.ceil(base_rows / (sb_cols + 1)) * lh
            _, _, scale2 = _frame(w, sb_h2)
            # 増やしても大きくならないならやめる（下に置くときは端数の差で行き来しないよう少し余裕を見る）
            if fs * scale2 <= font_s * scale * (1.0 if side == "right" else LIST_COL_GAIN):
                break
            if side == "right":
                # **列が狭くなって崩れる曲が増えるなら、文字がはっきり大きくならない限り増やさない**。
                # 比べるのは曲名を折ったあとの大きさ（折ると行が増えて、見込みより小さくなる）
                fs_now, (fold_now, clip_now) = _right_final(sb_cols)
                fs_new, (fold_new, clip_new) = _right_final(sb_cols + 1)
                # **名前が「…」で消えるぶんだけ、列を増やす条件を厳しくする**（2026-09-18）。折れるのは
                # 行が増えるだけで読めるが、途切れるのは文字そのものが消える。右に置くときは列を増やしても
                # マスは変わらず、得るのは字の大きさだけなので、消える名前と釣り合わない
                # （利用者の 6x6・36 曲で 8 曲、5x5・25 曲で 2 曲が消えていた）。消える曲 1 つにつき
                # CLIP_GAIN だけ必要な倍率を上げる（1 曲を消してよいのは字が 1.5 倍になるときだけ）
                # **今の列のままでは字が小さすぎて流し込みに落ちるなら、この番人は通す**。流し込みは
                # 曲の区切りが見えなくなるので、名前が 1 つ消えるより読みにくい
                need = LIST_COL_TIDY_GAIN + CLIP_GAIN * max(0, clip_new - clip_now)
                if fs_now * scale < FLOW_KEEP_FONT:
                    need = LIST_COL_TIDY_GAIN
                if (fold_new + clip_new) > (fold_now + clip_now) and fs_new * scale2 < fs_now * scale * need:
                    break
            else:
                # **下に置くときも同じ**（2026-09-17）。マスが少し大きくなるだけで 3 列にすると、
                # 4x4・1:1・16 曲でアーティスト名が「…」になり、曲名が変な所で折れていた（利用者の画像で指摘）。
                # 崩れる曲が増えるなら、マスが LIST_COL_TIDY_GAIN 倍以上大きくならない限り増やさない
                fold_now, clip_now = _list_damage(doc, font_s, (sb_w - LIST_COL_GAP * (sb_cols - 1)) // sb_cols)
                fold_new, clip_new = _list_damage(doc, fs, (w - LIST_COL_GAP * sb_cols) // (sb_cols + 1))
                if clip_new - clip_now > CLIP_MAX_RATIO * n_tracks:
                    break
                if (fold_new + clip_new) > (fold_now + clip_now) and scale2 < scale * LIST_COL_TIDY_GAIN:
                    break
            sb_cols, line_h, font_s, sb_w, sb_h = sb_cols + 1, lh, fs, w, sb_h2
            W, H, scale = _frame(sb_w, sb_h)
    # 曲名が 1 行に入らなければ 2 行に折るので、その曲だけ行が増える。増えたぶん高さを取り直す。
    # **割り付けは 1 度しか計算しない**（小さくした字で計算し直すと、折る・折らないを行き来するため）
    sb_plan: tuple[int, ...] = ()
    sb_arows: tuple[int, ...] = ()
    plan_at = (font_s, 0)   # 曲ごとの行数を数えた字と列の幅（最後に曲の順で数え直すため）
    if side != "none":
        col_w0 = (sb_w - LIST_COL_GAP * (sb_cols - 1)) // sb_cols
        plan_at = (font_s, col_w0)
        sb_plan = _row_plan(doc, font_s, col_w0)
        avail0 = max(1.0, col_w0 - _num_w(font_s))
        sb_arows = tuple(_artist_rows(_one_line(t.artist), font_s, avail0) for t in songs)
        # **判定は曲の順番に左右されない行数で**（`_plan_need`。2026-09-25）
        rows_per_col = _plan_need(sb_plan, sb_cols)
        # **1 曲が列をまたがないので、折らなくても 1 列の行数が見込みより増えることがある**（2026-09-17）。
        # 曲名＋アーティストの 2 行ひと組を 25 曲、2 列に分けると 13 曲 ＝ 26 行で、「50 行 ÷ 2 列 ＝ 25 行」の
        # 高さのまま描くと最後の曲がマスの下端からはみ出していた。そのときも高さを取り直す
        if sum(sb_plan) > base_rows or rows_per_col > math.ceil(base_rows / sb_cols):
            if side == "right":
                rows_now = max(1, rows_per_col)
                line_h = max(30, min(pitch // LEAD_PITCH_DIV, avail_h // rows_now))
                line_h = max(30, _snap_lead(line_h, pitch, max_lh=line_h))
                font_s = rnd(line_h * 0.56)
            else:
                sb_h = rows_per_col * line_h
            W, H, scale = _frame(sb_w, sb_h)
        elif side == "bottom":
            sb_h = rows_per_col * line_h
            W, H, scale = _frame(sb_w, sb_h)
    # **そろえるために行を縮めたせいで下限を割ったのなら、そろえるのをやめる**（2026-09-16）。
    # 行の高さはマスの段の送りの約数に寄せてある（`_snap_lead`）。5x5・16:9・25 曲の実測では
    # 96 → 88 に縮み、出力での曲名が 21.6px → **19.6px** になって `FLOW_MIN_FONT`（20px）を
    # わずかに割り、まるごと流し込みに落ちていた。段のそろいは見た目の細かい良さだが、
    # 「1 曲 1 行」が保てるかどうかは読みやすさそのもの。割るくらいなら寄せない
    if side == "right" and font_s * scale < FLOW_MIN_FONT:
        rows_fin = max(1, _plan_need(sb_plan, sb_cols) if sb_plan else math.ceil(base_rows / sb_cols))
        lh2 = max(30, min(pitch // LEAD_PITCH_DIV, avail_h // rows_fin))
        fs2 = rnd(lh2 * 0.56)
        if fs2 > font_s and fs2 * scale >= FLOW_MIN_FONT:
            line_h, font_s = lh2, fs2
    # **1 行型を試す**（`_inline_one_line`）。**全曲が 1 行に並ぶ大きさまで字を下げる**（2026-09-19）。
    # 以前は並ばない曲のアーティスト名だけ次の行の右端に落としていたが、落ちた行も 1 曲ぶんの高さを取るので、
    # どの曲のアーティストか迷い、行の間隔も不揃いになった（利用者の 3x3・16:9 と 5x5・16:9 の画像で指摘）。
    # 逆に、長い曲名が 1 曲あるだけで 1 行型をまるごと諦めていた（「Glory 3usi9 (feat. Hatsune Miku)」で
    # 字が 27.8px の 2 行型に落ちていた。1 行に並べれば 36.8px）。字がはっきり大きくなるときだけ採る
    sb_inline = False
    if side == "right":
        n_i = len(songs)
        lh_i, fs_i, w_i = _sidebar(1, n_i)
        # 下限は FLOW_MIN_FONT（20px）ではなく FLOW_KEEP_FONT（16px）。20px を割った 1 行型は下で流し込み・
        # 回り込み・柱を試し、そちらが「流し込みの右サイドバー」になるなら 1 行型に戻る（1 曲 1 行と同じ扱い）。
        # 20px で切ると、長い曲名が 1 曲ある 25 曲（5x5・16:9）が段落のような流し込みに落ちていた
        floor_i = max(math.ceil(font_s * INLINE_GAIN), math.ceil(FLOW_KEEP_FONT / scale))
        while fs_i >= floor_i and not _inline_one_line(doc, fs_i, w_i):
            fs_i -= 1
        if fs_i >= floor_i:
            sb_inline = True
            sb_cols, line_h, font_s, sb_w, sb_plan, sb_arows = 1, lh_i, fs_i, w_i, (1,) * n_i, ()
            # **行の高さは残りの高さいっぱいに広げる**（字の大きさはそのまま）。字は幅と行の上限
            # （マスの送りの 1/4）で決まるので、曲が少ないと下が 4 分の 1 ほど空いていた
            line_h = max(line_h, (gh - title_h) // max(1, n_i))
            W, H, scale = _frame(sb_w, sb_h)
    if side == "right" and title_h and line_h > 0 and not sb_inline:
        # **曲名リストの先頭も段の境目に乗せる**。リストはタイトルの帯のぶん下から始まるので、
        # 帯が行の整数倍でないと、行がそろっていても全体が半端にずれる。
        # 収まらないなら動かさない（はみ出すくらいならそろえないほうがよい）
        rows_now = _plan_need(sb_plan, sb_cols) if sb_plan else base_rows
        up = math.ceil(title_h / line_h) * line_h
        if up + rows_now * line_h <= gh:
            title_h = up
    # 曲が多いと、列を増やしても出力での文字が読めない大きさになる。そのときだけ流し込みに切り替える
    keep = (sb_w, sb_h, sb_cols, line_h, font_s, W, H, scale, title_h)   # 1 曲 1 行の組み方（下で戻すことがある）
    sb_flow = side != "none" and font_s * scale < FLOW_MIN_FONT
    sb_top = 0
    if sb_flow and side == "right" and ratio is not None and doc.cols <= SLAB_ROW_MAX_COLS:
        # **1 行型の表を試す**（TABLE_*）。幅は流し込みと同じく比率で余るぶん全部
        w_t = max(sb_w, rnd((title_top_h + gh + m * 2) * ratio) - m * 2 - gw - sb_gap)
        W_t, H_t, sc_t = _frame(w_t, sb_h)
        n_t = len(songs)
        best = None
        for cols_t in range(2, TABLE_MAX_COLS + 1):
            lh_t = (gh - title_h) // max(1, math.ceil(n_t / cols_t))
            cw_t = (w_t - rnd(lh_t * TABLE_GAP_LH) * (cols_t - 1)) // cols_t
            fs_t = rnd(lh_t * TABLE_FONT)
            while fs_t * sc_t >= FLOW_KEEP_FONT and not _inline_one_line(doc, fs_t, cw_t):
                fs_t -= 1
            if fs_t * sc_t >= FLOW_KEEP_FONT and (best is None or fs_t > best[2]):
                best = (cols_t, lh_t, fs_t)
        if best:
            sb_cols, line_h, font_s = best
            sb_w, W, H, scale = w_t, W_t, H_t, sc_t
            sb_inline, sb_flow = True, False
            sb_plan, sb_arows = (1,) * n_t, ()
            cap = rnd(font_s * TABLE_LH_CAP)
            if line_h > cap:
                sb_top = ((gh - title_h) - math.ceil(n_t / sb_cols) * cap) // 2
                line_h = cap
    if sb_flow:
        if side == "right" and ratio is not None:
            # 高さはグリッドで決まるので、横は比率から決まる。余る幅は全部サイドバーに回す
            # （1 曲 1 行のときは「最長の行」に合わせていたが、流し込みでは広いほど行が減って字が大きくできる）。
            # **ここで「マスの幅の 2 倍まで」と止めてはいけない**。1 列の並び（1xN）だと 1200 論理 px しか
            # 取れず、文字が下限まで落ちていた（1x32 を 16:9 にすると出力 12px）
            w_est = rnd((title_top_h + gh + m * 2) * ratio)
            sb_w = max(sb_w, w_est - m * 2 - gw - sb_gap)
        avail = (gh - title_h) if side == "right" else sb_h
        if side == "right":
            # **右に置くときは枠が先に決まる**（高さはグリッドで決まる）ので、
            # **出力での大きさから字の大きさを決める**。論理 px の決め打ち（上限 132）だと、
            # 枠が大きいときに出力で 9px にしかならなかった（1x32 を 16:9 にしたとき）
            W, H, scale = _frame(sb_w, sb_h)
            fitted = False
            for px in FLOW_TARGET_PX:
                fs = max(18, rnd(px / scale))
                # **マスの送りの約数に寄せる**（グリッドの横に流れる行が段とそろう）
                lh = _snap_lead(rnd(fs * 1.5), pitch)
                rows = _flow_rows(doc, fs, sb_w)
                if len(rows) * lh <= avail:
                    fitted = True
                    break
            # **入った段から 1 論理 px ずつ大きくして下の余りを詰める**（2026-09-18）。段の刻みは出力で 4〜8px あり、
            # 次の段との間の余りがそのまま下に残っていた（利用者の 10x15・150 曲で 1 行半ぶん）
            if fitted and px != FLOW_TARGET_PX[0]:
                for _ in range(FLOW_FINE_STEPS):
                    fs2 = fs + 1
                    lh2 = _snap_lead(rnd(fs2 * 1.5), pitch)
                    rows2 = _flow_rows(doc, fs2, sb_w)
                    if len(rows2) * lh2 > avail:
                        break
                    fs, lh, rows = fs2, lh2, rows2
        else:
            for fs in FLOW_FONT_STEPS:
                lh = rnd(fs * 1.5)
                rows = _flow_rows(doc, fs, gw)
                if len(rows) * lh <= avail:
                    break
        font_s, line_h, sb_cols = fs, lh, 1
        if side == "bottom":
            sb_h = len(rows) * line_h
        W, H, scale = _frame(sb_w, sb_h)
    # **曲名をマスの塊のまわりに回り込ませる**（`_wrap_plan`）。切り替える条件は 2 つ:
    #   - **マスが小さくならない**とき … 比率合わせで余っていた余白を曲名に使うので、
    #     正方形（1:1）では今までより大きなマスで、しかも大きな文字になる
    #   - マスが小さくなっても、**今の組み方では文字がまったく読めない**とき
    #     （21x12 を 16:9 にすると右に幅が残らず、文字が出力 4px になっていた）
    #   - **文字が段違いに大きくなる**とき（WRAP_SWITCH_GAIN 倍以上）。ただしマスの縮みは
    #     WRAP_CELL_KEEP まで。32x1 を 1:1 にすると、従来 16px / 回り込み 64px だった
    # **無条件には切り替えない**。9:16 に正方形の並びを入れたときのように、
    # 塊を中央に置くと左右の帯のぶんマスが小さくなるだけ、という組み合わせがある
    # **曲名をマスの横に、マスと同じ並び順で置く**（利用者の要望。1〜3 列の並び）。
    # 比率なしではサイドバーの幅がマス 1 つぶん（600 論理 px）しか取れず、出力が細長い帯になって
    # 文字も小さくなっていた（1x8 で 666x2400・本文 26px）。比率があるときは、
    # **マスが今の組み方より小さくならないときだけ**使う
    if doc.cols <= SLAB_ROW_MAX_COLS and side != "none":
        from backend.config import max_side
        rp = _slab_rows(doc, gw, gh, title_h, ratio, m, max_side())
        if rp is None and doc.cols > 1:   # 縦に積むと薄すぎる → 段の中で横に並べる
            rp = _slab_rows(doc, gw, gh, title_h, ratio, m, max_side(), beside=True)
        # 流し込みに落ちる並びは、今の組み方の字が読めない大きさなので無条件で置き換える
        if rp and (ratio is None or sb_flow or rp.scale >= scale):
            return Layout(rp.W, rp.H, rp.scale, rp.gx, rp.gy, gw, gh, title, rp.title_size, rp.title_h,
                          side, 0, 0, 1, rp.line_h, rp.font_s, sb_gap, True, (), (),
                          True, rp.pad, rp.top, rp.segs, True, wrap_tx=rp.tx, wrap_inline=rp.inline)
    if sb_flow and ratio is not None:
        from backend.config import max_side
        wp = _wrap_plan(doc, gw, gh, title_h, ratio, m, max_side())
        # 選んだ組み方を曲の順で組み直す関数（枠と字はそのまま。縦一列・表は曲ごとに 1 段なので要らない）
        wp_fix = lambda p: _wrap_plan(real, gw, gh, title_h, ratio, m, max_side(), refit=p)   # noqa: E731
        # **辺にぴったり付く組み方（柱・帯）があればそちらを優先する**。塊が片方の辺を
        # 使い切るので枠に余りが出ず、マスは回り込みと同じか大きくなる。
        # 回り込みのほうがマスを大きく取れるときだけ、そちらを残す
        sp = _slab_plan(doc, gw, gh, title_h, ratio, m, max_side())
        sp_fix = lambda p: _slab_plan(real, gw, gh, title_h, ratio, m, max_side(), refit=p)   # noqa: E731
        # **横一列に近い並びは、曲名を 1 曲 1 行の縦一列で下に置く**（流し込みより読みやすく、
        # 下の空きも埋まる）。マスが小さくならないときだけ
        st = _slab_stack(doc, gw, gh, title_h, ratio, m, max_side())
        if st and (sp is None or st.scale >= sp.scale):
            sp, sp_fix = st, None
        # **マスが小さくならないなら帯・柱を採る**。回り込みは塊を真ん中に置くので、
        # 横長の並び（7x1 など）だと**マスが下端に行ってタイトルだけが上に残る**。
        # 利用者の指摘「タイトルの下にマス画像があってほしい」に合わせて、辺に付ける側を優先する
        # **わずかな差なら辺に付ける側を採る**。ほぼ同じ大きさなのに回り込みが選ばれると、
        # 塊が真ん中に落ちてタイトルとのあいだに文字が挟まる（18x1 を 1:1 にしたときに起きた）
        if sp and (wp is None or sp.scale >= wp.scale * SLAB_PREFER):
            wp, wp_fix = sp, sp_fix
        if wp and (wp.scale >= scale or font_s * scale < WRAP_SWITCH_PX
                   or (wp.font_s * wp.scale >= font_s * scale * WRAP_SWITCH_GAIN
                       and wp.scale >= scale * WRAP_CELL_KEEP)):
            if wp_fix:
                wp = wp_fix(wp)
            return Layout(wp.W, wp.H, wp.scale, wp.gx, wp.gy, gw, gh, title, wp.title_size, wp.title_h,
                          side, 0, 0, 1, wp.line_h, wp.font_s, sb_gap, True, (), (),
                          True, wp.pad, wp.top, wp.segs, wp.rows_mode, wrap_inline=wp.inline)
    # **流し込みに落ちるくらいなら、1 曲 1 行を残す**（2026-09-17）。回り込みや柱・帯のほうがマスを大きく
    # 取れる並びは上で返っている。ここに来るのは「流し込みの右サイドバー」で、字は 24〜34px と大きいが
    # 高さの半分が空き、曲の区切りも見えない（利用者の 4x4・5x5・6x6 の 16:9 で「整列できそう」と指摘）。
    # 1 曲 1 行が FLOW_KEEP_FONT（16px）以上あるなら、そちら（実測 17〜21px）のほうが整って見える
    if sb_flow and keep[4] * keep[7] >= FLOW_KEEP_FONT:
        sb_w, sb_h, sb_cols, line_h, font_s, W, H, scale, title_h = keep
        sb_flow = False
    # **曲名リストの下端をマスの下端にそろえる**（2026-09-19）。行の高さはマスの送りの約数に寄せるので
    # （`_snap_lead`）、1 行に満たない余りがリストの下に残り、「下辺にそろいそうなのにそろっていない」と見えた
    # （利用者の 3x3・16:9・9 曲で指摘）。余りは**行の高さに均等に配る**（字の大きさはそのまま）。
    # タイトルの下にまとめて回すと、そこだけ大きく空いた。1 行ぶんを超える余りは動かさない
    # **ここから曲の順で組み直す**（2026-09-25）。組み方・枠・字・列数は `_canon` の並びで決めてあり、
    # 曲の順番では変わらない。描くのは曲の順なので、曲ごとの行数を数え直し、列の行数や流し込みの行数が
    # 見込みと違えば**行の高さだけ**を合わせる（字の大きさはそのまま）
    if side != "none" and not sb_flow and not sb_inline and sb_plan:
        sb_plan = _row_plan(real, *plan_at)
        avail_r = max(1.0, plan_at[1] - _num_w(plan_at[0]))
        sb_arows = tuple(_artist_rows(_one_line(t.artist), plan_at[0], avail_r) for t in _songs(real))
        if side == "bottom":
            # 下に置くときは曲名リストの高さ（`sb_h`）が枠に入っている。その高さに実際の行数を割り付ける
            rows_real = max(1, _plan_rows(sb_plan, sb_cols))
            if rows_real * line_h != sb_h:
                line_h = sb_h // rows_real
    if side == "right" and not sb_flow and not sb_inline and line_h > 0:
        rows_now = _plan_rows(sb_plan, sb_cols) if sb_plan else base_rows
        extra = gh - title_h - rows_now * line_h
        if extra < 0 and rows_now:
            # 曲の順で列の行数が見込みを超えた（2〜3 行に折れる曲が 1 つの列に集まった）→ 行の高さを詰める。
            # 見込みは `_plan_need` で「どんな並びでも入る行数」の ROWS_SQUEEZE 倍を取ってあるので、詰めすぎない
            line_h = (gh - title_h) // rows_now
            extra = gh - title_h - rows_now * line_h
        # **曲名リストの下端をマスの下端にそろえる**（2026-09-19。上のコメント）
        if title_h and 0 < extra <= line_h and rows_now:
            line_h += extra // rows_now
            title_h += extra % rows_now
    if sb_flow and side != "none":
        # 流し込みの行数も曲の順で 1〜2 行変わる。入りきらなければ行の高さを詰める（描くのは `render` の流し込み）
        n_real = len(_flow_rows(real, font_s, sb_w if side == "right" else gw))
        room = (gh - title_h) if side == "right" else sb_h
        if n_real * line_h > room:
            line_h = room // n_real
    content_w = gw + sb_gap + sb_w if side == "right" else gw
    content_h = title_top_h + gh + (sb_gap + sb_h if side == "bottom" else 0)
    L = Layout(W, H, scale, rnd((W - content_w) / 2), rnd((H - content_h) / 2), gw, gh,
               title, title_size, title_h, side, sb_w, sb_h, sb_cols, line_h, font_s, sb_gap, sb_flow,
               () if sb_flow else sb_plan, () if sb_flow else sb_arows,
               sb_inline=sb_inline and not sb_flow, sb_top=0 if sb_flow else sb_top)
    # **タイトルは曲名リストより十分大きくする**。ふだんの規則（マスの幅の 4.5%・上限 96）は
    # マスの数だけで決まるので、曲が少なくて曲名が大きくなると**タイトルのほうが小さくなる**
    # （1x6・16:9 で本文 46.6px にタイトル 16.9px ＝ 0.36 倍だった）。
    # 曲名の大きさが決まってから組み直す。タイトルを大きくすると曲名は同じか小さくなるので、
    # たいてい 1 回で収まる（回り込みは `_wrap_plan` の中で既に本文から決めているので対象外）。
    # **ただし組み直しで組み方が変わると本文のほうが大きくなることがある**（3x20 の比率なしで、
    # 1 曲 1 行 → 流し込みに変わって本文 85 → 120、タイトルが本文の 1.14 倍だった）。2 回まで回す
    if L.title and _depth < 2:
        want = rnd(L.font_s * TITLE_MIN_SCALE)
        if want > L.title_size:
            return layout(real, want, _depth + 1)
    return L


def _plan_need(plan: tuple[int, ...], cols: int) -> int:
    """**組み方を決めるときの** 1 列あたりの行数。曲の順番に左右されない（2026-09-25）。

    実際の並びで数える `_plan_rows` は、2〜3 行に折れる曲がどの列に集まるかで 1〜2 行変わり、
    同じ曲でも順番しだいで「3 列の表」と「流し込み」が入れ替わっていた（利用者の 7x7・16:9・49 曲）。
    - 行数を大きい順に並べて列に詰めたときの 1 列の行数（ふつうはこれ。実際の並びとの差はたいてい 0〜1 行）
    - ただし「どんな並びでも入る行数」（合計 ÷ 列数 ＋ いちばん多い曲の行数 − 1）の `ROWS_SQUEEZE` 倍は取る。
      実際の並びがこの見込みを超えたら、描くときに行の高さを詰める（字の大きさはそのまま）。
      詰めても元の `ROWS_SQUEEZE` 倍までなので、曲名とアーティスト名が重ならない
    """
    if cols <= 1 or not plan:
        return sum(plan)
    need = _plan_rows(tuple(sorted(plan, reverse=True)), cols)
    worst = math.ceil(sum(plan) / cols) + max(plan) - 1
    return max(need, math.ceil(worst * ROWS_SQUEEZE))


def _plan_rows(plan: tuple[int, ...], cols: int) -> int:
    """1 列あたりの行数。**1 曲が列をまたがないように**詰めたうえで、必ず cols 列に収まる値を返す。

    単純に「合計 ÷ 列数」で切ると、曲の行数がそろわないぶんがあふれて列が 1 つ増える
    （2 列のはずが 3 列目に 1 曲だけ置かれていた）。収まるまで 1 行ずつ広げる。
    """
    total = sum(plan)
    if cols <= 1:
        return total
    target = math.ceil(total / cols)
    while True:
        used, used_cols, most = 0, 1, 0
        for r in plan:
            if used and used + r > target:
                used_cols, most, used = used_cols + 1, max(most, used), 0
            used += r
        if used_cols <= cols:
            return max(most, used)
        target += 1


def _fit(content_w: int, content_h: int, pad: int, ratio: float | None) -> tuple[int, int]:
    """内容に四辺 pad の余白を足し、比率が指定なら短い方の辺を伸ばして合わせる。"""
    W, H = content_w + pad * 2, content_h + pad * 2
    if ratio is not None:
        if W / H < ratio:
            W = rnd(H * ratio)
        else:
            H = rnd(W / ratio)
    return W, H


def _title_width(title: str, title_size: int) -> int:
    """タイトル 1 行の幅（px）。右サイドバーの幅をこれ以上にして、タイトルが「…」で切れにくくする。"""
    # **1 字ずつ 1px に丸めて足す**（`char_w`）。文字列を丸ごと測ると PIL と Canvas で数 px 違い、
    # その差がサイドバーの幅 → 枠 → 縮尺の差になって、**出力での字の大きさが 1px 変わる**ことがある
    # （利用者の長い題の並びで、サーバー 46px・ブラウザ 45px になり、折り返す位置まで変わっていた）。
    # 流し込みの折り返しで同じ問題を解いたのと同じやり方
    return int(sum(char_w("bold", title_size, ch) for ch in title)) + 8 if title else 0


# ---------- 描画 ----------
def render(doc: GridDoc) -> Image.Image:
    """レイアウト（論理 px。CELL_PX=600 基準）を計算し、最終サイズ（max_side 以内）で直接描く。
    以前は原寸で描いてから縮小していたが、8×8 だと原寸キャンバスだけで 140MB になり、無料ホストのメモリ上限を超えた。"""
    doc = _cropped(_trimmed(doc))     # 描くときも刈った題・末尾の空き段を落とした並びを使う（`layout()` と同じものを見るため）
    o = doc.options
    L = layout(doc)
    S = L.scale                       # 1.0 か、max_side に収めるための縮小率
    sc = lambda v: rnd(v * S)         # 論理 px → 出力 px
    bg = _hex_to_rgb(o.bgCustom if o.bg == "custom" and o.bgCustom else TOKENS[o.bg])
    light = _is_light(bg)
    ink = _hex_to_rgb(TOKENS["ink" if light else "paper"])
    badge_bg = _hex_to_rgb(TOKENS["paper" if light else "ink"])
    # 番号・アーティスト名は文字色を背景へ 30% 寄せた色。固定トークン（muted / rule）だとセルリアンなどの
    # 中間の明るさの背景で埋もれるため、背景との差を常に文字色の 70% に保つ
    muted = _mix(ink, bg, 0.30)
    cell_bg = _hex_to_rgb(TOKENS["paper-3" if light else "ink-2"])

    im = Image.new("RGB", (sc(L.W), sc(L.H)), bg)
    if o.bgMode == "image" and o.bgImage:
        _paint_bg_image(im, o.bgImage, bg, o.bgImageAlpha)   # 好きな画像を背景に（2026-09-25）。文字の色は背景色（画像の平均の色）で決まる
    elif o.bgMode == "gradient" and o.bgGrad and o.bgGrad.image:
        _paint_bg_image(im, o.bgGrad.image, bg, 1.0)   # グラデーション背景（2026-09-25）。ブラウザが描いて上げた絵をそのまま敷く
    d = ImageDraw.Draw(im)

    # タイトル（グリッドの上。右サイドバーのときはサイドバーの中に描く）
    y0 = L.oy
    f_title = font("bold", max(8, sc(L.title_size)))
    if L.wrap:
        # 回り込みでは ox / oy がマスの塊の左上そのもの。タイトルは枠の左上に置く
        if L.title:
            # **字面（インク）の中心を帯の中心に置く**。PIL の anchor="lm"（上下の伸びの中心）と
            # Canvas の textBaseline="middle"（em ボックスの中心）は基準がずれていて、
            # 回り込みではタイトルが大きいぶん出力で 15px ほど食い違った
            tx = L.wrap_tx or L.wrap_pad
            t = _ellipsize(d, L.title, f_title, (L.W - L.wrap_pad - tx) * S)
            d.text((sc(tx), sc(L.wrap_top + L.title_h / 2) + rnd(max(8, sc(L.title_size)) * BASELINE)),
                   t, font=f_title, fill=ink, anchor="ls")
    elif L.title and L.side != "right":
        d.text((sc(L.ox), sc(y0 + L.title_h / 2)), _ellipsize(d, L.title, f_title, L.gw * S), font=f_title, fill=ink, anchor="lm")
        y0 += L.title_h

    # グリッド（画像は並列に取得し、取得スレッドの中でマスの大きさに切り抜く。原寸を抱えない）
    cw, ch = sc(CELL_W), sc(cell_h(doc))     # マスの幅と高さ（出力 px）
    num_px = max(8, sc(22))       # 番号の字の大きさ。**8px を下限にする**（ピクセルフォントはこれ以下で潰れる）
    num_font = font("pixel", num_px)
    from backend.config import public_mode
    with ThreadPoolExecutor(max_workers=2 if public_mode() else 6, initializer=lower_thread_priority) as ex:   # 公開時は控えめに（0.1 vCPU）
        covers = list(ex.map(lambda t: load_cover(t, cw, ch, t.fit or o.cellFit) if t else None, doc.cells))
    ov = o.overlay and overlay_ok(S, cell_short(doc))
    if ov:
        # 帯は全マス共通なので 1 回だけ作る。濃さは上端 0 → 下端 OVERLAY_ALPHA の直線（Canvas の線形グラデーションと同じ）
        cs = min(cw, ch)                      # 帯の文字は**短辺**から（16:9 は高さが短い）
        sh = max(1, rnd(ch * OVERLAY_SHADE))
        shade_mask = Image.new("L", (1, sh))
        shade_mask.putdata([rnd(255 * OVERLAY_ALPHA * (j + 0.5) / sh) for j in range(sh)])
        shade_mask = shade_mask.resize((cw, sh))
        shade = Image.new("RGB", (cw, sh), (0, 0, 0))
        ov_ts = max(8, rnd(cs * OVERLAY_TITLE))
        ov_as = max(8, rnd(cs * OVERLAY_ARTIST))
        f_ov_t, f_ov_a = font("bold", ov_ts), font("regular", ov_as)
        ov_pad = rnd(cs * OVERLAY_PAD)
    k = 0                             # 曲の入ったマスの序数（番号バッジ。空きマスは飛ばして詰める。2026-09-25）
    for i, t in enumerate(doc.cells):
        c, r = i % doc.cols, i // doc.cols
        x, y = sc(L.ox + c * (CELL_W + o.gap)), sc(y0 + r * (cell_h(doc) + o.gap))
        k += 1 if t else 0
        # **空きマスは塗らない**（背景の色が見える。2026-09-25、利用者の指摘。灰色の四角が並ぶと「読み込めなかった」ように見える）。
        # 曲の入ったマスだけ下地を塗る（ジャケットが取れなかったときに、そこに曲があると分かるように）。frontend の renderShareCanvas と同じ
        if t:
            d.rectangle((x, y, x + cw - 1, y + ch - 1), fill=cell_bg)
            cover = covers[i]
            if cover:
                im.paste(cover, (x, y))
                covers[i] = None
            if ov:
                im.paste(shade, (x, y + ch - sh), shade_mask)
                max_w = cw - ov_pad * 2
                title, artist = _one_line(t.title), _one_line(t.artist)
                ab = y + ch - ov_pad                                      # アーティスト名のベースライン
                tb = ab - rnd(ov_as * OVERLAY_LEAD) if artist else ab     # 曲名のベースライン
                ft = _shrink_font(d, title, f_ov_t, ov_ts, max_w)
                d.text((x + ov_pad, tb), _ellipsize(d, title, ft, max_w), font=ft, fill=OVERLAY_TEXT, anchor="ls")
                if artist:
                    fa = _shrink_font(d, artist, f_ov_a, ov_as, max_w, kind="regular")
                    d.text((x + ov_pad, ab), _ellipsize(d, artist, fa, max_w), font=fa, fill=OVERLAY_SUB, anchor="ls")
        # **番号バッジは曲の入ったマスだけ**、曲名リストと同じ序数で（2026-09-25。前は空きマスにも位置の番号を出していた）
        if o.numbers and t:
            label = f"{k:02d}"
            # **枠は字面（インク）に四辺の余白を足して作る**。ピクセルフォントは em ボックスの中で
            # 字面が上に寄るので、em の高さで枠を作ると数字が下に寄って見える。余白は 2px を下限にした
            # （マスが小さいときは 2px、大きいときは今までどおり sc(12)）
            bx0, by0, bx1, by1 = num_font.getbbox(label)
            pad = max(2, sc(12))
            bw, bh = (bx1 - bx0) + pad * 2, (by1 - by0) + pad * 2
            d.rectangle((x, y, x + bw - 1, y + bh - 1), fill=badge_bg)
            d.rectangle((x + bw, y, x + bw + sc(3), y + bh - 1), fill=ink)
            d.rectangle((x, y + bh, x + bw + sc(3), y + bh + sc(3)), fill=ink)
            d.text((x + pad - bx0, y + pad - by0), label, font=num_font, fill=ink)
    covers = None

    # 曲名をマス 1 つ 1 つの横に並べる（柱・1 列の並び）。番号 → 曲名、その下にアーティスト名
    if L.wrap and L.wrap_rows:
        fs = max(8, sc(L.font_s))
        f_num = font("pixel", max(8, sc(L.font_s * 0.8)))
        f_t = font("bold", fs)
        f_a = font("regular", max(8, rnd(fs * ARTIST_SCALE)))
        # **段の持ち方は 2 通り**（2026-09-25）。マスごと（`_slab_rows`）は段がマスの位置ごとにある（段の数 ＝ マスの数）ので、
        # 空きマスの段は残して何も描かない。縦一列・表（`_slab_stack`）は曲の入ったマスだけを積んである（段の数 ＝ 曲の数）。
        # 空きマスが無ければどちらも同じ対応になる。番号はどちらも曲の序数
        by_pos = len(L.wrap_segs) == len(doc.cells)
        for k, (i, t) in enumerate((i, t) for i, t in enumerate(doc.cells) if t):
            si = i if by_pos else k
            if si >= len(L.wrap_segs):
                break
            sx0, sy0, sw = L.wrap_segs[si]
            x, cy = sc(sx0), sc(sy0 + L.line_h / 2)
            num = f"{k + 1:02d}"
            # ピクセルフォントは em ボックスの中で字面が上に寄るので、字面の中心を行の中心に置く
            _, top, _, bottom = f_num.getbbox(num, anchor="ls")
            d.text((x, rnd(cy - (top + bottom) / 2)), num, font=f_num, fill=muted, anchor="ls")
            nw = d.textlength(num, font=f_num) + sc(L.font_s * 0.8)
            max_w = sc(sw) - nw
            title, artist = _one_line(t.title), _one_line(t.artist)
            if L.wrap_inline:
                # 1 行型: 曲名は番号の後ろ、アーティスト名は段の右端。同じベースラインに乗せる（右サイドバーの 1 行型と同じ）
                base = rnd(fs * BASELINE)
                d.text((x + nw, cy + base), _ellipsize(d, title, f_t, max_w), font=f_t, fill=ink, anchor="ls")
                if artist:
                    d.text((sc(sx0 + sw), cy + base), _ellipsize(d, artist, f_a, max_w), font=f_a, fill=muted, anchor="rs")
                continue
            # **1 行に入らない曲名は 2 行に折る**（「…」で切ると曲名が読めなくなる。
            # 折る位置の決め方はサイドバーと同じ `_split_title`）
            def rows_of(ft: ImageFont.FreeTypeFont) -> list[str]:
                ls = [title]
                if d.textlength(title, font=ft) > max_w:
                    l1, l2 = _split_title(d, title, ft, max_w)
                    ls = [l1, l2] if l2 else [l1]
                return ls + ([artist] if artist else [])
            rows = rows_of(f_t)
            # **1 マスの高さの ROW_FILL に収まる大きさまで字を下げ、下げた字で折り直す**（2026-09-22、利用者の指摘）。
            # 字は 1 マスの送りの 0.42 倍（SLAB_ROW_FONT1）で決めるので、曲名 1 行＋アーティスト名でも 1 マスの 9 割を埋めて
            # 曲と曲のあいだが詰まって見え、曲名が 2 行に折れると 1 マスを超えて次の曲に重なっていた（1x8・16:9 のマス）
            fs_r, ft_r, fa_r = fs, f_t, f_a
            k = len(rows)
            fit = int(sc(L.line_h) * ROW_FILL / ((k - 1) * (1.24 if k <= 2 else ROW3_STEP) + 0.5 + (0.5 * ARTIST_SCALE if artist else 0.5)))
            if fit < fs:
                fs_r = max(8, fit)
                ft_r, fa_r = font("bold", fs_r), font("regular", max(8, rnd(fs_r * ARTIST_SCALE)))
                rows = rows_of(ft_r)
            step = rnd(fs_r * (1.24 if len(rows) <= 2 else ROW3_STEP))
            top = cy - rnd(step * (len(rows) - 1) / 2)
            for j, text in enumerate(rows):
                is_artist = artist and j == len(rows) - 1
                f = fa_r if is_artist else ft_r
                size = max(8, rnd(fs_r * ARTIST_SCALE)) if is_artist else fs_r
                if not is_artist:
                    # **はみ出しがわずかなら縮めて収める**（右サイドバーの 2 行目と同じ規則）。
                    # 2 行に折っても 2 行ぶんの幅にわずかに足りない題があり（`I Love Love You
                    # (Love Love Super Dimension mix)` は 6px 超過）、「…」で切ると曲名が読めなくなる
                    f = _shrink_font(d, text, f, fs_r, max_w)
                # **行の中心からベースラインへ BASELINE だけ下げて描く**（ほかの組み方と同じ）。anchor="lm" は
                # Canvas の textBaseline="middle" と基準が違い、突き合わせで字が上下にずれていた（6px のぼかしで 4%）
                d.text((x + nw, top + j * step + rnd(size * BASELINE)), _ellipsize(d, text, f, max_w),
                       font=f, fill=muted if is_artist else ink, anchor="ls")
        _release_memory()
        return im

    # 曲名（マスの塊のまわりに回り込ませる）
    if L.wrap:
        fs = max(8, sc(L.font_s))
        sizes = {"num": ("pixel", max(8, sc(L.font_s * 0.8))), "title": ("bold", fs), "artist": ("regular", fs)}
        f_flow = {k: font(*v) for k, v in sizes.items()}
        colors = {"num": muted, "title": ink, "artist": muted}
        flow = _flow_rows(doc, L.font_s, 0.0, [float(sg[2]) for sg in L.wrap_segs])
        # **送りは 1px に丸めて足す**。実寸のまま足すと PIL と Canvas の 1px 未満の差が
        # 行の中で積み上がり、**文字が大きいほど大きくずれる**（32x1・1:1 で 11% の差になった）
        sp = float(rnd(f_flow["title"].getlength("　")))
        # **行の中身は 1 本のベースラインに乗せる**。anchor="lm"（PIL は上下の伸びの中心）と
        # Canvas の textBaseline="middle"（em ボックスの中心）は基準が違い、**文字が大きいほど
        # 食い違う**（32x1・1:1 の出力 64px で 10px ずれ、突き合わせで 11% の差になった）
        base = rnd(fs * BASELINE)
        for row, fr in enumerate(flow):
            if row >= len(L.wrap_segs):
                break
            sx0, sy0, sw = L.wrap_segs[row]
            x = sc(sx0)
            yy = sc(sy0 + L.line_h / 2) + base
            # 余った幅を曲の切れ目に配って段の右端をそろえる（配りすぎない規則は下の流し込みと同じ）
            extra = 0.0
            if fr.gaps and row < len(flow) - 1:
                # **上乗せも整数にする**。端数を持ったまま足すと、描く位置が両者で 1px ずれる
                extra = float(rnd(min(max(0.0, sc(sw) - sc(fr.width)) / fr.gaps, sp)))
            for j, (kind, text) in enumerate(fr.parts):
                if kind == "num" and j > 0:
                    x += sp + extra
                f = f_flow[kind]
                d.text((x, yy), text, font=f, fill=colors[kind], anchor="ls")
                x += rnd(d.textlength(text, font=f))
        _release_memory()
        return im

    # サイドバー（曲名リスト）
    if L.side != "none":
        sx = L.ox + L.gw + L.sb_gap if L.side == "right" else L.ox
        sy = (y0 if L.side == "right" else y0 + L.gh + L.sb_gap) + L.sb_top
        if (o.bgMode == "image" and o.bgImage) or (o.bgMode == "gradient" and o.bgGrad and o.bgGrad.image):
            # **曲名リストの後ろに地を敷く**（`LIST_VEIL`）。範囲はリストの枠をマスとの間隔の半分だけ広げたもの（マスには掛からない）。
            # 右ならタイトルも含めてマスの塊と同じ高さ、下ならリストの高さ
            vp = L.sb_gap / 2
            if L.side == "right":
                box = (sc(sx - vp), sc(y0 - vp), sc(sx + L.sb_w + vp), sc(y0 + L.gh + vp))
            else:
                box = (sc(L.ox - vp), sc(y0 + L.gh + vp), sc(L.ox + L.sb_w + vp), sc(y0 + L.gh + L.sb_gap + L.sb_h + vp))
            box = (max(0, box[0]), max(0, box[1]), min(im.width, box[2]), min(im.height, box[3]))
            if box[2] > box[0] and box[3] > box[1]:
                part = im.crop(box)
                im.paste(Image.blend(part, Image.new("RGB", part.size, bg), LIST_VEIL), box[:2])
                d = ImageDraw.Draw(im)
        # 列の幅。**右に置くときも列に割る**（列を増やしたのに全幅で描くと、2 列目が枠の外へ出る）
        col_w = (L.sb_w - LIST_COL_GAP * (L.sb_cols - 1)) // L.sb_cols
        if L.title and L.side == "right":
            # 字面の上端がグリッドの上端とそろうよう、行の中心でなく上寄せ（中心を上から 0.55 文字分）に置く
            d.text((sc(sx), sc(sy + L.title_size * 0.55)), _ellipsize(d, L.title, f_title, L.sb_w * S), font=f_title, fill=ink, anchor="lm")
            sy += L.title_h
        if L.sb_flow:
            # 曲名を続けて流し込む。行の中身は種類ごとに書体と色を変えて描く
            fs = max(8, sc(L.font_s))
            sizes = {"num": ("pixel", max(8, sc(L.font_s * 0.8))), "title": ("bold", fs), "artist": ("regular", fs)}
            f_flow = {k: font(*v) for k, v in sizes.items()}
            colors = {"num": muted, "title": ink, "artist": muted}
            flow = _flow_rows(doc, L.font_s, col_w)
            # 行の中身は 1 本のベースラインに乗せる（上の回り込みと同じ理由）
            base = rnd(fs * BASELINE)
            for row, fr in enumerate(flow):
                x = sc(sx)
                yy = sc(sy + row * L.line_h + L.line_h / 2) + base
                # 余った幅を曲の切れ目に均等に配って右端をそろえる。最後の行は伸ばさない。
                # ただし **配りすぎると切れ目が間延びする**ので、空白 1 つぶんまでしか広げない
                # （切れ目は最大でも空白 2 つぶん）。余りきらないぶんは行末に残す
                # 曲の切れ目は全角空白 1 つぶん。**これは必ず空ける**（描かずに幅だけ取ると、
                # 余りの無い行で曲と曲がくっつく。「Chevon06」のように番号が前の曲名に貼り付く）。
                # extra は右端をそろえるための上乗せで、空白 1 つぶんまで（切れ目は最大 2 つぶん）
                sp = float(rnd(f_flow["title"].getlength("　")))
                extra = 0.0
                if fr.gaps and row < len(flow) - 1:
                    extra = float(rnd(min(max(0.0, sc(col_w) - sc(fr.width)) / fr.gaps, sp)))
                for j, (kind, text) in enumerate(fr.parts):
                    # 番号の手前が曲の切れ目（行頭は除く）
                    if kind == "num" and j > 0:
                        x += sp + extra
                    f = f_flow[kind]
                    d.text((x, yy), text, font=f, fill=colors[kind], anchor="ls")
                    x += rnd(d.textlength(text, font=f))
            _release_memory()
            return im
        # **曲の入ったマスだけを詰めて並べる**（空きマスの行を作らない。番号は序数。2026-09-25）
        songs = _songs(doc)
        plan = L.sb_plan or tuple(1 for _ in songs)
        # 行の割り付け（列・その列の中での行番号）。**1 曲が列をまたがないように**詰める
        rows_per_col = _plan_rows(plan, L.sb_cols)
        places, col, used = [], 0, 0
        for r in plan:
            if used and used + r > rows_per_col and L.sb_cols > 1:
                col, used = col + 1, 0
            places.append((col, used))
            used += r
        font_s = max(8, sc(L.font_s))
        f_num = font("pixel", max(8, sc(L.font_s * 0.8)))
        f_title = font("bold", font_s)
        f_artist = font("regular", max(8, rnd(font_s * ARTIST_SCALE)))
        if L.sb_inline:
            # 1 行型: 曲名は番号の後ろ、アーティスト名は列の右端にそろえる。2 つは同じベースラインに乗せる
            # （字の大きさが違うので、行の中心で合わせると下端がずれて見える）
            base = rnd(font_s * BASELINE)
            per_col = math.ceil(len(songs) / max(1, L.sb_cols))   # 表（2〜3 列）のときの 1 列の曲数
            if L.sb_cols > 1:   # 表は列のあいだを行の高さから決める（TABLE_GAP_LH）
                tgap = rnd(L.line_h * TABLE_GAP_LH)
                col_w = (L.sb_w - tgap * (L.sb_cols - 1)) // L.sb_cols
            else:
                tgap = LIST_COL_GAP
            rule = _mix(ink, bg, TABLE_RULE)
            rule_h = max(1, rnd(font_s * 0.04))
            for i, t in enumerate(songs):
                col, row = divmod(i, per_col)
                cx = sx + col * (col_w + tgap)
                x = sc(cx)
                right = sc(cx + col_w)
                yy = sc(sy + row * L.line_h + L.line_h / 2)
                if L.sb_cols > 1 and row < per_col - 1 and i < len(songs) - 1:
                    ly = sc(sy + (row + 1) * L.line_h)
                    d.rectangle((x, ly, right - 1, ly + rule_h - 1), fill=rule)
                num = f"{i + 1:02d}"
                _, top, _, bottom = f_num.getbbox(num, anchor="ls")
                d.text((x, rnd(yy - (top + bottom) / 2)), num, font=f_num, fill=muted, anchor="ls")
                nw = d.textlength(num, font=f_num) + sc(L.font_s * 0.8)
                max_w = col_w * S - nw
                title, artist = _one_line(t.title), _one_line(t.artist)
                d.text((x + nw, yy + base), _ellipsize(d, title, f_title, max_w), font=f_title, fill=ink, anchor="ls")
                if artist:
                    # 1 行型は全曲が 1 行に並ぶ大きさで組んである（`_inline_one_line`）ので、同じ行の右端に置く
                    d.text((right, yy + base), _ellipsize(d, artist, f_artist, max_w), font=f_artist,
                           fill=muted, anchor="rs")
            _release_memory()
            return im
        # **割り付けで取った行数より少ない行で描けた曲のぶん、その列の後ろの曲を詰める**（2026-09-17）。
        # 割り付けは字ごとに 1px に丸めた幅で「3 行」と見込むが、実際に折ると 2 行で入ることがあり、
        # 空いた 1 行がそのまま隙間になっていた（利用者の 4x4・16:9 で 2 か所）。列の下に余りが出るほうがまし
        shift: dict[int, int] = {}
        for i, t in enumerate(songs):
            col, row = places[i]
            row -= shift.get(col, 0)
            x = sc(sx + col * (col_w + LIST_COL_GAP))
            row_y = lambda r: sc(sy + r * L.line_h + L.line_h / 2)   # noqa: E731
            yy = row_y(row)
            num = f"{i + 1:02d}"
            # ピクセルフォントは em ボックス内で字面が上に寄るので、字面（インク）の中心を行の中心に置く
            _, top, _, bottom = f_num.getbbox(num, anchor="ls")
            d.text((x, rnd(yy - (top + bottom) / 2)), num, font=f_num, fill=muted, anchor="ls")
            nw = d.textlength(num, font=f_num) + sc(L.font_s * 0.8)
            max_w = col_w * S - nw
            title, artist = _one_line(t.title), _one_line(t.artist)
            # 曲名の行（入らなければ 2 行に折る）。**アーティスト名は必ず次の行**
            # 割り付けで取った行数のうち、アーティストに割り当てた行（1 行か、折るなら 2 行）。
            # **`_row_plan` と同じ物差し（論理 px）で数える**
            a_rows = L.sb_arows[i] if i < len(L.sb_arows) else (1 if artist else 0)
            title_rows = plan[i] - a_rows
            if title_rows >= 2:
                l1, l2 = _split_title(d, title, f_title, max_w)
                if not l2:   # 割り付けでは 2 行取ったが実際は 1 行で収まった（測る字の大きさが少し違うため）
                    title_rows = 1
                    l1 = _ellipsize(d, title, f_title, max_w)
                if not (l2 and title_rows >= 3 and not _fits_shrunk(d, l2, f_title, font_s, max_w)):
                    d.text((x + nw, yy), l1, font=f_title, fill=ink, anchor="lm")
                if l2 and title_rows >= 3:
                    # **3 行目**（割り付けが 3 行取った題）。1/3 の所で折り直し、残りを半分に折る。
                    # 折った前半は必ず入る（`_split_title` は前半が収まる位置しか選ばない）ので、縮めるのは最後の行だけ
                    if _fits_shrunk(d, l2, f_title, font_s, max_w):
                        title_rows = 2   # 実際は縮めれば 2 行で収まった（測る字の大きさが少し違うため）
                    else:
                        l1, l2, l3 = _split_title3(d, title, f_title, font_s, max_w)
                        d.text((x + nw, yy), l1, font=f_title, fill=ink, anchor="lm")
                        d.text((x + nw, row_y(row + 1)), l2, font=f_title, fill=ink, anchor="lm")
                        l2 = l3
                        if not l3:
                            title_rows = 2
                if l2:
                    # 最後の行（たいていは「(feat. …)」）は、はみ出しがわずかなら**縮めて収める**。
                    # 「…」で切ると共演者が読めなくなるので、切るのは縮めても入らないときだけ
                    f2 = _shrink_font(d, l2, f_title, font_s, max_w)
                    d.text((x + nw, row_y(row + title_rows - 1)), _ellipsize(d, l2, f2, max_w), font=f2, fill=ink, anchor="lm")
            else:
                d.text((x + nw, yy), _ellipsize(d, title, f_title, max_w), font=f_title, fill=ink, anchor="lm")
            if artist:
                # アーティスト名は曲名のすぐ下に寄せる（行の中心のままだと均等に散らばって、
                # どの曲名の下なのかが読み取りにくい）
                a_size = max(8, rnd(font_s * ARTIST_SCALE))
                ay = row_y(row + title_rows) - sc(L.line_h * 0.14)
                a1, a2 = (_split_title(d, artist, f_artist, max_w) if a_rows >= 2 else (artist, ""))
                if a_rows >= 2 and not a2:
                    a_rows = 1   # 割り付けでは 2 行取ったが実際は 1 行で収まった（測る字の大きさが少し違うため）
                if a_rows >= 2:
                    d.text((x + nw, ay), a1, font=f_artist, fill=muted, anchor="lm")
                    fa2 = _shrink_font(d, a2, f_artist, a_size, max_w, kind="regular")
                    d.text((x + nw, row_y(row + title_rows + 1) - sc(L.line_h * 0.14)), _ellipsize(d, a2, fa2, max_w),
                           font=fa2, fill=muted, anchor="lm")
                else:
                    # 1 行のとき、はみ出しがわずかなら**縮めて収める**（曲名の最後の行と同じ考え方）
                    fa1 = _shrink_font(d, artist, f_artist, a_size, max_w, kind="regular")
                    d.text((x + nw, ay), _ellipsize(d, artist, fa1, max_w), font=fa1, fill=muted, anchor="lm")
            shift[col] = shift.get(col, 0) + max(0, plan[i] - (title_rows + a_rows))

    _release_memory()
    return im


def _release_memory() -> None:
    """描画で使った大きなバッファを OS に返す（glibc は解放済みでも抱え込み、RSS が下がらないことがある）"""
    import gc
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass   # Linux 以外


# ---------- 保存と世代管理 ----------
_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]+")


def outputs_keep() -> int:
    try:
        return max(1, int(os.getenv("OUTPUTS_KEEP", "50")))
    except ValueError:
        return 50


def prune_outputs(keep: int | None = None) -> int:
    """直近 keep 件を残して古い PNG を削除。削除数を返す。"""
    keep = outputs_keep() if keep is None else keep
    if not OUTPUTS.exists():
        return 0
    files = sorted(OUTPUTS.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for p in files[keep:]:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def render_to_file(doc: GridDoc) -> tuple[Path, Image.Image]:
    """PNG を outputs/<name>-<timestamp>.png に保存してパスと画像を返す。"""
    OUTPUTS.mkdir(exist_ok=True)
    im = render(doc)
    stem = _SAFE_RE.sub("", doc.name) or "grid"
    path = OUTPUTS / f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}.png"
    n = 1
    while path.exists():
        n += 1
        path = OUTPUTS / f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}-{n}.png"
    im.save(path, "PNG", compress_level=6)   # optimize=True は 3 倍遅いわりに数 % しか縮まない
    prune_outputs()
    return path, im
