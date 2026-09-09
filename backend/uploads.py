"""手入力用のローカル画像。uploads/ に保存し、/uploads/<name> という相対 URL で Track.image に入れる。

相対 URL にしておくのは、PUBLIC_BASE_URL（LAN IP や Tailscale）が変わっても壊れないようにするため。
/image-proxy・render.py・CLI はこの接頭辞を見てローカルファイルを直接読む。
"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = 40_000_000   # 展開爆弾対策

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads"
PREFIX = "/uploads/"
MAX_BYTES = 15 * 1024 * 1024
_NAME_RE = re.compile(r"^[a-f0-9]{16}\.(jpg|png|webp|gif)$")
_EXT = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}
_CTYPE = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


def is_upload_url(url: str) -> bool:
    return url.startswith(PREFIX)


def local_path(url: str) -> Path | None:
    """/uploads/<name> → 実ファイル。名前が不正か無ければ None。"""
    if not is_upload_url(url):
        return None
    name = url[len(PREFIX):]
    if not _NAME_RE.match(name):
        return None
    p = UPLOADS / name
    return p if p.is_file() else None


def content_type(path: Path) -> str:
    return _CTYPE.get(path.suffix.lstrip(".").lower(), "application/octet-stream")


def save_image_bytes(data: bytes) -> str:
    """画像として開けることを確認して保存し、/uploads/<name> を返す。同じ内容なら同じ名前になる。"""
    if len(data) > MAX_BYTES:
        raise ValueError("画像が大きすぎます（15MB まで）")
    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format or ""
        im.verify()
    except Exception as e:
        raise ValueError("画像として読めませんでした（JPEG / PNG / WebP / GIF に対応）") from e
    ext = _EXT.get(fmt)
    if ext is None:
        # 対応外の形式（BMP, TIFF, HEIC が Pillow で読めた場合など）は PNG に変換して保存
        try:
            im = Image.open(io.BytesIO(data)).convert("RGB")
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
        except Exception as e:
            raise ValueError("画像を変換できませんでした（大きすぎるか壊れています）") from e
        data, ext = buf.getvalue(), "png"
    name = f"{hashlib.sha1(data).hexdigest()[:16]}.{ext}"
    UPLOADS.mkdir(exist_ok=True)
    p = UPLOADS / name
    if not p.exists():
        p.write_bytes(data)
        from backend.config import public_mode
        if public_mode():
            from backend import housekeeping
            housekeeping.prune_uploads()
    return PREFIX + name


def import_file(path: str | Path) -> str:
    """CLI 用。PC 上の画像ファイルを uploads/ に取り込み /uploads/<name> を返す。"""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"ファイルがありません: {p}")
    return save_image_bytes(p.read_bytes())
