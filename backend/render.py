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
    # もう 1 組のパレット（2026-09-15 に追加）。リソグラフ寄りの上の 6 色より彩度が高い。
    # **この 6 色は実際の色見本から取った値なので oklch ではなく生の 16 進で持つ**
    # （frontend/index.html の TOKENS_RGB と POP_PALETTE にも同じ値がある。片方だけ変えない）
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
    side: str; sb_w: int; sb_h: int; sb_cols: int; line_h: int; font_s: int; sb_gap: int; sb_flow: bool
    sb_plan: tuple[int, ...] = ()   # 曲ごとの段数（1 か 2）。2 は「(feat. …)」を次の段へ落とすもの


# 曲が多いと 1 曲 1 行では文字が小さくなりすぎる（16×16 で出力 8px）。そこで曲名を
# 続けて流し込み、幅で折り返す。区切りの記号は置かない。番号がピクセルフォントで
# 本文と書体も色も違うので、それ自体が切れ目になる
class FlowRow(NamedTuple):
    parts: list[tuple[str, str]]   # ("num"|"title"|"artist", 文字列)
    width: float                   # 文字と曲間の送りで使った幅
    gaps: int                      # 曲の切れ目の数（余った幅をここに配る）


FLOW_MIN_FONT = 20        # 1 曲 1 行のとき、出力でこれより小さくなるなら流し込みに切り替える
# 入る限り大きく。曲が少ないほど大きな字になる（流し込みに切り替わるのは曲が多いときだけ）
FLOW_FONT_STEPS = (132, 120, 108, 96, 84, 72, 64, 56, 48, 42, 36, 30, 26, 22, 18)


# 曲名の末尾の「(feat. …)」。**ここだけは 2 段目に落とせる**（曲名の本体とアーティスト名を守るため）。
# 全角の括弧と、feat / ft / featuring の表記ゆれを見る。括弧が閉じていないもの（途中で切れた題）は対象外
_FEAT_RE = re.compile(r"\s*[（(\[]\s*(?:feat|ft|featuring)[.\s][^）)\]]*[）)\]]\s*$", re.IGNORECASE)


def _split_feat(title: str) -> tuple[str, str]:
    """曲名を「本体」と「(feat. …)」に分ける。無ければ (曲名, "")。"""
    m = _FEAT_RE.search(title)
    if not m or not m.start():   # 丸ごと feat. だけの題は分けない
        return title, ""
    return title[:m.start()].rstrip(), title[m.start():].strip()


# 曲名リスト（1 曲 1 行ではないほう）の作り。**曲名とアーティスト名を上下 2 行に分ける**。
# 横に並べると長い曲名でアーティストが押し出されるが、行を分ければ必ず読める。
# 曲が増えたら列を増やして、1 列あたりの行数を減らす（行間と文字を大きく保つため）
LIST_MIN_COL = 640        # 1 列の最小幅（論理 px）。これを割るなら列を増やさない
LIST_COMFY_FONT = 26      # 出力での曲名の大きさ（px）。これ未満なら列を増やす（下限は FLOW_MIN_FONT）
LIST_MAX_COLS = 3
LIST_COL_GAP = GAP_PX * 5   # 列と列のあいだ。マスの間隔と同じでは隣の曲名と近すぎて、どちらの列か迷う
ARTIST_SCALE = 0.78       # アーティスト名は曲名より小さく、薄い色で


def _row_plan(doc: GridDoc, font_s: int, max_w: float) -> tuple[int, ...]:
    """曲ごとの行数を返す。

    - アーティスト名があれば **曲名の行 + アーティストの行** で 2 行（無ければ 1 行）
    - 曲名が 1 行に収まらなければ曲名を 2 行に折り、その曲だけ 1 行増える（最大 3 行）
    """
    ft = font("bold", max(12, font_s))
    nw = font("pixel", rnd(font_s * 0.8)).getlength("00") + rnd(font_s * 0.8)
    avail = max(1.0, max_w - nw)
    plan = []
    for t in doc.cells:
        if not t:
            plan.append(1)
            continue
        rows = 2 if _one_line(t.artist) else 1
        if ft.getlength(_one_line(t.title)) > avail:
            rows += 1
        plan.append(rows)
    return tuple(plan)


