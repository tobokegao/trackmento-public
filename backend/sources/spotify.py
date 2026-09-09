"""Spotify。キーワード検索は開発者登録（OAuth）が要るので使わず、トラック／アルバムの URL 貼付だけ対応（キー不要）。

- open.spotify.com のページはブラウザ UA だと JS アプリの空殻しか返らないが、SNS のクローラ UA だと
  og:title / og:description（"Artist · Album · Song · Year"）/ og:image（640px）/ music:musician_description を返す
- 取れなかったときは /embed/track/<id> の __NEXT_DATA__（title / artists / visualIdentity.image）を読む
- spotify.link の短縮 URL と spotify:track:<id> の URI にも対応
"""
from __future__ import annotations

import html as html_
import json
import re
from urllib.parse import urlparse

import httpx

from backend.models import Track

CRAWLER_UA = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php) trackmento/0.1"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
_ID_RE = re.compile(r"/(track|album)/([A-Za-z0-9]{22})")
_URI_RE = re.compile(r"^spotify:(track|album):([A-Za-z0-9]{22})$")


def is_spotify(url: str) -> bool:
    if url.startswith("spotify:"):
        return True
    try:
        h = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return h in ("open.spotify.com", "spotify.com", "www.spotify.com", "play.spotify.com", "spotify.link")


_TITLE_NOISE_RE = re.compile(r"\s*(?:-\s*(?:album|single|ep|song(?: and lyrics)?)\s+by\s+.*)?\s*\|\s*Spotify\s*$", re.IGNORECASE)


def _clean_title(t: str | None) -> str | None:
    """og:title の "… - Album by Artist | Spotify" のような接尾辞を落とす。"""
    return _TITLE_NOISE_RE.sub("", t).strip() if t else t


def _meta(page: str, attr: str, name: str) -> str | None:
    m = re.search(r'<meta[^>]+%s="%s"[^>]+content="([^"]*)"' % (attr, re.escape(name)), page) or \
        re.search(r'<meta[^>]+content="([^"]*)"[^>]+%s="%s"' % (attr, re.escape(name)), page)
    return html_.unescape(m.group(1)) if m else None


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    if not is_spotify(url):
        raise ValueError("Spotify のトラック／アルバム URL（open.spotify.com/track/…）を貼ってください")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        m = _URI_RE.match(url)
        if not m and (urlparse(url).hostname or "").lower() == "spotify.link":
            r0 = await client.get(url, headers={"User-Agent": BROWSER_UA})
            url = str(r0.url)
        if not m:
            m = _ID_RE.search(urlparse(url).path)
        if not m:
            raise ValueError("Spotify のトラック／アルバム URL（open.spotify.com/track/…）を貼ってください")
        kind, sid = m.group(1), m.group(2)
        canonical = f"https://open.spotify.com/{kind}/{sid}"

        title = artist = album = image = None
        r = await client.get(canonical, headers={"User-Agent": CRAWLER_UA, "Accept": "text/html"})
        if r.status_code == 200:
            page = r.text
            title = _clean_title(_meta(page, "property", "og:title"))
            artist = _meta(page, "name", "music:musician_description")
            image = _meta(page, "property", "og:image")
            desc = _meta(page, "property", "og:description") or ""
            parts = [p.strip() for p in desc.split("·")]
            if kind == "track" and len(parts) >= 2:
                artist = artist or parts[0]
                album = parts[1]
            elif kind == "album":
                artist = artist or (parts[0] if parts else None)
                album = title
        if not title or not image:
            # フォールバック: 埋め込みプレイヤーのページに入っている JSON
            r2 = await client.get(f"https://open.spotify.com/embed/{kind}/{sid}", headers={"User-Agent": BROWSER_UA})
            if r2.status_code == 404:
                raise ValueError("Spotify にそのページがありません")
            r2.raise_for_status()
            mm = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r2.text, re.S)
            if mm:
                try:
                    ent = json.loads(mm.group(1)).get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                except json.JSONDecodeError:
                    ent = {}
                title = title or ent.get("title")
                artist = artist or ", ".join(a.get("name", "") for a in ent.get("artists", []) if a.get("name"))
                imgs = [i.get("url", "") for i in ent.get("visualIdentity", {}).get("image", [])]
                big = [u for u in imgs if "0000b273" in u] or imgs
                image = image or (big[0] if big else None)
        if not title:
            raise ValueError("Spotify から情報を取れませんでした（非公開か、ページの形式が変わった可能性）")
        if not image:
            raise ValueError("このページにはジャケット画像がありません")
    finally:
        if own:
            await client.aclose()
    return Track(
        source="spotify",
        title=title.strip(),
        artist=(artist or "").strip(),
        album=(album or None),
        image=image,
        thumb=image.replace("0000b273", "00001e02") if "0000b273" in image else image,
        external_url=canonical,
    )
