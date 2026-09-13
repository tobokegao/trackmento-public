"""プレイリスト（複数曲）の URL から Track の一覧を取る。

単体の URL は fromurl.fetch が 1 件返す。こちらは「まとめ」の URL を受けて複数返す。
対応:
  - ニコニコ動画のマイリスト  https://www.nicovideo.jp/mylist/<id>
      nvapi.nicovideo.jp の公開 API。X-Frontend-Id が要る。サムネイル・投稿者まで取れる
  - SoundCloud のセット        https://soundcloud.com/<user>/sets/<name>
      ページに埋まっている window.__sc_hydration の playlist.tracks
  - bilibili の収藏夹          https://space.bilibili.com/<uid>/favlist?fid=<media_id>
      api.bilibili.com/x/v3/fav/resource/list。単体の動画ページと違い Cookie が要らない
  - Spotify のプレイリスト      https://open.spotify.com/playlist/<id>
      /embed/playlist/<id> の __NEXT_DATA__（通常ページには曲が入っていない）

いずれも公開されているものだけが取れる（非公開・限定公開は 0 件か失敗）。
一度に返すのは MAX_ITEMS 件まで。マスの数より多く取っても使い道がないうえ、
候補の一覧が長くなりすぎる。
"""
from __future__ import annotations

import html
import json
import re
from urllib.parse import parse_qs, urlparse

import httpx

from backend.models import Track
from backend.sources import video

MAX_ITEMS = 50
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

_NICO_MYLIST_RE = re.compile(r"/mylist/(\d+)")
_SC_SET_RE = re.compile(r"^/[^/]+/sets/[^/]+")
_SPOTIFY_PLAYLIST_RE = re.compile(r"/playlist/([A-Za-z0-9]+)")
_BC_PLAYLIST_RE = re.compile(r"^/[^/]+/playlist/[^/]+")


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def kind(url: str) -> str:
    """プレイリストの種類。当てはまらなければ空文字（＝単体として扱う）。"""
    h, p = _host(url), urlparse(url)
    path, qs = p.path, parse_qs(p.query or "")
    if h.endswith("nicovideo.jp") and _NICO_MYLIST_RE.search(path):
        return "nicovideo"
    if h.endswith("soundcloud.com") and _SC_SET_RE.match(path):
        return "soundcloud"
    if h.endswith("bilibili.com") and "favlist" in path and qs.get("fid"):
        return "bilibili"
    if h.endswith("spotify.com") and _SPOTIFY_PLAYLIST_RE.search(path):
        return "spotify"
    if h.endswith("bandcamp.com") and _BC_PLAYLIST_RE.match(path):
        return "bandcamp"
    if (h.endswith("youtube.com") or h == "youtu.be") and qs.get("list"):
        return "youtube"
    return ""


def is_playlist(url: str) -> bool:
    return bool(kind(url))


def label(url: str) -> str:
    return {"nicovideo": "ニコニコ動画のマイリスト", "soundcloud": "SoundCloud のセット",
            "bilibili": "bilibili の収藏夹", "spotify": "Spotify のプレイリスト",
            "bandcamp": "Bandcamp のプレイリスト", "youtube": "YouTube の再生リスト"}.get(kind(url), "プレイリスト")


# ---- ニコニコ動画のマイリスト ----

async def _nicovideo(url: str, client: httpx.AsyncClient) -> list[Track]:
    m = _NICO_MYLIST_RE.search(urlparse(url).path)
    if not m:
        raise ValueError("マイリストの URL ではありません")
    r = await client.get(
        f"https://nvapi.nicovideo.jp/v2/mylists/{m.group(1)}",
        params={"pageSize": MAX_ITEMS},
        headers={"User-Agent": UA, "X-Frontend-Id": "6", "X-Frontend-Version": "0", "Accept": "application/json"},
    )
    r.raise_for_status()
    items = ((r.json().get("data") or {}).get("mylist") or {}).get("items") or []
    out: list[Track] = []
    for it in items:
        v = it.get("video") or {}
        vid, title = v.get("id"), (v.get("title") or "").strip()
        th = v.get("thumbnail") or {}
        image = th.get("largeUrl") or th.get("listingUrl") or th.get("url")
        if not (vid and title and image):
            continue
        out.append(Track(source="nicovideo", title=title, artist=((v.get("owner") or {}).get("name") or "").strip(),
                         image=image, thumb=image, external_url=f"https://www.nicovideo.jp/watch/{vid}"))
    return out


# ---- SoundCloud のセット ----

def _sc_track(t: dict) -> Track | None:
    """SoundCloud の 1 曲。ジャケットが無いもの（投稿者のアイコンしか無い曲）は入れない。"""
    title = (t.get("title") or "").strip()
    art = t.get("artwork_url")
    if not (title and art):
        return None
    return Track(source="soundcloud", title=title, artist=((t.get("user") or {}).get("username") or "").strip(),
                 image=art.replace("-large.", "-t500x500."), thumb=art, external_url=t.get("permalink_url"))


async def _sc_client_id(page_html: str, client: httpx.AsyncClient) -> str | None:
    """ページが読んでいる JS から client_id を拾う（公開ページに載っている値）。"""
    for js in reversed(re.findall(r'src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"', page_html)[-4:]):
        try:
            r = await client.get(js, headers={"User-Agent": UA})
            m = re.search(r'client_id\s*[:=]\s*"([A-Za-z0-9]{20,})"', r.text)
            if m:
                return m.group(1)
        except httpx.HTTPError:
            continue
    return None


