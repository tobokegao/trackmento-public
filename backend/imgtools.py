"""画像の後処理。動画サムネイルの黒帯（レターボックス／ピラーボックス）を切り落とす。

YouTube の hqdefault（480×360）は 16:9 の動画を 4:3 の枠に入れるため上下に黒帯が付く。ニコニコの旧サムネイルや
bilibili のカバーにも同様の帯があることがある。正方形のマスに中央切り抜きすると帯が残るので、取得時に落とす。
"""
from __future__ import annotations

from PIL import Image, ImageStat

VIDEO_THUMB_HOSTS = ("ytimg.com", "nimg.jp", "nicovideo.jp", "hdslb.com", "otodb.net")
DARK = 20          # 行／列の平均がこの明るさ（0〜255）未満で
DARK_MAX = 40      # かつ最大値もこれ未満なら「帯」とみなす（暗い映像は最大値が高いので区別できる）
MAX_FRAC = 0.25    # 各辺で切り落とす最大割合（誤検出で画像が消えないように）


def is_video_thumb(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in VIDEO_THUMB_HOSTS)


def _is_dark(gray: Image.Image, box: tuple[int, int, int, int]) -> bool:
    """1 行／1 列が「帯」か。平均が暗いだけでなく最大値も暗いこと（暗い映像の行を帯と誤認しないため）"""
    st = ImageStat.Stat(gray.crop(box))
    return st.mean[0] < DARK and st.extrema[0][1] < DARK_MAX


def _mean_row(gray: Image.Image, y: int) -> float:  # 互換用
    return ImageStat.Stat(gray.crop((0, y, gray.width, y + 1))).mean[0]


def letterbox_box(im: Image.Image) -> tuple[int, int, int, int] | None:
    """黒帯を除いた範囲 (left, top, right, bottom)。切るものが無ければ None。"""
    gray = im.convert("L")
    w, h = gray.size
    max_y, max_x = int(h * MAX_FRAC), int(w * MAX_FRAC)
    top = 0
    while top < max_y and _is_dark(gray, (0, top, w, top + 1)):
        top += 1
    bottom = h
    while bottom > h - max_y and _is_dark(gray, (0, bottom - 1, w, bottom)):
        bottom -= 1
    left = 0
    while left < max_x and _is_dark(gray, (left, top, left + 1, bottom)):
        left += 1
    right = w
    while right > w - max_x and _is_dark(gray, (right - 1, top, right, bottom)):
        right -= 1
    # 1〜2px の縁は圧縮ノイズのこともあるので無視。それ以上なら切る
    if top + (h - bottom) + left + (w - right) <= 2:
        return None
    if right - left < w * 0.5 or bottom - top < h * 0.5:
        return None
    return (left, top, right, bottom)


def trim_letterbox(im: Image.Image) -> Image.Image:
    box = letterbox_box(im)
    return im.crop(box) if box else im


def trim_letterbox_bytes(data: bytes, ctype: str) -> tuple[bytes, str]:
    """バイト列版。切るものが無ければそのまま返す。切ったら JPEG（品質 92）で返す。"""
    import io

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return data, ctype
    box = letterbox_box(im)
    if not box:
        return data, ctype
    out = io.BytesIO()
    im.crop(box).convert("RGB").save(out, "JPEG", quality=92, optimize=True)
    return out.getvalue(), "image/jpeg"
