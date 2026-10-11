"""「みんなの並びから探せるようにする」に印を付けた共有だけを集めた索引。

**共有は本来「URLを知っている人だけが見られる」もの**なので、ここに載るのは
共有するときに利用者が自分でチェックを入れたものだけ（既定はオフ）。チェックの無い共有は
1件も載らないし、載せた後でも30日で共有ごと消える。

作りの要点:

- **索引の実体はR2の `listed/<id>.json`**（1共有1ファイル、数百バイト）。
  `cache.sqlite3` はデプロイのたびにコンテナごと消えるので、覚えておく場所にできない
- **1ファイルにまとめない**。R2に追記は無いので、まとめると「読んで足して書き戻す」に
  なり、同時に共有した人の分が消える。1件1ファイルなら書き込みが競合しない
- **起動時に `listed/` を一覧してメモリへ**（`seed`）。`/image-proxy` の索引と同じやり方。
  印を付ける人は一部なので、共有そのもの（1日数千件）より桁違いに少ない
- 探すのは**メモリの中だけ**。外部の検索エンジンもSQLiteも使わない

`scripts/r2_prune.py` は `listed/` を特別扱いしないので、共有本体と同じ30日で消える。
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from . import storage
from .config import share_retention_days
from .merge import _n
from .names import trim

PREFIX = "listed/"
MAX_ENTRIES = 50_000      # メモリの上限（1件1KB見当）。超えたら古いものから落とす
MAX_TRACKS = 120          # 1件で覚える曲数。256マスの並びでも索引は太らせない
MAX_TEXT = 80             # 曲名・アーティスト名の1つあたりの長さ
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


# 「よく選ばれている曲」で、客演の書き方の違いを同じ曲にそろえる（「Tell Your World (feat. 初音ミク)」と「Tell Your World」、
# 「livetune feat. 初音ミク」と「livetune」）。数える鍵だけに使い、表示する名前はそのまま
_FEAT_T = re.compile(r"\s*[(\[（［]\s*(?:feat\.?|ft\.?|featuring)\s[^)\]）］]*[)\]）］]", re.I)
_FEAT_A = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s.*$", re.I)
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")


def _keys(e: dict) -> list[tuple[str, str, str, str]]:
    """「よく選ばれている曲」で数える形（曲名の鍵・アーティスト名の鍵・表示する曲名・アーティスト名）。
    同じグリッドの重複は1つに。刈り込みは正規表現が多くて重いので、載せるときに1回だけ通す（`popular` は数えるだけ）"""
    out, seen = [], set()
    for title, artist in e["tracks"]:
        t, a = trim(title, artist)
        nt, na = _n(_FEAT_T.sub("", t)) or _n(t), _n(_FEAT_A.sub("", a)) or _n(a)
        if not nt or (nt, na) in seen:
            continue
        seen.add((nt, na))
        out.append((nt, na, t, a))
    return out


def _artist_alias(items: list[dict]) -> dict[str, str]:
    """同じ人のアーティスト名の書き方違い（「米津玄師」と「Kenshi Yonezu」）を1つにそろえる表。

    出どころ（iTunesの日本と米国のストア、YouTubeなど）で名前の書き方が変わるので、載る並びの中から見つける（2026-10-11、利用者の求め）:
    - **同じ曲名が2曲以上**、2つの名前のどちらにもある → 同じ人
    - 曲名に**日本語（かな・漢字）**があり、一方の名前は日本語、もう一方はラテン文字だけ → 同じ人
      （「感電」が「米津玄師」と「Kenshi Yonezu」の両方にある。英語の曲名は「Lemon」のようにほかの人と重なりやすいので、これだけでは見ない）
    歌ってみたの歌い手が元の人とまとまることがあるが、数えるのは「同じ曲」なので害は小さいと見た
    """
    by_title: dict[str, set[str]] = {}
    for e in items:
        for nt, na, _, _ in e["_keys"]:
            if na:
                by_title.setdefault(nt, set()).add(na)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    pairs: Counter[tuple[str, str]] = Counter()
    for nt, arts in by_title.items():
        if len(arts) < 2 or len(arts) > 8:   # 「Lemon」のようにいろんな人が使う曲名は手がかりにしない
            continue
        jp_title = bool(_CJK.search(nt))
        ss = sorted(arts)
        for i, a in enumerate(ss):
            for b in ss[i + 1:]:
                pairs[(a, b)] += 1
                if jp_title and bool(_CJK.search(a)) != bool(_CJK.search(b)):
                    union(a, b)
    for (a, b), c in pairs.items():
        if c >= 2:
            union(a, b)
    return {a: find(a) for a in parent}


def _push(e: dict) -> None:
    e["_keys"] = _keys(e)   # ロックの外で（刈り込みが重いため）
    with _lock:
        if e["id"] in _ids:
            return
        e["_hay"] = _hay(e)
        _entries.append(e)
        _ids.add(e["id"])
        while len(_entries) > MAX_ENTRIES:
            _ids.discard(_entries.pop(0)["id"])


def forget(sid: str) -> None:
    """消えた共有を索引から外す。**期限より前に消したもの**（`scripts/delete_share.py`）は
    `_alive_after` の日付では外れないので、共有ページが410を返したときに呼ぶ"""
    with _lock:
        if sid not in _ids:
            return
        _ids.discard(sid)
        _entries[:] = [e for e in _entries if e["id"] != sid]
    global _tally_memo
    _tally_memo = None   # 外した並びの曲を「よく選ばれている曲」に数えたままにしない


def add(snap: dict) -> None:
    """共有1件を索引に載せる（R2にも小さな控えを置く）。**失敗しても共有そのものは壊さない**。"""
    e = _entry(snap)
    try:
        storage.get_storage().put(PREFIX + e["id"] + ".json",
                                  json.dumps(e, ensure_ascii=False).encode("utf-8"),
                                  "application/json;charset=utf-8")
    except Exception as ex:   # R2が不調でも共有は成立させる（次の起動で拾えないだけ）
        print(f"[listed] 控えを置けませんでした: {type(ex).__name__}")
    _push(e)


def seed() -> int:
    """起動時にR2の `listed/` を読んでメモリへ。読めた件数を返す。

    一覧は1000件ごとに1回（Class A）、本体は1件ずつGET（Class B、1件 $0.0000004）。
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
    global _tally_memo
    _tally_memo = None   # 読み込み前に数えた空の結果を覚えたままにしない（10-11の本番で20曲が出なかった）
    return len(got)