# 曲名を折るときに切りたい場所。**閉じ括弧の「後ろ」で折る**ので、括弧の中身が上下に分かれない
_BREAK_AFTER = "　 ）)］]】〉》」』"
_BREAK_BEFORE = "（([［[【〈《「『／/～-—"


def _break_at(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_w: float) -> tuple[str, str]:
    """切れ目が見つからないときの保険。max_w に収まるところまで入れて、字の途中で折る。"""
    cut = len(text)
    while cut > 1 and d.textlength(text[:cut], font=f) > max_w:
        cut -= 1
    return text[:cut].rstrip(), text[cut:].lstrip()


def _split_title(d: ImageDraw.ImageDraw, title: str, f: ImageFont.FreeTypeFont, max_w: float) -> tuple[str, str]:
    """曲名を 2 行に分ける。**なるべく 2 行の長さがそろう位置**で折る。

    切れ目の候補は「区切りに使える記号の前後」。そのうち**行の真ん中にいちばん近いもの**を選ぶ。
    「(feat. …)」の手前は少し優遇する（そこで折れれば曲名の本体が単独で読めるため）。
    候補が無ければ字の途中で折る。
    """
    total = d.textlength(title, font=f)
    target = total / 2
    head, _feat = _split_feat(title)
    feat_at = len(head) + 1 if _feat else -1   # 括弧の手前（空白を 1 つ挟む）
    best: tuple[float, int] | None = None
    for i in range(1, len(title)):
        if not (title[i - 1] in _BREAK_AFTER or title[i] in _BREAK_BEFORE):
            continue
        w1 = d.textlength(title[:i].rstrip(), font=f)
        if w1 > max_w:
            break
        score = abs(w1 - target)
        if i == feat_at or (feat_at > 0 and abs(i - feat_at) <= 1):
            score *= 0.6   # 「(feat. …)」の手前は優遇。ちょうどよい位置なら選ばれる
        if best is None or score < best[0]:
            best = (score, i)
    if best is not None:
        i = best[1]
        return title[:i].rstrip(), title[i:].lstrip()
    return _break_at(d, title, f, max_w)


def _clip_to(text: str, f: ImageFont.FreeTypeFont, max_w: float) -> str:
    """max_w に収まるところまで切って「…」を付ける。"""
    if f.getlength(text) <= max_w:
        return text
    while text and f.getlength(text + "…") > max_w:
        text = text[:-1]
    return text + "…"


