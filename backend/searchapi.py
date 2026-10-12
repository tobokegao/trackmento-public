"""曲の検索（`/search`）と、URL・プレイリストからの取り込み（`/from-url` / `/from-playlist`）。

ソースを足すときはここの `SOURCES` に足す（ほかに触る所は `docs/sources.md`）。
2026-10-12に `main.py` から分けた（名前はそのまま）。
"""
from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend import searchcache
from backend.cache import _search_ttl, cache
from backend.config import public_mode
from backend.loadstats import _note_srch
from backend.logutil import brief
from backend.merge import merge
from backend.models import Track
from backend.sources import discogs, fromurl, itunes, musicbrainz, otodb, playlist, vocadb

router = APIRouter()

# 1ソースあたりの検索の上限秒。超えたソースは「失敗」扱いにして他の結果を返す。
# 20秒だったのを12秒に下げた（2026-09-16）。MusicBrainzは1秒1回の制限＋順番待ち（MAX_QUEUE 6）＋
# 503の再試行（1.5 + 3秒）で20秒近くまで伸びることがあり、点検で /searchの最大が20.1秒になっていた。
# MusicBrainzはiTunesで0件のときの予備なので、それ以上待たせるより「見つからない」を返すほうが親切
SOURCE_TIMEOUT = 12
# ソースごとの上限秒（無ければSOURCE_TIMEOUT）。VocaDBは選んだときだけ使うソースで、応答に波がある
# （2026-09-19の実測で0.3〜6.5秒、点検で2時間に7件が12秒の時間切れ。利用者から「タイムアウトする」と報告）。
# 12秒はMusicBrainzの予備検索に合わせた値なので、選んで待っているVocaDBには短い
SOURCE_TIMEOUTS = {"vocadb": 25}
# 時間切れでも取得を捨てないソース。裏で最後まで待ち（`SOURCE_HARD_TIMEOUT` まで）、届いた結果を覚える。
# 以前は時間切れを60秒「失敗」として覚えていたので、言われたとおり再検索すると即座にまた失敗が返っていた。
# 今は再検索が走っている取得にそのまま合流するか、覚えた結果を即返す。
# MusicBrainzは入れない（1秒1回の順番待ちの枠を、誰も待っていない取得で握り続けることになる）
KEEP_ON_TIMEOUT = {"vocadb", "otodb"}
SOURCE_HARD_TIMEOUT = 45
_inflight: dict[tuple[str, str, str], asyncio.Task] = {}   # (ソース, 曲名, アーティスト) → 走っている取得
FAIL_TTL = 60         # 失敗した検索を覚えておく秒数（同じ検索の連打を外部に流さない）
_fail_log: dict[str, list] = {}   # (ソース名 + 理由) → [最後に出した時刻, その後の省略件数]。同じ失敗は60秒に1行


def _log_search_failure(name: str, reason: str) -> None:
    """同じソース・同じ理由の失敗は60秒に1行にまとめる（iTunesの遮断中などは毎秒出て読めなくなる）。"""
    key = f"{name}:{reason}"
    now = time.monotonic()
    ent = _fail_log.get(key)
    if ent and now - ent[0] < 60:
        ent[1] += 1
        return
    extra = f"（ほか{ent[1]}件を省略）" if ent and ent[1] else ""
    _fail_log[key] = [now, 0]
    print(f"[search] {name} failed: {reason}{extra}")
_recent_fail: dict[tuple[str, str, str], tuple[float, str]] = {}   # (source, q, artist) → (時刻, busy|error)

# source省略時はこの順で並べ、重複は先のソースを残す: iTunes > MusicBrainz > Discogs
# （iTunesは速くて安定、MusicBrainzは1秒1回の制限を全員で共有するため混雑しやすい）
SOURCES = {"itunes": itunes.search, "musicbrainz": musicbrainz.search}
if discogs.enabled():
    SOURCES["discogs"] = discogs.search
# **省略時はiTunesだけ**。MusicBrainzは「1秒に1リクエスト」の制限があり、常に一緒に引くと
# 検索が2秒かかる（iTunesだけなら0.2秒。2026-09-15の実測）。見つからなかったときだけ下で引き直す
DEFAULT_SOURCES = ("itunes",)
FALLBACK_SOURCE = "musicbrainz"
SOURCES["otodb"] = otodb.search     # 音MADデータベース。ALLには含めず、明示選択のときだけ
# ボカロのデータベース。**応答が1.6〜2.8秒**とiTunesより遅いので、これも明示選択のときだけ。
# iTunesに配信の無いボカロ曲（とその作者名）が引けるのが利点
SOURCES["vocadb"] = vocadb.search