def _alive_after() -> str:
    """これより古い共有はもう消えている（`scripts/r2_prune.py` が保持日数で消す）。

    **長く動いているプロセスでは、索引だけがメモリに残り続ける**。R2から本体が消えた共有を
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
    一致した曲は最大6つまで添える（どの曲で当たったのか分かるように）。
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


def _row(e: dict) -> dict:
    return {"id": e["id"], "title": e["title"], "n": e["n"],
            "cols": e["cols"], "rows": e["rows"], "createdAt": e["createdAt"], "hits": []}


# 「私を構成する9曲」の形の題。載る並びの大半がこれなので、「いろんな切り口」からは外す
# （「作曲してる曲の構成」のように「構成」だけのものは外さない）
_COMMON_TITLE = re.compile(r"構成(する|した|して)|make(s)? me|made me", re.I)


def _theme_key(title: str) -> str:
    """「いろんな切り口」で同じ題かを比べる形。数字と記号を落とす（「好きな音MAD9選」と「好きな音MAD10選」は同じ題）。"""
    return re.sub(r"[\d\W_]+", "", _norm(title))


def _same_theme(a: str, b: str) -> bool:
    """言い回しが違うだけの同じ題か。**いちばん長い共通の部分が、短いほうの6割以上**なら同じと見る。

    ぴったり同じ文字列だけをまとめていたとき、「好きな音MAD9選」「我的音mad9選」「9個の音MAD」が
    8件のうち3件を占めた（2026-09-24、本番の点検）。共通の「音mad」は短いほう（個の音mad）の6割を超える。
    6割にしたのは「好きな曲（VTuber）」と「好きな曲（アニメ）」を別の題に残すため（共通の「好きな曲」は4/7）。
    """
    if a == b:
        return True
    n = min(len(a), len(b))
    if n == 0:
        return False
    m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size >= 2 and m.size >= 0.6 * n


def varied(limit: int = 8) -> list[dict]:
    """探す前の画面の上に出す「いろんな切り口」。**想定外の使い方を目立たせる**（2026-09-24、open-use ⑤）。

    載る並びの大半は「私を構成する9曲」で、新しい順に並べるだけだと、ほかのテーマの並びが埋もれる。
    題のあるもののうち「構成する」の形を外し、同じ題（言い回しだけ違うものも。`_same_theme`）は新しい1件にまとめる。
    運営が手で選ぶことはしない（選ぶ手間が毎回かかる。2026-09-24に利用者が自動を選んだ）。
    """
    with _lock:
        items = list(reversed(_entries))
    out, seen = [], []
    alive = _alive_after()
    for e in items:
        if e["createdAt"] and e["createdAt"] < alive:
            break
        if not e["title"] or _COMMON_TITLE.search(e["title"]):
            continue
        key = _theme_key(e["title"])
        if any(_same_theme(key, k) for k in seen):
            continue
        seen.append(key)
        out.append(_row(e))
        if len(out) >= limit:
            break
    return out


POPULAR_TTL = 600         # 「よく選ばれている曲」を数え直す間隔（秒）
POPULAR_MIN = 2           # 1つのグリッドにしか無い曲は出さない（どれも1件だと順位にならない）
POPULAR_SAME = 3          # これだけの曲が重なり、かつ小さいほうの半分以上なら同じ人の並びと見る
RARE_PER_GROUP = 2        # 「ひとりだけが選んだ曲」で、1人の並びから出す曲数の上限（1人の25曲で20曲が埋まらないように）
_tally_memo: tuple[float, dict] | None = None


def _tally() -> dict:
    """載る並びの曲を数えた結果。「よく選ばれている曲」と「ひとりだけが選んだ曲」が共有する。
    全件をなめるので、`POPULAR_TTL` のあいだは前の結果を返す（2026-10-11）。

    - 曲の見分けは刈り込み（`names.trim`）をしてから `merge._n` でそろえた曲名とアーティスト名（`_keys`）。
      客演の書き方（feat.）は落とし、アーティスト名の書き方違いはそろえる（`_artist_alias`）
    - **曲が大きく重なる並びは1つにまとめて数える**。手直ししながら同じ並びを載せ直す人がいて、
      1人の「私を構成する25曲」の約25回分で上位20曲が埋まった（2026-10-11、本番）。重なりが
      `POPULAR_SAME` 曲以上かつ小さいほうの半分以上なら同じ人の並びと見て、曲はまとまりごとに1と数える
    """
    global _tally_memo
    now = time.monotonic()
    memo = _tally_memo
    if memo and now - memo[0] < POPULAR_TTL:
        return memo[1]
    with _lock:
        items = list(_entries)
    alive = _alive_after()
    items = [e for e in items if not (e["createdAt"] and e["createdAt"] < alive)]
    alias = _artist_alias(items)
    groups: list[set[str]] = []
    gnew: list[str] = []                  # まとまりごとの、いちばん新しい載せた日
    where: dict[str, list[int]] = {}      # 曲 → それを含むまとまり
    names: dict[str, Counter[tuple[str, str]]] = {}
    kart: dict[str, str] = {}             # 曲 → そろえたアーティスト名
    for e in items:
        ks = set()
        for nt, na, t, a in e["_keys"]:
            na = alias.get(na, na)
            k = nt + "|" + na
            ks.add(k)
            kart[k] = na
            names.setdefault(k, Counter())[(t, a)] += 1
        shared = Counter(g for k in ks for g in where.get(k, ()))
        gid = next((g for g, c in shared.most_common()
                    if c >= POPULAR_SAME and c * 2 >= min(len(ks), len(groups[g]))), None)
        if gid is None:
            gid = len(groups)
            groups.append(set())
            gnew.append("")
        gnew[gid] = max(gnew[gid], e["createdAt"] or "")
        for k in ks - groups[gid]:
            groups[gid].add(k)
            where.setdefault(k, []).append(gid)
    art: Counter[str] = Counter()         # アーティスト → それを選んだまとまりの数
    for g in groups:
        for na in {kart[k] for k in g if kart[k]}:
            art[na] += 1
    out = {"count": Counter(k for g in groups for k in g), "names": names,
           "where": where, "gnew": gnew, "kart": kart, "art": art}
    if _seeded:   # 読み込みの途中は覚えない
        _tally_memo = (now, out)
    return out


def popular(limit: int = 20) -> list[dict]:
    """探す前の画面に出す「よく選ばれている曲」。載る並びのうち、**入っているグリッドの数**が多い順。

    数えるのはみんなのグリッドに載せたもの（opt-in）だけで、保持日数より古いものは数えない
    （共有と一緒に消えるので、自然に「最近30日」の集計になる）。1つのグリッドに同じ曲が2つあっても1と数える。
    表示する名前は、同じ曲のなかでいちばん多く使われていた書き方にする。
    """
    tl = _tally()
    out = []
    for k, n in tl["count"].most_common():
        if n < POPULAR_MIN or len(out) >= limit:
            break
        t, a = tl["names"][k].most_common(1)[0][0]
        out.append({"title": t, "artist": a, "n": n})
    return out


def rare(limit: int = 20) -> list[dict]:
    """探す前の画面に出す「ひとりだけが選んだ曲」（2026-10-11、利用者の求め）。順位は付けない。

    **1まとまり（＝1人）の並びにしか入っていない曲**のうち、そのアーティストの曲をほかの誰も
    選んでいないものを先に、同じ段なら新しく載ったものを先に出す。1人の並びからは `RARE_PER_GROUP` 曲まで
    （1人の25曲で20曲が埋まらないように）。アーティスト名の無い曲は、アーティストでは測れないので
    「誰も選んでいない」側に数える。
    """
    tl = _tally()
    ks = [k for k, n in tl["count"].items() if n == 1]
    ks.sort(key=lambda k: tl["gnew"][tl["where"][k][0]], reverse=True)
    ks.sort(key=lambda k: tl["art"][tl["kart"][k]] if tl["kart"][k] else 1)   # 並べ替えは安定なので、同じ段は新しい順のまま
    out, per = [], Counter()
    for k in ks:
        gid = tl["where"][k][0]
        if per[gid] >= RARE_PER_GROUP:
            continue
        per[gid] += 1
        t, a = tl["names"][k].most_common(1)[0][0]
        out.append({"title": t, "artist": a})
        if len(out) >= limit:
            break
    return out


def newest(limit: int = 12, skip: set[str] | frozenset[str] = frozenset()) -> list[dict]:
    """探す前の画面に出す「最近の並び」。題のあるものだけ（無題ばかり並べても選べない）。

    `skip` は「いろんな切り口」に出したもの。同じ並びを2つの節に続けて出さない。
    """
    with _lock:
        items = list(reversed(_entries))
    out = []
    alive = _alive_after()
    for e in items:
        if e["createdAt"] and e["createdAt"] < alive:
            break
        if not e["title"] or e["id"] in skip:
            continue
        out.append(_row(e))
        if len(out) >= limit:
            break
    return out
