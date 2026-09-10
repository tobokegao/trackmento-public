"""全ソース共通のレスポンス型。"""
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

Source = Literal["itunes", "musicbrainz", "discogs", "bandcamp", "soundcloud", "youtube", "nicovideo", "bilibili", "spotify", "otodb", "manual"]


MAX_TEXT = 300
MAX_URL = 2048


def _is_http(v: str) -> bool:
    return v.lower().startswith(("http://", "https://")) and len(v) <= MAX_URL


def _safe_ref(v: str) -> bool:
    return _is_http(v) or (v.startswith("/uploads/") and "/" not in v[len("/uploads/"):] and len(v) <= 80)


class Track(BaseModel):
    source: Source
    title: str
    artist: str
    album: Optional[str] = None
    image: str
    thumb: Optional[str] = None
    external_url: Optional[str] = None

    @field_validator("title", "artist", "album", mode="before")
    @classmethod
    def _one_line(cls, v):
        # 改行・タブは空白 1 つに（Pillow は改行を含む文字列の幅計測で ValueError を投げる）。長さも抑える
        return " ".join(str(v).split())[:MAX_TEXT] if isinstance(v, str) else v

    @field_validator("image", mode="before")
    @classmethod
    def _image_url(cls, v):
        # 画像は https?:// の URL か、アップロード（/uploads/<name>）だけ。それ以外は不正としてマスごと落とす
        if not isinstance(v, str) or not _safe_ref(v.strip()):
            raise ValueError("image は https?:// の URL か /uploads/ の参照だけ受け付けます")
        return v.strip()[:MAX_URL]

    @field_validator("thumb", "external_url", mode="before")
    @classmethod
    def _opt_url(cls, v):
        # リンク先は https?:// だけ。javascript: や data: は捨てる（共有を読み込んだ他人のブラウザで開かれるため）
        if v is None:
            return None
        v = str(v).strip()
        return v[:MAX_URL] if _is_http(v) else None