@router.get("/artist-candidates")
async def artist_candidates(
    title: str = Query("", description="曲名", max_length=300),
    at: str = Query("", description="このマスの動画の投稿日（ISO）。これより新しい投稿は外す", max_length=40),
    self_id: str = Query("", description="このマスの動画ID（結果から外す）", max_length=32),
    url: str = Query("", description="このマスの動画のURL（ニコニコ / YouTube）。otoDBの作品を引く", max_length=300),
) -> dict:
    """**転載の元になった投稿の候補**（ニコニコ動画の同じ題の古い投稿と、otoDBの作品）。

    利用者が編集パネルで「元の投稿を探す」を押したときだけ呼ばれる。**自動では引かない**
    （100曲の並びで100リクエストになる）。ニコニコは古い順に最大3件。
    otoDBは、マスの動画が登録済みの作品なら作者（Creatorのタグ）と、作品に登録されたほかの投稿（2026-09-21）。

    結果は覚えておく（`cache` の `nicosearch` / `otodb-origin`、7日）。**検索語は鍵にしない**
    （`searchcache.py` と同じ決まり。プライバシーポリシーの「検索キーワードは恒常的に記録しない」）。
    otoDBの鍵は動画のURL（公開の動画を指すだけで、利用者の入れた語ではない）。
    """
    from backend.sources import nicosearch, otodb

    async def nico() -> tuple[list, bool]:
        key = f"{title}|{at}|{self_id}"
        hit = cache.get_search("nicosearch", key, "")
        if hit is not None:
            return hit, True
        rows = await nicosearch.older_posts(title, before=at, self_id=self_id)
        cache.set_search("nicosearch", key, "", rows)
        return rows, False

    (rows, cached), work = await asyncio.gather(nico(), otodb.origin_by_video(url))
    return {"candidates": rows, "otodb": work if work and work.get("artist") else None, "cached": cached}


@router.get("/search")
async def search(
    request: Request,
    q: str = Query("", description="曲名", max_length=200),
    artist: str = Query("", description="アーティスト名", max_length=200),
    source: str | None = Query(None, description="itunes|musicbrainz|discogs|otodb|vocadb。省略時はiTunesだけ（otodb・vocadbは含まない）"),
    nocache: bool = Query(False, description="trueでキャッシュを使わず取り直す（公開モードでは無視）"),
    lang: str = Query("ja", pattern="^(ja|en)$", description="enでiTunesの曲名・アーティスト名を米国のストアの表記にする"),
) -> JSONResponse:
    if public_mode():
        nocache = False
    if not (q.strip() or artist.strip()):
        raise HTTPException(400, "qまたはartistを指定してください")
    if source:
        names = [s for s in source.split(",") if s]
        unknown = [s for s in names if s not in SOURCES]
        if unknown:
            raise HTTPException(400, f"未知のソース: {unknown}")
    else:
        names = list(DEFAULT_SOURCES)

    results, failed = await search_sources(names, q, artist, request.app.state.http, nocache=nocache)
    out: list[Track] = []
    for res in results:
        out.extend(res)
    # ソースの指定が無くて1件も出なければMusicBrainzでも引く（iTunesに無い音源の取りこぼしを埋める）。
    # **指定があるときは足さない**（利用者が選んだ通りに返す）
    if not out and not source and not failed:
        names = [FALLBACK_SOURCE]
        results, failed = await search_sources(names, q, artist, request.app.state.http, nocache=nocache)
        for res in results:
            out.extend(res)
    if lang == "en":
        # 英語の画面ではiTunesの表記を米国のストアのものに（まとめる前に差し替え、重複の判定も英語表記で行う）
        out = await itunes.to_english(out, client=request.app.state.http)
    tracks = merge(out) if len(names) > 1 else out
    headers = {}
    if failed:
        # 失敗したソースをフロントに知らせる（ヘッダはASCIIのみ）。例: "musicbrainz=busy,itunes=error"
        headers["X-Search-Failed"] = ",".join(f"{n}={k}" for n, k in failed.items())
    return JSONResponse([t.model_dump() for t in tracks], headers=headers)


