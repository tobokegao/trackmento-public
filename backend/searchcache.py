"""検索結果の控えを R2 にも置く（2026-09-19）。

サーバーで引いた検索結果（VocaDB・otoDB・Discogs・MusicBrainz の引き直しなど）は `cache.sqlite3` に
1 週間覚えているが、**このファイルはデプロイのたびにコンテナごと消える**。最近はほぼ毎日デプロイして
いるので、実際には数時間〜1 日しかもっていなかった。VocaDB は 1 回の検索に数秒〜25 秒かかることがあり、
デプロイ直後に同じ曲を引き直すと、その待ちがそのまま利用者に返っていた。

- 置き場所は `searchcache/<鍵>.json`。**鍵は秘密鍵つきのハッシュ**（HMAC）で、検索語から推測できない。
  R2 は公開ドメインから読めるので、素の sha1 だと「誰かがこの語を検索したか」を当てて確かめられてしまう
- **中身に検索語は入れない**（結果と時刻だけ）。プライバシーポリシーの「検索キーワードは恒常的に記録しない」と
  両立させるため。結果そのものは各サービスの公開情報
- 起動後に `searchcache/` を一覧して索引をメモリに作る（`imgcache/` と同じやり方）。索引に無ければ R2 を
  見に行かないので、外れのたびに R2 へ 1 往復することはない
- 期限は 6 日（`TTL`）。`scripts/r2_prune.py` が 7 日で消すので、それより短くしておく（画像と同じ関係）
- 書き込みは応答の後ろに回す（待たない）。落としても次に引き直すだけ
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from typing import Any

from backend import storage

PREFIX = "searchcache/"
TTL = 6 * 24 * 3600
INDEX_MAX = 200_000          # 1 件 100B ほど。20 万件で 20MB
TASKS_MAX = 32
_INDEX: dict[str, float] = {}   # 鍵 → 書いた時刻
_TASKS: set[asyncio.Task] = set()


def _secret() -> bytes:
    cfg = storage.configured_r2() or {}
    return (os.getenv("SEARCHCACHE_SECRET") or cfg.get("R2_SECRET_ACCESS_KEY") or "local").encode()


def _key(source: str, q: str, artist: str) -> str:
    msg = f"{source}\n{q}\n{artist}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]


def enabled() -> bool:
    return storage.get_storage().is_remote


def get(source: str, q: str, artist: str, ttl: int) -> list[dict[str, Any]] | None:
    """控えがあれば結果（Track の dict の並び）。無い・古い・読めないなら None。**同期**（to_thread で呼ぶ）"""
    k = _key(source, q, artist)
    at = _INDEX.get(k)
    if at is None or time.time() - at > min(ttl, TTL):
        return None
    try:
        raw = storage.get_storage().get(f"{PREFIX}{k}.json")
        doc = json.loads(raw) if raw else None
    except Exception:
        return None
    if not doc or time.time() - float(doc.get("ts") or 0) > min(ttl, TTL):
        _INDEX.pop(k, None)
        return None
    tracks = doc.get("tracks")
    return tracks if isinstance(tracks, list) else None


def _put(source: str, q: str, artist: str, tracks: list[dict[str, Any]]) -> None:
    k = _key(source, q, artist)
    body = json.dumps({"ts": time.time(), "tracks": tracks}, ensure_ascii=False).encode()
    storage.get_storage().put(f"{PREFIX}{k}.json", body, "application/json")
    if len(_INDEX) < INDEX_MAX:
        _INDEX[k] = time.time()


def put_bg(source: str, q: str, artist: str, tracks: list[dict[str, Any]]) -> None:
    """R2 への書き込みを応答の後ろに回す。R2 が不調なときに溜め込まないよう、走っている本数で頭打ち"""
    if not tracks or not enabled() or len(_TASKS) >= TASKS_MAX:
        return

    async def run() -> None:
        try:
            await asyncio.to_thread(_put, source, q, artist, tracks)
        except Exception as e:
            print(f"[error] 検索結果を R2 に置けませんでした: {type(e).__name__}: {e}")

    t = asyncio.create_task(run())
    _TASKS.add(t)
    t.add_done_callback(_TASKS.discard)


def seed() -> int:
    """R2 の searchcache/ を一覧して索引を作る。**同期**（起動後に to_thread で呼ぶ）"""
    if not enabled():
        return 0
    got: dict[str, float] = {}
    for key, _size, modified in storage.get_storage().list_objects(PREFIX):
        name = key[len(PREFIX):].rsplit(".", 1)[0]
        if len(name) == 32 and len(got) < INDEX_MAX:
            got[name] = modified.timestamp()
    _INDEX.update(got)
    return len(got)
