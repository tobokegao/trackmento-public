"""手入力用のローカル画像。uploads/ に保存し、/uploads/<name> という相対 URL で Track.image に入れる。

相対 URL にしておくのは、PUBLIC_BASE_URL（LAN IP や Tailscale）が変わっても壊れないようにするため。
/image-proxy・render.py・CLI はこの接頭辞を見てローカルファイルを直接読む。
"""
from __future__ import annotations

import io
import re
import secrets
from pathlib import Path

from PIL import Image

from backend import storage

Image.MAX_IMAGE_PIXELS = 24_000_000   # 展開爆弾対策（render.py と同じ値）

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads"
PREFIX = "/uploads/"
MAX_BYTES = 15 * 1024 * 1024
_NAME_RE = re.compile(r"^[a-f0-9]{16}\.(jpg|png|webp|gif)$")
MAX_SIDE = 2048   # これより大きい画像は縮めて保存する（マスの描画には十分。元画像の情報量も減らす）
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


def content_type(path: Path | str) -> str:
    return _CTYPE.get(str(path).rsplit(".", 1)[-1].lower(), "application/octet-stream")


def read_bytes(url: str) -> tuple[bytes, str] | None:
    """/uploads/<name> の中身と content-type。R2 を使っているときはそちらから、無ければローカルから。"""
    if not is_upload_url(url):
        return None
    name = url[len(PREFIX):]
    if not _NAME_RE.match(name):
        return None
    st = storage.get_storage()
    if st.is_remote:
        data = st.get(f"uploads/{name}")
        return (data, content_type(name)) if data is not None else None
    p = UPLOADS / name
    return (p.read_bytes(), content_type(p)) if p.is_file() else None


def _reencode(data: bytes) -> tuple[bytes, str]:
    """画素だけを取り出して保存し直す。EXIF（撮影日時・位置情報・機種）や埋め込みプロファイル、コメントは残さない。
    写真（JPEG）は JPEG、それ以外は PNG（透明を保つ）。GIF は最初のコマだけ。長辺は MAX_SIDE まで縮める。"""
    try:
        im = Image.open(io.BytesIO(data))
        fmt = im.format or ""
        if fmt == "JPEG":
            im.draft("RGB", (MAX_SIDE, MAX_SIDE))   # 縮小デコード（原寸を展開しない）。MAX_SIDE 以上の最小スケールになる
        im.load()
    except Exception as e:
        raise ValueError("画像として読めませんでした（JPEG / PNG / WebP / GIF に対応）") from e
    try:
        if fmt == "JPEG":
            from PIL import ImageOps
            im = ImageOps.exif_transpose(im)   # 向きだけは反映してから EXIF を捨てる
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        im = Image.frombytes(im.mode, im.size, im.tobytes())   # 画素だけを新しい画像に写す（info のコメント・ICC・EXIF を持ち越さない）
        buf = io.BytesIO()
        if fmt == "JPEG":
            im.convert("RGB").save(buf, "JPEG", quality=90, optimize=True)
            return buf.getvalue(), "jpg"
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("LA", "P") else "RGB")
        im.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "png"
    except Exception as e:
        raise ValueError("画像を変換できませんでした（大きすぎるか壊れています）") from e


def save_image_bytes(data: bytes) -> str:
    """画像として開けることを確認し、メタデータを落として保存し、/uploads/<name> を返す。名前はランダム。"""
    if len(data) > MAX_BYTES:
        raise ValueError("画像が大きすぎます（15MB まで）")
    data, ext = _reencode(data)
    name = f"{secrets.token_hex(8)}.{ext}"
    st = storage.get_storage()
    if st.is_remote:
        # 公開サーバーのディスクは再デプロイで消えるので、R2 に置く（バケットのライフサイクルで期限管理）
        st.put(f"uploads/{name}", data, content_type(name))
        return PREFIX + name
    UPLOADS.mkdir(exist_ok=True)
    p = UPLOADS / name
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