async def search_sources(names: list[str], q: str, artist: str, client: httpx.AsyncClient, *, nocache: bool = False) -> tuple[list[list[Track]], dict[str, str]]:
    """ソースごとにキャッシュを引き、無いものだけ並列で取りに行く。失敗したソースは空扱いにし、名前と理由（busy/error）を返す。"""
    failed: dict[str, str] = {}
    results: list[list[Track] | None] = [None] * len(names)
    now = time.monotonic()
    # 外へ聞く語（VocaDBは曲名だけ・表記の揺れをそろえたもの。下の `_narrow` で手元で絞る）
    keys = [_source_key(name, q, artist) for name in names]
    if not nocache:
        for i, name in enumerate(names):
            kq, ka = keys[i]
            hit = await asyncio.to_thread(cache.get_search, name, kq, ka)
            from_r2 = False
            if hit is None:
                # SQLiteはデプロイのたびに消えるので、R2の控えも見る（索引に無ければR2へは行かない）
                hit = await asyncio.to_thread(searchcache.get, name, kq, ka, _search_ttl(name))
                if hit is not None:
                    from_r2 = True
                    await asyncio.to_thread(cache.set_search, name, kq, ka, hit)
            if hit is not None:
                results[i] = _narrow(name, [Track.model_validate(t) for t in hit], q, artist)
                _note_srch(name, 1 if from_r2 else 0)
                continue
            # 直前に失敗した同じ検索は外部に聞き直さない（同じ検索の連打でiTunes / MusicBrainzを叩き続けないため）
            recent = _recent_fail.get((name, kq, ka))
            if recent and now - recent[0] < FAIL_TTL:
                results[i] = []
                failed[name] = recent[1]
                _note_srch(name, 3)
    misses = [i for i, r in enumerate(results) if r is None]
    if misses:
        async def timed(i: int) -> tuple[float, list[Track]]:
            t0 = time.monotonic()
            try:
                got = await _fetch_source(names[i], *keys[i], client)
                return time.monotonic() - t0, got
            except Exception as e:
                e.elapsed = time.monotonic() - t0   # 失敗までの時間も分布に入れる（時間切れはここで25秒などになる）
                raise
        fetched = await asyncio.gather(*(timed(i) for i in misses), return_exceptions=True)
        for i, res in zip(misses, fetched):
            if isinstance(res, BaseException):
                _note_srch(names[i], 3, getattr(res, "elapsed", 0.0))
            else:
                dt, res = res
                _note_srch(names[i], 2, dt)
            if isinstance(res, BaseException):
                # 1ソースの失敗で全体を落とさない。失敗は永続キャッシュには入れず、FAIL_TTL秒だけ覚える
                _log_search_failure(names[i], brief(res))
                results[i] = []
                failed[names[i]] = "busy" if isinstance(res, (musicbrainz.SourceBusy, itunes.SourceBlocked, asyncio.TimeoutError)) or "503" in str(res) else "error"
                if isinstance(res, asyncio.TimeoutError) and names[i] in KEEP_ON_TIMEOUT:
                    continue   # 取得は裏で続いている。再検索はそこへ合流するので、失敗として覚えない
                _recent_fail[(names[i], *keys[i])] = (now, failed[names[i]])
                if len(_recent_fail) > 500:
                    for k in [k for k, v in _recent_fail.items() if now - v[0] >= FAIL_TTL]:
                        del _recent_fail[k]
                continue
            results[i] = _narrow(names[i], res, q, artist)
            if res and names[i] not in KEEP_ON_TIMEOUT:  # 空は保存しない（後からデータが増えたときや一時的な失敗で0件が固定されないように）
                dumped = [t.model_dump() for t in res]
                await asyncio.to_thread(cache.set_search, names[i], *keys[i], dumped)
                searchcache.put_bg(names[i], *keys[i], dumped)
    return [r or [] for r in results], failed


# ---- 外へ聞く語と、手元での絞り込み（2026-09-20）----
# VocaDBは曲名だけで引き、アーティストでの絞り込みは手元で行う（`vocadb.query_key` / `narrow`）。
# **控えの鍵もその語にする**ので、「メルトryo」と「メルトsupercell」、「ｼｬﾙﾙ」と「シャルル」は
# VocaDBへ1回しか聞かない。ほかのソースは今までどおり（曲名とアーティストをそのまま渡す）


