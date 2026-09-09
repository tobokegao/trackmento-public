"""URL 貼付の振り分け。Bandcamp / SoundCloud / YouTube / ニコニコ動画 / bilibili をホスト名で判定して fetch 関数を返す。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx

from backend.models import Track
from backend.sources import bandcamp, soundcloud, video

Fetcher = Callable[..., Awaitable[Track]]


def resolve(url: str) -> tuple[str, Fetcher]:
    """(表示名, fetch) を返す。どれにも当てはまらなければ Bandcamp として扱う（独自ドメインの Bandcamp があるため）。"""
    if soundcloud.is_soundcloud(url):
        return "SoundCloud", soundcloud.fetch
    if video.is_youtube(url):
        return "YouTube", video.fetch_youtube
    if video.is_nicovideo(url):
        return "ニコニコ動画", video.fetch_nicovideo
    if video.is_bilibili(url):
        return "bilibili", video.fetch_bilibili
    return "Bandcamp", bandcamp.fetch


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    _, fn = resolve(url)
    return await fn(url, client=client)
