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
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


_char_w_cache: dict[tuple[str, int, str], float] = {}


def char_w(kind: str, size: int, ch: str) -> float:
    """1 字の幅（1px に丸めたもの）。**流し込みは同じ字を何度も測る**ので控えておく
    （21x12 のような大きな並びだと、割り付けを探すあいだに数十万回になる）。"""
    key = (kind, size, ch)
    w = _char_w_cache.get(key)
    if w is None:
        w = _char_w_cache[key] = float(rnd(font(kind, size).getlength(ch)))
    return w


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
    フォントに無い文字もここで落とす。

    **まず NFC で合成する**。濁点・半濁点が結合文字（U+3099 / U+309A）で入っている題があり
    （利用者の「人生を歩む上で…」）、Pillow は合成せずに素の「て」と濁点を別々に置くので
    **「上て」「及ひ」と濁点が消えて見える**。Canvas は合成するので、直さないと両描画がずれる
    （字幅も変わるので折り返す位置まで変わり、突き合わせで 7.7% の差になっていた）"""
    return " ".join(_drawable(unicodedata.normalize("NFC", s or "")).split())


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
    # 回り込み（マスの塊を中央に置き、まわりの余白に曲名を流し込む）
    wrap: bool = False
    wrap_pad: int = 0                                   # 四辺の余白
    wrap_top: int = 0                                   # タイトルの帯の上端（余り分を上下に分けて下げる）
    wrap_segs: tuple[tuple[int, int, int], ...] = ()    # 行ごとの (x, y, 幅)。左段 → 右段の順
    wrap_rows: bool = False                             # 段が 1 曲ずつ（マスの横に並べる）


# 曲が多いと 1 曲 1 行では文字が小さくなりすぎる（16×16 で出力 8px）。そこで曲名を
# 続けて流し込み、幅で折り返す。区切りの記号は置かない。番号がピクセルフォントで
# 本文と書体も色も違うので、それ自体が切れ目になる
class FlowRow(NamedTuple):
    parts: list[tuple[str, str]]   # ("num"|"title"|"artist", 文字列)
    width: float                   # 文字と曲間の送りで使った幅
    gaps: int                      # 曲の切れ目の数（余った幅をここに配る）


FLOW_MIN_FONT = 20        # 1 曲 1 行のとき、出力でこれより小さくなるなら流し込みに切り替える
# 行の中心からベースラインまでの下向きの量（字の大きさに対する比）。**実測せず固定比にする**。
# PIL の字面（getbbox）と Canvas の actualBoundingBox は数 px 違い、実測で決めると
# 小さい文字ほど食い違いが目立つ。IBM Plex Sans JP の「あ」で 10〜128px を測ると 0.375〜0.406、
# 平均 0.38。両者で同じ式を使えば必ず同じ位置になる
BASELINE = 0.38
# 回り込み（正方形以下の比率で曲が多いとき）。マスの塊を中央に置き、左上から右下へ文字を流す。
# 塊にぶつかる行は「左の段 → 塊の向こう側の右の段」と続ける
WRAP_GAP_EM = 0.75        # マスの塊と文字（字面）のあいだ。文字の大きさに対する割合
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
LIST_COL_GAIN = 1.02        # 下に置くとき、列を増やしてこの倍率以上大きくならないならやめる
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
# 記号の切れ目を使う条件: 1 行目が「真ん中」のこの割合に届くこと。届かないなら字の途中で折る
SPLIT_HEAD_MIN = 0.45


def _break_at(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_w: float) -> tuple[str, str]:
    """切れ目が見つからないときの保険。max_w に収まるところまで入れて、字の途中で折る。"""
    cut = len(text)
    while cut > 1 and d.textlength(text[:cut], font=f) > max_w:
        cut -= 1
    return text[:cut].rstrip(), text[cut:].lstrip()


def _break_near(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont,
                max_w: float, target: float) -> tuple[str, str]:
    """字の途中で折る。**行の真ん中にいちばん近い所**を選ぶ（`_break_at` は右端まで詰める）。"""
    best: tuple[float, int] | None = None
    for i in range(1, len(text)):
        w1 = d.textlength(text[:i], font=f)
        if w1 > max_w:
            break
        score = abs(w1 - target)
        if best is None or score < best[0]:
            best = (score, i)
    if best is None:
        return _break_at(d, text, f, max_w)
    i = best[1]
    return text[:i].rstrip(), text[i:].lstrip()


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
    best: tuple[float, int, bool] | None = None   # (真ん中からの遠さ, 位置, 「(feat. …)」の手前か)
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
    # **偏りすぎる切れ目は使わない**。括弧や【】が題の先頭近くにあると、そこしか候補が無いことがあり、
    # 「いき」＋「(稚拙な詩歌への…」のように 1 行目が数文字だけになる（利用者の画像で発覚）。
    # 1 行目が真ん中の `SPLIT_HEAD_MIN` に届かないなら、字の途中でも真ん中に近い所で折る
    # 「(feat. …)」の手前だけは偏っていても使う（曲名の本体が単独で読めるほうが分かりやすい）
    if best is not None and (best[2]
                             or d.textlength(title[:best[1]].rstrip(), font=f) >= target * SPLIT_HEAD_MIN):
        i = best[1]
        return title[:i].rstrip(), title[i:].lstrip()
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

    def put(kind: str, text: str) -> None:
        nonlocal x
        f = fonts[kind]
        for ch in text:
            if full():
                return
            # **折り返しの判定は 1px に丸めた字幅で行う**。PIL と Canvas の字幅は 1px 未満だけ違い、
            # 生の値で足していくと境目の字で折る・折らないが入れ替わり、そこから先の行が全部ずれる。
            # 丸めればほとんどの字で同じ値になり、両者が同じ位置で折る（描くときは実寸のまま）
            w = char_w(*sizes[kind], ch)
            if x + w > cw() and cur:
                flush()
            if cur and cur[-1][0] == kind:
                cur[-1] = (kind, cur[-1][1] + ch)
            else:
                cur.append((kind, ch))
            x += w

    for i, t in enumerate(doc.cells):
        if not t:
            continue
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


def _slab_frame(fixed: int, ratio: float, m: int, vertical: bool) -> tuple[int, int, int]:
    """塊が使い切る辺の長さ `fixed` から枠と余白を出す。

    余白は「枠の短いほうの辺の 3.5%」（`_frame` と同じ規則）なので、枠と余白が互いを参照する。
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
        pad = max(m, rnd(min(W, H) * 0.035))
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
               max_side_v: int, beside: bool = False) -> WrapPlan | None:
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
    pitch = CELL_PX + doc.options.gap          # マスの段 1 つぶんの送り
    # **段の中で縦に積むか、横に並べるか**。縦に積むほうが 1 行が長く取れて読みやすいので既定。
    # ただし段が多いと 1 曲ぶんが薄くなりすぎるので（2x32 で出力 10.8px）、そのときは横に並べる
    # （マスと同じ「左から右へ、次の段へ」の順になる）
    side_by_side = beside
    per = pitch if side_by_side else rnd(pitch / cols)   # 曲名 1 曲ぶんの高さ
    font_s = rnd(per * SLAB_ROW_FONT)
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
                pad = max(m, rnd(min(W, H) * 0.035))
            W, H = gw + wgap + seg_w + pad * 2, top_h + gh + pad * 2
        else:
            W, H, pad = _slab_frame(gh + top_h, ratio, m, True)
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
    return WrapPlan(W, H, scale, font_s, per, t_size, t_h, pad, pad, gx, gy, segs, [], 1.0, True)


