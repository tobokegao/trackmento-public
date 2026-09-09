"""全ソース共通のレスポンス型。"""
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

Source = Literal["itunes", "musicbrainz", "discogs", "bandcamp", "soundcloud", "youtube", "nicovideo", "bilibili", "spotify", "otodb", "manual"]


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
        # 改行・タブは空白 1 つに（Pillow は改行を含む文字列の幅計測で ValueError を投げる）
        return " ".join(str(v).split()) if isinstance(v, str) else v
