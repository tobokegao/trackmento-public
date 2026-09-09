"""URL 貼付の振り分け。Bandcamp / SoundCloud / YouTube / ニコニコ動画 / bilibili / Spotify をホスト名で判定して fetch 関数を返す。

動画サイト（ニコニコ／YouTube／bilibili／SoundCloud）で直接取れなかったとき（削除済みなど）は
roxy（otoDB）にフォールバックする。sm12345 や BV… のような ID だけが貼られたときは roxy に直接聞く。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from backend.models import Track
from backend.sources import bandcamp, otodb, soundcloud, spotify, video

Fetcher = Callable[..., Awaitable[Track]]
_ROXY_FALLBACK = {"SoundCloud", "YouTube", "ニコニコ動画", "bilibili"}


def resolve(url: str) -> tuple[str, Fetcher]:
    """(表示名, fetch) を返す。どれにも当てはまらなければ Bandcamp として扱う（独自ドメインの Bandcamp があるため）。"""
    if otodb.is_video_id(url):
        return "otoDB", otodb.roxy_fetch
    if soundcloud.is_soundcloud(url):
        return "SoundCloud", soundcloud.fetch
    if video.is_youtube(url):
        return "YouTube", video.fetch_youtube
    if video.is_nicovideo(url):
        return "ニコニコ動画", video.fetch_nicovideo
    if video.is_bilibili(url):
        return "bilibili", video.fetch_bilibili
    if spotify.is_spotify(url):
        return "Spotify", spotify.fetch
    return "Bandcamp", bandcamp.fetch


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    label, fn = resolve(url)
    try:
        return await fn(url, client=client)
    except (ValueError, httpx.HTTPError) as e:
        if label not in _ROXY_FALLBACK:
            raise
        # 削除済み・非公開などで直接取れない → otoDB（roxy）に登録があればそれを使う
        try:
            t = await otodb.roxy_fetch(url, client=client)
        except (ValueError, httpx.HTTPError):
            raise e from None
        return t
