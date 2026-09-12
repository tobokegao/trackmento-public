"""Bandcamp。公式 API は無いので、トラック／アルバムページの URL を受け取り
og:image と JSON-LD（MusicRecording / MusicAlbum）から曲名・アーティストを取る。
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from backend import netguard
from backend.models import Track

_IMG_SIZE_RE = re.compile(r"_(\d+)\.(jpg|png)$")
UA = "Mozilla/5.0 (compatible; musicgrid-local/0.1)"


def _canonical(url: str) -> str:
    """クエリ（?from=… などの追跡パラメータ）とフラグメントを落とす（共有 JSON に載るため）"""
    from urllib.parse import urlsplit, urlunsplit
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))


# bcbits の末尾 _NN は解像度。_0 = 原寸, _10 = 1200px, _16 = 700px, _7 = 160px。
# 書き出しのマスは 600px（render.py / index.html の CELL_PX）なので、それを上回る最小の _16 を使う。
# _0 は実測で 1 枚 6.5MB あり、_16 なら 87KB（-98%）。Bandcamp は /image-proxy を必ず通るため、
# ここが大きいと Render の転送量（課金対象）を直撃する。
COVER_SIZE = 16
THUMB_SIZE = 7


def _sized(url: str, size: int) -> str:
    """bcbits の画像 URL を指定の解像度に差し替える。"""
    return _IMG_SIZE_RE.sub(lambda m: f"_{size}.{m.group(2)}", url)


def clamp_size(url: str) -> str:
    """原寸（_0）や 1200px（_10）で保存済みの URL を 600px 相当（_16）に落とす。
    既に _16 以下ならそのまま返す。/image-proxy から呼び、過去のグリッドにも効かせる。"""
    if "bcbits.com" not in url:
        return url
    m = _IMG_SIZE_RE.search(url)
    if not m or m.group(1) in ("16", "7", "2", "3", "42", "8"):   # 700px 以下のコードはそのまま
        return url
    return _sized(url, COVER_SIZE)


def _from_jsonld(soup: BeautifulSoup) -> dict:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _name(obj) -> str | None:
    return obj.get("name") if isinstance(obj, dict) else None


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("URL の形式が正しくありません")
    if not netguard.url_ok(url):
        raise ValueError("この宛先のページは取得できません（公開されている http(s) の URL を貼ってください）")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        # 任意の URL を取りに行く入口なので、私設アドレス宛てとそこへのリダイレクトは netguard が拒否する
        r = await netguard.safe_get(client, url, headers={"User-Agent": UA})
        r.raise_for_status()
    finally:
        if own:
            await client.aclose()
    soup = BeautifulSoup(r.text, "lxml")

    def meta(prop: str, attr: str = "property") -> str | None:
        t = soup.find("meta", attrs={attr: prop})
        return t.get("content") if t else None

    og_image = meta("og:image")
    if not og_image:
        raise ValueError("このページにはジャケット画像（og:image）がありません")

    ld = _from_jsonld(soup)
    title = ld.get("name")
    artist = _name(ld.get("byArtist"))
    album = None
    if ld.get("@type") == "MusicRecording":
        album = _name(ld.get("inAlbum"))
    elif ld.get("@type") == "MusicAlbum":
        album = title

    if not title or not artist:
        # og:title は "Title, by Artist" の形式
        og_title = meta("og:title") or meta("title", "name") or ""
        m = re.match(r"^(.*?),\s*by\s+(.*)$", og_title)
        if m:
            title = title or m.group(1).strip()
            artist = artist or m.group(2).strip()
        else:
            title = title or og_title.strip() or url
            artist = artist or (meta("og:site_name") or "")

    return Track(
        source="bandcamp",
        title=title,
        artist=artist,
        album=album,
        image=_sized(og_image, COVER_SIZE),
        thumb=_sized(og_image, THUMB_SIZE),
        external_url=_canonical(url),
    )
