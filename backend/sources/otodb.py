"""otoDB（音MAD データベース）と roxy。

- 検索: https://otodb.net/api/work/search?query=…&limit=30 → items[].title / thumbnail / tags。
  作者はタグのうち category=4（Creator）の名前。サムネイルは otoDB の CDN にあるので、元動画が削除済みでも残る
- roxy: https://roxy.otodb.net/xml?q=<動画 ID か URL> → title / thumbnail / identifier。
  otoDB 登録済みならそのデータ（identifier が otodb:<id>）、未登録なら各サイトから取ってくる。
  直接取得に失敗したとき（削除済みなど）のフォールバックに使う。
  **未登録からの取得が効くのはニコニコだけ**（2026-09 実測）。YouTube / bilibili / SoundCloud は
  生きている URL でも 404 "Cannot fallback" を返す。identifier が niconico:<id> なら各サイトからの取得
どちらもキー不要。
"""
from __future__ import annotations

import asyncio
import re
from xml.etree import ElementTree

import httpx

from backend.models import Track

SEARCH = "https://otodb.net/api/work/search"
WORK = "https://otodb.net/api/work/work"
ROXY = "https://roxy.otodb.net/xml"
UA = "trackmento/0.1 (+https://github.com/local/musicgrid-local)"
CREATOR = 4  # WorkTagCategory.Creator
PAGE = 30       # otoDB の 1 ページの上限（31 以上を渡すと 422）
MAX_PAGES = 8   # ページングの頭打ち。240 件あればマスの上限（256）にほぼ届く
# roxy の結果を置く擬似ソース名（backend/cache.py の search テーブルを間借りする）。
# roxy は応答に Cache-Control を持たないので、こちらで覚えないと同じプレイリストを貼るたび叩いてしまう。
# 見つからなかったときも空リストで覚える（消えた動画の大半は otoDB にも無く、そちらのほうが多い）
ROXY_CACHE = "roxy"
_ID_RE = re.compile(r"^(?:(?:sm|nm|so)\d+|BV[0-9A-Za-z]{10}|av\d+|[A-Za-z0-9_-]{11})$")

# otoDB の CDN。URL に大きさを指定する仕組みが無く、常に 1280x720 / 約 245KB を返す。
# 他の配信元のような clamp_size（URL の書き換え）ができないので、/image-proxy でサーバー側で縮める
IMAGE_HOSTS = ("otodb.net",)


def is_otodb_image(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in IMAGE_HOSTS)


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


async def search(q: str, artist: str = "", *, limit: int = PAGE, client: httpx.AsyncClient | None = None) -> list[Track]:
    """otoDB を検索する。limit が 1 ページ（30 件）を超えるときは offset で続きを取る。

    30 件は otoDB 側の上限（settings.py の NINJA_PAGINATION_MAX_LIMIT）で、31 以上を渡すと 422 になる。
    応答には全体の件数が count で入っているので、そこまで来たら止める。
    otoDB は匿名の GET を 60 秒キャッシュする作りなので（middleware.py の AnonymousReadOnlyCacheMiddleware）、
    ページングしても重くはならないが、念のため MAX_PAGES で頭を打つ。
    """
    query = " ".join(s for s in (q.strip(), artist.strip()) if s)
    if not query:
        return []
    want = max(1, min(limit, PAGE * MAX_PAGES))
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    items: list[dict] = []
    try:
        for page in range(MAX_PAGES):
            params = {"query": query, "limit": PAGE}
            if page:
                params["offset"] = page * PAGE
            r = await client.get(SEARCH, params=params, headers={"User-Agent": UA, "Accept": "application/json"})
            r.raise_for_status()
            body = r.json()
            got = body.get("items") or []
            items.extend(got)
            if len(got) < PAGE or len(items) >= want or len(items) >= (body.get("count") or 0):
                break
    finally:
        if own:
            await client.aclose()
    out: list[Track] = []
    for it in items[:want]:
        t = _to_track(it)
        if t:
            out.append(t)
    return out


async def roxy_fetch(query: str, *, client: httpx.AsyncClient | None = None, timeout: float = 45) -> Track:
    """roxy で動画 ID／URL からタイトルとサムネイルを取る。otoDB 登録済みなら作者も付ける。

    timeout は既定 45 秒（roxy は各サイトへ取りに行くぶん遅いことがある）。プレイリストの
    穴埋めのようにまとめて呼ぶときは、全体が待たされないよう短めを渡す。
    """
    from backend.cache import cache   # 局所 import（他のソースと同じく、取得そのものは cache を知らない作りにしてある）

    ref = query.strip()
    hit = await asyncio.to_thread(cache.get_search, ROXY_CACHE, ref, "")
    if hit is not None:
        if not hit:
            raise ValueError("roxy / otoDB にも情報がありませんでした")
        return Track(**hit[0])
    own = client is None
    client = client or httpx.AsyncClient(timeout=25, follow_redirects=True)
    try:
        r = await client.get(ROXY, params={"q": ref}, headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code == 404:
            # 「otoDB にも無い」は確定した結果なので覚える。ここを覚えないと、同じプレイリストを
            # 貼り直すたびに全部の穴をもう一度 roxy に聞くことになる
            await asyncio.to_thread(cache.set_search, ROXY_CACHE, ref, "", [])
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
    t = Track(source="otodb", title=title, artist=artist, album=None, image=thumb, thumb=thumb, external_url=url or None)
    await asyncio.to_thread(cache.set_search, ROXY_CACHE, ref, "", [t.model_dump()])
    return t
