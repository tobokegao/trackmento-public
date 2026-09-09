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
        if not row or time.time() - row[1] > SEARCH_TTL:
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
            if time.time() - row[2] > IMAGE_TTL:
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
