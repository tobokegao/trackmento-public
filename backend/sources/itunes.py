"""iTunes Search API。キー不要。

https://itunes.apple.com/search?term=...&entity=song&country=JP&limit=25
artworkUrl100 の "100x100" を "1000x1000" に置き換えると高解像度が取れる。

Apple は共有ホスティング（Render など）の IP を 403/429 で遮断することがある。その場合は
ITUNES_PROXY_URL（Cloudflare Workers の中継。scripts/cloudflare/itunes-proxy.js）を設定すると、
Cloudflare の IP から Apple を呼ぶ。ITUNES_PROXY_TOKEN は中継側の TOKEN と同じ値（他人に使われないため）。
"""
from __future__ import annotations

import os
import re
import time

import httpx

from backend.merge import _n
from backend.models import Track

ENDPOINT = "https://itunes.apple.com/search"
BLOCK_SECONDS = 600   # 403/429 を受けたあと iTunes を叩かない秒数
_blocked_until = 0.0


def proxy_url() -> str:
    """中継（Cloudflare Workers）の URL。無ければ空文字（Apple を直接呼ぶ）。"""
    return os.getenv("ITUNES_PROXY_URL", "").strip().rstrip("/")


def _endpoint() -> tuple[str, dict[str, str]]:
    p = proxy_url()
    if not p:
        return ENDPOINT, {}
    token = os.getenv("ITUNES_PROXY_TOKEN", "").strip()
    return f"{p}/search", ({"X-Trackmento-Token": token} if token else {})


def is_blocked() -> bool:
    return time.monotonic() < _blocked_until


class SourceBlocked(Exception):
    """Apple にこのサーバーの IP が拒否（403）または制限（429）されている。しばらく呼ばない。"""
_SIZE_RE = re.compile(r"/\d+x\d+(bb)?\.(jpg|png)$")


def hires(url: str, size: int = 1000) -> str:
    """artworkUrl100 → 1000x1000 版 URL。"""
    return _SIZE_RE.sub(lambda m: f"/{size}x{size}{m.group(1) or ''}.{m.group(2)}", url)


def _to_track(item: dict) -> Track | None:
    art = item.get("artworkUrl100") or item.get("artworkUrl60")
    if not art:
        return None
    return Track(
        source="itunes",
        title=item.get("trackName") or "",
        artist=item.get("artistName") or "",
        album=item.get("collectionName"),
        image=hires(art),
        thumb=art,
        external_url=item.get("trackViewUrl"),
    )


async def search(q: str, artist: str = "", *, limit: int = 25, country: str = "JP",
                 client: httpx.AsyncClient | None = None) -> list[Track]:
    term = f"{artist} {q}".strip()
    if not term:
        return []
    params = {"term": term, "entity": "song", "country": country, "limit": limit}
    global _blocked_until
    if time.monotonic() < _blocked_until:
        raise SourceBlocked("iTunes がこのサーバーからのアクセスを制限しています（しばらく待ってから再検索）")
    own = client is None
    client = client or httpx.AsyncClient(timeout=10)
    endpoint, headers = _endpoint()
    try:
        r = await client.get(endpoint, params=params, headers=headers)
        if r.status_code in (403, 429):
            # 共有 IP（Render など）が Apple に拒否されている。叩き続けると悪化するので一定時間止める
            _blocked_until = time.monotonic() + BLOCK_SECONDS
            print(f"[itunes] {r.status_code}{'（中継経由）' if proxy_url() else ''} → {BLOCK_SECONDS}s 停止")
            raise SourceBlocked(f"iTunes がこのサーバーからのアクセスを制限しています（{r.status_code}）")
        r.raise_for_status()
        data = r.json()
    finally:
        if own:
            await client.aclose()
    # iTunes の検索はあいまい（アルバム名や作曲者にも当たり、関係ない曲まで返る）ので、
    # 正規化した曲名にクエリを含み、かつアーティスト名にクエリのアーティストを含むものだけに絞る
    # （空白・記号・大小・全角半角は無視）。完全一致を先頭に、それ以外はそのあとに並べる
    want_title, want_artist = _n(q), _n(artist)
    exact: list[Track] = []
    partial: list[Track] = []
    for item in data.get("results", []):
        if item.get("wrapperType") not in (None, "track"):
            continue
        t = _to_track(item)
        if not t:
            continue
        nt, na = _n(t.title), _n(t.artist)
        if want_title and want_title not in nt:
            continue
        if want_artist and want_artist not in na:
            continue
        (exact if (not want_title or nt == want_title) and (not want_artist or na == want_artist) else partial).append(t)
    return exact + partial