async def _soundcloud(url: str, client: httpx.AsyncClient) -> list[Track]:
    r = await client.get(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    r.raise_for_status()
    m = re.search(r"window\.__sc_hydration\s*=\s*(\[.*?\]);", r.text, re.S)
    if not m:
        raise ValueError("SoundCloud のページから曲の一覧を読めませんでした")
    try:
        hydration = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ValueError("SoundCloud のページの形式が変わったようです") from e
    tracks = []
    for ent in hydration:
        if ent.get("hydratable") == "playlist":
            tracks = (ent.get("data") or {}).get("tracks") or []
            break
    # ページに埋まっているのは先頭の数曲だけで、残りは id しか入っていない。
    # 足りない分は公開 API（client_id はページの JS に載っている）でまとめて引く
    out: list[Track] = [t for t in (_sc_track(x) for x in tracks if x.get("title")) if t]
    missing = [str(x["id"]) for x in tracks if not x.get("title") and x.get("id")][: MAX_ITEMS - len(out)]
    if missing:
        cid = await _sc_client_id(r.text, client)
        if cid:
            for i in range(0, len(missing), 20):   # ids はまとめて渡せるが、長すぎる URL を避けて 20 件ずつ
                try:
                    rr = await client.get("https://api-v2.soundcloud.com/tracks",
                                          params={"ids": ",".join(missing[i:i + 20]), "client_id": cid},
                                          headers={"User-Agent": UA, "Accept": "application/json"})
                    rr.raise_for_status()
                except httpx.HTTPError:
                    break   # 途中で失敗しても、そこまでに取れた分は返す
                out.extend(t for t in (_sc_track(x) for x in rr.json()) if t)
                if len(out) >= MAX_ITEMS:
                    break
    return out[:MAX_ITEMS]


# ---- bilibili の収藏夹 ----

async def _bilibili(url: str, client: httpx.AsyncClient) -> list[Track]:
    fid = (parse_qs(urlparse(url).query or "").get("fid") or [""])[0]
    if not fid.isdigit():
        raise ValueError("収藏夹の URL ではありません（fid が要ります）")
    r = await client.get(
        "https://api.bilibili.com/x/v3/fav/resource/list",
        params={"media_id": fid, "pn": 1, "ps": min(MAX_ITEMS, 20), "platform": "web"},
        headers={"User-Agent": UA, "Referer": "https://space.bilibili.com/", "Accept": "application/json"},
    )
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 0:
        raise ValueError(f"bilibili が拒否しました（{body.get('message')}）")
    medias = (body.get("data") or {}).get("medias") or []
    out: list[Track] = []
    for m in medias:
        title, cover, bvid = (m.get("title") or "").strip(), m.get("cover") or "", m.get("bvid")
        if not (title and cover and bvid):
            continue
        cover = cover.replace("http://", "https://", 1)
        out.append(Track(source="bilibili", title=title, artist=((m.get("upper") or {}).get("name") or "").strip(),
                         image=video.bili_sized(cover), thumb=video.bili_sized(cover, video.BILI_THUMB_SUFFIX),
                         external_url=f"https://www.bilibili.com/video/{bvid}/"))
    return out


# ---- Spotify のプレイリスト ----

async def _spotify(url: str, client: httpx.AsyncClient) -> list[Track]:
    m = _SPOTIFY_PLAYLIST_RE.search(urlparse(url).path)
    if not m:
        raise ValueError("プレイリストの URL ではありません")
    # 通常のページには曲が入っていない。埋め込み用のページを読む
    r = await client.get(f"https://open.spotify.com/embed/playlist/{m.group(1)}",
                         headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    r.raise_for_status()
    nd = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text, re.S)
    if not nd:
        raise ValueError("Spotify のページから曲の一覧を読めませんでした")
    try:
        data = json.loads(nd.group(1))
    except json.JSONDecodeError as e:
        raise ValueError("Spotify のページの形式が変わったようです") from e
    entity = (((data.get("props") or {}).get("pageProps") or {}).get("state") or {}).get("data", {}).get("entity") or {}
    out: list[Track] = []
    for t in (entity.get("trackList") or [])[:MAX_ITEMS]:
        title = (t.get("title") or "").strip()
        # 画像はプレイリスト単位でしか付かないことがある。その場合は曲ごとの visuals を優先
        cover = ""
        for v in (t.get("visualIdentity") or {}).get("image") or []:
            if v.get("url"):
                cover = v["url"]
        if not cover:
            for v in (entity.get("visualIdentity") or {}).get("image") or []:
                if v.get("url"):
                    cover = v["url"]
        if not (title and cover):
            continue
        out.append(Track(source="spotify", title=title, artist=(t.get("subtitle") or "").strip(),
                         image=cover, thumb=cover,
                         external_url=f"https://open.spotify.com/track/{t.get('uid') or ''}" if t.get("uid") else None))
    return out


_FETCHERS = {"nicovideo": _nicovideo, "soundcloud": _soundcloud, "bilibili": _bilibili, "spotify": _spotify}


async def fetch(url: str, *, client: httpx.AsyncClient | None = None) -> list[Track]:
    """プレイリストの URL から Track の一覧。対応していない種類なら ValueError。"""
    k = kind(url)
    fn = _FETCHERS.get(k)
    if not fn:
        raise ValueError("このプレイリストにはまだ対応していません")
    own = client is None
    client = client or httpx.AsyncClient(timeout=30, follow_redirects=True)
    try:
        out = await fn(url, client)
    finally:
        if own:
            await client.aclose()
    if not out:
        raise ValueError("曲を取れませんでした（非公開か、空のプレイリストの可能性）")
    return out[:MAX_ITEMS]
