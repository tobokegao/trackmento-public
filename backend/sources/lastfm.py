"""Last.fm。API キー必須（.env の LASTFM_API_KEY）。未設定ならソース一覧に出さない。

track.search は画像が空のことが多いので、上位数件に track.getInfo を叩き
album.image[extralarge] を使う。Last.fm のデフォルト画像（星マーク）は「画像なし」扱い。
"""
from __future__ import annotations

import asyncio
import os

import httpx

from backend.models import Track

ENDPOINT = "https://ws.audioscrobbler.com/2.0/"
PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"
_sem = asyncio.Semaphore(5)


def api_key() -> str:
    return os.getenv("LASTFM_API_KEY", "").strip()


def enabled() -> bool:
    return bool(api_key())


def _pick_image(images: list[dict] | None) -> tuple[str | None, str | None]:
    """(高解像度, サムネ)。プレースホルダは None。"""
    if not images:
        return None, None
    by_size = {i.get("size"): i.get("#text") for i in images if i.get("#text")}
    big = by_size.get("mega") or by_size.get("extralarge") or by_size.get("large")
    thumb = by_size.get("large") or by_size.get("medium") or big
    if not big or PLACEHOLDER_HASH in big:
        return None, None
    # 300x300 → 元サイズ（サイズ指定セグメントを外す）
    hires = big.replace("/300x300/", "/").replace("/174s/", "/")
    return hires, thumb


async def _get(client: httpx.AsyncClient, **params) -> dict:
    params.update(api_key=api_key(), format="json")
    r = await client.get(ENDPOINT, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


async def search(q: str, artist: str = "", *, limit: int = 10, client: httpx.AsyncClient | None = None) -> list[Track]:
    if not enabled() or not q.strip():
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        params = {"method": "track.search", "track": q.strip(), "limit": limit}
        if artist.strip():
            params["artist"] = artist.strip()
        data = await _get(client, **params)
        matches = (data.get("results") or {}).get("trackmatches", {}).get("track", []) or []

        async def info(m: dict) -> Track | None:
            async with _sem:
                try:
                    d = await _get(client, method="track.getInfo", track=m.get("name", ""), artist=m.get("artist", ""), autocorrect=1)
                except httpx.HTTPError:
                    return None
            tr = d.get("track") or {}
            album = tr.get("album") or {}
            image, thumb = _pick_image(album.get("image"))
            if not image:
                return None
            return Track(
                source="lastfm",
                title=tr.get("name") or m.get("name") or q,
                artist=(tr.get("artist") or {}).get("name") or m.get("artist") or artist,
                album=album.get("title"),
                image=image,
                thumb=thumb,
                external_url=tr.get("url") or m.get("url"),
            )

        results = await asyncio.gather(*(info(m) for m in matches))
    finally:
        if own:
            await client.aclose()
    seen: set[str] = set()
    out: list[Track] = []
    for t in results:
        if t and t.image not in seen:
            seen.add(t.image)
            out.append(t)
    return out
