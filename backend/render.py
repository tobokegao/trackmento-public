"""Pillow によるサーバー側 PNG 描画。CLI からも /render からも使う。

レイアウト計算はフロント（frontend/index.html の layout()）と同じ式にしてあるので、
Web で「画像を作る」とサーバーで作ったものが同じ寸法・配置になる。
色は CSS の oklch トークンを sRGB に変換して使う。
"""
from __future__ import annotations

import io
import math
import unicodedata
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from backend import imgtools, netguard, uploads
from backend.cache import cache
from backend.logutil import brief
from backend.grids import GridDoc
from backend.models import NO_COVER, Track

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
OUTPUTS = ROOT / "outputs"

CELL_PX = 600
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
}


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _is_light(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.55


# ---------- フォント ----------
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    """kind: 'bold' | 'regular' | 'pixel'（Silkscreen Bold）"""
    key = (kind, size)
    if key not in _font_cache:
        name = {"bold": "IBMPlexSansJP-Bold.ttf", "regular": "IBMPlexSansJP-Regular.ttf", "pixel": "Silkscreen-Bold.ttf"}[kind]
        p = FONTS / name
        try:
            _font_cache[key] = ImageFont.truetype(str(p), size)
        except OSError as e:
            raise RuntimeError(f"フォントが見つかりません: {p}") from e
    return _font_cache[key]


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
    フォントに無い文字もここで落とす"""
    return " ".join(_drawable(s or "").split())


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
    if not ctype.startswith("image/") or len(r.content) > IMAGE_MAX_BYTES:
        raise ValueError(f"画像として扱えません: {ctype} {len(r.content)} bytes")
    data = r.content
    if imgtools.is_video_thumb(url):
        # 動画のサムネイルは黒帯を切ってから保存する。/image-proxy も同じキャッシュを返すので、
        # どちらの経路が先に保存しても内容が同じになる（ブラウザ描画とサーバー描画の切り抜きが揃う）
        data, ctype = imgtools.trim_letterbox_bytes(data, ctype)
    cache.set_image(url, ctype, data)
    return data


def load_cover(t: Track, size: int = CELL_PX) -> Image.Image | None:
    """ジャケットを取得し、マスの大きさ（CELL_PX 角）に切り抜いて返す。
    原寸の画像を持ち続けないこと（64 枚 × 数千 px で GB 単位になる）。JPEG は draft で縮小デコードする。
    高解像度（image）が取れないときはサムネイル（thumb）で代用する（Cover Art Archive の 500、YouTube の maxres 欠落など）。"""
    urls = [t.image] + ([t.thumb] if t.thumb and t.thumb != t.image else [])
    for url in urls:
        try:
            return _load_cover_from(url, t, size)
        except Exception as e:  # 1枚の失敗で全体を止めない
            timed_out = isinstance(e, httpx.TimeoutException)
            retry = url != urls[-1] and not timed_out   # 配信元が応答しないときはサムネイルも同じ配信元なので待たない
            print(f"[render] image failed ({brief(e)}): {t.title} / {t.artist}" + ("（サムネイルで再試行）" if retry else ""))
            if not retry:
                break
    return None


def _load_cover_from(url: str, t: Track, size: int) -> Image.Image:
    data = fetch_image_bytes(url)
    with Image.open(io.BytesIO(data)) as src:
        if src.format == "JPEG":
            src.draft("RGB", (size, size))   # マスの大きさ以上で最も小さい 1/2・1/4・1/8 スケールでデコード（デコードが描画 CPU の大半）
        im = src.convert("RGB")
    if imgtools.is_video_thumb(url) or t.source in ("youtube", "nicovideo", "bilibili", "otodb"):
        im = imgtools.trim_letterbox(im)   # 動画サムネイルの黒帯を落としてから切り抜く
    fitted = _cover_fit(im, size, size)
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


# ---------- レイアウト ----------
@dataclass
class Layout:
    W: int; H: int; scale: float; ox: int; oy: int
    gw: int; gh: int
    title: str; title_size: int; title_h: int
    side: str; sb_w: int; sb_h: int; sb_cols: int; line_h: int; font_s: int; sb_gap: int


def layout(doc: GridDoc) -> Layout:
    o = doc.options
    cols, rows, n, m, g = doc.cols, doc.rows, doc.size, o.margin, o.gap
    title = _one_line(doc.title) if o.showTitle else ""
    gw = cols * CELL_PX + (cols - 1) * g
    gh = rows * CELL_PX + (rows - 1) * g
    title_size = rnd(min(96, max(48, gw * 0.045)))
    title_h = rnd(title_size * 1.9) if title else 0
    ratio = RATIOS[o.ratio]
    # サイドバー: 横長・設定なしなら右、正方形以下（1:1 / 4:5 / 9:16）ならグリッドの下。
    # 正方形で右に置くと内容が横長になり、上下の余白ばかり広がるため
    side = ("right" if ratio is None or ratio > 1 else "bottom") if o.sidebar else "none"
    # 右サイドバーのときタイトルはサイドバーの上（曲名リストの前）に置く。グリッドの上に置くと内容が縦長になり、
    # 横長の比率（16:9）で左右の余白ばかり広がるため
    title_top_h = 0 if side == "right" else title_h
    line_h = max(30, min(84, (gh - title_h) // n)) if side == "right" else rnd(max(48, min(96, gw * 0.045)))
    font_s = rnd(line_h * 0.5)
    sb_w = sb_h = 0
    sb_cols = 1
    if side == "right":
        # 幅は「最長の行」に合わせる（最低 720px、最大でグリッド幅と同じ）。長い曲名が「…」で切れにくくなる
        need = max(_longest_line(doc, font_s), _title_width(title, title_size))
        sb_w, sb_h = max(720, min(gw, need)), gh
    if side == "bottom":
        # 列数: 9:16 は 12 曲まで 1 列。1:1 / 4:5 は縦に伸びると横の余りが増えるので 6 曲以上で 2 列
        sb_cols = 2 if n > 12 or (ratio >= 0.8 and n >= 6) else 1
        sb_w, sb_h = gw, math.ceil(n / sb_cols) * line_h
    sb_gap = 0 if side == "none" else GAP_PX * 4
    content_w = gw + sb_gap + sb_w if side == "right" else gw
    content_h = title_top_h + gh + (sb_gap + sb_h if side == "bottom" else 0)
    W, H = _fit(content_w, content_h, m, ratio)
    if ratio is not None and (W, H) != (content_w + m * 2, content_h + m * 2):
        # 比率合わせで余りが出る辺は余白が広がる。反対の辺が指定値（既定 16px）のままだと上下（縦長なら左右）だけ
        # 極端に狭く見えるため、余りが出るときは指定値と「内容の短辺の 4%」の大きい方を四辺の最小余白にする
        W, H = _fit(content_w, content_h, max(m, rnd(min(content_w, content_h) * 0.04)), ratio)
    from backend.config import max_side
    scale = min(1.0, max_side() / max(W, H))
    return Layout(W, H, scale, rnd((W - content_w) / 2), rnd((H - content_h) / 2), gw, gh,
                  title, title_size, title_h, side, sb_w, sb_h, sb_cols, line_h, font_s, sb_gap)


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
    return int(math.ceil(font("bold", title_size).getlength(title))) + 8 if title else 0


def _longest_line(doc: GridDoc, font_s: int) -> int:
    """サイドバー 1 行（番号 + 曲名 + アーティスト）の最大幅（px）。"""
    f_num, f_title, f_artist = font("pixel", rnd(font_s * 0.8)), font("bold", font_s), font("regular", font_s)
    nw = f_num.getlength("00") + rnd(font_s * 0.8)
    best = 0
    for t in doc.cells:
        if t:
            best = max(best, nw + f_title.getlength(_one_line(t.title)) + f_artist.getlength(f"  {_one_line(t.artist)}"))
    return int(math.ceil(best)) + 8


def _fit_line(d: ImageDraw.ImageDraw, title: str, artist: str, font_s: int, max_w: float) -> tuple[ImageFont.FreeTypeFont, ImageFont.FreeTypeFont, str, str]:
    """1 行が max_w に収まるよう、フォントを 65% まで縮め、それでも入らなければアーティスト → 曲名の順に省略する。"""
    for scale in (1.0, 0.92, 0.85, 0.78, 0.72, 0.65):
        fs = max(12, rnd(font_s * scale))
        ft, fa = font("bold", fs), font("regular", fs)
        a = f"  {artist}" if artist else ""
        if d.textlength(title, font=ft) + d.textlength(a, font=fa) <= max_w:
            return ft, fa, title, a
    ft, fa = font("bold", max(12, rnd(font_s * 0.65))), font("regular", max(12, rnd(font_s * 0.65)))
    a = f"  {artist}" if artist else ""
    tw = d.textlength(title, font=ft)
    if tw <= max_w * 0.7:
        return ft, fa, title, _ellipsize(d, a, fa, max_w - tw)
    return ft, fa, _ellipsize(d, title, ft, max_w), ""


# ---------- 描画 ----------
def render(doc: GridDoc) -> Image.Image:
    """レイアウト（論理 px。CELL_PX=600 基準）を計算し、最終サイズ（max_side 以内）で直接描く。
    以前は原寸で描いてから縮小していたが、8×8 だと原寸キャンバスだけで 140MB になり、無料ホストのメモリ上限を超えた。"""
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
    d = ImageDraw.Draw(im)

    # タイトル（グリッドの上。右サイドバーのときはサイドバーの中に描く）
    y0 = L.oy
    f_title = font("bold", max(8, sc(L.title_size)))
    if L.title and L.side != "right":
        d.text((sc(L.ox), sc(y0 + L.title_h / 2)), _ellipsize(d, L.title, f_title, L.gw * S), font=f_title, fill=ink, anchor="lm")
        y0 += L.title_h

    # グリッド（画像は並列に取得し、取得スレッドの中でマスの大きさに切り抜く。原寸を抱えない）
    cell = sc(CELL_PX)
    num_font = font("pixel", max(8, sc(22)))
    from backend.config import public_mode
    with ThreadPoolExecutor(max_workers=2 if public_mode() else 6, initializer=lower_thread_priority) as ex:   # 公開時は控えめに（0.1 vCPU）
        covers = list(ex.map(lambda t: load_cover(t, cell) if t else None, doc.cells))
    for i, t in enumerate(doc.cells):
        c, r = i % doc.cols, i // doc.cols
        x, y = sc(L.ox + c * (CELL_PX + o.gap)), sc(y0 + r * (CELL_PX + o.gap))
        d.rectangle((x, y, x + cell - 1, y + cell - 1), fill=cell_bg)
        if t:
            cover = covers[i]
            if cover:
                im.paste(cover, (x, y))
                covers[i] = None
        if o.numbers:
            label = f"{i + 1:02d}"
            bw, bh = math.ceil(d.textlength(label, font=num_font)) + sc(24), sc(40)
            d.rectangle((x, y, x + bw - 1, y + bh - 1), fill=badge_bg)
            d.rectangle((x + bw, y, x + bw + sc(3), y + bh - 1), fill=ink)
            d.rectangle((x, y + bh, x + bw + sc(3), y + bh + sc(3)), fill=ink)
            d.text((x + sc(12), y + bh / 2 + 1), label, font=num_font, fill=ink, anchor="lm")
    covers = None

    # サイドバー（曲名リスト）
    if L.side != "none":
        sx = L.ox + L.gw + L.sb_gap if L.side == "right" else L.ox
        sy = y0 if L.side == "right" else y0 + L.gh + L.sb_gap
        col_w = L.sb_w if L.side == "right" else (L.sb_w - GAP_PX * 2 * (L.sb_cols - 1)) // L.sb_cols
        if L.title and L.side == "right":
            # 字面の上端がグリッドの上端とそろうよう、行の中心でなく上寄せ（中心を上から 0.55 文字分）に置く
            d.text((sc(sx), sc(sy + L.title_size * 0.55)), _ellipsize(d, L.title, f_title, L.sb_w * S), font=f_title, fill=ink, anchor="lm")
            sy += L.title_h
        per_col = doc.size if L.side == "right" else math.ceil(doc.size / L.sb_cols)
        font_s = max(8, sc(L.font_s))
        f_num = font("pixel", max(8, sc(L.font_s * 0.8)))
        for i, t in enumerate(doc.cells):
            col, row = i // per_col, i % per_col
            x = sc(sx + col * (col_w + GAP_PX * 2))
            yy = sc(sy + row * L.line_h + L.line_h / 2)
            num = f"{i + 1:02d}"
            # ピクセルフォントは em ボックス内で字面が上に寄るので、字面（インク）の中心を行の中心に置く
            _, top, _, bottom = f_num.getbbox(num, anchor="ls")
            d.text((x, rnd(yy - (top + bottom) / 2)), num, font=f_num, fill=muted, anchor="ls")
            nw = d.textlength(num, font=f_num) + sc(L.font_s * 0.8)
            if not t:
                continue
            max_w = col_w * S - nw
            f_title, f_artist, title_s, artist_s = _fit_line(d, _one_line(t.title), _one_line(t.artist), font_s, max_w)
            d.text((x + nw, yy), title_s, font=f_title, fill=ink, anchor="lm")
            if artist_s:
                d.text((x + nw + d.textlength(title_s, font=f_title), yy), artist_s, font=f_artist, fill=muted, anchor="lm")

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