def _slab_stack(doc: GridDoc, gw: int, gh: int, title_h: int, ratio: float, m: int,
                max_side_v: int) -> WrapPlan | None:
    """**塊を上に敷き、曲名を 1 曲 1 行の縦一列で下に置く**割り付け（段の少ない横長の並び）。

    7x1 を 9:16 に入れたときのように、塊が横一列だと下に大きな空きが残る。曲名を流し込むと
    行が長くて読みにくいので、**1 曲 1 行で縦に積み、まとめて真ん中に置く**（利用者の提案）。
    並びは「タイトル → 塊 → 曲名リスト」。曲名の大きさは、縦に全部入って、かつ 1 行が
    `WRAP_MIN_SEG` 字ぶんの幅を持てる中でいちばん大きいものを選ぶ。
    """
    n = len(doc.cells)
    if not n or doc.rows > SLAB_STACK_MAX_ROWS or n > SLAB_STACK_MAX_SONGS:
        return None
    W, H, pad = _slab_frame(gw, ratio, m, False)
    if W <= 0 or H <= 0:
        return None
    scale = min(1.0, max_side_v / max(W, H))
    seg_w = W - pad * 2
    for target in SLAB_TARGET_PX:
        if target < SLAB_ROW_MIN:
            break
        font_s = max(18, rnd(target / scale))
        if seg_w < font_s * WRAP_MIN_SEG:      # 1 行が短すぎる
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
        per = rnd(font_s * SLAB_STACK_LINE)    # 1 曲ぶんの高さ（曲名の行 + アーティストの行）
        avail = (H - pad) - y0
        if per * n > avail:                    # 縦に入らない → 次の（小さい）大きさ
            continue
        # **中身ごと下げて上下の余白をそろえる**（曲名だけ真ん中に置くと塊から離れて見える）
        dy = max(0, (avail - per * n) // 2)
        segs = tuple((pad, y0 + dy + i * per, seg_w) for i in range(n))
        return WrapPlan(W, H, scale, font_s, per, t_size, t_h, pad, pad, pad, gy,
                        segs, [], 1.0, True)
    return None


def _slab_plan(doc: GridDoc, gw: int, gh: int, title_h: int, ratio: float, m: int,
               max_side_v: int) -> WrapPlan | None:
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
    def build(target: int) -> WrapPlan | None:
        # **タイトルの帯の高さは文字の大きさから決まり、文字の大きさは枠（縮尺）から決まる**ので、
        # 帯 0 から始めて何回か回す。3 回で動かなくなる
        extra = 0
        W = H = pad = font_s = line_h = wgap = t_h = t_size = 0
        for _ in range(4):
            fixed = (gh + extra) if vertical else gw
            W, H, pad = _slab_frame(fixed, ratio, m, vertical)
            if W <= 0 or H <= 0:
                return None
            scale = min(1.0, max_side_v / max(W, H))
            font_s = max(18, rnd(target / scale))
            line_h = rnd(font_s * 1.5)
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
                        tuple(segs), rows, len(rows) / n_seg)

    for target in SLAB_TARGET_PX:
        if target < SLAB_MIN_FONT:
            break
        got = build(target)
        if got:
            return got
    return None


