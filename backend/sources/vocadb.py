"""VocaDB（ボーカロイド楽曲のデータベース）。

- 検索: https://vocadb.net/api/songs?query=…&fields=ThumbUrl,PVs&lang=Japanese
  `artistString` が「ハチ feat. 初音ミク」の形で返るので、作者と歌声合成ソフトがまとめて手に入る。
  iTunes に配信の無いボカロ曲でも引ける
- **並べ替えを指定しないと原曲が上に来ない**。`sort=RatingScore` と `preferAccurateMatches=true` を
  付けると「メルト」で ryo の原曲が 1 位になる（付けないと歌ってみた・REMIX が先に並ぶ。実測）
- ジャケットは `thumbUrl` をそのまま使わない。YouTube のものは `default.jpg`（120x90・4.8KB）で、
  マス（600px）には粗すぎる。**`hqdefault.jpg`（480x360・39KB）へ URL を書き換える**
  （`clamp_size` と同じ考え方で、こちらで縮めたり拡大したりはしない）。
  ニコニコの CDN は素の URL が 130x100 しか無いので `.L`（360x270）を足す。ただし
  **古い動画には大きい版が無い**（実測で 17,000,000 番台までは 404、19,000,000 番台から 200）ので、
  番号で線を引く（`NICO_L_FROM`）

キーは要らない。データは CC ライセンスなので、画面のフッターに出典を出している。
"""
from __future__ import annotations

import re

import httpx

from backend.models import Track

API = "https://vocadb.net/api/songs"
UA = "trackmento/0.1 (+https://trackmento.com)"
PAGE = 30            # 1 回に取る件数の上限（VocaDB 側は 50 まで受けるが、候補パネルに合わせる）
TIMEOUT = 20         # 実測で 1.6〜2.8 秒。iTunes より遅いので、選んだときだけ引く
# 元ページの URL を組み立てられる PV の種類（曲名リストのリンク先に使う）
_WATCH = {"NicoNicoDouga": "https://www.nicovideo.jp/watch/{}",
          "Youtube": "https://www.youtube.com/watch?v={}",
          "Bilibili": "https://www.bilibili.com/video/{}"}


# ニコニコの大きいサムネイル（`.L`）が存在する動画番号の下限。**実測で線を引いた**
# （17,000,000 番台までは 404、19,000,000 番台から 200）。古い動画は素の 130x100 のまま使う
NICO_L_FROM = 19_000_000
_NICO_THUMB = re.compile(r"^https://nicovideo\.cdn\.nimg\.jp/thumbnails/(\d+)/(\d+)$")


def clamp_size(url: str) -> str:
    """サムネイルを大きい版に差し替える。**URL の書き換えだけ**（再エンコードはしない）。

    - YouTube … VocaDB が返すのは `default.jpg`（120x90・4.8KB）で、マス（600px）には粗い。
      `hqdefault.jpg` は 480x360・39KB で、どの動画にも必ずある（`sddefault` は無いことがある）
    - ニコニコ … 素の URL は 130x100。`.L` を足すと 360x270 になる（`NICO_L_FROM` 以降の動画だけ）
    """
    if "i.ytimg.com/vi/" in url:
        return url.replace("/default.jpg", "/hqdefault.jpg")
    m = _NICO_THUMB.match(url)
    if m and m.group(1) == m.group(2) and int(m.group(1)) >= NICO_L_FROM:
        return url + ".L"
    return url


def _links(item: dict) -> str | None:
    """曲名リストのリンク先。PV があればその動画のページ、無ければ VocaDB の曲のページ。"""
    for pv in item.get("pvs") or []:
        tmpl, pv_id = _WATCH.get(pv.get("service") or ""), (pv.get("pvId") or "").strip()
        if tmpl and pv_id:
            return tmpl.format(pv_id)
    return f"https://vocadb.net/S/{item.get('id')}" if item.get("id") else None


async def search(q: str, artist: str = "", *, limit: int = PAGE,
                 client: httpx.AsyncClient | None = None) -> list[Track]:
    """VocaDB を検索する。原曲が上に来るように評価の高い順で引く。"""
    # **query は曲名だけ**（無ければアーティスト名）。「シャルル バルーン」のように 2 つをつなぐと
    # VocaDB は曲名にその全文が含まれるものを探して 0 件になる（artistName パラメータは無視される。実測）。
    # アーティスト名はこちらで絞る（下）。半角の濁点（ﾊﾞ）や単独の濁点（ハ゛）は merge._n が吸収する
    query = q.strip() or artist.strip()
    if not query:
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        r = await client.get(API, params={
            "query": query, "maxResults": max(1, min(limit, PAGE)),
            "nameMatchMode": "Auto", "sort": "RatingScore", "preferAccurateMatches": "true",
            "fields": "ThumbUrl,PVs", "lang": "Japanese",
        }, headers={"User-Agent": UA})
        r.raise_for_status()
        items = (r.json() or {}).get("items") or []
    finally:
        if own:
            await client.aclose()

    out: list[Track] = []
    for it in items:
        title = (it.get("name") or "").strip()
        image = clamp_size((it.get("thumbUrl") or "").strip())
        if not (title and image):
            continue
        out.append(Track(
            source="vocadb",
            title=title,
            # 「ハチ feat. 初音ミク」。feat. の前が作者なので、そのまま出すと曲の並びで読みやすい
            artist=(it.get("artistString") or "").strip(),
            album=None,
            image=image,
            thumb=image,
            external_url=_links(it),
        ))
    if q.strip() and artist.strip():
        # アーティストで絞る。1 件も残らなければ絞らずに返す（表記が違うだけのことがある）
        from backend.merge import _n
        key = _n(artist)
        hit = [t for t in out if key and key in _n(t.artist)]
        out = hit or out
    return out
