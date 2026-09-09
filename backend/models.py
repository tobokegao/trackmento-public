"""全ソース共通のレスポンス型。"""
from typing import Literal, Optional

from pydantic import BaseModel

Source = Literal["itunes", "musicbrainz", "discogs", "bandcamp", "soundcloud", "youtube", "nicovideo", "bilibili", "spotify", "manual"]


class Track(BaseModel):
    source: Source
    title: str
    artist: str
    album: Optional[str] = None
    image: str
    thumb: Optional[str] = None
    external_url: Optional[str] = None
