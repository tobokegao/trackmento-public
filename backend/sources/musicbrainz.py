"""MusicBrainz + Cover Art Archive。キー不要。

制約: MusicBrainz API は 1 req/秒、User-Agent 必須（.env の MB_USER_AGENT）。
recording 検索 → releases[] の release MBID → CAA の front-500 を HEAD で確認し、404 は「画像なし」として除外。
"""
from __future__ import annotations

import asyncio
import os
import time

import httpx

from backend.models import Track

MB_ENDPOINT = "https://musicbrainz.org/ws/2/recording"
CAA = "https://coverartarchive.org/release/{mbid}/front-{size}"
_lock = asyncio.Lock()
_last_call = 0.0
_caa_sem = asyncio.Semaphore(8)


def _user_agent() -> str:
    return os.getenv("MB_USER_AGENT", "musicgrid-local/0.1 (https://github.com/local/musicgrid-local)")


def _lucene_escape(s: str) -> str:
    out = []
    for ch in s:
        if ch in r'+-&|!(){}[]^"~*?:\/':
            out.append("\\")
        out.append(ch)
    return "".join(out)


async def _mb_get(client: httpx.AsyncClient, params: dict) -> dict:
    """1 req/秒をプロセス全体で守る。"""
    global _last_call
    async with _lock:
        wait = 1.0 - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()
        headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
        r = await client.get(MB_ENDPOINT, params=params, headers=headers)
        if r.status_code == 503:  # レート制限。1回だけ待って再試行
            await asyncio.sleep(1.1)
            _last_call = time.monotonic()
            r = await client.get(MB_ENDPOINT, params=params, headers=headers)
    r.raise_for_status()
    return r.json()


async def _caa_exists(client: httpx.AsyncClient, mbid: str) -> bool:
    async with _caa_sem:
        try:
            # CAA は画像があれば 307 で archive.org へ転送、無ければ 404。転送先まで追わない
            r = await client.head(CAA.format(mbid=mbid, size=250), headers={"User-Agent": _user_agent()}, follow_redirects=False, timeout=8)
            return r.status_code in (200, 302, 307)
        except httpx.HTTPError:
            return False


def _release_order(rel: dict) -> tuple:
    """Official → 日本盤 → 日付順 で並べる。"""
    return (
        rel.get("status") != "Official",
        rel.get("country") != "JP",
        rel.get("date") or "9999",
    )


async def search(q: str, artist: str = "", *, limit: int = 12, client: httpx.AsyncClient | None = None) -> list[Track]:
    terms = []
    if q.strip():
        terms.append(f'recording:"{_lucene_escape(q.strip())}"')
    if artist.strip():
        terms.append(f'artist:"{_lucene_escape(artist.strip())}"')
    if not terms:
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        data = await _mb_get(client, {"query": " AND ".join(terms), "fmt": "json", "limit": limit})
        recordings = data.get("recordings", [])

        # 各 recording について候補 release を並べ、CAA を確認
        async def resolve(rec: dict) -> Track | None:
            rels = sorted(rec.get("releases") or [], key=_release_order)
            for rel in rels[:3]:  # 1曲あたり最大3リリースまで確認
                mbid = rel.get("id")
                if mbid and await _caa_exists(client, mbid):
                    credits = rec.get("artist-credit") or []
                    artist_name = "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in credits) or artist
                    return Track(
                        source="musicbrainz",
                        title=rec.get("title") or q,
                        artist=artist_name,
                        album=rel.get("title"),
                        image=CAA.format(mbid=mbid, size=1200),
                        thumb=CAA.format(mbid=mbid, size=250),
                        external_url=f"https://musicbrainz.org/recording/{rec.get('id')}",
                    )
            return None

        results = await asyncio.gather(*(resolve(r) for r in recordings))
    finally:
        if own:
            await client.aclose()

    # 同じジャケット（同じ release）は1件にまとめる
    seen: set[str] = set()
    out: list[Track] = []
    for t in results:
        if t and t.image not in seen:
            seen.add(t.image)
            out.append(t)
    return out
