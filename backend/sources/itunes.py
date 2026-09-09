"""iTunes Search API。キー不要。

https://itunes.apple.com/search?term=...&entity=song&country=JP&limit=25
artworkUrl100 の "100x100" を "1000x1000" に置き換えると高解像度が取れる。
"""
from __future__ import annotations

import re

import httpx

from backend.merge import _n
from backend.models import Track

ENDPOINT = "https://itunes.apple.com/search"
_SIZE_RE = re.compile(r"/\d+x\d+(bb)?\.(jpg|png)$")


def hires(url: str, size: int = 1000) -> str:
    """artworkUrl100 → 1000x1000 版 URL。"""
    return _SIZE_RE.sub(lambda m: f"/{size}x{size}{m.group(1) or ''}.{m.group(2)}", url)


def _to_track(item: dict) -> Track | None:
    art = item.get("artworkUrl100") or item.get("artworkUrl60")
    if not art:
        return None
    return Track(
        source="itunes",
        title=item.get("trackName") or "",
        artist=item.get("artistName") or "",
        album=item.get("collectionName"),
        image=hires(art),
        thumb=art,
        external_url=item.get("trackViewUrl"),
    )


async def search(q: str, artist: str = "", *, limit: int = 25, country: str = "JP",
                 client: httpx.AsyncClient | None = None) -> list[Track]:
    term = f"{artist} {q}".strip()
    if not term:
        return []
    params = {"term": term, "entity": "song", "country": country, "limit": limit}
    own = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        r = await client.get(ENDPOINT, params=params)
        r.raise_for_status()
        data = r.json()
    finally:
        if own:
            await client.aclose()
    # iTunes の検索はあいまい（曲名の一部一致・カバー・オルゴール版まで返る）ので、
    # 正規化した曲名／アーティスト名が完全に一致するものだけに絞る（空白・記号・大小・全角半角は無視）
    want_title, want_artist = _n(q), _n(artist)
    out: list[Track] = []
    for item in data.get("results", []):
        if item.get("wrapperType") not in (None, "track"):
            continue
        t = _to_track(item)
        if not t:
            continue
        if want_title and _n(t.title) != want_title:
            continue
        if want_artist and _n(t.artist) != want_artist:
            continue
        out.append(t)
    return out
