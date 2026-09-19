"""プレイリスト（複数曲）の URL から Track の一覧を取る。

単体の URL は fromurl.fetch が 1 件返す。こちらは「まとめ」の URL を受けて複数返す。
対応:
  - ニコニコ動画のマイリスト  https://www.nicovideo.jp/mylist/<id>
      nvapi.nicovideo.jp の公開 API。X-Frontend-Id が要る。サムネイル・投稿者まで取れる
  - SoundCloud のセット        **やめた**（2026-09-20。内部 API が要るため。曲ごとの URL は使える）
  - bilibili の収藏夹          **やめた**（2026-09-20。規約が書面許可を要求しているため）
  - Spotify のプレイリスト      https://open.spotify.com/playlist/<id>
      公式の Web API（playlists/<id>/tracks）。`SPOTIFY_CLIENT_ID` / `_SECRET` が要る（無ければ取らない）
  - Bandcamp のプレイリスト     https://bandcamp.com/<user>/playlist/<name>
      data-blob の appData.tracklist.tracks。画像は artId から組み立てる
  - YouTube の再生リスト        https://www.youtube.com/playlist?list=<id>
      公式の Data API（playlistItems.list）。`YOUTUBE_API_KEY` が要る（無ければ取らない）

いずれも公開されているものだけが取れる（非公開・限定公開は 0 件か失敗）。
一度に返すのは MAX_ITEMS 件まで。
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
from urllib.parse import parse_qs, urlparse

import httpx

from backend.models import Track
from backend.sources import applemusic, bandcamp, otodb, spotify, video, vocadb

# マスの上限（256）より多く取る。入りきらない分は候補に置かれ、そこから選んで絞り込めるため
# （500 は実機で候補パネルの描画が 500 件 52ms／1000 件 132ms だったので、その手前で切った値。
#  ニコニコのマイリストの上限もちょうど 500 で、他のソースは実測でこれに届かない）。
# 1 回のページ取得で返る分だけ入れる（ソースによっては 1 回で全部返らない。
# ニコニコは全件、YouTube は 100 件、bilibili は 20 件が上限）
MAX_ITEMS = 500

# **名乗りは正直にする**（2026-09-20）。以前は素の Chrome の User-Agent を送っていたが、
# ブラウザのふりをすると相手から「誰が来ているか」が分からず、多すぎれば連絡も遮断もできない。
# 形は Bandcamp 向けと同じ「Mozilla/5.0 (compatible; …)」。古い形を見て中身を出すサイトがあるため、
# 互換の殻だけ残して名前と連絡先を入れる
UA = "Mozilla/5.0 (compatible; trackmento/0.1; +https://trackmento.com)"

_NICO_MYLIST_RE = re.compile(r"/mylist/(\d+)")
_SC_SET_RE = re.compile(r"^/[^/]+/sets/[^/]+")
_SPOTIFY_PLAYLIST_RE = re.compile(r"/playlist/([A-Za-z0-9]+)")
_BC_PLAYLIST_RE = re.compile(r"^/[^/]+/playlist/[^/]+")
# **アルバムのページも「まとめて取る」対象にする**。以前は 1 マス（アルバム 1 枚）にしかならず、
# しかもレーベルのアカウントが上げたものだと、その 1 マスのアーティストがレーベル名になっていた
_BC_ALBUM_RE = re.compile(r"^/album/[^/]+")


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
    if h.endswith("bandcamp.com") and (_BC_PLAYLIST_RE.match(path) or _BC_ALBUM_RE.match(path)):
        return "bandcamp"
    if (h.endswith("youtube.com") or h == "youtu.be") and qs.get("list"):
        return "youtube"
    if applemusic.kind(url) in ("album", "playlist"):   # 単曲は /from-url のまま
        return "applemusic"
    return ""


def is_playlist(url: str) -> bool:
    return bool(kind(url))


def label(url: str) -> str:
    return {"nicovideo": "ニコニコ動画のマイリスト", "soundcloud": "SoundCloud のセット",
            "bilibili": "bilibili の収藏夹", "spotify": "Spotify のプレイリスト",
            "bandcamp": "Bandcamp のプレイリスト", "youtube": "YouTube の再生リスト",
            "applemusic": "Apple Music"}.get(kind(url), "プレイリスト")


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
    await _fill_artist_from_vocadb(out, client)
    return out


_PV_FILL_MAX = 24        # 1 つのマイリストで VocaDB に聞く上限
_PV_FILL_BUDGET = 10     # 全体で待つ秒数（間に合った分だけ反映する）


async def _fill_artist_from_vocadb(out: list[Track], client: httpx.AsyncClient) -> None:
    """投稿者名が空の動画（退会・非公開・転載）を VocaDB で埋める。消えた動画（`is_gone`）は otoDB 側で埋めるので除く"""
    holes = [i for i, t in enumerate(out) if not t.artist and not is_gone(t.title) and t.external_url]
    if not holes:
        return

    async def one(i: int) -> None:
        name = await vocadb.artist_for_video(out[i].external_url.rsplit("/", 1)[-1], out[i].title, client=client)
        if name:
            out[i] = out[i].model_copy(update={"artist": name})

    try:
        await asyncio.wait_for(asyncio.gather(*(one(i) for i in holes[:_PV_FILL_MAX])), timeout=_PV_FILL_BUDGET)
    except asyncio.TimeoutError:
        pass


# ---- SoundCloud のセット ----
# **セットの一覧を取るのはやめた**（2026-09-20）。曲の一覧を揃えるにはページに埋まった JSON と、
# 公式ドキュメントに無い内部 API（`api-v2.soundcloud.com`）が要った。SoundCloud の API Terms は
# §10 で「API 経由で正当に取れるもの以外を scraping などで集めること」を禁じ、§01 で「API を叩くには
# client ID が要る」としている。内部 API はその「API」に当たらないと読むのが自然なので外した。
# **曲ごとの URL は今までどおり使える**（`backend/sources/soundcloud.py` の公式 oEmbed）


async def _soundcloud(url: str, client: httpx.AsyncClient) -> list[Track]:
    raise ValueError("SoundCloud のセットは、曲ごとの URL を貼ってください"
                     "（セットをまとめて取るのは、SoundCloud の API の決まりに合わせてやめました）")


# ---- bilibili の収藏夹 ----
# **やめた**（2026-09-20）。理由は `backend/sources/video.py` の fetch_bilibili と同じ
# （規約 4.2.11 が書面許可を要求、`api.bilibili.com` は robots.txt で全面 Disallow）


async def _bilibili(url: str, client: httpx.AsyncClient) -> list[Track]:
    raise ValueError("bilibili には対応していません。曲名・アーティスト名と画像の URL を手で入れてください")


# ---- Spotify のプレイリスト ----
# **公式の Web API を使う**（2026-09-20）。以前は `/embed/playlist/<id>` の `__NEXT_DATA__` を読んでいたが、
# Spotify の robots.txt は `Disallow: /embed/` で、Developer Terms も robot / spider による取得を禁じている。
# 鍵（`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`）が無いときは取らない

SPOTIFY_PAGE = 100     # API の上限


async def _spotify(url: str, client: httpx.AsyncClient) -> list[Track]:
    m = _SPOTIFY_PLAYLIST_RE.search(urlparse(url).path)
    if not m:
        raise ValueError("プレイリストの URL ではありません")
    if not spotify.enabled():
        raise ValueError("Spotify のプレイリストは今まとめて取れません。曲ごとの URL を貼ってください")
    out: list[Track] = []
    for offset in range(0, MAX_ITEMS, SPOTIFY_PAGE):
        body = await spotify.api_get(f"/playlists/{m.group(1)}/tracks", client,
                                     {"limit": SPOTIFY_PAGE, "offset": offset,
                                      "fields": "items(track(name,artists(name),album(name,images),external_urls)),next"})
        for it in body.get("items") or []:
            t = it.get("track") or {}
            title = (t.get("name") or "").strip()
            album = t.get("album") or {}
            image, thumb = spotify.pick_image(album.get("images") or [])
            if not (title and image):
                continue
            out.append(Track(source="spotify", title=title,
                             artist=", ".join(a.get("name", "").strip() for a in t.get("artists") or [] if a.get("name")),
                             album=(album.get("name") or "").strip() or None,
                             image=image, thumb=thumb,
                             external_url=(t.get("external_urls") or {}).get("spotify")))
            if len(out) >= MAX_ITEMS:
                return out
        if not body.get("next"):
            break
    return out


# ---- Bandcamp のプレイリスト ----

def _bc_album(text: str, url: str) -> list[Track]:
    """アルバムのページ（`data-tralbum`）から収録曲を取り出す。

    **曲ごとの `artist` を優先する**（コンピレーションやレーベルのアカウントでは、
    アルバム全体の名前がレーベル名になっていることがある）。無ければアルバムの `artist`。
    ジャケットは曲ごとの `art_id` があればそれ、無ければアルバムの `art_id` から組み立てる。
    """
    m = re.search(r'data-tralbum="(.*?)"', text, re.S)
    if not m:
        return []
    try:
        d = json.loads(html.unescape(m.group(1)))
    except json.JSONDecodeError:
        return []
    tracks = d.get("trackinfo") or []
    if not tracks:
        return []
    base = (d.get("url") or url).split("/album/")[0]
    album_artist = (d.get("artist") or "").strip()
    album_title = ((d.get("current") or {}).get("title") if isinstance(d.get("current"), dict) else None)
    album_art = d.get("art_id")
    out: list[Track] = []
    for t in tracks[:MAX_ITEMS]:
        title = (t.get("title") or "").strip()
        art_id = t.get("art_id") or album_art
        if not (title and art_id):
            continue
        link = t.get("title_link") or ""
        out.append(Track(source="bandcamp", title=title,
                         artist=(t.get("artist") or album_artist or "").strip(),
                         album=album_title,
                         image=f"https://f4.bcbits.com/img/a{art_id}_{bandcamp.COVER_SIZE}.jpg",
                         thumb=f"https://f4.bcbits.com/img/a{art_id}_{bandcamp.THUMB_SIZE}.jpg",
                         external_url=(base + link) if link.startswith("/") else (link or None)))
    return out


async def _bandcamp(url: str, client: httpx.AsyncClient) -> list[Track]:
    r = await client.get(url, headers={"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
    r.raise_for_status()
    got = _bc_album(r.text, url)          # アルバムのページ
    if got:
        return got
    m = re.search(r'data-blob="(.*?)"', r.text, re.S)   # ファンのプレイリスト
    if not m:
        raise ValueError("Bandcamp のページから曲の一覧を読めませんでした")
    try:
        blob = json.loads(html.unescape(m.group(1)))
    except json.JSONDecodeError as e:
        raise ValueError("Bandcamp のページの形式が変わったようです") from e
    tracks = (((blob.get("appData") or {}).get("tracklist") or {}).get("tracks")) or []
    out: list[Track] = []
    for t in tracks[:MAX_ITEMS]:
        title, art_id = (t.get("title") or "").strip(), t.get("artId")
        if not (title and art_id):
            continue
        # artId から画像 URL を組み立てる（a<artId>_<サイズ>.jpg）。_16 は 700px でマス 600px に足りる
        image = f"https://f4.bcbits.com/img/a{art_id}_{bandcamp.COVER_SIZE}.jpg"
        out.append(Track(source="bandcamp", title=title,
                         artist=(t.get("artistName") or "").strip(),
                         album=((t.get("album") or {}).get("title") or None) if isinstance(t.get("album"), dict) else None,
                         image=image, thumb=f"https://f4.bcbits.com/img/a{art_id}_{bandcamp.THUMB_SIZE}.jpg",
                         external_url=t.get("bandUrl") or None))
    return out


# ---- YouTube の再生リスト ----
# **公式の Data API を使う**（2026-09-20）。以前は再生リストのページ HTML（ytInitialData）を読んでいたが、
# YouTube の利用規約は自動アクセスを禁じていて、例外は「robots.txt に従う公開検索エンジン」と「書面の許可」だけ。
# Data API なら `playlistItems.list` 1 回が 1 ユニットで、1 日 10,000 ユニットの枠に収まる
# （500 曲でも 10 回＝10 ユニット）。**キーが無いときは再生リストを取らない**（曲ごとの URL は今までどおり）。
# 単体の動画は公式 oEmbed（`backend/sources/video.py`）なのでキーは要らない
YT_API = "https://www.googleapis.com/youtube/v3/playlistItems"
YT_PAGE = 50          # API の上限
YT_MAX_PAGES = 10     # 500 曲ぶん。1 ページ 1 ユニット


def youtube_key() -> str:
    return os.getenv("YOUTUBE_API_KEY", "").strip()


async def _youtube(url: str, client: httpx.AsyncClient) -> list[Track]:
    list_id = (parse_qs(urlparse(url).query or "").get("list") or [""])[0]
    if not list_id:
        raise ValueError("再生リストの URL ではありません（list= が要ります）")
    key = youtube_key()
    if not key:
        raise ValueError("YouTube の再生リストは今まとめて取れません。曲ごとの動画の URL を貼ってください")
    out: list[Track] = []
    seen: set[str] = set()
    token = ""
    for _ in range(YT_MAX_PAGES):
        params = {"part": "snippet", "playlistId": list_id, "maxResults": YT_PAGE, "key": key}
        if token:
            params["pageToken"] = token
        r = await client.get(YT_API, params=params, headers={"Accept": "application/json"})
        if r.status_code == 404:
            raise ValueError("その再生リストが見つかりません（非公開か、URL が違うようです）")
        if r.status_code == 403:
            # 割り当てを使い切ったか、キーの設定が違う。どちらも利用者には同じ案内でよい
            raise ValueError("YouTube の再生リストを取れませんでした。しばらく待つか、曲ごとの URL を貼ってください")
        r.raise_for_status()
        body = r.json() or {}
        for it in body.get("items") or []:
            sn = it.get("snippet") or {}
            vid = ((sn.get("resourceId") or {}).get("videoId") or "").strip()
            title = (sn.get("title") or "").strip()
            if not (re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) and title) or vid in seen:
                continue
            seen.add(vid)
            # ジャケットは URL を組み立てる（API の thumbnails は消えた動画だと空。大きさの選び方は今までと同じ）
            # 投稿者は videoOwnerChannelTitle（消えた動画では無い）。以前はアバターの読み上げ文から
            # 拾っていたが、API では素直に取れる
            out.append(Track(source="youtube", title=title,
                             artist=(sn.get("videoOwnerChannelTitle") or "").strip(),
                             image=f"https://i.ytimg.com/vi/{vid}/sddefault.jpg",
                             thumb=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                             external_url=f"https://www.youtube.com/watch?v={vid}"))
            if len(out) >= MAX_ITEMS:
                return out
        token = body.get("nextPageToken") or ""
        if not token:
            break
    return out


# 削除・非公開の動画は、プレイリストに決まり文句のタイトルと灰色のサムネイルで残る。
# otoDB（roxy）に登録があれば本当のタイトル・作者・サムネイルを取れるので、そちらに差し替える。
# otoDB のサムネイルは元動画が消えても残るため、音MAD のプレイリストではかなりの確率で埋まる
# ニコニコは「削除された動画」「非公開動画」、YouTube は「[削除された動画]」「[非公開の動画]」
# （英語ロケールだと Deleted video / Private video）、bilibili は「已失效视频」。表記の揺れごと並べる
_GONE_TITLES = ("削除された動画", "非公開動画", "非公開の動画", "この動画は削除されました",
                "deleted video", "private video", "unavailable video", "unavailable",
                "已失效视频", "已失效視頻", "失效视频")
_ROXY_MAX = 24        # 1 つのプレイリストで roxy を呼ぶ上限。1 件ずつ各サイトへ取りに行くので多いと待たされる
_ROXY_TIMEOUT = 12    # 1 件あたり
_ROXY_BUDGET = 25     # 1 つのプレイリストの穴埋め全体。使い切ったら取れた分だけ反映する

# roxy はもともと「人が表計算に 1 件ずつ貼る」ような使われ方を想定した小さなサービスで、
# うちのように公開サイトからまとめて自動で叩くのは例外的な使い方。
# **セマフォはプロセス全体で 1 つ持つ**（リクエストごとに作ると、同時に n 人がプレイリストを貼った
# ときに n 倍の並列で殴ることになる）。利用者が何人いても roxy から見た同時接続はここの数だけ。
_ROXY_SEM = asyncio.Semaphore(max(1, int(os.getenv("ROXY_CONCURRENCY", "3"))))


def is_gone(title: str) -> bool:
    """プレイリストに残った「削除された動画」等の決まり文句か。"""
    return (title or "").strip().strip("[]").casefold() in _GONE_TITLES


async def _fill_from_otodb(out: list[Track], client: httpx.AsyncClient) -> int:
    """消えた動画の枠を otoDB（roxy）で埋める。並び順は変えない。取れなければそのまま残す。"""
    holes = [(i, t.external_url) for i, t in enumerate(out) if t.external_url and is_gone(t.title)]
    if not holes:
        return 0
    filled = 0

    async def one(i: int, ref: str) -> None:
        nonlocal filled
        async with _ROXY_SEM:
            try:
                got = await otodb.roxy_fetch(ref, client=client, timeout=_ROXY_TIMEOUT)
            except (ValueError, httpx.HTTPError, asyncio.TimeoutError):
                return
            # リンク先は元の動画のまま残す（otoDB の作品ページより、貼った本人の意図に近い）
            out[i] = got.model_copy(update={"external_url": ref})
            filled += 1

    try:
        await asyncio.wait_for(asyncio.gather(*(one(i, r) for i, r in holes[:_ROXY_MAX])), timeout=_ROXY_BUDGET)
    except asyncio.TimeoutError:
        pass   # 間に合った分だけ反映されている
    if holes:
        print(f"[playlist] 消えた動画 {len(holes)} 件 → otoDB で {filled} 件を復元")
    return filled


_FETCHERS = {"nicovideo": _nicovideo, "soundcloud": _soundcloud, "bilibili": _bilibili, "spotify": _spotify,
             "bandcamp": _bandcamp, "youtube": _youtube,
             "applemusic": lambda url, client: applemusic.fetch(url, client=client)}


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
        if not out:
            raise ValueError("曲を取れませんでした（非公開か、空のプレイリストの可能性）")
        out = out[:MAX_ITEMS]
        # 削除・非公開で中身が分からない分を otoDB で埋める（client を閉じる前に済ませる）
        await _fill_from_otodb(out, client)
    finally:
        if own:
            await client.aclose()
    return out
