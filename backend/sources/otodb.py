"""otoDB（音MAD データベース）と roxy。

- 検索: https://otodb.net/api/work/search?query=…&limit=30 → items[].title / thumbnail / tags。
  作者はタグのうち category=4（Creator）の名前。サムネイルは otoDB の CDN にあるので、元動画が削除済みでも残る
- roxy: https://roxy.otodb.net/xml?q=<動画 ID か URL> → title / thumbnail / identifier。
  otoDB 登録済みならそのデータ、未登録なら各サイトから取ってくる「ベストエフォートの取得プロキシ」。
  ニコニコ／YouTube／bilibili／SoundCloud の直接取得に失敗したとき（削除済みなど）のフォールバックに使う
どちらもキー不要。
"""
from __future__ import annotations

import re
from xml.etree import ElementTree

import httpx

from backend.models import Track

SEARCH = "https://otodb.net/api/work/search"
WORK = "https://otodb.net/api/work/work"
ROXY = "https://roxy.otodb.net/xml"
UA = "trackmento/0.1 (+https://github.com/local/musicgrid-local)"
CREATOR = 4  # WorkTagCategory.Creator
_ID_RE = re.compile(r"^(?:(?:sm|nm|so)\d+|BV[0-9A-Za-z]{10}|av\d+|[A-Za-z0-9_-]{11})$")


def is_video_id(s: str) -> bool:
    """URL ではなく動画 ID だけが貼られたか（sm…, BV…, YouTube の 11 文字）。"""
    return bool(_ID_RE.match(s.strip()))


def _creators(tags: list[dict]) -> str:
    return ", ".join(t.get("name", "") for t in tags or [] if t.get("category") == CREATOR and t.get("name"))


def _to_track(item: dict) -> Track | None:
    thumb = item.get("thumbnail")
    if not thumb:
        return None
    return Track(
        source="otodb",
        title=item.get("title") or "",
        artist=_creators(item.get("tags") or []),
        album=None,
        image=thumb,
        thumb=thumb,
        external_url=f"https://otodb.net/work/{item.get('id')}",
    )


async def search(q: str, artist: str = "", *, limit: int = 30, client: httpx.AsyncClient | None = None) -> list[Track]:
    query = " ".join(s for s in (q.strip(), artist.strip()) if s)
    if not query:
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        r = await client.get(SEARCH, params={"query": query, "limit": min(30, limit)}, headers={"User-Agent": UA, "Accept": "application/json"})
        r.raise_for_status()
        items = r.json().get("items") or []
    finally:
        if own:
            await client.aclose()
    out: list[Track] = []
    for it in items:
        t = _to_track(it)
        if t:
            out.append(t)
    return out


async def roxy_fetch(query: str, *, client: httpx.AsyncClient | None = None) -> Track:
    """roxy で動画 ID／URL からタイトルとサムネイルを取る。otoDB 登録済みなら作者も付ける。"""
    own = client is None
    client = client or httpx.AsyncClient(timeout=25, follow_redirects=True)
    try:
        r = await client.get(ROXY, params={"q": query.strip()}, headers={"User-Agent": UA})
        if r.status_code == 404:
            raise ValueError("roxy / otoDB にも情報がありませんでした")
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        title = (root.findtext("title") or "").strip()
        thumb = (root.findtext("thumbnail") or "").strip()
        ident = (root.findtext("identifier") or "").strip()
        url = (root.findtext("url") or "").strip()
        if not title or not thumb:
            raise ValueError("roxy からタイトルかサムネイルが取れませんでした")
        artist = ""
        if ident.startswith("otodb:"):
            try:
                w = await client.get(WORK, params={"work_id": ident.split(":", 1)[1]}, headers={"User-Agent": UA, "Accept": "application/json"}, timeout=15)
                if w.status_code == 200:
                    artist = _creators(w.json().get("tags") or [])
            except httpx.HTTPError:
                pass
    finally:
        if own:
            await client.aclose()
    return Track(source="otodb", title=title, artist=artist, album=None, image=thumb, thumb=thumb, external_url=url or None)
