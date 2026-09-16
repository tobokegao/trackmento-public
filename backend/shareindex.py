"""「みんなの並びから探せるようにする」に印を付けた共有だけを集めた索引。

**共有は本来「URL を知っている人だけが見られる」もの**なので、ここに載るのは
共有するときに利用者が自分でチェックを入れたものだけ（既定はオフ）。チェックの無い共有は
1 件も載らないし、載せた後でも 30 日で共有ごと消える。

作りの要点:

- **索引の実体は R2 の `listed/<id>.json`**（1 共有 1 ファイル、数百バイト）。
  `cache.sqlite3` はデプロイのたびにコンテナごと消えるので、覚えておく場所にできない
- **1 ファイルにまとめない**。R2 に追記は無いので、まとめると「読んで足して書き戻す」に
  なり、同時に共有した人の分が消える。1 件 1 ファイルなら書き込みが競合しない
- **起動時に `listed/` を一覧してメモリへ**（`seed`）。`/image-proxy` の索引と同じやり方。
  印を付ける人は一部なので、共有そのもの（1 日数千件）より桁違いに少ない
- 探すのは**メモリの中だけ**。外部の検索エンジンも SQLite も使わない

`scripts/r2_prune.py` は `listed/` を特別扱いしないので、共有本体と同じ 30 日で消える。
"""
from __future__ import annotations

import json
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from . import storage
from .config import share_retention_days

PREFIX = "listed/"
MAX_ENTRIES = 50_000      # メモリの上限（1 件 1KB 見当）。超えたら古いものから落とす
MAX_TRACKS = 120          # 1 件で覚える曲数。256 マスの並びでも索引は太らせない
MAX_TEXT = 80             # 曲名・アーティスト名の 1 つあたりの長さ
SEED_WORKERS = 16         # 起動時の読み込みの並列数

_lock = threading.Lock()
_entries: list[dict] = []          # 新しいものが後ろ
_ids: set[str] = set()
_seeded = False


def _norm(s: str) -> str:
    """突き合わせ用の形。全角・半角と大文字・小文字をそろえ、空白を落とす。
    画面側の `nkey()` ほど厳密でなくてよい（あちらは重複を消すため、こちらは部分一致のため）。"""
    return "".join(unicodedata.normalize("NFKC", s or "").casefold().split())


def _entry(snap: dict) -> dict:
    """共有のスナップショットから、索引に載せるぶんだけ抜き出す。"""
    tracks = []
    for c in (snap.get("cells") or []):
        if not c:
            continue
        tracks.append([(c.get("title") or "")[:MAX_TEXT], (c.get("artist") or "")[:MAX_TEXT]])
        if len(tracks) >= MAX_TRACKS:
            break
    return {
        "id": snap["id"],
        "title": (snap.get("title") or "")[:60],
        "createdAt": snap.get("createdAt") or "",
        "cols": snap.get("cols") or 0,
        "rows": snap.get("rows") or 0,
        "n": sum(1 for c in (snap.get("cells") or []) if c),
        "tracks": tracks,
    }


def _hay(e: dict) -> str:
    """その共有の中の文字をぜんぶつないだもの（部分一致で探す相手）。"""
    return _norm(e["title"] + "".join(t + a for t, a in e["tracks"]))


def _push(e: dict) -> None:
    with _lock:
        if e["id"] in _ids:
            return
        e["_hay"] = _hay(e)
        _entries.append(e)
        _ids.add(e["id"])
        while len(_entries) > MAX_ENTRIES:
            _ids.discard(_entries.pop(0)["id"])


def add(snap: dict) -> None:
    """共有 1 件を索引に載せる（R2 にも小さな控えを置く）。**失敗しても共有そのものは壊さない**。"""
    e = _entry(snap)
    try:
        storage.get_storage().put(PREFIX + e["id"] + ".json",
                                  json.dumps(e, ensure_ascii=False).encode("utf-8"),
                                  "application/json;charset=utf-8")
    except Exception as ex:   # R2 が不調でも共有は成立させる（次の起動で拾えないだけ）
        print(f"[listed] 控えを置けませんでした: {type(ex).__name__}")
    _push(e)


