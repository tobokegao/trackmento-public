"""MusicBrainz + Cover Art Archive。キー不要。

制約: MusicBrainz API は 1 req/秒、User-Agent 必須（.env の MB_USER_AGENT）。
recording 検索 → releases[] の release MBID → CAA の front-500 を HEAD で確認し、404 は「画像なし」として除外。
"""
from __future__ import annotations

import asyncio
import os
import time
from urllib.parse import quote_plus

import httpx

from backend.models import Track


def youtube_search_url(artist: str, title: str) -> str:
    """曲を YouTube で検索する URL。MusicBrainz には音源が無いので、元リンクはこれにする"""
    return "https://www.youtube.com/results?search_query=" + quote_plus(f"{artist} {title}".strip())

MB_ENDPOINT = "https://musicbrainz.org/ws/2/recording"


class SourceBusy(Exception):
    """一時的に使えない（混雑・レート制限）。検索全体は続け、利用者にその旨を知らせる"""
CAA = "https://coverartarchive.org/release/{mbid}/front-{size}"
_lock = asyncio.Lock()
_waiting = 0          # _lock を待っている（または握っている）呼び出しの数
MAX_QUEUE = 6         # これ以上並んでいたら待たずに SourceBusy（1 req/秒なので 6 件 ≒ 6 秒以上の待ち）
REQUEST_TIMEOUT = 8   # 1 回の HTTP 呼び出しの上限秒。ロックを握ったまま長く待たない
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
    global _last_call, _waiting
    if _waiting >= MAX_QUEUE:
        # 利用者が重なると 1 req/秒の列が伸び、全員が SOURCE_TIMEOUT でタイムアウトする。並びすぎなら早めに諦める
        raise SourceBusy("MusicBrainz が混雑しています（順番待ち）。少し待ってから再検索してください")
    _waiting += 1
    try:
        async with _lock:
            wait = 1.0 - (time.monotonic() - _last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            _last_call = time.monotonic()
            headers = {"User-Agent": _user_agent(), "Accept": "application/json"}
            r = await client.get(MB_ENDPOINT, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            # 503 = 混雑かレート制限。間隔を広げながら最大 2 回まで再試行（1 回では通らないことが多い）
            for wait in (1.5, 3.0):
                if r.status_code != 503:
                    break
                await asyncio.sleep(wait)
                _last_call = time.monotonic()
                r = await client.get(MB_ENDPOINT, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    finally:
        _waiting -= 1
    if r.status_code == 503:
        raise SourceBusy("MusicBrainz が混雑しています（503）。少し待ってから再検索してください")
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
                        # 元リンクは MusicBrainz のページではなく、その曲を YouTube で検索した結果にする（試聴しやすい）
                        external_url=youtube_search_url(artist_name, rec.get("title") or q),
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
