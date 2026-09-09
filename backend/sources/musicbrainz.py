"""musicbrainz ソース（未実装）。"""
from backend.models import Track


async def search(q: str, artist: str = "") -> list[Track]:
    raise NotImplementedError