def seed() -> int:
    """起動時に R2 の `listed/` を読んでメモリへ。読めた件数を返す。

    一覧は 1000 件ごとに 1 回（Class A）、本体は 1 件ずつ GET（Class B、1 件 $0.0000004）。
    起動を止めないよう、呼ぶ側は後ろのタスクで回すこと。
    """
    global _seeded
    st = storage.get_storage()
    keys = [k for k, _, _ in st.list_objects(PREFIX) if k.endswith(".json")]

    def read(k: str):
        try:
            b = st.get(k)
            return json.loads(b) if b else None
        except Exception:
            return None

    got = []
    with ThreadPoolExecutor(max_workers=SEED_WORKERS) as pool:
        for e in pool.map(read, keys):
            if isinstance(e, dict) and e.get("id"):
                got.append(e)
    got.sort(key=lambda e: e.get("createdAt") or "")   # 新しいものが後ろ
    for e in got:
        _push(e)
    _seeded = True
    return len(got)


def _alive_after() -> str:
    """これより古い共有はもう消えている（`scripts/r2_prune.py` が保持日数で消す）。

    **長く動いているプロセスでは、索引だけがメモリに残り続ける**。R2 から本体が消えた共有を
    探せてしまうと、開いても「見つかりません」になる。作った日で切って出さないようにする。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=share_retention_days())
    return cutoff.isoformat(timespec="seconds").replace("+00:00", "Z")


def ready() -> bool:
    return _seeded


def count() -> int:
    return len(_entries)


def search(q: str, limit: int = 40) -> list[dict]:
    """空白で区切った語を**すべて**含む共有を、新しい順に返す。

    語ごとに「曲名・アーティスト名・並びの題をつないだ文字列」の部分一致で見る。
    一致した曲は最大 6 つまで添える（どの曲で当たったのか分かるように）。
    """
    terms = [_norm(w) for w in (q or "").split() if _norm(w)]
    if not terms:
        return []
    out = []
    alive = _alive_after()
    with _lock:
        items = list(reversed(_entries))
    for e in items:
        if e["createdAt"] and e["createdAt"] < alive:
            break   # 新しい順に見ているので、ここから先は全部期限切れ
        if not all(t in e["_hay"] for t in terms):
            continue
        hits = [f"{t} — {a}" if a else t for t, a in e["tracks"]
                if all(x in _norm(t + a) for x in terms)][:6]
        out.append({"id": e["id"], "title": e["title"], "n": e["n"],
                    "cols": e["cols"], "rows": e["rows"], "createdAt": e["createdAt"],
                    "hits": hits})
        if len(out) >= limit:
            break
    return out


def remove(sid: str) -> None:
    """載せるのをやめる（今は使っていないが、通報や本人からの申し出で消せるように）。"""
    with _lock:
        if sid in _ids:
            _ids.discard(sid)
            _entries[:] = [e for e in _entries if e["id"] != sid]
    try:
        storage.get_storage().delete(PREFIX + sid + ".json")
    except Exception:
        pass


def newest(limit: int = 12) -> list[dict]:
    """探す前の画面に出す「最近の並び」。題のあるものだけ（無題ばかり並べても選べない）。"""
    with _lock:
        items = list(reversed(_entries))
    out = []
    alive = _alive_after()
    for e in items:
        if e["createdAt"] and e["createdAt"] < alive:
            break
        if not e["title"]:
            continue
        out.append({"id": e["id"], "title": e["title"], "n": e["n"],
                    "cols": e["cols"], "rows": e["rows"], "createdAt": e["createdAt"], "hits": []})
        if len(out) >= limit:
            break
    return out