def _flow_rows(doc: GridDoc, font_s: int, max_w: float) -> list[FlowRow]:
    """流し込んだときの各行を返す。

    **折り返しは字の単位**。曲の単位で折ると行の頭がいつも番号になって、規則的に見えてしまう。
    字で折れば文章のように流れる。そのかわりサーバー（PIL）とブラウザ（Canvas）で
    折り返す位置がわずかにずれる（字幅の計り方が違うため）。内容は同じで、位置だけの違い。

    行には「使った幅」と「曲の切れ目の数」を添える。描画側が余った幅を切れ目に配って
    右端をそろえる。
    """
    fonts = {"num": font("pixel", rnd(font_s * 0.8)), "title": font("bold", font_s), "artist": font("regular", font_s)}
    gap = float(rnd(fonts["title"].getlength("　")))   # 曲と曲のあいだは全角空白 1 つぶん
    rows: list[FlowRow] = []
    cur: list[tuple[str, str]] = []
    x = 0.0
    gaps = 0

    def flush() -> None:
        nonlocal cur, x, gaps
        if cur:
            rows.append(FlowRow(cur, x, gaps))
        cur, x, gaps = [], 0.0, 0

    def put(kind: str, text: str) -> None:
        nonlocal x
        f = fonts[kind]
        for ch in text:
            # **折り返しの判定は 1px に丸めた字幅で行う**。PIL と Canvas の字幅は 1px 未満だけ違い、
            # 生の値で足していくと境目の字で折る・折らないが入れ替わり、そこから先の行が全部ずれる。
            # 丸めればほとんどの字で同じ値になり、両者が同じ位置で折る（描くときは実寸のまま）
            w = float(rnd(f.getlength(ch)))
            if x + w > max_w and cur:
                flush()
            if cur and cur[-1][0] == kind:
                cur[-1] = (kind, cur[-1][1] + ch)
            else:
                cur.append((kind, ch))
            x += w

    for i, t in enumerate(doc.cells):
        if not t:
            continue
        if cur:
            # 曲の切れ目。**行末に来た切れ目は数えない**（数えると、その行の幅に使っていない
            # 送りが入り、余りの配り方がずれる）
            if x + gap > max_w:
                flush()
            else:
                x += gap
                gaps += 1
        put("num", f"{i + 1:02d}")
        put("title", " " + _one_line(t.title))
        if t.artist:
            put("artist", " " + _one_line(t.artist))
    flush()
    return rows


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
    # 1 曲は「曲名の行 + アーティストの行」の 2 行。まずその前提で行の高さを見積もる
    base_rows = sum(2 if (t and _one_line(t.artist)) else 1 for t in doc.cells)
    avail_h = gh - title_h
    sb_w = sb_h = 0
    sb_cols = 1
    sb_gap = 0 if side == "none" else GAP_PX * 4
    cap = gw
    if side == "right" and ratio is not None:
        # **比率が決まっているときは、横に余る幅を先にサイドバーへ回す**。高さはグリッドで決まるので、
        # 全体の幅は比率から決まってしまい、サイドバーを狭くしたぶんは余白になって捨てられるだけ
        # **グリッド幅で下駄を履かせない**。比率から決まる幅を超えると、その分だけ上下の余白が
        # 広がるか、はみ出して描かれる（2 列にしたとき実際にはみ出した）
        w_est = rnd((title_top_h + gh + m * 2) * ratio)
        cap = max(LIST_MIN_COL, min(gw * 2, w_est - m * 2 - gw - sb_gap))

    def _sidebar(cols: int, rows_total: int) -> tuple[int, int, int]:
        """列数を決めたときの (行の高さ, 文字の大きさ, サイドバーの幅)。"""
        if side == "right":
            lh = max(30, min(96, avail_h // max(1, math.ceil(rows_total / cols))))
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
        pad = max(m, rnd(min(cw, ch) * 0.035))
        w, h = _fit(cw, ch, pad, ratio)
        if ratio is not None and (w, h) != (cw + pad * 2, ch + pad * 2):
            # 比率合わせで余りが出る辺は余白が広がる。反対の辺が狭いままだと上下（縦長なら左右）だけ
            # 極端に狭く見えるため、余りが出るときは「内容の短辺の 4%」まで引き上げる
            w, h = _fit(cw, ch, max(m, rnd(min(cw, ch) * 0.04)), ratio)
        from backend.config import max_side
        return w, h, min(1.0, max_side() / max(w, h))

    W, H, scale = _frame(sb_w, sb_h)
    # **文字が小さくなるなら、まず列を増やす**。1 列のまま縦に詰めるより、列を割って 1 列あたりの
    # 行数を減らしたほうが行間も文字も大きく取れる（25 曲で 2 列。参考にした他サービスと同じ考え方）。
    # 判断は論理 px ではなく**出力で何 px になるか**で行う（比率・余白・タイトルの有無で変わるため）
    if side == "right":
        while sb_cols < LIST_MAX_COLS and font_s * scale < LIST_COMFY_FONT:
            lh, fs, w = _sidebar(sb_cols + 1, base_rows)
            if (w - LIST_COL_GAP * sb_cols) // (sb_cols + 1) < LIST_MIN_COL:
                break
            _, _, scale2 = _frame(w, sb_h)
            if fs * scale2 <= font_s * scale:   # 増やしても大きくならないならやめる
                break
            sb_cols, line_h, font_s, sb_w = sb_cols + 1, lh, fs, w
            W, H, scale = _frame(sb_w, sb_h)
    # 曲名が 1 行に入らなければ 2 行に折るので、その曲だけ行が増える。増えたぶん高さを取り直す。
    # **割り付けは 1 度しか計算しない**（小さくした字で計算し直すと、折る・折らないを行き来するため）
    sb_plan: tuple[int, ...] = ()
    if side != "none":
        col_w0 = (sb_w - LIST_COL_GAP * (sb_cols - 1)) // sb_cols
        sb_plan = _row_plan(doc, font_s, col_w0)
        rows_per_col = _plan_rows(sb_plan, sb_cols)
        if sum(sb_plan) > base_rows:
            if side == "right":
                line_h = max(30, min(96, avail_h // max(1, rows_per_col)))
                font_s = rnd(line_h * 0.56)
            else:
                sb_h = rows_per_col * line_h
            W, H, scale = _frame(sb_w, sb_h)
        elif side == "bottom":
            sb_h = rows_per_col * line_h
            W, H, scale = _frame(sb_w, sb_h)
    # 曲が多いと、列を増やしても出力での文字が読めない大きさになる。そのときだけ流し込みに切り替える
    sb_flow = side != "none" and font_s * scale < FLOW_MIN_FONT
    if sb_flow:
        if side == "right" and ratio is not None:
            # 高さはグリッドで決まるので、横は比率から決まる。余る幅は全部サイドバーに回す
            # （1 曲 1 行のときは「最長の行」に合わせていたが、流し込みでは広いほど行が減って字が大きくできる）
            w_est = rnd((title_top_h + gh + m * 2) * ratio)
            sb_w = max(sb_w, min(gw * 2, w_est - m * 2 - gw - sb_gap))
        avail = (gh - title_h) if side == "right" else sb_h
        for fs in FLOW_FONT_STEPS:
            lh = rnd(fs * 1.5)
            rows = _flow_rows(doc, fs, sb_w if side == "right" else gw)
            if len(rows) * lh <= avail:
                break
        font_s, line_h, sb_cols = fs, lh, 1
        if side == "bottom":
            sb_h = len(rows) * line_h
        W, H, scale = _frame(sb_w, sb_h)
    content_w = gw + sb_gap + sb_w if side == "right" else gw
    content_h = title_top_h + gh + (sb_gap + sb_h if side == "bottom" else 0)
    return Layout(W, H, scale, rnd((W - content_w) / 2), rnd((H - content_h) / 2), gw, gh,
                  title, title_size, title_h, side, sb_w, sb_h, sb_cols, line_h, font_s, sb_gap, sb_flow,
                  () if sb_flow else sb_plan)


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
    return int(math.ceil(font("bold", title_size).getlength(title))) + 8 if title else 0


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
        # 列の幅。**右に置くときも列に割る**（列を増やしたのに全幅で描くと、2 列目が枠の外へ出る）
        col_w = (L.sb_w - LIST_COL_GAP * (L.sb_cols - 1)) // L.sb_cols
        if L.title and L.side == "right":
            # 字面の上端がグリッドの上端とそろうよう、行の中心でなく上寄せ（中心を上から 0.55 文字分）に置く
            d.text((sc(sx), sc(sy + L.title_size * 0.55)), _ellipsize(d, L.title, f_title, L.sb_w * S), font=f_title, fill=ink, anchor="lm")
            sy += L.title_h
        if L.sb_flow:
            # 曲名を続けて流し込む。行の中身は種類ごとに書体と色を変えて描く
            fs = max(8, sc(L.font_s))
            f_flow = {"num": font("pixel", max(8, sc(L.font_s * 0.8))), "title": font("bold", fs), "artist": font("regular", fs)}
            colors = {"num": muted, "title": ink, "artist": muted}
            flow = _flow_rows(doc, L.font_s, col_w)
            for row, fr in enumerate(flow):
                x = sc(sx)
                yy = sc(sy + row * L.line_h + L.line_h / 2)
                # 余った幅を曲の切れ目に均等に配って右端をそろえる。最後の行は伸ばさない。
                # ただし **配りすぎると切れ目が間延びする**ので、空白 1 つぶんまでしか広げない
                # （切れ目は最大でも空白 2 つぶん）。余りきらないぶんは行末に残す
                # 曲の切れ目は全角空白 1 つぶん。**これは必ず空ける**（描かずに幅だけ取ると、
                # 余りの無い行で曲と曲がくっつく。「Chevon06」のように番号が前の曲名に貼り付く）。
                # extra は右端をそろえるための上乗せで、空白 1 つぶんまで（切れ目は最大 2 つぶん）
                sp = f_flow["title"].getlength("　")
                extra = 0.0
                if fr.gaps and row < len(flow) - 1:
                    extra = min(max(0.0, sc(col_w) - sc(fr.width)) / fr.gaps, sp)
                for j, (kind, text) in enumerate(fr.parts):
                    # 番号の手前が曲の切れ目（行頭は除く）
                    if kind == "num" and j > 0:
                        x += sp + extra
                    f = f_flow[kind]
                    d.text((x, yy), text, font=f, fill=colors[kind], anchor="lm")
                    x += d.textlength(text, font=f)
            _release_memory()
            return im
        plan = L.sb_plan or tuple(1 for _ in doc.cells)
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
        for i, t in enumerate(doc.cells):
            col, row = places[i]
            x = sc(sx + col * (col_w + LIST_COL_GAP))
            row_y = lambda r: sc(sy + r * L.line_h + L.line_h / 2)   # noqa: E731
            yy = row_y(row)
            num = f"{i + 1:02d}"
            # ピクセルフォントは em ボックス内で字面が上に寄るので、字面（インク）の中心を行の中心に置く
            _, top, _, bottom = f_num.getbbox(num, anchor="ls")
            d.text((x, rnd(yy - (top + bottom) / 2)), num, font=f_num, fill=muted, anchor="ls")
            nw = d.textlength(num, font=f_num) + sc(L.font_s * 0.8)
            if not t:
                continue
            max_w = col_w * S - nw
            title, artist = _one_line(t.title), _one_line(t.artist)
            # 曲名の行（入らなければ 2 行に折る）。**アーティスト名は必ず次の行**
            title_rows = plan[i] - (1 if artist else 0)
            if title_rows >= 2:
                l1, l2 = _split_title(d, title, f_title, max_w)
                if not l2:   # 割り付けでは 2 行取ったが実際は 1 行で収まった（測る字の大きさが少し違うため）
                    title_rows = 1
                    l1 = _ellipsize(d, title, f_title, max_w)
                d.text((x + nw, yy), l1, font=f_title, fill=ink, anchor="lm")
                if l2:
                    # 2 行目（たいていは「(feat. …)」）は、はみ出しがわずかなら**縮めて収める**。
                    # 「…」で切ると共演者が読めなくなるので、切るのは縮めても入らないときだけ
                    f2 = f_title
                    for k in (0.92, 0.86, 0.8):
                        if d.textlength(l2, font=f2) <= max_w:
                            break
                        f2 = font("bold", max(8, rnd(font_s * k)))
                    d.text((x + nw, row_y(row + 1)), _ellipsize(d, l2, f2, max_w), font=f2, fill=ink, anchor="lm")
            else:
                d.text((x + nw, yy), _ellipsize(d, title, f_title, max_w), font=f_title, fill=ink, anchor="lm")
            if artist:
                # アーティスト名は曲名のすぐ下に寄せる（行の中心のままだと均等に散らばって、
                # どの曲名の下なのかが読み取りにくい）
                ay = row_y(row + title_rows) - sc(L.line_h * 0.14)
                d.text((x + nw, ay), _ellipsize(d, artist, f_artist, max_w), font=f_artist, fill=muted, anchor="lm")

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
