"""SQLite キャッシュ（cache.sqlite3）。

- search: ソース別の検索結果（JSON）。同じ検索を繰り返しても API を叩かない
- image:  /image-proxy と render.py が取得した画像バイト列。CDN の再取得を避ける

sqlite3 は同期 API なので、FastAPI からは asyncio.to_thread 経由で呼ぶ。
接続はプロセス内で 1 本を共有し、ロックで直列化する（アクセス量は小さい）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "cache.sqlite3"

SEARCH_TTL = 7 * 24 * 3600        # 検索結果は 1 週間
IMAGE_TTL = 30 * 24 * 3600        # 画像は 30 日
# ソース／ホストごとの期限（各サービスの利用条件と、聞き直しの重さに合わせる）
#   Discogs: API Terms of Use で「6 時間より古い Content を表示しない」「必要以上にキャッシュしない」
#   YouTube: API ポリシーでデータの保持は 30 日まで（サムネイルも同じ扱いにする）
# roxy（otodb.ROXY_CACHE）は 1 日。応答に Cache-Control が無いぶんこちらで覚える。
# 見つからなかった分も空リストで覚えるので、あとで otoDB に登録されたものを拾えるよう長くしすぎない
# VocaDB だけ 14 日と長い（2026-09-21）。外へ聞くと数秒〜25 秒かかり、その待ちがそのまま利用者に返る。
# 点検では R2 の控えに当たったのが 81 回中 9 回（19%）しかなく、6 日では足りていなかった。
# 新しく登録された曲は最大 2 週間出てこないが、VocaDB は新曲より既存曲を引く使われ方が大半
SEARCH_TTL_BY_SOURCE = {"discogs": 6 * 3600, "roxy": 24 * 3600, "vocadb": 14 * 24 * 3600,
                        "nicosearch": 7 * 24 * 3600,   # 転載元の候補（backend/sources/nicosearch.py）
                        "otodb-origin": 7 * 24 * 3600}   # otoDB の作品から引いた転載元（otodb.origin_by_video）
IMAGE_TTL_BY_HOST = {"discogs.com": 6 * 3600, "ytimg.com": 24 * 3600}


def _search_ttl(source: str) -> int:
    return SEARCH_TTL_BY_SOURCE.get(source, SEARCH_TTL)


def _image_ttl(url: str) -> int:
    from urllib.parse import urlparse
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return IMAGE_TTL
    for suffix, ttl in IMAGE_TTL_BY_HOST.items():
        if host == suffix or host.endswith("." + suffix):
            return ttl
    return IMAGE_TTL
IMAGE_MAX_TOTAL = 300 * 1024 * 1024  # 画像テーブルの上限（古いものから削除）

_SCHEMA = """
CREATE TABLE IF NOT EXISTS search (
  key   TEXT PRIMARY KEY,
  body  TEXT NOT NULL,
  ts    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS image (
  url    TEXT PRIMARY KEY,
  ctype  TEXT NOT NULL,
  data   BLOB NOT NULL,
  size   INTEGER NOT NULL,
  ts     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS image_ts ON image(ts);
"""
# R2 に上げた画像のキーを覚える列（後から足す）。ここに値があれば、その URL は R2 から直接配信できる
_MIGRATIONS = ["ALTER TABLE image ADD COLUMN r2key TEXT"]

# R2 に置いた画像を「まだある」とみなす時間。R2 側の掃除（r2_prune.py の --image-cache-hours）より
# 短くしておかないと、消えた後もリダイレクトし続けて 404 になる。
#
# **2026-09-20 に 6 日 → 13 日（掃除も 7 日 → 14 日）**。期限が切れた画像は、現物が R2 にあっても
# 「無い」とみなして配信元から取り直し、同じ鍵に上書きしていた。1 回の取り直しは
# 「配信元から落とす」＋「利用者へ返す」で帯域 2 回ぶん（37KB の画像で 74KB ＝ $0.0000106）に、
# PutObject 1 回（$0.0000045）が乗る。伸ばすとストレージが約 5GB 増えるが $0.015/GB・月なので
# +$0.08/月。**帯域は $0.15/GB（Render Hobby の込みは月 5GB だけ）で 10 倍高い**ので、
# ストレージを帯域と交換する取引になる。実際の効き目は `[img]` の stale で測れる
R2_IMAGE_TTL = 13 * 24 * 3600


def _skey(source: str, q: str, artist: str) -> str:
    return f"{source}|{q.strip().casefold()}|{artist.strip().casefold()}"


class Cache:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # ---- 接続 ----
    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_SCHEMA)
            for sql in _MIGRATIONS:   # 既にある DB に列を足す。二度目は duplicate column で落ちるので握りつぶす
                try:
                    conn.execute(sql)
                except sqlite3.OperationalError:
                    pass
            conn.commit()
            self._conn = conn
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ---- 検索結果 ----
    def get_search(self, source: str, q: str, artist: str) -> list[dict[str, Any]] | None:
        with self._lock:
            row = self._db().execute("SELECT body, ts FROM search WHERE key=?", (_skey(source, q, artist),)).fetchone()
        if not row or time.time() - row[1] > _search_ttl(source):
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def set_search(self, source: str, q: str, artist: str, tracks: list[dict[str, Any]]) -> None:
        body = json.dumps(tracks, ensure_ascii=False)
        with self._lock:
            db = self._db()
            db.execute("INSERT OR REPLACE INTO search(key, body, ts) VALUES (?,?,?)", (_skey(source, q, artist), body, time.time()))
            db.commit()

    # ---- 画像 ----
    def get_image(self, url: str) -> tuple[str, bytes] | None:
        with self._lock:
            db = self._db()
            row = db.execute("SELECT ctype, data, ts FROM image WHERE url=?", (url,)).fetchone()
            if not row:
                return None
            if time.time() - row[2] > _image_ttl(url):
                db.execute("DELETE FROM image WHERE url=?", (url,))
                db.commit()
                return None
            return row[0], bytes(row[1])

    def set_image(self, url: str, ctype: str, data: bytes) -> None:
        with self._lock:
            db = self._db()
            db.execute(
                "INSERT OR REPLACE INTO image(url, ctype, data, size, ts) VALUES (?,?,?,?,?)",
                (url, ctype, sqlite3.Binary(data), len(data), time.time()),
            )
            db.commit()

    def get_image_r2key(self, url: str) -> str | None:
        """この URL の画像を R2 に上げてあればそのキー。無ければ None。

        本体（BLOB）を読まずに済むので、R2 へ寄せた後の通常の経路はこれだけで足りる。
        R2 のライフサイクルで消える前に期限切れにする（R2_IMAGE_TTL）。
        """
        with self._lock:
            db = self._db()
            row = db.execute("SELECT r2key, ts FROM image WHERE url=? AND r2key IS NOT NULL", (url,)).fetchone()
            if not row:
                return None
            age = time.time() - row[1]
            if age > min(_image_ttl(url), R2_IMAGE_TTL):
                return None
            return row[0]

    def mark_image_r2(self, url: str, r2key: str) -> None:
        """既にキャッシュ済みの画像に、R2 へ上げたことを記録する。"""
        with self._lock:
            db = self._db()
            db.execute("UPDATE image SET r2key=? WHERE url=?", (r2key, url))
            db.commit()

    # ---- 保守 ----
    def prune(self) -> dict[str, int]:
        """期限切れを消し、画像テーブルを上限以内に収める。起動時に呼ぶ。"""
        now = time.time()
        with self._lock:
            db = self._db()
            s = db.execute("DELETE FROM search WHERE ts < ?", (now - SEARCH_TTL,)).rowcount
            i = db.execute("DELETE FROM image WHERE ts < ?", (now - IMAGE_TTL,)).rowcount
            total = db.execute("SELECT COALESCE(SUM(size),0) FROM image").fetchone()[0]
            trimmed = 0
            if total > IMAGE_MAX_TOTAL:
                for url, size in db.execute("SELECT url, size FROM image ORDER BY ts ASC"):
                    db.execute("DELETE FROM image WHERE url=?", (url,))
                    total -= size
                    trimmed += 1
                    if total <= IMAGE_MAX_TOTAL:
                        break
            db.commit()
            if s or i or trimmed:
                db.execute("VACUUM")
        return {"search_expired": s, "image_expired": i, "image_trimmed": trimmed}

    def clear(self, kind: str | None = None) -> None:
        with self._lock:
            db = self._db()
            if kind in (None, "search"):
                db.execute("DELETE FROM search")
            if kind in (None, "image"):
                db.execute("DELETE FROM image")
            db.commit()
            db.execute("VACUUM")

    def stats(self) -> dict[str, Any]:
        with self._lock:
            db = self._db()
            searches = db.execute("SELECT COUNT(*) FROM search").fetchone()[0]
            images, size = db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM image").fetchone()
        return {"searches": searches, "images": images, "image_bytes": size, "path": str(self.path)}


cache = Cache()
