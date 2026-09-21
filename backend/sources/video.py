"""YouTube / ニコニコ動画。動画ページの URL からタイトル・投稿者・サムネイルを取る（キー不要）。

- YouTube: https://www.youtube.com/oembed?url=…&format=json → title, author_name。
  サムネイルは動画 ID から i.ytimg.com の maxresdefault → sddefault → hqdefault の順に存在するものを使う
- ニコニコ動画: https://ext.nicovideo.jp/api/getthumbinfo/{sm…} (XML) → title, user_nickname / ch_name, thumbnail_url。
  新しい動画は thumbnail_url + ".L" で大きい画像が取れる（無ければ元のまま）
- bilibili: 公開 API（x/web-interface/view）は Cookie 無しだと 412 で弾かれるので、動画ページの HTML に埋め込まれた
  window.__INITIAL_STATE__（videoData.title / owner.name / pic）を読む。無ければ og:title / og:image / meta[name=author]。
  b23.tv の短縮 URL はリダイレクト先を使う
サムネイルは 16:9 なので、正方形のマスでは中央が切り出される。
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import httpx

from backend import netguard
from backend.logutil import brief

from backend.models import Origin, Track
from backend.sources import vocadb

UA = "trackmento/0.1 (+https://trackmento.com)"
YT_OEMBED = "https://www.youtube.com/oembed"
YT_VIDEOS = "https://www.googleapis.com/youtube/v3/videos"
# **`fields` で絞ること**。`part=snippet` を丸ごと受けると 1 件 5.7KB、絞れば 1.0KB
YT_FIELDS = "items(id,snippet(title,channelTitle,description,publishedAt,thumbnails/medium))"
NICO_THUMBINFO = "https://ext.nicovideo.jp/api/getthumbinfo/"
_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_NICO_ID_RE = re.compile(r"\b((?:sm|nm|so)\d+)\b")
_BILI_ID_RE = re.compile(r"/video/((?:BV[0-9A-Za-z]{10})|(?:av\d+))", re.IGNORECASE)
_BILI_STATE_RE = re.compile(r"window\.__INITIAL_STATE__=(\{.*?\});\(function", re.S)

# bilibili の画像 CDN（hdslb.com）は URL の後ろに @<幅>w_<高さ>h_1c を付けると、その大きさに切って返す。
# 付けないと原寸（実測 1076x608 で 640KB）が返り、書き出しのマス 600px には過剰。600 角なら 50KB（-92%）。
BILI_COVER_SUFFIX = "@600w_600h_1c"   # 600 = render.py / index.html の CELL_PX
BILI_THUMB_SUFFIX = "@320w_320h_1c"
_BILI_SIZE_RE = re.compile(r"@[0-9a-z_]+$")


def bili_sized(url: str, suffix: str = BILI_COVER_SUFFIX) -> str:
    """hdslb.com の画像 URL に大きさの指定を付ける（既に付いていれば置き換える）。"""
    if "hdslb.com" not in url:
        return url
    return _BILI_SIZE_RE.sub("", url) + suffix


# YouTube のサムネイルの名前 → 正方形に切り出したときの実寸（＝短辺）。実測した寸法とバイト数:
#   default 120x90 3.4KB / mqdefault 320x180 12KB / hqdefault 480x360 23KB / sddefault 640x480 32KB
# マスは正方形なので、横幅ではなく短辺で足りるかを見る
_YT_SIZES = (("default", 90), ("mqdefault", 180), ("hqdefault", 360), ("sddefault", 480), ("maxresdefault", 720))
_YT_THUMB_RE = re.compile(r"(/vi/[A-Za-z0-9_-]{11}/)(\w+)(\.jpg)$")
_YT_PX = dict(_YT_SIZES)


def clamp_size(url: str, want_px: int = 600) -> str:
    """動画サムネイルの URL を、欲しい実寸を満たす最小の大きさにする。
    /image-proxy から呼び、大きすぎる指定で保存済みの過去のグリッドにも効かせる。"""
    if "hdslb.com" in url:
        # bilibili は URL の後ろに大きさ指定を付ける（既に付いていればそのまま）
        if _BILI_SIZE_RE.search(url):
            return url
        n = max(1, int(want_px))
        return f"{url}@{n}w_{n}h_1c"
    if "ytimg.com" in url:
        m = _YT_THUMB_RE.search(url)
        if not m:
            return url
        now = _YT_PX.get(m.group(2), 10000)
        name, px = next(((n, p) for n, p in _YT_SIZES if p >= want_px), ("sddefault", 640))
        # 16:9 のサムネイルは正方形に切り出すので、高さが足りるものを選ぶ（横幅の 9/16 が実質の高さ）
        return url if now <= px else url[:m.start()] + f"{m.group(1)}{name}{m.group(3)}"
    return url


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def is_youtube(url: str) -> bool:
    h = _host(url)
    return h in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")


def is_nicovideo(url: str) -> bool:
    h = _host(url)
    return h.endswith("nicovideo.jp") or h == "nico.ms"


def is_bilibili(url: str) -> bool:
    h = _host(url)
    return h.endswith("bilibili.com") or h == "b23.tv"


def _meta(html: str, attr: str, name: str) -> str | None:
    m = re.search(r'<meta[^>]+%s="%s"[^>]+content="([^"]*)"' % (attr, re.escape(name)), html) or \
        re.search(r'<meta[^>]+content="([^"]*)"[^>]+%s="%s"' % (attr, re.escape(name)), html)
    return m.group(1) if m else None


# **bilibili の自動取得はやめた**（2026-09-20）。利用者規約 4.2.11 が「事前の明確な書面許可なしに、
# 自動プログラム・スクリプト等でプラットフォームのサービス・コンテンツ・データを取得すること」を禁じており、
# `api.bilibili.com` の robots.txt も `User-agent: * / Disallow: /` で全面的に塞いでいる。
# 許可を求める窓口も見当たらず、正規のやり方が無い。画像 URL の手入力でマスには入れられる。
# **すでに並びに入っている bilibili の曲はそのまま映る**（画像の URL はグリッドに残っているため）


async def fetch_bilibili(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    raise ValueError("bilibili には対応していません。手入力で、曲名・アーティスト名・画像の URL と、リンク先に動画の URL を入れてください")


def youtube_id(url: str) -> str | None:
    p = urlparse(url)
    h = (p.hostname or "").lower()
    if h == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
    else:
        vid = parse_qs(p.query).get("v", [""])[0]
        if not vid:
            m = re.match(r"^/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})", p.path)
            vid = m.group(1) if m else ""
    return vid if _YT_ID_RE.match(vid or "") else None


def nicovideo_id(url: str) -> str | None:
    m = _NICO_ID_RE.search(urlparse(url).path)
    return m.group(1) if m else None


async def _head_ok(client: httpx.AsyncClient, url: str) -> bool:
    try:
        r = await client.head(url, headers={"User-Agent": UA}, timeout=8, follow_redirects=True)
        return r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
    except httpx.HTTPError:
        return False


# 概要欄で「元の動画」を指す語。**この語が同じ行か 1 つ前の行にあるときだけ**、その行の URL を元とみなす。
# 絞らないと、自分の別の動画への誘導（「Niconico→ …」）まで転載元として拾ってしまう
ORIGIN_MARK = re.compile(
    r"転載|本家|原曲|元動画|元ネタ|再\s*up|re-?up(?:load)?|mirror|reprint|"
    r"source|original|出典|引用元|さんの動画", re.I)
ORIGIN_NICO = re.compile(r"(?:nicovideo\.jp/watch/|nico\.ms/)((?:sm|nm|so)\d+)", re.I)
ORIGIN_YT = re.compile(r"(?:youtu\.be/|youtube\.com/watch\?v=|youtube\.com/shorts/)([A-Za-z0-9_-]{11})", re.I)


def find_origin(desc: str, self_id: str = "") -> tuple[str, str] | None:
    """概要欄から元動画を探す。見つかれば (種類, ID)。

    実測（みんなの並びの YouTube 113 曲、2026-09-21）で**検出 1 件・誤検出 0 件**。
    概要欄にニコニコの URL があるのは 4 件だが、3 件は転載ではなく自分の別動画への誘導で、
    手がかりの語で絞ることで正しく外せている。**転載は珍しいが、当たったときは確実**。
    """
    lines = (desc or "").splitlines()
    for i, line in enumerate(lines):
        near = line + ("\n" + lines[i - 1] if i else "")   # 「ニコニコ動画より転載」の次の行に Source: … がある形
        if not ORIGIN_MARK.search(near):
            continue
        for kind, rx in (("nicovideo", ORIGIN_NICO), ("youtube", ORIGIN_YT)):
            m = rx.search(line)
            if m and m.group(1) != self_id:
                return kind, m.group(1)
    return None


async def _origin_of(client: httpx.AsyncClient, desc: str, self_id: str):
    """概要欄から元動画を見つけ、その投稿者名まで引いて `Origin` にする。見つからなければ None。
    **転載が見つかったときだけ 1 回だけ追加で問い合わせる**（実測で 113 件中 1 件）"""
    got = find_origin(desc, self_id)
    if not got:
        return None
    kind, oid = got
    artist = ""
    try:
        if kind == "nicovideo":
            r = await client.get(NICO_THUMBINFO + oid, headers={"User-Agent": UA})
            if r.status_code == 200:
                root = ElementTree.fromstring(r.text)
                if root.get("status") == "ok":
                    artist = (root.findtext(".//user_nickname") or root.findtext(".//ch_name") or "").strip()
        else:
            snip = await _yt_snippet(client, oid)
            artist = (snip.get("channelTitle") or "").strip() if snip else ""
    except Exception as e:
        print(f"[youtube] 転載元の投稿者が引けませんでした（{kind} {oid}）: {brief(e)}")
    return Origin(kind=kind, id=oid, artist=artist)


async def _yt_snippet(client: httpx.AsyncClient, vid: str) -> dict | None:
    """Data API（`videos.list`）で題・チャンネル名・概要欄を取る。鍵が無い・枠切れなら None。

    **1 unit / 回**で、`id` は 50 件までまとめられる（無料枠は 10,000 units/日）。
    再生リストの取得（`playlist.py` の `playlistItems.list`）と同じ枠を使うので、
    **枠切れ（403）でも落とさず oEmbed に倒す**（再生リストを巻き添えにしない）。
    `fields` で絞らないと 1 件 5.7KB、絞れば 1.0KB（2026-09-21 の実測）。
    """
    from backend.sources.playlist import youtube_key
    key = youtube_key()
    if not key:
        return None
    try:
        r = await client.get(YT_VIDEOS, params={
            "part": "snippet", "id": vid, "fields": YT_FIELDS, "key": key}, headers={"User-Agent": UA})
        if r.status_code != 200:
            print(f"[youtube] videos.list {r.status_code}（oEmbed に倒します）")
            return None
        items = r.json().get("items") or []
        return items[0].get("snippet") if items else None
    except Exception as e:
        print(f"[youtube] videos.list 失敗（oEmbed に倒します）: {brief(e)}")
        return None


async def fetch_youtube(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    vid = youtube_id(url)
    if not vid:
        raise ValueError("YouTube の動画 URL（watch?v=… / youtu.be/…）を貼ってください")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    origin = None
    try:
        # **まず Data API**（概要欄が取れるので、転載元が分かる）。鍵が無ければ oEmbed
        snip = await _yt_snippet(client, vid)
        if snip:
            title, author = (snip.get("title") or "").strip(), (snip.get("channelTitle") or "").strip()
            thumb0 = ((snip.get("thumbnails") or {}).get("medium") or {}).get("url") or ""
            origin = await _origin_of(client, snip.get("description") or "", vid)
        else:
            r = await client.get(YT_OEMBED, params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"}, headers={"User-Agent": UA})
            if r.status_code in (400, 401, 403, 404):  # 存在しない ID は 400 で返る
                raise ValueError("YouTube にその動画がありません（非公開・削除・埋め込み不可の可能性）")
            r.raise_for_status()
            d = r.json()
            title, author = (d.get("title") or "").strip(), (d.get("author_name") or "").strip()
            thumb0 = d.get("thumbnail_url") or ""
        image = thumb0 or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        for name in ("maxresdefault", "sddefault"):
            cand = f"https://i.ytimg.com/vi/{vid}/{name}.jpg"
            if await _head_ok(client, cand):
                image = cand
                break
    finally:
        if own:
            await client.aclose()
    return Track(
        source="youtube",
        title=title or url,
        artist=author,
        album=None,
        image=image,
        thumb=thumb0 or image,
        external_url=f"https://www.youtube.com/watch?v={vid}",
        origin=origin,
    )


async def fetch_nicovideo(url: str, *, client: httpx.AsyncClient | None = None) -> Track:
    vid = nicovideo_id(url)
    if not vid:
        raise ValueError("ニコニコ動画の URL（…/watch/sm12345）を貼ってください")
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True)
    try:
        r = await client.get(NICO_THUMBINFO + vid, headers={"User-Agent": UA})
        r.raise_for_status()
        root = ElementTree.fromstring(r.text)
        if root.get("status") != "ok":
            code = root.findtext(".//code") or "?"
            raise ValueError(f"ニコニコ動画から取れませんでした（{code}: 削除済みか非公開の可能性）")
        thumb = root.findtext(".//thumbnail_url") or ""
        if not thumb:
            raise ValueError("この動画にはサムネイルがありません")
        image = thumb
        if await _head_ok(client, thumb + ".L"):
            image = thumb + ".L"
        artist = (root.findtext(".//user_nickname") or root.findtext(".//ch_name") or "").strip()
        if not artist:
            # 投稿者が退会・非公開だと名前が返らない。VocaDB に登録があれば作者名で埋める（転載なら題から探す）
            artist = await vocadb.artist_for_video(vid, (root.findtext(".//title") or "").strip(), client=client)
    finally:
        if own:
            await client.aclose()
    return Track(
        source="nicovideo",
        title=(root.findtext(".//title") or "").strip() or vid,
        artist=artist,
        album=None,
        image=image,
        thumb=thumb,
        external_url=f"https://www.nicovideo.jp/watch/{vid}",
    )
