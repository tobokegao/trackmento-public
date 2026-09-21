"""ニコニコ動画の**同じ題の古い投稿**を探す（転載の元をたどるため）。

概要欄に何も書いていない転載のための最後の手段。利用者が編集パネルで
「元の投稿を探す」を押したときだけ引く（自動では引かない。100 曲の並びで 100 リクエストになる）。

**転載の向きは 4 通りある**（ニコニコ→YouTube、YouTube→ニコニコ、ニコニコ→ニコニコ、YouTube→YouTube）。
ここで拾えるのは元がニコニコにあるものだけで、**YouTube 内での転載は手がかりがない**
（ニコニコのスナップショット検索に当たる公開 API が YouTube に無く、概要欄も読まないため）。

使うのは公開のスナップショット検索 API。**`_context` にアプリ名を入れる決まり**で、
**1 秒に 1 リクエストまで**が目安（`docs/services-terms.md`）。

並べ替えの鍵は**題の一致度と投稿日**。再生数順のままだと別の動画が 1 位になる
（「物凄い狂っとるフランちゃんが物凄いうた」では「ニコ静ツアー」版が 121 万再生で 1 位だった）。
"""
from __future__ import annotations

import asyncio
import re
import time
from xml.etree import ElementTree

import httpx

from backend.logutil import brief
from backend.merge import _n
from backend.models import Origin
from backend.names import _drop_brackets, trim

SNAPSHOT = "https://snapshot.search.nicovideo.jp/api/v2/snapshot/video/contents/search"
THUMBINFO = "https://ext.nicovideo.jp/api/getthumbinfo/"
CONTEXT = "trackmento"          # API の決まり（アプリ名を入れる）
UA = "trackmento/0.1 (+https://trackmento.com)"
MIN_INTERVAL = 1.0              # 1 秒に 1 リクエストまで（API の目安）
MAX_CANDIDATES = 3              # 投稿者名まで引くのは上位 3 件だけ
MIN_MATCH = 0.5                 # 題の一致度がこれ未満は候補にしない

_last_call = 0.0
_lock = asyncio.Lock()


def match_ratio(a: str, b: str) -> float:
    """題の一致度（0〜1）。正規化して**共通接頭辞の長さ ÷ 長いほうの長さ**。

    前から見るのは、転載が題の頭をそのまま写すことが多いため。後ろは
    「【ななひら】」「【^p^】」のように投稿者ごとの飾りが付いて当てにならない。
    """
    # **刈り込みを通してから比べる**。【ニコカラ】のような分類のタグが頭に付くと、
    # 同じ曲でも共通接頭辞がゼロになる（backend/names.py）
    x, y = _n(trim(a, "")[0]), _n(trim(b, "")[0])
    if not x or not y:
        return 0.0
    n = 0
    for i in range(min(len(x), len(y))):
        if x[i] != y[i]:
            break
        n += 1
    return n / max(len(x), len(y))


async def _wait_turn() -> None:
    """1 秒に 1 リクエストまで空ける（連打への備え）"""
    global _last_call
    async with _lock:
        gap = time.monotonic() - _last_call
        if gap < MIN_INTERVAL:
            await asyncio.sleep(MIN_INTERVAL - gap)
        _last_call = time.monotonic()


async def _uploader(client: httpx.AsyncClient, vid: str) -> str:
    """動画 ID から投稿者名。取れなければ空文字"""
    try:
        r = await client.get(THUMBINFO + vid, headers={"User-Agent": UA})
        if r.status_code != 200:
            return ""
        root = ElementTree.fromstring(r.text)
        if root.get("status") != "ok":
            return ""
        return (root.findtext(".//user_nickname") or root.findtext(".//ch_name") or "").strip()
    except Exception as e:
        print(f"[nicosearch] 投稿者が引けませんでした（{vid}）: {brief(e)}")
        return ""


async def older_posts(title: str, *, before: str = "", self_id: str = "",
                      client: httpx.AsyncClient | None = None) -> list[dict]:
    """同じ題の投稿を、**一致度で絞ってから投稿日の古い順**に返す。

    `before` に ISO の日時を渡すと、それより新しいものは外す（マス自身の動画より新しい
    投稿は「元」ではありえない）。`self_id` はマス自身の動画 ID（結果から外す）。

    返すのは `[{id, title, artist, at, match}]` を最大 `MAX_CANDIDATES` 件。
    **古い順が元とは限らない**（元が消えて再投稿されたもの、権利者が後から上げ直したものがある）ので、
    候補として出すだけで自動では差し替えない。
    """
    # **検索語は刈り込んで括弧も落とした「核」にする**。題そのままだと 0 件になり
    # （【ニコカラ】…（OnVo）【字幕大】で totalCount 0）、刈っただけでも 1 件しか出ない。
    # 核で引けば 65 件出て、そこから一致度で絞るほうが取りこぼしが少ない（2026-09-21 の実測）
    q = _drop_brackets(trim(title, "")[0]).strip()
    if len(_n(q)) < 2:
        return []
    own = client is None
    client = client or httpx.AsyncClient(timeout=20, follow_redirects=True)
    try:
        await _wait_turn()
        r = await client.get(SNAPSHOT, params={
            "q": q, "targets": "title", "fields": "contentId,title,userId,startTime,viewCounter",
            "_sort": "-viewCounter", "_limit": 10, "_context": CONTEXT}, headers={"User-Agent": UA})
        if r.status_code != 200:
            print(f"[nicosearch] {r.status_code}: {r.text[:120]}")
            return []
        data = r.json().get("data") or []
        rows = []
        for d in data:
            cid = d.get("contentId") or ""
            at = d.get("startTime") or ""
            if not cid or cid == self_id:
                continue
            if before and at >= before:      # マス自身より新しいものは「元」ではない
                continue
            m = match_ratio(title, d.get("title") or "")
            if m >= MIN_MATCH:
                rows.append({"id": cid, "title": d.get("title") or "", "at": at, "match": round(m, 3)})
        rows.sort(key=lambda x: x["at"])     # **古い順**（元の投稿がいちばん古い見込み）
        rows = rows[:MAX_CANDIDATES]
        for row in rows:
            row["artist"] = await _uploader(client, row["id"])
        return [r for r in rows if r.get("artist")]
    except Exception as e:
        print(f"[nicosearch] 検索に失敗しました: {brief(e)}")
        return []
    finally:
        if own:
            await client.aclose()


def to_origin(row: dict) -> Origin:
    return Origin(kind="nicovideo", id=row["id"], artist=row.get("artist") or "")