def _wrap_plan(doc: GridDoc, gw: int, gh: int, title_h: int, ratio: float, m: int,
               max_side_v: int) -> WrapPlan | None:
    """**マスの塊を中央に置き、まわりの余白に曲名を流し込む**割り付けを探す。

    正方形以下の比率で曲が多いと、今までは「上にマス・下に曲名」で組んでいた。
    内容が縦長なので比率合わせで**左右にごっそり余白が残り**、そのぶんマスが小さくなる。
    まわりに流し込めば余白を使い切れるので、同じ出力サイズでマスを大きくできる。

    決め方は「**出力での文字の大きさを FLOW_MIN_FONT に固定し、入る範囲で枠をいちばん小さくする**」
    （枠が小さいほど、出力に占めるマスの塊が大きい）。枠の大きさは塊に対する % で二分探索する。
    入らなければ None を返し、呼び出し側は今までの組み方に戻す。
    """
    pad0 = max(m, rnd(min(gw, title_h + gh) * 0.035))
    Wb, Hb = _fit(gw, title_h + gh, pad0, ratio)

    def build(pct: int, target: int) -> WrapPlan | None:
        W, H = rnd(Wb * pct / 100), rnd(Hb * pct / 100)
        scale = min(1.0, max_side_v / max(W, H))
        font_s = max(18, rnd(target / scale))
        line_h = rnd(font_s * 1.5)
        pad = max(m, rnd(min(W, H) * 0.035))
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
        min_w = font_s * WRAP_MIN_SEG
        if gx - wgap - pad < min_w and W - pad * 2 - gw - wgap >= min_w:
            gx = pad                   # コの字（塊は左端の中央、文字は上・右・下）
        x0, x1 = pad, W - pad
        ox0, ox1 = gx - wgap, gx + gw + wgap
        segs: list[tuple[int, int, int]] = []
        for r in range(n_top):                          # 塊の上の帯（枠いっぱい）
            segs.append((x0, top - a + r * line_h, x1 - x0))
        # 塊の左右。**左の段をぜんぶ埋めてから右の段へ移る**（1 行ごとに左右へ飛ぶと読みにくい、
        # と実際に読んでみての指摘があった）。新聞の段組みと同じ読み方になる
        n_side = (gh + a * 2) // line_h
        if ox0 - x0 >= min_w:
            segs += [(x0, gy - a + r * line_h, ox0 - x0) for r in range(n_side)]
        if x1 - ox1 >= min_w:
            segs += [(ox1, gy - a + r * line_h, x1 - ox1) for r in range(n_side)]
        y = gy + gh + wgap - a                          # 塊の下の帯（枠いっぱい）
        while y + line_h - a <= bot:
            segs.append((x0, y, x1 - x0))
            y += line_h
        if not segs:
            return None
        rows = _flow_rows(doc, font_s, 0.0, [float(sg[2]) for sg in segs], len(segs) + 1)
        if len(rows) > len(segs):
            return None
        # **使わなかった行のぶんは、上下に半分ずつ分ける**。文字が下の帯の途中で終わると
        # 下だけ大きく空いて「途中で終わった」ように見える。中身ごと下げれば上下が同じ余白になる
        segs = segs[:len(rows)]
        last = (segs[-1][1] + line_h - a) if segs else top
        dy = max(0, (bot - max(gy + gh, last)) // 2)
        if dy:
            gy += dy
            segs = [(sx, sy + dy, sw) for sx, sy, sw in segs]
        return WrapPlan(W, H, scale, font_s, line_h, t_size, t_h, pad, pad + dy, gx, gy, tuple(segs), rows)

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
        floor = base.scale * (WRAP_CELL_KEEP if CELL_PX * base.scale >= WRAP_CELL_OK
                              else WRAP_CELL_KEEP_SMALL)
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
        return best
    return None


def layout(doc: GridDoc, _title_px: int | None = None) -> Layout:
    o = doc.options
    cols, rows, n, m, g = doc.cols, doc.rows, doc.size, o.margin, o.gap
    title = _one_line(doc.title) if o.showTitle else ""
    gw = cols * CELL_PX + (cols - 1) * g
    gh = rows * CELL_PX + (rows - 1) * g
    # `_title_px` は「曲名リストより十分大きく」するための組み直し（下の TITLE_MIN_SCALE を参照）
    title_size = _title_px or rnd(min(96, max(48, gw * 0.045)))
    title_h = rnd(title_size * 1.9) if title else 0
    ratio = RATIOS[o.ratio]
    # サイドバー: 横長なら右、正方形以下（1:1 / 4:5 / 9:16）ならグリッドの下。
    # 正方形で右に置くと内容が横長になり、上下の余白ばかり広がるため。
    # **比率なしのときは「マスの塊が縦長なら右・横長なら下」**。枠は内容に合わせて伸びるので、
    # 長いほうの辺にさらに足すと極端な形になる（32x1 を右に足すと出力 2400x39 だった）
    side = ("none" if not o.sidebar
            else ("right" if gh >= gw else "bottom") if ratio is None
            else "right" if ratio > 1 else "bottom")
    # 右サイドバーのときタイトルはサイドバーの上（曲名リストの前）に置く。グリッドの上に置くと内容が縦長になり、
    # 横長の比率（16:9）で左右の余白ばかり広がるため
    title_top_h = 0 if side == "right" else title_h
    # 1 曲は「曲名の行 + アーティストの行」の 2 行。まずその前提で行の高さを見積もる
    base_rows = sum(2 if (t and _one_line(t.artist)) else 1 for t in doc.cells)
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
            sb_cols, line_h, font_s, sb_w, sb_h = sb_cols + 1, lh, fs, w, sb_h2
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
            for px in FLOW_TARGET_PX:
                fs = max(18, rnd(px / scale))
                lh = rnd(fs * 1.5)
                rows = _flow_rows(doc, fs, sb_w)
                if len(rows) * lh <= avail:
                    break
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
                          side, 0, 0, 1, rp.line_h, rp.font_s, sb_gap, True, (),
                          True, rp.pad, rp.top, rp.segs, True)
    if sb_flow and ratio is not None:
        from backend.config import max_side
        wp = _wrap_plan(doc, gw, gh, title_h, ratio, m, max_side())
        # **辺にぴったり付く組み方（柱・帯）があればそちらを優先する**。塊が片方の辺を
        # 使い切るので枠に余りが出ず、マスは回り込みと同じか大きくなる。
        # 回り込みのほうがマスを大きく取れるときだけ、そちらを残す
        sp = _slab_plan(doc, gw, gh, title_h, ratio, m, max_side())
        # **横一列に近い並びは、曲名を 1 曲 1 行の縦一列で下に置く**（流し込みより読みやすく、
        # 下の空きも埋まる）。マスが小さくならないときだけ
        st = _slab_stack(doc, gw, gh, title_h, ratio, m, max_side())
        if st and (sp is None or st.scale >= sp.scale):
            sp = st
        # **マスが小さくならないなら帯・柱を採る**。回り込みは塊を真ん中に置くので、
        # 横長の並び（7x1 など）だと**マスが下端に行ってタイトルだけが上に残る**。
        # 利用者の指摘「タイトルの下にマス画像があってほしい」に合わせて、辺に付ける側を優先する
        # **わずかな差なら辺に付ける側を採る**。ほぼ同じ大きさなのに回り込みが選ばれると、
        # 塊が真ん中に落ちてタイトルとのあいだに文字が挟まる（18x1 を 1:1 にしたときに起きた）
        if sp and (wp is None or sp.scale >= wp.scale * SLAB_PREFER):
            wp = sp
        if wp and (wp.scale >= scale or font_s * scale < WRAP_SWITCH_PX
                   or (wp.font_s * wp.scale >= font_s * scale * WRAP_SWITCH_GAIN
                       and wp.scale >= scale * WRAP_CELL_KEEP)):
            return Layout(wp.W, wp.H, wp.scale, wp.gx, wp.gy, gw, gh, title, wp.title_size, wp.title_h,
                          side, 0, 0, 1, wp.line_h, wp.font_s, sb_gap, True, (),
                          True, wp.pad, wp.top, wp.segs, wp.rows_mode)
    content_w = gw + sb_gap + sb_w if side == "right" else gw
    content_h = title_top_h + gh + (sb_gap + sb_h if side == "bottom" else 0)
    L = Layout(W, H, scale, rnd((W - content_w) / 2), rnd((H - content_h) / 2), gw, gh,
               title, title_size, title_h, side, sb_w, sb_h, sb_cols, line_h, font_s, sb_gap, sb_flow,
               () if sb_flow else sb_plan)
    # **タイトルは曲名リストより十分大きくする**。ふだんの規則（マスの幅の 4.5%・上限 96）は
    # マスの数だけで決まるので、曲が少なくて曲名が大きくなると**タイトルのほうが小さくなる**
    # （1x6・16:9 で本文 46.6px にタイトル 16.9px ＝ 0.36 倍だった）。
    # 曲名の大きさが決まってから組み直す。タイトルを大きくすると曲名は同じか小さくなるので、
    # **1 回で必ず収まる**（回り込みは `_wrap_plan` の中で既に本文から決めているので対象外）
    if L.title and _title_px is None:
        want = rnd(L.font_s * TITLE_MIN_SCALE)
        if want > L.title_size:
            return layout(doc, want)
    return L


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
    if L.wrap:
        # 回り込みでは ox / oy がマスの塊の左上そのもの。タイトルは枠の左上に置く
        if L.title:
            # **字面（インク）の中心を帯の中心に置く**。PIL の anchor="lm"（上下の伸びの中心）と
            # Canvas の textBaseline="middle"（em ボックスの中心）は基準がずれていて、
            # 回り込みではタイトルが大きいぶん出力で 15px ほど食い違った
            t = _ellipsize(d, L.title, f_title, (L.W - L.wrap_pad * 2) * S)
            d.text((sc(L.wrap_pad), sc(L.wrap_top + L.title_h / 2) + rnd(max(8, sc(L.title_size)) * BASELINE)),
                   t, font=f_title, fill=ink, anchor="ls")
    elif L.title and L.side != "right":
        d.text((sc(L.ox), sc(y0 + L.title_h / 2)), _ellipsize(d, L.title, f_title, L.gw * S), font=f_title, fill=ink, anchor="lm")
        y0 += L.title_h

    # グリッド（画像は並列に取得し、取得スレッドの中でマスの大きさに切り抜く。原寸を抱えない）
    cell = sc(CELL_PX)
    num_px = max(8, sc(22))       # 番号の字の大きさ。**8px を下限にする**（ピクセルフォントはこれ以下で潰れる）
    num_font = font("pixel", num_px)
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
        for i, t in enumerate(doc.cells):
            if i >= len(L.wrap_segs):
                break
            sx0, sy0, sw = L.wrap_segs[i]
            x, cy = sc(sx0), sc(sy0 + L.line_h / 2)
            num = f"{i + 1:02d}"
            # ピクセルフォントは em ボックスの中で字面が上に寄るので、字面の中心を行の中心に置く
            _, top, _, bottom = f_num.getbbox(num, anchor="ls")
            d.text((x, rnd(cy - (top + bottom) / 2)), num, font=f_num, fill=muted, anchor="ls")
            nw = d.textlength(num, font=f_num) + sc(L.font_s * 0.8)
            if not t:
                continue
            max_w = sc(sw) - nw
            title, artist = _one_line(t.title), _one_line(t.artist)
            # **1 行に入らない曲名は 2 行に折る**（「…」で切ると曲名が読めなくなる。
            # 折る位置の決め方はサイドバーと同じ `_split_title`）
            lines = [title]
            if d.textlength(title, font=f_t) > max_w:
                l1, l2 = _split_title(d, title, f_t, max_w)
                lines = [l1, l2] if l2 else [l1]
            rows = lines + ([artist] if artist else [])
            # 行の間隔。3 行（曲名 2 行＋アーティスト名）のときは詰めて 1 マスの高さに収める
            step = rnd(fs * (1.24 if len(rows) <= 2 else 1.12))
            top = cy - rnd(step * (len(rows) - 1) / 2)
            for j, text in enumerate(rows):
                is_artist = artist and j == len(rows) - 1
                f = f_a if is_artist else f_t
                d.text((x + nw, top + j * step), _ellipsize(d, text, f, max_w),
                       font=f, fill=muted if is_artist else ink, anchor="lm")
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