def _source_key(name: str, q: str, artist: str) -> tuple[str, str]:
    """そのソースに渡す（曲名, アーティスト名）。控えとキャッシュの鍵にもこれを使う"""
    return (vocadb.query_key(q, artist), "") if name == "vocadb" else (q, artist)


def _narrow(name: str, tracks: list[Track], q: str, artist: str) -> list[Track]:
    """曲名だけで引いたソースの結果を、手元でアーティスト名で絞る"""
    return vocadb.narrow(tracks, q, artist) if name == "vocadb" else tracks


async def _fetch_source(name: str, q: str, artist: str, client: httpx.AsyncClient) -> list[Track]:
    """1ソースを取りに行く。`KEEP_ON_TIMEOUT` のソースは時間切れでも取得を止めず、
    同じ検索が走っていればそこへ合流する（同時に同じ語で検索されても外部へは1回）。"""
    limit = SOURCE_TIMEOUTS.get(name, SOURCE_TIMEOUT)
    if name not in KEEP_ON_TIMEOUT:
        return await asyncio.wait_for(SOURCES[name](q, artist, client=client), timeout=limit)
    key = (name, q, artist)
    task = _inflight.get(key)
    if task is None:
        async def run() -> list[Track]:
            try:
                res = await asyncio.wait_for(SOURCES[name](q, artist, client=client), timeout=SOURCE_HARD_TIMEOUT)
                if res:  # 空は保存しない（上と同じ理由）
                    dumped = [t.model_dump() for t in res]
                    await asyncio.to_thread(cache.set_search, name, q, artist, dumped)
                    searchcache.put_bg(name, q, artist, dumped)
                return res
            finally:
                _inflight.pop(key, None)
        task = asyncio.create_task(run())
        # 誰も待っていないまま失敗したときの「Task exception was never retrieved」を出さない
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        _inflight[key] = task
    # 時間切れで打ち切るのは「この応答が待つこと」だけで、取得そのものは続ける。
    # **`asyncio.shield` は使わない**。待つ側が先に諦めたあとで取得が失敗すると、shieldが
    # 「exception in shielded future」とTracebackをログに出し、点検のエラー行に数えられていた（2026-09-19）
    done, _ = await asyncio.wait({task}, timeout=limit)
    if not done:
        raise asyncio.TimeoutError
    return task.result()


class BandcampBody(BaseModel):
    url: str = Field(max_length=2048)


@router.post("/from-playlist", response_model=list[Track])
async def from_playlist(request: Request, body: BandcampBody) -> list[Track]:
    """プレイリスト（まとめ）のURLから複数曲を取る。ニコニコのマイリスト、SoundCloudのセット、
    bilibiliの収藏夹、Spotifyのプレイリストなど。単体のURLは /from-urlのまま。"""
    url = body.url.strip()
    if not playlist.is_playlist(url):
        raise HTTPException(400, "プレイリストのURLではありません")
    try:
        return await playlist.fetch(url, client=request.app.state.http)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except httpx.HTTPStatusError as e:
        print(f"[playlist] {playlist.label(url)} {e.response.status_code}")
        raise HTTPException(502, f"{playlist.label(url)}から取れませんでした。少し待ってからもう一度お試しください") from e
    except httpx.HTTPError as e:
        print(f"[playlist] {playlist.label(url)} {e!r}")
        raise HTTPException(502, f"{playlist.label(url)}につながりませんでした。少し待ってからもう一度お試しください") from e


@router.post("/from-url", response_model=Track)
@router.post("/bandcamp", response_model=Track)   # 旧名。互換のため残す
async def from_url(request: Request, body: BandcampBody) -> Track:
    """Bandcamp / SoundCloud / YouTube / ニコニコ動画 / bilibili / SpotifyのURLからジャケット（サムネイル）・曲名・アーティストを取る。"""
    url = body.url.strip()
    label, _ = fromurl.resolve(url)
    try:
        return await fromurl.fetch(url, client=request.app.state.http)   # 直接取れなければroxyにフォールバックする
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except httpx.HTTPStatusError as e:
        print(f"[from-url] {label} {e.response.status_code}")
        raise HTTPException(502, f"{label}から取れませんでした。少し待ってからもう一度お試しください") from e
    except httpx.HTTPError as e:
        print(f"[from-url] {label} {e!r}")
        raise HTTPException(502, f"{label}につながりませんでした。少し待ってからもう一度お試しください") from e
