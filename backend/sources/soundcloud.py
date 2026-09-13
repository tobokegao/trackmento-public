"""SoundCloud。公式 API は新規登録が閉じているので、キー不要の oEmbed を使う。

https://soundcloud.com/oembed?url=<トラック URL>&format=json
→ title（"曲名 by アーティスト"）、author_name、thumbnail_url（…-t500x500.jpg）。
サムネイルの "-t500x500" を "-original" に変えると原寸が取れる（無い場合は t500x500 に戻す）。
キーワード検索は API が無いので、Bandcamp と同じく URL を貼ってもらう運用。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

from backend import netguard
from backend.models import Track

OEMBED = "https://soundcloud.com/oembed"
UA = "trackmento/0.1 (+https://github.com/local/musicgrid-local)"

# 画像 URL の末尾（…-t500x500.jpg）で大きさが決まる。実測: t500x500 89KB / t300x300 37KB / t200x200 18KB
_SC_SIZE_RE = re.compile(r"-(original|t\d+x\d+|large|small|badge|tiny|mini|t\d+)\.(jpg|png)$", re.IGNORECASE)
_SC_SIZES = ((200, "t200x200"), (300, "t300x300"), (500, "t500x500"))
_SC_SIZE_PX = {"tiny": 20, "mini": 16, "badge": 47, "small": 32, "large": 100,
               "t200x200": 200, "t300x300": 300, "t500x500": 500, "original": 10000}


def clamp_size(url: str, want_px: int = 500) -> str:
    """sndcdn.com の画像 URL を、欲しい実寸を満たす最小の大きさに落とす。
    既にそれ以下ならそのまま返す。/image-proxy から呼び、過去のグリッドにも効かせる。"""
    if "sndcdn.com" not in url:
        return url
    m = _SC_SIZE_RE.search(url)
    if not m:
        return url
    now = _SC_SIZE_PX.get(m.group(1).lower(), 10000)
    name, px = next(((n, p) for p, n in _SC_SIZES if p >= want_px), ("t500x500", 500))
    return url if now <= px else _SC_SIZE_RE.sub(f"-{name}.{m.group(2)}", url)
_BY_RE = re.compile(r"^(?P<title>.+?)\s+by\s+(?P<artist>.+)$", re.IGNORECASE)


def _canonical(url: str) -> str:
    """?si=… や utm_* などの追跡パラメータとフラグメントを落とす（共有 JSON に載るため）"""
    from urllib.parse import urlsplit, urlunsplit
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def is_soundcloud(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in ("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com", "on.soundcloud.com")


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not is_soundcloud(url):
        raise ValueError("SoundCloud のトラック URL（https://soundcloud.com/…）を貼ってください")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        if (p.hostname or "").lower() == "on.soundcloud.com":
            # アプリの共有で出る短縮 URL。oEmbed は受け付けないので、検査付きでリダイレクト先（soundcloud.com/…）に直す
            r0 = await netguard.safe_get(client, url, headers={"User-Agent": UA})
            url = getattr(r0, "final_url", url).split("?", 1)[0]
        r = await client.get(OEMBED, params={"url": url, "format": "json"}, headers={"User-Agent": UA})
        if r.status_code == 404:
            raise ValueError("SoundCloud にそのページがありません（非公開トラックや削除済みの可能性）")
        if r.status_code == 403:
            raise ValueError("このトラックは SoundCloud 側で埋め込みが許可されていません（アートワークを取れません）。手入力で画像 URL を指定してください")
        r.raise_for_status()
        d = r.json()
        thumb = d.get("thumbnail_url") or ""
        if not thumb:
            raise ValueError("このトラックにはアートワークがありません")
        image = thumb.replace("-t500x500", "-original")
        if image != thumb:
            try:
                h = await client.head(image, headers={"User-Agent": UA}, timeout=8)
                if h.status_code != 200:
                    image = thumb
            except httpx.HTTPError:
                image = thumb
    finally:
        if own:
            await client.aclose()

    raw_title = (d.get("title") or "").strip()
    artist = (d.get("author_name") or "").strip()
    title = raw_title
    m = _BY_RE.match(raw_title)
    if m and (not artist or m.group("artist").strip().casefold() == artist.casefold()):
        title, artist = m.group("title").strip(), artist or m.group("artist").strip()
    elif artist and raw_title.lower().endswith(f" by {artist}".lower()):
        title = raw_title[: -len(f" by {artist}")].strip()
    return Track(
        source="soundcloud",
        title=title or url,
        artist=artist,
        album=None,
        image=image,
        thumb=thumb,
        external_url=_canonical(url),
    )
