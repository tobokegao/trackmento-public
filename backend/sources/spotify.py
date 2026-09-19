"""Spotify。トラック／アルバムの URL 貼付に対応する。

**2026-09-20 に公式の Web API へ移した**。それまでは `open.spotify.com` のページを SNS のクローラの
User-Agent で読み、og タグと `/embed/…` の `__NEXT_DATA__` から曲名・アーティスト・ジャケットを拾っていた。
Spotify の Developer Terms（IV.2.4）は robot / spider による取得を明示で禁じており、robots.txt も
`Disallow: /embed/` で、まさにその場所を塞いでいる。

**今は鍵を入れていない**（2026-09-20）。2026 年 2 月から、開発者アプリを登録するアカウントに
Spotify Premium が要るようになったため（新しい Client ID は 2/11、既存は 3/9 から）。
そのため実際に動くのは下の「鍵が無いとき」の経路。鍵を入れればそのまま公式 API に切り替わる。

- **鍵があるとき**（`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`）… Client Credentials で access token を取り、
  `api.spotify.com/v1/tracks|albums/<id>` を引く。曲名・アーティスト・アルバム・ジャケット 640px が取れる
- **鍵が無いとき** … 公式の oEmbed（`open.spotify.com/oembed`、認証不要）に落ちる。
  曲名とジャケット 300px は取れるが、**アーティスト名は返らない**（利用者が手で入れることになる）
- spotify.link の短縮 URL と spotify:track:<id> の URI にも対応
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import time
from urllib.parse import urlparse

import httpx

from backend import netguard

from backend.models import Track

UA = "trackmento/0.1 (+https://trackmento.com)"
API = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
OEMBED = "https://open.spotify.com/oembed"
_ID_RE = re.compile(r"/(track|album)/([A-Za-z0-9]{22})")
_URI_RE = re.compile(r"^spotify:(track|album):([A-Za-z0-9]{22})$")

_token: tuple[float, str] = (0.0, "")   # (使える期限, access token)
_token_lock = asyncio.Lock()


def is_spotify(url: str) -> bool:
    if url.startswith("spotify:"):
        return True
    try:
        h = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return h in ("open.spotify.com", "spotify.com", "www.spotify.com", "play.spotify.com", "spotify.link")


def enabled() -> bool:
    """公式 API の鍵が揃っているか。無ければ oEmbed に落ちる（アーティスト名が取れない）"""
    return bool(os.getenv("SPOTIFY_CLIENT_ID", "").strip() and os.getenv("SPOTIFY_CLIENT_SECRET", "").strip())


async def access_token(client: httpx.AsyncClient) -> str:
    """Client Credentials の access token。期限まで使い回す（1 時間）。鍵が無ければ空文字"""
    global _token
    if not enabled():
        return ""
    if _token[1] and time.monotonic() < _token[0]:
        return _token[1]
    async with _token_lock:
        if _token[1] and time.monotonic() < _token[0]:
            return _token[1]
        pair = f"{os.getenv('SPOTIFY_CLIENT_ID', '').strip()}:{os.getenv('SPOTIFY_CLIENT_SECRET', '').strip()}"
        basic = base64.b64encode(pair.encode()).decode()
        r = await client.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                              headers={"Authorization": f"Basic {basic}", "User-Agent": UA})
        r.raise_for_status()
        body = r.json() or {}
        tok = (body.get("access_token") or "").strip()
        # 期限の 60 秒手前で取り直す（時計のずれと、取りに行く時間のぶん）
        _token = (time.monotonic() + max(60.0, float(body.get("expires_in") or 3600) - 60), tok)
        return tok


async def api_get(path: str, client: httpx.AsyncClient, params: dict | None = None) -> dict:
    """Web API を引く。429（レート制限）は Retry-After ぶん待って 1 回だけ取り直す"""
    tok = await access_token(client)
    if not tok:
        raise ValueError("Spotify の鍵が設定されていません")
    for attempt in range(2):
        r = await client.get(f"{API}{path}", params=params or {},
                             headers={"Authorization": f"Bearer {tok}", "Accept": "application/json", "User-Agent": UA})
        if r.status_code == 429 and attempt == 0:
            await asyncio.sleep(min(float(r.headers.get("Retry-After") or 1), 5))
            continue
        if r.status_code == 404:
            raise ValueError("Spotify にそのページがありません（非公開か、URL が違うようです）")
        r.raise_for_status()
        return r.json() or {}
    raise ValueError("Spotify が混み合っています。少し待ってからもう一度貼ってください")


def pick_image(images: list[dict]) -> tuple[str, str]:
    """(ジャケット, 一覧用のサムネイル)。Spotify は 640 / 300 / 64px を返すので、大きい順に選ぶ。
    **こちらで縮めたり拡大したりはしない**（ほかのソースの `clamp_size` と同じ考え方）"""
    sized = sorted([i for i in images or [] if i.get("url")], key=lambda i: -(i.get("width") or 0))
    if not sized:
        return "", ""
    big = sized[0]["url"]
    small = next((i["url"] for i in sized if (i.get("width") or 0) <= 300), big)
    return big, small


def _artists(items: list[dict]) -> str:
    return ", ".join(a.get("name", "").strip() for a in items or [] if a.get("name"))


async def _oembed(kind: str, sid: str, client: httpx.AsyncClient) -> Track:
    """鍵が無いときの控え。公式 oEmbed は曲名とジャケット 300px だけで、アーティスト名は返らない"""
    canonical = f"https://open.spotify.com/{kind}/{sid}"
    r = await client.get(OEMBED, params={"url": canonical}, headers={"User-Agent": UA, "Accept": "application/json"})
    if r.status_code == 404:
        raise ValueError("Spotify にそのページがありません（非公開か、URL が違うようです）")
    r.raise_for_status()
    body = r.json() or {}
    title, image = (body.get("title") or "").strip(), (body.get("thumbnail_url") or "").strip()
    if not (title and image):
        raise ValueError("Spotify から情報を取れませんでした")
    return Track(source="spotify", title=title, artist="", album=None,
                 image=image, thumb=image, external_url=canonical)


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    if not is_spotify(url):
        raise ValueError("Spotify のトラック／アルバム URL（open.spotify.com/track/…）を貼ってください")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        m = _URI_RE.match(url)
        if not m and (urlparse(url).hostname or "").lower() == "spotify.link":
            r0 = await netguard.safe_get(client, url, headers={"User-Agent": UA})   # 短縮 URL の展開も検査付きで
            url = getattr(r0, "final_url", str(r0.url))
        if not m:
            m = _ID_RE.search(urlparse(url).path)
        if not m:
            raise ValueError("Spotify のトラック／アルバム URL（open.spotify.com/track/…）を貼ってください")
        kind, sid = m.group(1), m.group(2)
        if not enabled():
            return await _oembed(kind, sid, client)

        d = await api_get(f"/{kind}s/{sid}", client)
        title = (d.get("name") or "").strip()
        artist = _artists(d.get("artists") or [])
        if kind == "track":
            album_obj = d.get("album") or {}
            album = (album_obj.get("name") or "").strip() or None
            image, thumb = pick_image(album_obj.get("images") or [])
        else:
            album = title
            image, thumb = pick_image(d.get("images") or [])
        if not title:
            raise ValueError("Spotify から情報を取れませんでした")
        if not image:
            raise ValueError("このページにはジャケット画像がありません")
    finally:
        if own:
            await client.aclose()
    return Track(
        source="spotify",
        title=title,
        artist=artist,
        album=album,
        image=image,
        thumb=thumb,
        external_url=f"https://open.spotify.com/{kind}/{sid}",
    )
