"""YouTube / ニコニコ動画。動画ページの URL からタイトル・投稿者・サムネイルを取る（キー不要）。

- YouTube: https://www.youtube.com/oembed?url=…&format=json → title, author_name。
  サムネイルは動画 ID から i.ytimg.com の maxresdefault → sddefault → hqdefault の順に存在するものを使う
- ニコニコ動画: https://ext.nicovideo.jp/api/getthumbinfo/{sm…} (XML) → title, user_nickname / ch_name, thumbnail_url。
  新しい動画は thumbnail_url + ".L" で大きい画像が取れる（無ければ元のまま）
- bilibili: 公開 API（x/web-interface/view）は Cookie 無しだと 412 で弾かれるので、動画ページの HTML に埋め込まれた
  window.__INITIAL_STATE__（videoData.title / owner.name / pic）を読む。無ければ og:title / og:image / meta[name=author]。
  b23.tv の短縮 URL はリダイレクト先を使う
サムネイルは 16:9 なので、正方形のマスでは中央が切り出される。
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import httpx

from backend.models import Track

UA = "trackmento/0.1 (+https://github.com/local/musicgrid-local)"
YT_OEMBED = "https://www.youtube.com/oembed"
NICO_THUMBINFO = "https://ext.nicovideo.jp/api/getthumbinfo/"
_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_NICO_ID_RE = re.compile(r"\b((?:sm|nm|so)\d+)\b")
_BILI_ID_RE = re.compile(r"/video/((?:BV[0-9A-Za-z]{10})|(?:av\d+))", re.IGNORECASE)
_BILI_STATE_RE = re.compile(r"window\.__INITIAL_STATE__=(\{.*?\});\(function", re.S)
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_youtube(url: str) -> bool:
    h = _host(url)
    return h in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")


def is_nicovideo(url: str) -> bool:
    h = _host(url)
    return h.endswith("nicovideo.jp") or h == "nico.ms"


def is_bilibili(url: str) -> bool:
    h = _host(url)
    return h.endswith("bilibili.com") or h == "b23.tv"


def _meta(html: str, attr: str, name: str) -> str | None:
    m = re.search(r'<meta[^>]+%s="%s"[^>]+content="([^"]*)"' % (attr, re.escape(name)), html) or \
        re.search(r'<meta[^>]+content="([^"]*)"[^>]+%s="%s"' % (attr, re.escape(name)), html)
    return m.group(1) if m else None


async def fetch_bilibili(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    headers = {"User-Agent": BROWSER_UA, "Accept": "text/html", "Accept-Language": "ja,en;q=0.8"}
    try:
        if _host(url) == "b23.tv":
            r0 = await client.get(url, headers=headers, follow_redirects=False)
            url = r0.headers.get("location") or url
        m = _BILI_ID_RE.search(urlparse(url).path)
        if not m:
            raise ValueError("bilibili の動画 URL（bilibili.com/video/BV… または av…）を貼ってください")
        vid = m.group(1)
        r = await client.get(f"https://www.bilibili.com/video/{vid}/", headers=headers)
        if r.status_code == 404:
            raise ValueError("bilibili にその動画がありません")
        r.raise_for_status()
        html = r.text
        title = artist = pic = None
        sm = _BILI_STATE_RE.search(html)
        if sm:
            try:
                vd = (json.loads(sm.group(1)) or {}).get("videoData") or {}
                title, artist, pic = vd.get("title"), (vd.get("owner") or {}).get("name"), vd.get("pic")
            except json.JSONDecodeError:
                pass
        if not title:
            t = _meta(html, "property", "og:title") or ""
            title = re.sub(r"_哔哩哔哩_bilibili$", "", t).strip() or None
        artist = artist or _meta(html, "name", "author") or ""
        pic = pic or (_meta(html, "property", "og:image") or "").split("@")[0]
        if not title or "视频去哪了" in title:
            raise ValueError("bilibili にその動画がありません（削除済みか非公開の可能性）")
        if not pic:
            raise ValueError("この動画にはカバー画像がありません")
        if pic.startswith("//"):
            pic = "https:" + pic
        pic = pic.replace("http://", "https://", 1)
    finally:
        if own:
            await client.aclose()
    return Track(
        source="bilibili",
        title=title.strip(),
        artist=artist.strip(),
        album=None,
        image=pic,
        thumb=pic + "@320w_320h_1c",   # bilibili の画像 CDN はサイズ指定サフィックスで縮小できる
        external_url=f"https://www.bilibili.com/video/{vid}/",
    )


def youtube_id(url: str) -> str | None:
    p = urlparse(url)
    h = (p.hostname or "").lower()
    if h == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
    else:
        vid = parse_qs(p.query).get("v", [""])[0]
        if not vid:
            m = re.match(r"^/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})", p.path)
            vid = m.group(1) if m else ""
    return vid if _YT_ID_RE.match(vid or "") else None


def nicovideo_id(url: str) -> str | None:
    m = _NICO_ID_RE.search(urlparse(url).path)
    return m.group(1) if m else None


async def _head_ok(client: httpx.AsyncClient, url: str) -> bool:
    try:
        r = await client.head(url, headers={"User-Agent": UA}, timeout=8, follow_redirects=True)
        return r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
    except httpx.HTTPError:
        return False


async def fetch_youtube(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    vid = youtube_id(url)
    if not vid:
        raise ValueError("YouTube の動画 URL（watch?v=… / youtu.be/…）を貼ってください")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        r = await client.get(YT_OEMBED, params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}, headers={"User-Agent": UA})
        if r.status_code in (400, 401, 403, 404):  # 存在しない ID は 400 で返る
            raise ValueError("YouTube にその動画がありません（非公開・削除・埋め込み不可の可能性）")
        r.raise_for_status()
        d = r.json()
        image = d.get("thumbnail_url") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        for name in ("maxresdefault", "sddefault"):
            cand = f"https://i.ytimg.com/vi/{vid}/{name}.jpg"
            if await _head_ok(client, cand):
                image = cand
                break
    finally:
        if own:
            await client.aclose()
    return Track(
        source="youtube",
        title=(d.get("title") or "").strip() or url,
        artist=(d.get("author_name") or "").strip(),
        album=None,
        image=image,
        thumb=d.get("thumbnail_url") or image,
        external_url=f"https://www.youtube.com/watch?v={vid}",
    )


async def fetch_nicovideo(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    vid = nicovideo_id(url)
    if not vid:
        raise ValueError("ニコニコ動画の URL（…/watch/sm12345）を貼ってください")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        r = await client.get(NICO_THUMBINFO + vid, headers={"User-Agent": UA})
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        if root.get("status") != "ok":
            code = root.findtext(".//code") or "?"
            raise ValueError(f"ニコニコ動画から取れませんでした（{code}: 削除済みか非公開の可能性）")
        thumb = root.findtext(".//thumbnail_url") or ""
        if not thumb:
            raise ValueError("この動画にはサムネイルがありません")
        image = thumb
        if await _head_ok(client, thumb + ".L"):
            image = thumb + ".L"
    finally:
        if own:
            await client.aclose()
    return Track(
        source="nicovideo",
        title=(root.findtext(".//title") or "").strip() or vid,
        artist=(root.findtext(".//user_nickname") or root.findtext(".//ch_name") or "").strip(),
        album=None,
        image=image,
        thumb=thumb,
        external_url=f"https://www.nicovideo.jp/watch/{vid}",
    )
