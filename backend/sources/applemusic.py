"""Apple Music（music.apple.com）の URL から曲を取る。キー不要。

- 単曲 / アルバム … 公式の iTunes Lookup API（https://itunes.apple.com/lookup）。
  URL の ?i=<trackId> があれば単曲、無ければアルバムの収録曲をまとめて返す。
  既にある iTunes ソースと同じ形の応答なので、画像も同じ扱い（artworkUrl100 → 600x600）ができる。
- プレイリスト … Lookup API の対象外。ページに埋まっている serialized-server-data を読む。
  artwork.dictionary.url は "…/{w}x{h}bb.{f}" というテンプレートなので、実寸を埋めて使う。

storefront（/jp/ の部分）は URL から取る。country が違うと Lookup が 0 件になることがある。
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

import httpx

from backend.models import Track
from backend.sources.itunes import COVER_PX

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
LOOKUP = "https://itunes.apple.com/lookup"
MAX_ITEMS = 256   # backend/sources/playlist.py と同じ

_ALBUM_RE = re.compile(r"/(?:[a-z]{2}/)?album/[^/]*/(\d+)")
_PLAYLIST_RE = re.compile(r"/(?:[a-z]{2}/)?playlist/[^/]*/(pl\.[A-Za-z0-9_-]+)")
_SONG_RE = re.compile(r"/(?:[a-z]{2}/)?song/[^/]*/(\d+)")
_STOREFRONT_RE = re.compile(r"^/([a-z]{2})/")
# artwork のテンプレート "…/{w}x{h}bb.{f}" に実寸を埋める
_TPL_RE = re.compile(r"\{w\}x\{h\}(\w*)\.\{f\}")


def is_applemusic(url: str) -> bool:
    try:
        h = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return h in ("music.apple.com", "itunes.apple.com") or h.endswith(".music.apple.com")


def _storefront(url: str) -> str:
    m = _STOREFRONT_RE.match(urlparse(url).path)
    return (m.group(1) if m else "jp").upper()


def kind(url: str) -> str:
    """"song" / "album" / "playlist" / ""（判別できない）。"""
    if not is_applemusic(url):
        return ""
    p = urlparse(url)
    if _PLAYLIST_RE.search(p.path):
        return "playlist"
    if _SONG_RE.search(p.path):
        return "song"
    if _ALBUM_RE.search(p.path):
        # ?i=<trackId> が付いていればアルバムの中の 1 曲を指している
        return "song" if (parse_qs(p.query or "").get("i") or [""])[0].isdigit() else "album"
    return ""


def _from_lookup(item: dict) -> Track | None:
    """Lookup API の 1 件 → Track。iTunes ソースと同じ形なので画像の扱いも揃う。"""
    art = item.get("artworkUrl100") or item.get("artworkUrl60")
    title = (item.get("trackName") or "").strip()
    if not (art and title):
        return None
    return Track(source="itunes", title=title, artist=(item.get("artistName") or "").strip(),
                 album=item.get("collectionName"),
                 image=re.sub(r"/\d+x\d+(bb)?\.(jpg|png)$", lambda m: f"/{COVER_PX}x{COVER_PX}{m.group(1) or ''}.{m.group(2)}", art),
                 thumb=art, external_url=item.get("trackViewUrl"))


async def _lookup(client: httpx.AsyncClient, params: dict) -> list[dict]:
    r = await client.get(LOOKUP, params=params, headers={"User-Agent": UA, "Accept": "application/json"})
    r.raise_for_status()
    return r.json().get("results") or []


def _walk_tracks(node, out: list) -> None:
    """serialized-server-data を辿って曲の項目を集める（決まった場所に無いので全体を歩く）。"""
    if isinstance(node, dict):
        if node.get("title") and node.get("artwork") and (node.get("subtitleLinks") or node.get("artistName")):
            out.append(node)
        for v in node.values():
            _walk_tracks(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_tracks(v, out)


def _from_page_item(x: dict) -> Track | None:
    title = (x.get("title") or "").strip()
    aw = (x.get("artwork") or {}).get("dictionary") or {}
    tpl = aw.get("url") or ""
    if not (title and tpl):
        return None
    links = x.get("subtitleLinks") or []
    artist = (x.get("artistName") or (links[0].get("title") if links else "") or "").strip()
    # id は "track-lockup - pl.xxx - <trackId>" の形。曲でない項目（プレイリスト自体の見出しなど）は
    # 末尾が数字にならないので、ここで落とす
    m = re.search(r"(\d{6,})\s*$", str(x.get("id") or ""))
    if not m:
        return None
    ext = f"https://music.apple.com/jp/song/{m.group(1)}"
    return Track(source="itunes", title=title, artist=artist,
                 image=_TPL_RE.sub(lambda mm: f"{COVER_PX}x{COVER_PX}{mm.group(1)}.jpg", tpl),
                 thumb=_TPL_RE.sub(lambda mm: f"100x100{mm.group(1)}.jpg", tpl),
                 external_url=ext)


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> list[Track]:
    """Apple Music の URL から Track の一覧（単曲なら 1 件）。"""
    k = kind(url)
    if not k:
        raise ValueError("Apple Music の曲・アルバム・プレイリストの URL を貼ってください")
    own = client is None
    client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
    country = _storefront(url)
    try:
        if k == "song":
            p = urlparse(url)
            tid = (parse_qs(p.query or "").get("i") or [""])[0]
            if not tid.isdigit():
                m = _SONG_RE.search(p.path)
                tid = m.group(1) if m else ""
            if not tid.isdigit():
                raise ValueError("曲の ID を読めませんでした")
            out = [t for t in (_from_lookup(x) for x in await _lookup(client, {"id": tid, "country": country})) if t]
        elif k == "album":
            m = _ALBUM_RE.search(urlparse(url).path)
            res = await _lookup(client, {"id": m.group(1), "country": country, "entity": "song"})
            out = [t for t in (_from_lookup(x) for x in res if x.get("wrapperType") == "track") if t]
        else:
            r = await client.get(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
            r.raise_for_status()
            sm = re.search(r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>', r.text, re.S)
            if not sm:
                raise ValueError("Apple Music のページから曲の一覧を読めませんでした")
            try:
                data = json.loads(sm.group(1))
            except json.JSONDecodeError as e:
                raise ValueError("Apple Music のページの形式が変わったようです") from e
            items: list = []
            _walk_tracks(data, items)
            out = [t for t in (_from_page_item(x) for x in items) if t]
    finally:
        if own:
            await client.aclose()
    if not out:
        raise ValueError("曲を取れませんでした（非公開か、この地域で配信されていない可能性）")
    return out[:MAX_ITEMS]
