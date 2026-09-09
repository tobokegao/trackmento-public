"""Discogs。パーソナルトークン必須（.env の DISCOGS_TOKEN）。未設定ならソース一覧に出さない。

https://api.discogs.com/database/search?track={q}&artist={a}&type=release&token=...
- 60 req/分。検索 1 回につき API 1 回なので十分
- 結果は「リリース」単位。title は "Artist - Release" 形式なので分割し、曲名は検索語をそのまま使う
- cover_image が spacer.gif のものは「画像なし」として除外
"""
from __future__ import annotations

import os
import re

import httpx

from backend.models import Track

ENDPOINT = "https://api.discogs.com/database/search"
UA = "trackmento/0.1 +https://github.com/local/musicgrid-local"
_DISAMBIG_RE = re.compile(r"(\s*\(\d+\)|\*)+$")  # "Artist (2)" / "Artist*" の重複回避サフィックス


def token() -> str:
    return os.getenv("DISCOGS_TOKEN", "").strip()


def enabled() -> bool:
    return bool(token())


def _split_title(title: str) -> tuple[str, str]:
    """"Artist - Release" → (artist, release)。区切りが無ければ artist は空。"""
    artist, sep, release = title.partition(" - ")
    if not sep:
        return "", title.strip()
    return _DISAMBIG_RE.sub("", artist.strip()), release.strip()


def _to_track(item: dict, q: str, artist_query: str) -> Track | None:
    cover = item.get("cover_image") or ""
    if not cover or cover.endswith("spacer.gif"):
        return None
    artist, release = _split_title(item.get("title") or "")
    uri = item.get("uri") or ""
    return Track(
        source="discogs",
        title=q.strip() or release,
        artist=artist or artist_query.strip(),
        album=release or None,
        image=cover,
        thumb=item.get("thumb") or cover,
        external_url=f"https://www.discogs.com{uri}" if uri.startswith("/") else (uri or None),
    )


async def search(q: str, artist: str = "", *, limit: int = 15, client: httpx.AsyncClient | None = None) -> list[Track]:
    if not enabled() or not (q.strip() or artist.strip()):
        return []
    params: dict[str, str | int] = {"type": "release", "per_page": limit, "token": token()}
    if q.strip():
        params["track"] = q.strip()
    if artist.strip():
        params["artist"] = artist.strip()
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        out = await _query(client, params, q, artist)
        if not out and q.strip() and artist.strip():
            # Discogs はアーティスト表記（ローマ字／別名）が違うと track+artist で 0 件になりやすい。
            # そのときはアーティストのリリース一覧に落として、収録盤を選べるようにする
            params.pop("track", None)
            out = await _query(client, params, q, artist)
    finally:
        if own:
            await client.aclose()
    return out


async def _query(client: httpx.AsyncClient, params: dict, q: str, artist: str) -> list[Track]:
    r = await client.get(ENDPOINT, params=params, headers={"User-Agent": UA, "Accept": "application/json"})
    r.raise_for_status()
    seen: set[str] = set()
    out: list[Track] = []
    for item in r.json().get("results", []):
        t = _to_track(item, q, artist)
        if t and t.image not in seen:
            seen.add(t.image)
            out.append(t)
    return out
