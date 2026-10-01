"""URL貼付の振り分け。Bandcamp / SoundCloud / YouTube / ニコニコ動画 / bilibili / Spotifyをホスト名で判定してfetch関数を返す。

動画サイト（ニコニコ／YouTube／SoundCloud）で直接取れなかったとき（削除済みなど）は
roxy（otoDB）にフォールバックする。sm12345やBV… のようなIDだけが貼られたときは、
normalize() がそのサイトのURLに組み立ててから同じ流れに乗せる。

実際に拾えるのはほぼニコニコだけ（roxyが未登録から取りに行くのがニコニコのみのため）。
それ以外を _ROXY_FALLBACKに残してあるのは、otoDB側が広げたときにそのまま効くようにするため。
空振りしても失敗時に1回余分に問い合わせるだけで、結果は元の例外を返す。
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

import httpx

from backend.models import Track
from backend.logutil import brief
from backend.sources import applemusic, bandcamp, otodb, soundcloud, spotify, video

Fetcher = Callable[..., Awaitable[Track]]


async def _applemusic_one(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    """Apple Musicを1件で返す（アルバムやプレイリストのURLなら先頭の曲）。
    まとめて取りたいときはplaylist.fetchが使われる。"""
    return (await applemusic.fetch(url, client=client))[0]
# bilibiliは入れない。fetch_bilibiliが自分でroxy（otoDB）→ VocaDBの順に引く（bilibili本体は叩かない）
_ROXY_FALLBACK = {"SoundCloud", "YouTube", "ニコニコ動画"}

# 動画IDだけが貼られたとき、そのサイトのURLに組み立てる。以前はIDをまるごとroxyに投げていたが、
# roxyが扱えるのはニコニコだけなのでBV… とYouTubeの11文字は必ず失敗していた（毎回roxyへの無駄打ち）。
# 各サイトから直接取り、消えていたときだけ _ROXY_FALLBACK経由でroxyに回す方がどちらにも良い
_ID_URL = (
    (re.compile(r"^(?:sm|nm|so)\d+$"), "https://www.nicovideo.jp/watch/{}"),
    (re.compile(r"^(?:BV[0-9A-Za-z]{10}|av\d+)$"), "https://www.bilibili.com/video/{}"),
    (re.compile(r"^[A-Za-z0-9_-]{11}$"), "https://www.youtube.com/watch?v={}"),
)


def normalize(url: str) -> str:
    """動画IDだけならそのサイトのURLにする。URLならそのまま。"""
    s = url.strip()
    for pat, tpl in _ID_URL:
        if pat.match(s):
            return tpl.format(s)
    return url


def resolve(url: str) -> tuple[str, Fetcher]:
    """(表示名, fetch) を返す。どれにも当てはまらなければBandcampとして扱う（独自ドメインのBandcampがあるため）。"""
    url = normalize(url)
    if soundcloud.is_soundcloud(url):
        return "SoundCloud", soundcloud.fetch
    if video.is_youtube(url):
        return "YouTube", video.fetch_youtube
    if video.is_nicovideo(url):
        return "ニコニコ動画", video.fetch_nicovideo
    if video.is_bilibili(url):
        return "bilibili", video.fetch_bilibili
    if applemusic.is_applemusic(url):
        return "Apple Music", _applemusic_one
    if spotify.is_spotify(url):
        return "Spotify", spotify.fetch
    return "Bandcamp", bandcamp.fetch


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    url = normalize(url)
    label, fn = resolve(url)
    try:
        return await fn(url, client=client)
    except (ValueError, httpx.HTTPError) as e:
        if label not in _ROXY_FALLBACK:
            raise
        # 削除済み・非公開などで直接取れない → otoDB（roxy）に登録があればそれを使う
        try:
            t = await otodb.roxy_fetch(url, client=client)
        except (ValueError, httpx.HTTPError) as e2:
            print(f"[from-url] {label}失敗（{brief(e)}）→ roxyも失敗（{brief(e2)}）")
            raise e from None
        return t
