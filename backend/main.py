"""FastAPIエントリポイント。起動: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
import re
import secrets
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
import time
from datetime import datetime, timezone
from collections import Counter, defaultdict, deque

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import articles, grids, housekeeping, pages, render, searchcache, share, shareindex, storage, support, uploads
from backend.cache import cache
from backend.config import (app_url_for, base_url_for, cors_origins, frontend_url, max_cells, migrate_to, public_base_url, public_mode,
                            rate_limit_per_minute, share_budget_bytes, share_limits, share_retention_days, trust_proxy)
from backend.grids import GridDoc, GridOptions
from backend.gziptext import GZipText
from backend.loadstats import (CLIENT_KINDS, LAT_BUCKETS, _5XX_TOP, _STATS_TOP, _UA_KINDS, _5xx_stats, _client_stats, _lat_bucket,
                               _note_out, _note_src, _note_upload, _out_line, _ref_stats, _rss_mb, _src_stats, _srch_stats, _stat_key,
                               _stats, _stats_field, _ua_kind, _ua_stats, _upload_line)
from backend.sources import itunes, vocadb

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OUTPUTS = ROOT / "outputs"
GRIDS = ROOT / "grids"
FRONTEND = ROOT / "frontend"
FONTS = ROOT / "fonts"

# **.envを読んでから読み込む**。どちらも読み込んだときに環境変数を見る（IMAGE_* の上限、Discogsのトークンなど）
from backend import imageproxy, searchapi  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    OUTPUTS.mkdir(exist_ok=True)
    GRIDS.mkdir(exist_ok=True)
    uploads.UPLOADS.mkdir(exist_ok=True)
    share.SHARES.mkdir(exist_ok=True)
    if public_mode():
        cleaned = housekeeping.run_all()
        if any(cleaned.values()):
            print(f"[housekeeping] {cleaned}")
        print(f"[public] 公開モード: CORS={cors_origins()} FRONTEND_URL={frontend_url() or '(このサーバー)'} RATE_LIMIT={rate_limit_per_minute()}/min")
    st = storage.get_storage()
    print(f"[storage] 共有の保存先: {st.name}" + (f"（公開URL: {st.public_url('') or '無し → バックエンドが中継'}）" if st.is_remote else ""))
    pruned = await asyncio.to_thread(cache.prune)
    if any(pruned.values()):
        print(f"[cache] pruned {pruned}")
    removed = render.prune_outputs()
    if removed:
        print(f"[outputs] removed {removed} old files")
    print(f"[public] PNGのURLは{public_base_url()}/outputs/... で返します（.envのPUBLIC_BASE_URL）")
    app.state.started_at = time.time()
    global _app_shell
    try:
        _app_shell = _check_app_shell()   # 切り出したCSS / JSがR2に載っていれば殻を配る
    except Exception as e:
        print(f"[app] 殻を確かめられませんでした（1枚のまま配ります）: {type(e).__name__}: {e}")
        _app_shell = None
    monitor = asyncio.create_task(_load_monitor()) if public_mode() else None
    # **全体の上限を使っているときだけ数える**（2026-09-21）。`count_today()` はバケットを1周するので
    # 起動あたりClass A 214回かかるが、`SHARE_LIMIT_PER_DAY` が0（＝無制限）だと復元した数を読む分岐
    # （`_share()` の `if per_day and …`）が成立せず、ログ1行のためだけに払っていた。
    # 共有の件数は毎日の掃除が `metrics/r2.jsonl` に残すので、運用ボードはそちらから出す
    seed = asyncio.create_task(_seed_share_count()) if public_mode() and st.is_remote and share_limits()[1] else None
    imgidx = asyncio.create_task(imageproxy._seed_r2_index()) if st.is_remote else None
    listed = asyncio.create_task(_seed_listed_index())
    srchidx = asyncio.create_task(_seed_search_index()) if st.is_remote else None
    usage = asyncio.create_task(imageproxy._usage_loop()) if (public_mode() or st.is_remote) else None
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=10),   # MusicBrainzやroxyは遅いことがある
        follow_redirects=True,
        headers={"User-Agent": os.getenv("MB_USER_AGENT", "trackmento/0.1 (+https://trackmento.com)")},
        event_hooks={"request": [_note_out]},   # 外へ出した要求をホストごとに数える（`[out]`）
    )
    try:
        yield
    finally:
        if monitor:
            monitor.cancel()
        if seed:
            seed.cancel()
        if imgidx:
            imgidx.cancel()
        if srchidx:
            srchidx.cancel()
        if usage:
            usage.cancel()
        listed.cancel()
        await app.state.http.aclose()
        cache.close()


app = FastAPI(title="TRACKMENTO", lifespan=lifespan)


@functools.lru_cache(maxsize=1)
def _r2_origin() -> str:
    """R2の公開URLのオリジン（CSPに足すための " https://…" 形式）。R2を使っていなければ空文字。"""
    st = storage.get_storage()
    if not st.is_remote:
        return ""
    from urllib.parse import urlsplit
    p = urlsplit(st.public_url("") or "")
    return f" {p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""

# ---------- 描画は専用の低優先度スレッドで ----------
# もとは無料ホスト（0.1 vCPU）向けに1本・待ち2件だった（描画が重なるとイベントループがCPUを
# 取れず、Renderのヘルスチェック（5秒）に落ちて再起動されるため）。**Standard（1 vCPU / 2048MB）に
# 上げたので広げる**。2026-09-15の点検でCPU最大0.118 / 1.0・メモリ203 / 2048MBと余っているのに、
# 2時間で `/share` の503が15件出ていた
from concurrent.futures import ThreadPoolExecutor

_RENDER_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="render", initializer=render.lower_thread_priority)
MAX_RENDER_QUEUE = 6   # サーバー描画（フォールバック）は1件40〜80秒かかる。待たせるより早めに断る。
                       # 2/4では1日36,000共有の時間帯に2時間で7件断っていた（点検の「異常あり」）。
                       # CPUは最大0.36/1.0・メモリ332/2048MBと余っているので3/6に広げた（2026-09-17）
_render_waiting = [0]


async def run_render(fn, *args):
    if _render_waiting[0] >= MAX_RENDER_QUEUE:
        raise HTTPException(503, "共有の生成が混み合っています。30秒ほど待ってからもう一度お試しください", headers={"Retry-After": "30"})
    _render_waiting[0] += 1
    try:
        return await asyncio.get_running_loop().run_in_executor(_RENDER_POOL, functools.partial(fn, *args))
    finally:
        _render_waiting[0] -= 1


def _release_and_report(detail: bool, tasks: int) -> str:
    """gc＋malloc_trimを回し、`[mem]` の1行を返す（2026-10-06、RSSが再起動ごとに積み上がる原因を探すため）。

    見分け方: trimでRSSが大きく下がるならglibcの抱え込み、`blocks`（Pythonが割り当て中のブロック数）や
    索引の件数がRSSと一緒に増えるならPythonのオブジェクトが溜まっている。`top` はgcが追う入れ物
    （dict・list・tupleなど。strやintは入らない）の種類ごとの数。数えるのに一瞬GILを握るので1時間に1回だけ。
    **語やURLは出さない**（数だけ）。
    """
    import gc
    import sys
    before = _rss_mb()
    render._release_memory()
    after = _rss_mb()
    parts = [f"rss={before or 0:.0f}>{after or 0:.0f}MB", f"blocks={sys.getallocatedblocks()}",
             f"img_index={len(imageproxy._IMG_INDEX)}", f"search_index={len(searchcache._INDEX)}", f"listed={shareindex.count()}",
             f"inflight={len(searchapi._inflight)}", f"tasks={tasks}"]
    if detail:
        objs = gc.get_objects()
        top = Counter(type(o).__name__ for o in objs).most_common(8)
        parts.append(f"objs={len(objs)}")
        parts.append("top=" + ",".join(f"{k}:{n}" for k, n in top))
        del objs
    return "[mem] " + " ".join(parts)


async def _load_monitor():
    """1秒ごとにループの遅れを測り（0.5秒超なら記録）、60秒ごとにリクエスト集計を出す。"""
    tick = 0
    while True:
        t0 = time.monotonic()
        await asyncio.sleep(1.0)
        lag = time.monotonic() - t0 - 1.0
        if lag > 0.5:
            print(f"[loop] lag={lag:.1f}s render_queue={_render_waiting[0]}")
        tick += 1
        if tick % 600 == 0:
            # 10分ごとにgc＋malloc_trim。画像中継やR2一覧の一時バッファをglibcが抱え込み、RSSが下がらないため。
            # その前後のRSSと中身の数を `[mem]` に出す（1時間に1回は種類ごとの数も）
            print(await asyncio.to_thread(_release_and_report, tick % 3600 == 0, len(asyncio.all_tasks())))
        if tick % 60 == 0 and _stats:
            items = sorted(_stats.items(), key=lambda kv: -kv[1][1])
            fields = [_stats_field(k, v) for k, v in items[:_STATS_TOP]]
            if rest := items[_STATS_TOP:]:
                agg = [sum(v[0] for _, v in rest), sum(v[1] for _, v in rest), max(v[2] for _, v in rest),
                       sum(v[3] for _, v in rest), [sum(col) for col in zip(*(v[4] for _, v in rest))]]
                fields.append(_stats_field("ほか", agg))
            print("[stats] " + " ".join(fields))
            _stats.clear()
        if tick % 60 == 0 and _srch_stats:
            print("[srch] " + " ".join(
                f"{k}:db{v[0]}/r2{v[1]}/net{v[2]}/fail{v[3]}/max{v[5]:.1f}s/h" + ".".join(str(n) for n in v[6])
                for k, v in sorted(_srch_stats.items())))
            _srch_stats.clear()
        if tick % 60 == 0 and (out_line := _out_line()):
            print(out_line)
        if tick % 60 == 0 and imageproxy._img_stats:
            # imgcacheの当たり外れ。hit/(hit+miss) が42% を下回ると、R2に置くより
            # 中継したほうが安くなる（put $0.0000045対 帯域74KB $0.0000106）
            print("[img] " + " ".join(f"{k}={imageproxy._img_stats[k]}" for k in ("hit", "miss", "put", "stale") if k in imageproxy._img_stats))
            imageproxy._img_stats.clear()
            if len(imageproxy._img_stale) > imageproxy._IMG_INDEX_MAX // 10:   # 取り直されないまま溜まったぶんは捨てる
                imageproxy._img_stale.clear()
        if tick % 60 == 0 and (calls := vocadb.take_calls()):
            # VocaDBへ聞いた回数と、覚えていて聞かずに済んだ回数（種類ごと）。語そのものは数えない
            print("[vocadb] " + " ".join(f"{k}={n}" for k, n in sorted(calls.items())))
        if tick % 60 == 0 and (up_line := _upload_line()):
            print(up_line)
        if tick % 60 == 0 and _client_stats:
            print("[client] " + " ".join(f"{k}={n}" for k, n in sorted(_client_stats.items(), key=lambda kv: -kv[1])))
            _client_stats.clear()
        if tick % 60 == 0 and _5xx_stats:
            # 5xxの内訳。[stats] の5xxは件数しか分からないので、理由（HTTPExceptionのdetail）を添える。
            # 理由が _5XX_TOPを超えたぶんは「ほか」にまとめて数だけ残す（取りこぼさない）
            top = sorted(_5xx_stats.items(), key=lambda kv: -kv[1])
            for key, n in top[:_5XX_TOP]:
                print(f"[5xx] {n} {key}")
            if (rest := sum(n for _, n in top[_5XX_TOP:])):
                print(f"[5xx] {rest} 000 - ほか{len(top) - _5XX_TOP}種類")
            _5xx_stats.clear()
        if tick % 60 == 0 and _ua_stats:
            # 経路ごとのUA種別の内訳。どの経路をボットが踏んでいるかが分かると、
            # robots.txtで減らせるぶんと、減らしてはいけないぶん（リンクカード）を分けて考えられる
            by_path: dict[str, dict[str, int]] = {}
            for (path, kind), n in _ua_stats.items():
                by_path.setdefault(path, {})[kind] = n
            top = sorted(by_path.items(), key=lambda kv: -sum(kv[1].values()))[:6]
            print("[ua] " + " ".join(
                f"{path}:" + ",".join(f"{k}={n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
                for path, kinds in top))
            _ua_stats.clear()
        if tick % 60 == 0 and _src_stats:
            # どこから来たか（`?src=…`）。多い順に出す。**人の識別になるものは含まない**
            print("[src] " + " ".join(f"{k}={n}" for k, n in sorted(_src_stats.items(), key=lambda kv: -kv[1])))
            _src_stats.clear()
        if tick % 60 == 0 and _ref_stats:
            # どこから来たか（Refererのホスト名）。多い順に上位12件だけ
            top_ref = sorted(_ref_stats.items(), key=lambda kv: -kv[1])[:12]
            print("[ref] " + " ".join(f"{k}={n}" for k, n in top_ref))
            _ref_stats.clear()


def _wants_html(request: Request) -> bool:
    """ブラウザのアドレスバーやリンクから直接開いた要求か（fetchはAccept: */* なのでJSONのまま）。"""
    return request.method in ("GET", "HEAD") and "text/html" in request.headers.get("accept", "")


def _lang_for(request: Request | None) -> str:
    """案内ページ・共有ページの言語。開いた人のAccept-Languageで決める。

    共有ページは受け取った人が開くものなので、共有した人が画面で選んだ言語ではなく、
    開く人のブラウザの設定に合わせる。ヘッダが無ければ日本語（このサイトの元の言語）。
    """
    if request is not None:
        # **URLの ?lang=en / ?lang=jaが最優先**（画面側と同じ規則）。共有ページを英語で見せたいときに使う
        q = (request.query_params.get("lang") or "").strip().lower()
        if q in ("ja", "en"):
            return q
    header = (request.headers.get("accept-language") or "") if request is not None else ""
    for part in header.split(","):
        tag = part.split(";")[0].strip().lower()
        if tag and tag != "*":
            return "ja" if tag.startswith("ja") else "en"
    return "ja"


def _log_5xx(request: Request, status: int, detail: str) -> None:
    """HTTPExceptionで返した5xxを理由ごとに数える。1分ごとに _load_monitorが [5xx] 行で出す。

    raise HTTPException(...) はunhandled_errorを通らないのでログに何も出ず、点検では
    「エラー行0・5xx N」としか分からなかった（/image-proxyの503/502がこれで、
    最大24秒の原因を突き止めるのに時間がかかった）。印は [error] と分ける。
    [error] は「想定外の例外」を数える枠で、そこに配信元都合の502を混ぜると判定が鈍るため。
    1件ごとに出さず [stats] と同じ60秒窓でまとめるのは、件数を取りこぼさずに行数を抑えるため。
    パスは _stat_keyで種別に潰す（queryには外部の画像URLが入るので出さない）。
    """
    if status < 500 and not (status == 404 and request.url.path.startswith("/image-proxy")):
        return   # /image-proxyの404（配信元に無い）だけは4xxでも内訳に残す（どの配信元が消えているかを見るため）
    key = f"{status} {_stat_key(request.url.path)} {detail[:80]}"
    if not public_mode():
        print(f"[5xx] 1 {key}")   # ローカルは _load_monitorが動かないので、その場で出す
        return
    if len(_5xx_stats) < 500:     # 理由が際限なく増える種類のものが出ても溜め込まない
        _5xx_stats[key] = _5xx_stats.get(key, 0) + 1


def _error_response(request: Request, status: int, detail: str, headers: dict | None = None) -> Response:
    """エラーはfetchにはJSON、ブラウザ遷移には案内ページ（存在しないURL・期限切れの画像・429・500で{"detail": …}を見せない）。"""
    if _wants_html(request):
        return HTMLResponse(share.notice_html(status, base_url_for(request), app_url_for(request), detail, _lang_for(request)), status_code=status, headers=headers)
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
    """raise HTTPException(...) と、ルートに無いパスの404・メソッド違いの405。"""
    _log_5xx(request, exc.status_code, str(exc.detail))
    return _error_response(request, exc.status_code, str(exc.detail), exc.headers)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> Response:
    """想定外の例外もJSON（ブラウザ遷移なら案内ページ）で返す（フロントが「Internal Server Error」の生テキストをJSONとして
    読もうとして失敗しないように）。原因はサーバーログに残す。"""
    import traceback
    if isinstance(exc, ClientDisconnect):   # 利用者が送信途中で離脱しただけ（アプリ内ブラウザや回線切替）。トレースバック不要
        print(f"[error] {request.method} {request.url.path}: 送信途中で切断")
        return JSONResponse({"detail": "送信が途中で切れました"}, status_code=400)
    print(f"[error] {request.method} {request.url.path}: {exc!r}")
    print("".join(traceback.format_exception(exc)))
    return _error_response(request, 500, "サーバーでエラーが起きました。時間をおいてもう一度お試しください。直らない場合はお問い合わせフォームからお知らせください")


if cors_origins():
    # GitHub Pagesなど別オリジンのフロントから呼べるようにする（Cookieは使わないのでcredentialsは不要）
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"], max_age=600)
app.add_middleware(GZipText)

# ---------- 簡易レートリミット（IPごと・1分間の回数。公開時の連打・スクレイピング対策） ----------
_RATE_PATHS = ("/search", "/from-url", "/from-playlist", "/bandcamp", "/upload", "/share", "/share/upload", "/render", "/grids", "/hiccup")
_hits: dict[str, deque] = defaultdict(deque)
# 共有の1日あたり回数（IPごと／全体）。プロセス内カウンタ。日付が変わるとリセット
_share_day = {"date": "", "per_ip": defaultdict(int), "total": 0}


_IP_SALT = secrets.token_bytes(16)   # 起動ごとに変わる。IPを復元できない形で数えるためだけに使う


def _client_ip(request: Request) -> str:
    """回数制限のキー。生のIPは保持せず、プロセス限りの乱数と混ぜたハッシュにする。
    TRUST_PROXY=1のときはプロキシが付けたヘッダから利用者のIPを取る。
    RenderはCloudflareの後ろにいるので、X-Forwarded-Forの末尾はCloudflareのエッジIPになる。
    末尾を使うと利用者全員が数個のキーに集約され、初めての人でも「1日20回」に当たってしまう。
    そこでCloudflareが必ず付け直すCF-Connecting-IP（無ければTrue-Client-IP）を優先し、
    どちらも無ければX-Forwarded-Forの先頭（Renderの仕様: 先頭が利用者のIP）を使う。
    先頭は利用者が偽装できるが、影響は自分の回数制限を逃れられる程度（他人の枠は減らせない）"""
    ip = request.client.host if request.client else "?"
    if trust_proxy():
        forwarded = (request.headers.get("cf-connecting-ip") or request.headers.get("true-client-ip") or "").strip()
        if not forwarded:
            xff = [v.strip() for v in (request.headers.get("x-forwarded-for") or "").split(",") if v.strip()]
            if xff:
                forwarded = xff[0]
        if forwarded:
            ip = forwarded[:64]
    return hashlib.sha256(_IP_SALT + ip.encode("utf-8", "replace")).hexdigest()[:24]


def _check_share_quota(request: Request) -> None:
    per_ip, per_day = share_limits()
    if not per_ip and not per_day:
        return
    today = time.strftime("%Y-%m-%d")
    if _share_day["date"] != today:
        _share_day.update(date=today, per_ip=defaultdict(int), total=0)
    ip = _client_ip(request)
    if per_ip and _share_day["per_ip"][ip] >= per_ip:
        print(f"[share] quota: 端末の上限{per_ip}回 → 429")
        raise HTTPException(429, f"この端末からの共有は1日{per_ip}回までです。明日またお試しください")
    if per_day and _share_day["total"] >= per_day:
        print(f"[share] quota: 全体の上限{per_day}回（本日{_share_day['total']}件）→ 429")
        raise HTTPException(429, f"本日の共有回数がサーバー全体の上限（{per_day}回）に達しました。明日またお試しください")


async def _seed_share_count() -> None:
    """起動時に今日の共有数を保存先の一覧から数え、全体カウンタに入れる（プロセス内カウンタはデプロイ・再起動で0に戻るため。
    端末ごとの回数は復元しない）。一覧は数秒かかるのでスレッドで。"""
    try:
        n = await asyncio.to_thread(share.count_today)
    except Exception as e:
        print(f"[share] 今日の共有数の復元に失敗: {e!r}")
        return
    today = time.strftime("%Y-%m-%d")
    if _share_day["date"] != today:
        _share_day.update(date=today, per_ip=defaultdict(int), total=0)
    _share_day["total"] = max(_share_day["total"], n)
    print(f"[share] 本日の共有数を復元: {_share_day['total']}件（上限{share_limits()[1] or '無制限'}）")


def _count_share(request: Request) -> None:
    _share_day["per_ip"][_client_ip(request)] += 1
    _share_day["total"] += 1


_BODY_LIMIT_JSON = 1 * 1024 * 1024
_BODY_LIMIT_UPLOAD = 16 * 1024 * 1024


@app.middleware("http")
async def request_stats(request: Request, call_next):
    if not public_mode():
        return await call_next(request)
    t0 = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        dt = time.monotonic() - t0
        key = _stat_key(request.url.path)
        s = _stats.setdefault(key, [0, 0.0, 0.0, 0, [0] * (len(LAT_BUCKETS) + 1)])
        s[0] += 1
        s[1] += dt
        s[2] = max(s[2], dt)
        s[4][_lat_bucket(dt)] += 1
        if status >= 500:
            s[3] += 1
        ua = _ua_kind(request.headers.get("user-agent", ""))
        _ua_stats[(key, ua)] = _ua_stats.get((key, ua), 0) + 1


# 移転先へ301で送る経路。**画面（`/`）とAPIは送らない**。
# APIを送ると、開いたままの古いタブが別オリジンへ投げることになりCORSで落ちる
_MIGRATE_PATHS = ("/s/", "/find", "/sitemap.xml", "/robots.txt", "/guide", "/howto", "/articles", "/privacy", "/terms", "/about", "/updates")


def _migrate_host(request: Request) -> str:
    """移転先が設定されていて、今の要求がそれと違うホストで来ていれば、移転先のベースURLを返す。"""
    target = migrate_to()
    if not target:
        return ""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip().lower()
    return "" if not host or host == urllib.parse.urlsplit(target).netloc.lower() else target


def _migrate_redirect(request: Request) -> Response | None:
    """引っ越し中の古いドメインで、移すべき経路なら301を返す。それ以外はNone。"""
    if request.method not in ("GET", "HEAD"):
        return None
    path = request.url.path
    if not path.startswith(_MIGRATE_PATHS):
        return None
    if not (target := _migrate_host(request)):
        return None
    q = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"{target}{path}{q}", status_code=301)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # **引っ越し中の古いドメインは、共有ページなどを移転先へ301で送る**（MIGRATE_TO、2026-09-18）。
    # 画面（`/`）だけは送らずにそのまま返す。ブラウザに保存されている並びを引き継いでから、
    # 画面自身が移転先へ移動するため（サーバーの301ではlocalStorageを持っていけない）
    if (moved := _migrate_redirect(request)) is not None:
        return moved
    # 大きすぎるボディは読む前に断る（メモリ・ディスク消費を抑える）。ブラウザのfetchは必ずContent-Lengthを付ける
    if request.method in ("POST", "PUT"):
        cap = _BODY_LIMIT_UPLOAD if request.url.path in ("/upload", "/share/upload") else _BODY_LIMIT_JSON
        cl = request.headers.get("content-length")
        if cl is None or not cl.isdigit():
            return JSONResponse({"detail": "Content-Lengthが必要です"}, status_code=411)
        if int(cl) > cap:
            return JSONResponse({"detail": f"リクエストが大きすぎます（{cap // (1024*1024)}MBまで）"}, status_code=413)
    request.state.csp_nonce = secrets.token_urlsafe(16)
    limit = rate_limit_per_minute()
    if limit and request.url.path.startswith(_RATE_PATHS):
        ip = _client_ip(request)   # プロキシのヘッダを信頼するのはTRUST_PROXY=1のときだけ
        now = time.monotonic()
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return JSONResponse({"detail": "リクエストが多すぎます。1分ほど待ってからもう一度お試しください"}, status_code=429, headers={"Retry-After": "60"})
        q.append(now)
        if len(_hits) > 5000:  # メモリが膨らまないように古いIPを捨てる
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60][:1000]:
                _hits.pop(k, None)
    response = await call_next(request)
    if request.url.path.startswith("/fonts/"):
        # 同梱フォント（合計2.6 MBのWOFF2）は変わらないので長くキャッシュさせる。アプリ内ブラウザでも2回目以降は読み直さない
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    # CSP: スクリプトはこのサーバーが埋めたnonce付きのものだけ。画像は同一オリジン＋R2の公開URL（https:）＋Canvasのblob/data
    # 304には付けない: ブラウザは304のヘッダーでキャッシュ済み応答のヘッダーを更新するので、新しいnonceのCSPが
    # 古い本文（古いnonce）に適用されてスクリプトが止まる。付けなければキャッシュ済みのCSP（本文と一致）がそのまま残る
    if response.status_code != 304:
      # フォントと画像をR2から配るときは、その公開URLだけをfont-src / connect-srcに足す
      # （外部の任意のホストを開くわけではない。自分のバケット1つだけ）
      r2 = _r2_origin()
      # 引っ越し先へつながるかを画像で確かめる（frontendのreachable）。本番はhttps: で済むが、
      # 手元でhttp://127.0.0.1へ引っ越させて確かめるときのために、その1つだけ足す
      mig = f" {migrate_to()}" if migrate_to().startswith("http://") else ""
      response.headers.setdefault("Content-Security-Policy",
        # script-srcはnonceだけ（**外に出した <script src> にもnonceは効く**ので、R2のオリジンを足す必要はない）。
        # style-srcには足す: 切り出したapp.<hash>.cssをR2から <link> で読むため
        f"default-src 'self'; script-src 'nonce-{request.state.csp_nonce}'; style-src 'self' 'unsafe-inline'{r2}; "
        # connect-src: iTunesとMusicBrainz（＋Cover Art Archive → archive.orgへリダイレクト）の検索はブラウザから直接叩く
        # （サーバーの共有IPがAppleに遮断され、MusicBrainzにはレート制限されるため）
        # media-src / frame-src: 共有ページの試聴（iTunesの試聴音源をAppleから直接流す・Bandcampの公式プレイヤー。`share._PREVIEW_JS`）
        f"img-src 'self' data: blob: https:{mig}; connect-src 'self' https://itunes.apple.com https://musicbrainz.org https://coverartarchive.org https://archive.org https://*.archive.org https://*.mzstatic.com{r2}; font-src 'self'{r2}; media-src 'self' https://audio-ssl.itunes.apple.com{r2}; frame-src 'self' https://bandcamp.com; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'self'")
    if public_mode() and request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response
app.mount("/outputs", StaticFiles(directory=OUTPUTS, check_dir=False), name="outputs")
app.mount("/fonts", StaticFiles(directory=FONTS, check_dir=False), name="fonts")
# 画面に貼る絵（PayPalの広告など）。殻を配るときはR2のapp/banners/ に差し替わる（CSS・JSと同じ）。1枚のHTMLで配るときだけここから出る
app.mount("/app/banners", StaticFiles(directory=FRONTEND / "banners", check_dir=False), name="banners")
if not storage.get_storage().is_remote:
    app.mount("/uploads", StaticFiles(directory=uploads.UPLOADS, check_dir=False), name="uploads")
else:
    @app.get("/uploads/{fname}")
    async def upload_file(fname: str) -> Response:
        got = await run_in_threadpool(uploads.read_bytes, uploads.PREFIX + fname)
        if got is None:
            raise HTTPException(404, "アップロード画像が見つかりません（期限切れの可能性）")
        return Response(content=got[0], media_type=got[1], headers={"Cache-Control": "public, max-age=86400"})
if not storage.get_storage().is_remote:
    app.mount("/shares", StaticFiles(directory=share.SHARES, check_dir=False), name="shares")
else:
    # R2のときはバックエンドが中継する（JSONはCORSを気にせず読めるように常にこちら。PNGは公開URLがあればそちらを案内）
    @app.get("/shares/{fname}")
    async def share_file(fname: str) -> Response:
        sid, _, ext = fname.rpartition(".")
        if ext == "jpg" and sid.endswith("-og"):
            sid = sid[:-3]
        if ext not in ("png", "json", "jpg") or not share.valid_id(sid):
            raise HTTPException(404, "not found")
        data = await run_in_threadpool(storage.get_storage().get, fname)
        if data is None:
            # **消えた共有は410（Gone）**。404だと検索エンジンが「一時的な不調」とみて数か月再訪する。
            # IDの形が正しいのに無い＝期限切れで消したもの、なので「もう無い」と伝える（2026-09-17）
            raise HTTPException(410, "この共有は見つかりません（期限切れの可能性）")
        # JSONはcharsetを明示する（付けないと端末によっては既定の文字コードで開かれ、曲名が文字化けする）
        return Response(content=data, media_type={"png": "image/png", "jpg": "image/jpeg"}.get(ext, "application/json;charset=utf-8"),
                        headers={"Cache-Control": "public, max-age=86400"})


_FONT_CSS_FALLBACK = """
@font-face { font-family: "IBM Plex Sans JP"; font-weight: 400; font-style: normal; font-display: swap; src: url("fonts/IBMPlexSansJP-Regular.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Sans JP"; font-weight: 700; font-style: normal; font-display: swap; src: url("fonts/IBMPlexSansJP-Bold.woff2") format("woff2"); }
@font-face { font-family: "JF Dot MPlus12"; font-weight: 400; font-style: normal; font-display: swap; src: url("fonts/JF-Dot-MPlus12.woff2") format("woff2"); }
"""


FONTS_R2_PREFIX = "fonts/"
# フォントをR2から配るか（既定は有効）。公開URLとR2が無ければ自動でこのサーバーから配る
FONTS_FROM_R2 = os.getenv("FONTS_FROM_R2", "1") not in ("0", "false", "no")


def _fonts_r2_base() -> str:
    """R2に置いたフォントの公開URLの先頭。使えないときは空文字。"""
    if not FONTS_FROM_R2:
        return ""
    st = storage.get_storage()
    if not st.is_remote:
        return ""
    return (st.public_url(FONTS_R2_PREFIX) or "").rstrip("/")


@app.get("/fonts-css/{name}")
async def fonts_css(name: str) -> Response:
    """分割フォントのCSS。中のsrcをR2の公開URLに差し替えて返す。

    フォントは新規の訪問1回あたり210KB（実測）で、Renderの転送量の大半を占めていた。
    前段のCloudflareはWeb Serviceの応答をキャッシュしないため、訪問のたびにここから出ていく。
    R2は転送量が無料なので、断片のURLだけそちらに向ける（CSS自体は12KBと小さい）。
    """
    if not re.fullmatch(r"fonts\.[0-9a-f]{8}\.css", name):
        raise HTTPException(404, "not found")
    p = FONTS / "split" / name
    if not p.is_file():
        raise HTTPException(404, "not found")
    css = p.read_text(encoding="utf-8")
    base = _fonts_r2_base()
    if base:
        css = css.replace('url("/fonts/split/', f'url("{base}/')
    return Response(css, media_type="text/css", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@functools.lru_cache(maxsize=1)
def _font_head() -> str:
    """分割フォントの @font-faceを読む <link>（scripts/build_fonts.pyが生成したfonts/split/fonts.<hash>.css。
    ハッシュ名なので1年キャッシュに乗る）。無ければフル版の @font-faceを埋め込む。"""
    hashed = sorted((FONTS / "split").glob("fonts.*.css")) if (FONTS / "split").is_dir() else []
    if hashed:
        # 断片をR2から配るときは、srcを書き換えたCSSを返す /fonts-css/ 経由にする
        base = _fonts_r2_base()
        # **URLにR2の公開ドメインの印を付ける**。CSSの中身（断片のURL）はR2のドメインで変わるのに、
        # ファイル名は断片の中身から作るので変わらない。1年のimmutableで配っているため、
        # 印が無いとドメインを替えたあとも古いCSSを使い続け、**CSPで新ドメイン以外は弾かれて
        # フォントが1つも読めなくなる**（2026-09-14に本番で実際に起きた。日本語がシステムフォントになり、
        # 共有画像もブラウザで作れずサーバー描画に落ちていた）
        tag = hashlib.sha1(base.encode()).hexdigest()[:8] if base else ""
        path = f"fonts-css/{hashed[-1].name}?o={tag}" if base else f"fonts/split/{hashed[-1].name}"
        return f'<link rel="stylesheet" href="{path}">'
    print("[fonts] fonts/split/fonts.<hash>.cssが無いのでフル版のフォントを配ります（python scripts/build_fonts.pyで生成）")
    return f"<style>{_FONT_CSS_FALLBACK}</style>"


APP_R2_PREFIX = "app/"
# 切り出したCSSとJSをR2から配るか（既定は有効）。R2と公開URLが無ければ自動で1枚のまま配る
APP_FROM_R2 = os.getenv("APP_FROM_R2", "1") not in ("0", "false", "no")
_app_shell: str | None = None   # 使える殻（frontend/dist/index.htmlの中身）。使わないならNone


def _check_app_shell() -> str | None:
    """殻を使ってよければその中身、駄目ならNone。起動時に1回だけ呼ぶ。

    **殻が指すapp.<hash>.css / .jsがR2に両方載っていることを確かめてから使う**。
    上げ忘れたままデプロイしても、1枚のindex.htmlに倒れるだけで白い画面にならない
    （フォントは上げ忘れると本番で404になる作りで、CLAUDE.mdに注意書きが要った。同じ轍を踏まない）。
    確かめるのはHeadObject 2回で、Class Bなので実質無料。
    """
    shell_path = FRONTEND / "dist" / "index.html"
    if not APP_FROM_R2 or not shell_path.is_file():
        return None
    st = storage.get_storage()
    base = st.public_url(APP_R2_PREFIX) if st.is_remote else ""
    if not base:
        return None
    shell = shell_path.read_text(encoding="utf-8")
    names = re.findall(r'"' + re.escape(APP_R2_PREFIX) + r'(app\.[0-9a-f]{8}\.(?:css|js))"', shell)
    if len(names) != 2:
        print(f"[app] 殻が指すファイルが{len(names)}個でした（cssとjsの2個であること）。1枚のまま配ります")
        return None
    for name in names:
        if not st.exists(APP_R2_PREFIX + name):
            print(f"[app] {name}がR2にありません。1枚のまま配ります"
                  "（python scripts/build_app.py → scripts/upload_app_r2.py）")
            return None
    # 殻の中は相対パス。配るときにR2の公開URLへ差し替える（フォントと同じやり方）
    shell = shell.replace(f'"{APP_R2_PREFIX}', f'"{base.rstrip("/")}/')
    print(f"[app] CSSとJSをR2から配ります（{', '.join(names)}）")
    return shell


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    # OGタグの絶対URL（__BASE__）をこのサーバーのURLに置き換えて配る
    _note_src(request)
    src = _app_shell if _app_shell is not None else (FRONTEND / "index.html").read_text(encoding="utf-8")
    html = src.replace("__BASE__", base_url_for(request))
    html = html.replace("__PUBLIC__", "1" if public_mode() else "0")   # /statusが遮断されても公開モードだと分かるように
    html = html.replace("__MIGRATE__", _migrate_host(request))   # 引っ越し中なら移転先。画面が並びを持って移動する
    html = html.replace("__RETENTION__", str(share_retention_days()))   # 共有が消えるまでの日数（説明文）
    html = html.replace("__SUPPORT__", support.meta(), 1)   # サーバー代の進み具合の棒（backend/support.py）
    html = html.replace("<!--__FONT_LINK__-->", _font_head(), 1)   # 分割フォントの @font-face（<link>）
    html = html.replace("__LOGO_FONT__", share.logo_font_url(), 1)   # ロゴ専用フォント（中身のハッシュ付き）
    # ピクセルフォント（Silkscreen）もR2から配る。分割していないので <link> ではなくHTML内の
    # @font-faceを直接書き換える。**ttfの控えはサーバーのまま**（woff2を読めない古い環境用で、まず使われない）
    if (fbase := _fonts_r2_base()):
        for _f in ("Silkscreen-Regular.woff2", "Silkscreen-Bold.woff2"):
            html = html.replace(f'url("fonts/{_f}")', f'url("{fbase}/{_f}")')   # **woff2だけ**（ttfはR2に置いていない）
    # ETagはnonceを入れる前の内容から作る（nonceは毎回変わる）。ブラウザが同じETagを持っていれば304で本文（約40KB）を省く。
    # 304にはCSPヘッダーを付けない（付けるとキャッシュ済み本文のnonceと食い違ってスクリプトが止まる。middleware側で除外）
    etag = '"' + hashlib.sha256(html.encode("utf-8")).hexdigest()[:16] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    # CSP（script-src 'nonce-…'）用。**外に出した <script src> にもnonceは効く**ので、
    # 殻を配るときも1枚で配るときも同じ1行で済む（idで狙う）
    html = html.replace('<script id="app-js"', f'<script id="app-js" nonce="{request.state.csp_nonce}"', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache", "ETag": etag})   # no-cache = 毎回ETagで確認（更新をすぐ配る）


@app.get("/ads.txt")
async def ads_txt() -> Response:
    """AdSenseに出す広告枠の販売許可（IABのads.txt）。ルート直下に置く決まり。
    公開されることが前提のファイルなので、publisher IDを書いてよい。"""
    body = "google.com, pub-6662407728160305, DIRECT, f08c47fec0942fa0\n"
    return Response(body, media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})


_ROBOTS_DISALLOW = ("/search", "/from-url", "/from-playlist", "/image-proxy", "/grids", "/shares",
                    "/uploads", "/outputs", "/health", "/render", "/upload", "/share")
# 共有ページ（`/s/<id>`）を名指しの相手にだけ断る（2026-09-21）。ページ自体は前から `noindex` なので
# 検索結果には出ていないが、確かめるためのクロールは来続けていた（点検の2時間で検索ボットが102件、
# `/s/` への要求の70% が人以外）。30日で消えるページなので索引される値打ちがそもそも無い。
# **`User-agent: *` には入れない**。Xなどがリンクカードを作るための取得まで止まってしまう
_ROBOTS_SHARE_DENY = "/s/"
# 断る相手は、ログのUA種別（`_UA_KINDS`）の「AI」「検索」と同じ顔ぶれにする（名前を2か所に書かない）。
# ただしapplebotはiMessageなどのリンクカードにも使われるので外す（`applebot-extended` はAI学習用なので残す）
_ROBOTS_KEEP = ("applebot",)
_ROBOTS_DENY_AGENTS = tuple(t for kind, tokens in _UA_KINDS if kind in ("AI", "検索")
                            for t in tokens if t not in _ROBOTS_KEEP)


@app.get("/robots.txt")
async def robots(request: Request) -> Response:
    """トップは索引してよい。API・画像・共有の中身はクロール対象から外す"""
    common = [f"Disallow: {p}" for p in _ROBOTS_DISALLOW]
    lines = ["User-agent: *", "Allow: /$", *common, ""]
    # 名指しの相手は `*` のグループを見ないので、共通の分もここへ書き写す（robots.txtの決まり）
    lines += [f"User-agent: {name}" for name in _ROBOTS_DENY_AGENTS]
    lines += ["Allow: /$", *common, f"Disallow: {_ROBOTS_SHARE_DENY}", ""]
    lines += [f"Sitemap: {base_url_for(request)}/sitemap.xml", ""]
    return Response("\n".join(lines), media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/sitemap.xml")
async def sitemap(request: Request) -> Response:
    base = base_url_for(request)
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{base}/</loc><changefreq>weekly</changefreq></url>"
            + "".join(f"<url><loc>{base}/{k}</loc><changefreq>monthly</changefreq></url>" for k in pages.BODIES)
            + "".join(f"<url><loc>{base}/articles/{a['slug']}</loc><lastmod>{a['date']}</lastmod></url>"
                      for a in articles.ARTICLES)
            + "</urlset>\n")
    return Response(body, media_type="application/xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/og.png")
async def og_image() -> FileResponse:
    return FileResponse(FRONTEND / "og.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.ico")
async def favicon_ico() -> FileResponse:
    return FileResponse(FRONTEND / "favicon.ico", media_type="image/x-icon", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.png")
async def favicon_png() -> FileResponse:
    return FileResponse(FRONTEND / "favicon.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/bg-mark.png")
async def bg_mark_png() -> FileResponse:
    """背景色の「画像」の既定（TRACKMENTOのロゴを敷き詰めた絵。scripts/build_icons.pyが作る）。"""
    return FileResponse(FRONTEND / "bg-mark.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/no-cover.png")
async def no_cover_png() -> FileResponse:
    """ジャケットが無い曲のマスに使う画像（scripts/build_icons.pyが作る）。"""
    return FileResponse(FRONTEND / "no-cover.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/apple-touch-icon.png")
async def apple_touch_icon() -> FileResponse:
    return FileResponse(FRONTEND / "apple-touch-icon.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/icon-192.png")
@app.get("/icon-512.png")
async def app_icon(request: Request) -> FileResponse:
    """ホーム画面のアイコン（scripts/build_icons.pyが作る）。manifest.webmanifestから指す。"""
    name = request.url.path.lstrip("/")
    return FileResponse(FRONTEND / name, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


# **Web Share Target**（2026-09-24、運用ボードのideas-0923）。ホーム画面に追加すると、Androidのほかのアプリの
# 「共有」にTRACKMENTOが出て、URLを直接送れる。受け取りはfrontendのtakeSharedUrl()。
# 引数の名前にst_ を付けるのは、共有ページから開く ?share=<id> と取り違えないため。
# **Service Workerは置かない**（Chromeのインストールの条件に入っていない。置くと古い画面が残る心配が増える）
MANIFEST = {
    "name": "TRACKMENTO",
    "short_name": "TRACKMENTO",
    "description": "好きなトラックのサムネイルを並べて1枚の画像に。",
    "lang": "ja",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#F6F6F4",
    "theme_color": "#F6F6F4",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
    "share_target": {
        "action": "/",
        "method": "GET",
        "enctype": "application/x-www-form-urlencoded",   # GETの既定と同じ。書かないとChromeが注意を出す
        "params": {"title": "st_title", "text": "st_text", "url": "st_url"},
    },
}


@app.get("/manifest.webmanifest")
async def manifest() -> Response:
    return Response(json.dumps(MANIFEST, ensure_ascii=False), media_type="application/manifest+json",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/health")
@app.get("/status")   # Webはこちらを使う。EasyPrivacyに「||onrender.com/health」があり、広告ブロッカー入りのブラウザ（Vivaldiなど）は /healthを遮断する
async def health() -> dict:
    # started_at / uptime_s: デプロイ無しの再起動（ディスク初期化）をログ無しで切り分けるため
    # itunes_server: サーバー経由のiTunesがAppleに制限されているか（Webはブラウザから直接叩くので参考情報）
    common = {
        "ok": True,
        "sources": sorted(searchapi.SOURCES),
        "started_at": datetime.fromtimestamp(app.state.started_at, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "uptime_s": int(time.time() - app.state.started_at),
        "itunes_server": "blocked" if itunes.is_blocked() else "ok",
        "itunes_proxy": bool(itunes.proxy_url()),   # サーバー側iTunesをCloudflare Workers経由にしているか
        "frontend_url": frontend_url(),
        "storage": storage.get_storage().name,
    }
    if public_mode():
        # 公開時は内部情報（キャッシュのパス、内部IP、グリッド名）を出さない。
        # 常駐メモリはログにだけ出す。Renderのヘルスチェック（約5秒おき）でも呼ばれるので、出力は60秒に1回に間引く
        now = time.monotonic()
        if now - _health_logged_at[0] >= 60:
            rss = _rss_mb()
            if rss is not None:
                _health_logged_at[0] = now
                print(f"[health] rss={rss:.0f}MB uptime={common['uptime_s']}s")
        return {**common, "public": True}
    return {
        **common,
        "cache": await asyncio.to_thread(cache.stats),
        "public_base_url": public_base_url(),
        "public": False,
        "grids": grids.list_names(),
    }


app.include_router(searchapi.router)    # /artist-candidates・/search・/from-playlist・/from-url（backend/searchapi.py）
app.include_router(imageproxy.router)   # /image-r2・/image-proxy（backend/imageproxy.py）


@app.post("/hiccup", status_code=204)
async def hiccup(request: Request) -> Response:
    """画面から届く「ブラウザ側で起きた失敗」の件数（`CLIENT_KINDS`）。**種類と回数だけ**を受け取り、
    60秒ごとに `[client]` 行で出す。本文は `{"kind": 回数, …}`。知らない種類・多すぎる回数は捨てる。
    `navigator.sendBeacon` で送られてくるので、内容の型はtext/plainのこともある（JSONとして読む）"""
    try:
        body = json.loads((await request.body())[:2048] or b"{}")
    except ValueError:
        return Response(status_code=204)
    if isinstance(body, dict):
        for k, n in list(body.items())[:20]:
            if k in CLIENT_KINDS and isinstance(n, int) and 0 < n <= 50:
                _client_stats[k] = _client_stats.get(k, 0) + n
    return Response(status_code=204)


async def _seed_search_index() -> None:
    """起動後にR2のsearchcache/ を一覧して索引を作る（検索結果の控え。backend/searchcache.py）。
    失敗しても外部に引き直すだけなので握りつぶす"""
    try:
        n = await asyncio.to_thread(searchcache.seed)
    except Exception as e:
        print(f"[error] 検索結果の控えの索引を作れませんでした: {type(e).__name__}: {e}")
        return
    print(f"[storage] searchcacheの索引: {n}件（デプロイ後も検索結果を使い回す）")


async def _seed_listed_index() -> None:
    """起動後に「みんなの並びから探せる」共有の索引を読み直す。

    共有そのもの（1日数千件）ではなく、**印を付けたものだけ**を読む。
    失敗しても探せなくなるだけで、共有は壊れない。
    """
    try:
        n = await asyncio.to_thread(shareindex.seed)
    except Exception as e:
        print(f"[error] みんなの並びの索引を作れませんでした: {type(e).__name__}: {e}")
        return
    print(f"[listed] みんなの並びの索引: {n}件")


# ---------- グリッドJSON（CLIとWebで共有） ----------
def _grid_name(name: str) -> str:
    try:
        return grids.validate_name(name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/grids")
async def grids_index() -> dict:
    if public_mode():
        raise HTTPException(404, "公開モードでは一覧を出しません")
    return {"grids": grids.list_names()}


@app.get("/grids/{name}", response_model=GridDoc)
async def grid_get(name: str) -> GridDoc:
    name = _grid_name(name)
    if not grids.exists(name):
        raise HTTPException(404, f"グリッド{name}はまだありません")
    try:
        return grids.load(name)
    except ValueError as e:
        raise HTTPException(500, str(e)) from e


@app.put("/grids/{name}", response_model=GridDoc)
async def grid_put(name: str, doc: GridDoc) -> GridDoc:
    """Webの自動保存とJSON読み込みが呼ぶ。savedAtが無ければ今の時刻を入れる。"""
    name = _grid_name(name)
    doc.name = name
    if not doc.savedAt:
        doc.touch()
    grids.save(doc)
    if public_mode():
        _grid_saves[0] += 1
        if _grid_saves[0] % 50 == 0:
            await run_in_threadpool(housekeeping.prune_grids_count)
    return doc


_grid_saves = [0]


_health_logged_at = [0.0]   # [health] を最後に出した時刻（monotonic）


@app.delete("/grids/{name}")
async def grid_delete(name: str) -> dict:
    if public_mode():
        raise HTTPException(404, "公開モードでは削除できません")
    name = _grid_name(name)
    p = grids.path_for(name)
    if p.exists():
        p.unlink()
    return {"ok": True}


# ---------- サーバー側描画 ----------
class RenderBody(BaseModel):
    grid: str = "default"
    # 以下は省略可。指定したものだけグリッドのオプションを上書きし、グリッドJSONにも保存する
    size: str | None = None          # "3x3"
    ratio: str | None = None
    sidebar: bool | None = None
    overlay: bool | None = None
    title: str | None = None
    showTitle: bool | None = None
    numbers: bool | None = None
    bg: str | None = None
    bgCustom: str | None = None
    margin: int | None = None
    pad: str | None = None
    gap: int | None = None
    # Webが /shareで並びをそのまま送る用。サーバーのディスクが消えていても（Renderの再起動など）共有できるようにする
    doc: GridDoc | None = None


def _check_cells(doc: GridDoc) -> None:
    limit = max_cells()
    if limit and doc.size > limit:
        raise HTTPException(400, f"公開サーバーでは1枚あたり{limit}マスまでです（今は{doc.cols}×{doc.rows}）")


def apply_render_options(doc: GridDoc, body: RenderBody) -> bool:
    """bodyの指定をdocに反映。変更があればTrue。"""
    changed = False
    if body.size:
        try:
            c, r = (int(v) for v in body.size.lower().split("x"))
        except ValueError as e:
            raise HTTPException(400, "sizeは3x3のように指定してください") from e
        if (c, r) != (doc.cols, doc.rows):
            doc.resize(max(1, min(grids.MAX_COLS, c)), max(1, min(grids.MAX_ROWS, r)))
            changed = True
    if body.title is not None and body.title != doc.title:
        doc.title = body.title[:60]
        changed = True
    opts = doc.options.model_dump()
    for k in ("ratio", "sidebar", "overlay", "showTitle", "numbers", "bg", "bgCustom", "margin", "pad", "gap"):
        v = getattr(body, k)
        if v is not None and v != opts.get(k):
            opts[k] = v
            changed = True
    if body.bgCustom and body.bg is None:
        opts["bg"] = "custom"
    if body.sidebar and body.overlay is None and opts.get("overlay"):
        opts["overlay"] = False   # 横に並べると言われたら、重ねるのはやめる
        changed = True
    if changed:
        try:
            doc.options = GridOptions.model_validate(opts)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return changed


@app.post("/render")
async def render_grid(request: Request, body: RenderBody = Body(default_factory=RenderBody)) -> dict:
    if public_mode():
        raise HTTPException(404, "公開モードでは /renderは使えません（「トラックを共有」を使ってください）")
    name = _grid_name(body.grid)
    try:
        doc = grids.load(name)
    except ValueError as e:
        raise HTTPException(500, str(e)) from e
    if not any(doc.cells):
        raise HTTPException(400, f"グリッド{name}に曲がありません")
    if apply_render_options(doc, body):
        doc.touch()
        grids.save(doc)
    _check_cells(doc)
    try:
        path, im = await run_render(render.render_to_file, doc)
    except HTTPException:
        raise
    except RuntimeError as e:  # フォント欠落など
        raise HTTPException(500, str(e)) from e
    return {
        "url": f"{base_url_for(request)}/outputs/{path.name}",
        "file": path.name,
        "width": im.width,
        "height": im.height,
        "grid": doc.model_dump(),
    }


# ---------- 手入力用の画像アップロード ----------
@app.post("/upload")
async def upload_image(request: Request, file: UploadFile = File(...)) -> dict:
    """PCやスマホの画像ファイルをuploads/ に保存し、Track.imageに入れる相対URLを返す。"""
    data = await file.read(uploads.MAX_BYTES + 1)
    if len(data) > uploads.MAX_BYTES:
        raise HTTPException(413, "画像が大きすぎます（15MBまで）")
    if not data:
        raise HTTPException(400, "ファイルが空です")
    try:
        url = await run_in_threadpool(uploads.save_image_bytes, data)
    except ValueError as e:
        raise HTTPException(415, str(e)) from e
    return {"url": url, "absolute": f"{base_url_for(request)}{url}"}


# ---------- トラックを共有（PNG + 並びのスナップショット + 共有ページ） ----------
def _doc_for_share(body: RenderBody) -> GridDoc:
    """共有する並びを決める。ブラウザが持っている並び（doc）を正とし、無ければサーバーのJSONを読む。"""
    name = _grid_name(body.grid)
    if body.doc is not None:
        # ブラウザが持っている並びを正とする（サーバー側のJSONは再起動で消えていることがある）
        doc = body.doc
        doc.name = name
        if not doc.savedAt:
            doc.touch()
        grids.save(doc)
    else:
        try:
            doc = grids.load(name)
        except ValueError as e:
            raise HTTPException(500, str(e)) from e
    if not any(doc.cells):
        raise HTTPException(400, f"グリッド{name}に曲がありません")
    if apply_render_options(doc, body):
        doc.touch()
        grids.save(doc)
    _check_cells(doc)
    return doc


async def _finish_share(request: Request, coro) -> dict:
    """保存処理（coroutine）を実行し、回数を数え、共有URLを付けて返す。失敗の扱いは共通。"""
    try:
        info = await coro
    except HTTPException:
        raise   # 待ち行列の上限（503）など
    except share.BudgetExceeded as e:
        raise HTTPException(507, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    except Exception as e:  # R2への保存失敗など
        import traceback
        print(f"[share] failed: {e!r}")
        print(traceback.format_exc())
        raise HTTPException(502, "共有の保存に失敗しました。少し待ってからもう一度お試しください") from e
    _count_share(request)
    if public_mode() and not storage.get_storage().is_remote:
        housekeeping.prune_shares()   # R2のときはバケットのライフサイクルルールに任せる
    base = base_url_for(request)
    img_abs = info["image"] if info["image"].startswith("http") else f"{base}{info['image']}"
    return {**info, "url": f"{base}/s/{info['id']}", "image_url": img_abs, "png_url": img_abs}   # png_urlは旧キー


@app.post("/share")
async def share_grid(request: Request, body: RenderBody = Body(default_factory=RenderBody)) -> dict:
    """サーバーで描いて共有する（CLIと、ブラウザ描画ができない端末のフォールバック）。"""
    doc = _doc_for_share(body)
    _check_share_quota(request)
    budget = share_budget_bytes() if (public_mode() or storage.get_storage().is_remote) else 0
    return await _finish_share(request, run_render(share.create, doc, budget))


# 同時に受け付ける共有アップロード。超えたら待たせず503（本文を抱えたまま並ぶとメモリが膨らむ）。
# **3は無料ホスト時代の値**。回線の遅い端末が枠を握ると後続が全部断られ、2026-09-15の点検で
# 2時間に21件の503が出ていた（`/share/upload` の最大応答85.2秒）。Standardなら8で足りる
_UPLOAD_SEM = asyncio.Semaphore(8)
# **受け取り中と、検査・保存は分けて数える**。一緒にすると、回線の細い端末が1件で枠を握り、
# その間の後続が全部503になる（2026-09-15の点検で `/share/upload` の最大応答が122.7秒、
# 653件中5件が503）。受け取りは待つだけなので広く取ってよい。本文の大きい部分は
# Starletteが一時ファイルに逃がすので、待たせてもメモリは膨らまない。
# **バイト列に読むのは内側（8枠）の中**で行う（外で読むと32件ぶん抱えることになる）
_UPLOAD_RECV = asyncio.Semaphore(int(os.getenv("SHARE_UPLOAD_RECV", "32") or 32))


@app.post("/share/upload")
async def share_upload(request: Request) -> dict:
    """ブラウザで描いた本体画像（JPEG。古いタブからはPNG）とカード用JPEGを受け取って共有する。サーバーはヘッダ検査と保存だけ
    （無料ホストの0.1 vCPUでは描画がヘルスチェックを止めるため、描画は端末側で行う）。
    フォーム: doc（JSON文字列）, image（旧名png）, og"""
    _check_share_quota(request)   # 本文（数MB）を読む前に断る。上限到達中に受け取ってから429にしない
    if _UPLOAD_RECV.locked():
        _note_upload(busy=True)
        raise HTTPException(503, "共有が混み合っています。10秒ほど待ってからもう一度お試しください", headers={"Retry-After": "10"})
    async with _UPLOAD_RECV:      # 受け取り（回線が細いと数十秒かかる）
        t_recv = time.monotonic()
        try:
            form = await request.form()
        except ClientDisconnect:   # 利用者が送信途中で離脱（アプリ内ブラウザや回線切替）。サーバー側の異常ではないので5xxにしない
            _note_upload(recv=time.monotonic() - t_recv, cut=True)
            print("[share] 送信途中で切断（利用者側の離脱）")
            raise HTTPException(400, "送信が途中で切れました。もう一度お試しください")
        _note_upload(recv=time.monotonic() - t_recv, kb=int(request.headers.get("content-length") or 0) / 1024)
        doc, image, og = form.get("doc"), form.get("image") or form.get("png"), form.get("og")
        # **カード用（og）は送られてこないのがふつう**（2026-09-16から、本体だけ送ってカードはサーバーで作る）。
        # 開いたままの古いタブは今までどおり送ってくるので、来たときはそれを使う
        if not isinstance(doc, str) or not isinstance(image, StarletteUploadFile):   # request.form() が返すのはstarletteのUploadFile
            raise HTTPException(400, "並び（doc）と画像（image）が必要です")
        try:
            raw = json.loads(doc)   # {"grid": "u-…", "doc": {...}}（/shareのJSONボディと同じ形）
            body = RenderBody(grid=raw.get("grid", "default"), doc=GridDoc.model_validate(raw["doc"]))
        except Exception as e:
            print(f"[share] 並びが読めない: {e!r}")
            raise HTTPException(400, "並びのデータを読めませんでした。ページを読み込み直してからもう一度お試しください") from e
        gdoc = _doc_for_share(body)
        async with _UPLOAD_SEM:   # 検査と保存（CPUとR2。数百msで終わる）
            img_b = await image.read(share.MAX_UPLOAD_IMAGE + 1)
            og_b = await og.read(share.MAX_UPLOAD_OG + 1) if isinstance(og, StarletteUploadFile) else None
            try:
                w, h, ext = await asyncio.to_thread(share.check_uploaded, img_b, og_b)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            _check_share_quota(request)
            budget = share_budget_bytes() if (public_mode() or storage.get_storage().is_remote) else 0
            t_save = time.monotonic()
            try:
                return await _finish_share(request, run_in_threadpool(share.store, gdoc, img_b, og_b, w, h, budget, ext))
            finally:
                _note_upload(save=time.monotonic() - t_save)


# ---------- 自分の共有をあとから外す・消す（2026-09-26、利用者の案） ----------
# 共有したときに返した鍵（ownerKey）を持っている端末だけが頼める。鍵は並びのJSONにSHA-256だけ置いてある（backend/share.py）。
# 鍵は144ビットの乱数なので総当たりは現実的でないが、念のため端末ごとに1時間30回まで
_OWNER_TRIES: dict[str, list[float]] = defaultdict(list)
_OWNER_TRIES_MAX = 30


def _check_owner_tries(request: Request) -> None:
    ip, now = _client_ip(request), time.monotonic()
    tries = [t for t in _OWNER_TRIES[ip] if now - t < 3600]
    if len(tries) >= _OWNER_TRIES_MAX:
        raise HTTPException(429, "しばらく時間をおいてからもう一度お試しください")
    tries.append(now)
    _OWNER_TRIES[ip] = tries
    if len(_OWNER_TRIES) > 10_000:   # 覚えている端末が増えすぎたら古いものを捨てる
        for k in [k for k, v in _OWNER_TRIES.items() if not v or now - v[-1] >= 3600]:
            _OWNER_TRIES.pop(k, None)


class OwnerBody(BaseModel):
    key: str = Field("", max_length=64)


@app.post("/s/{sid}/unlist")
@app.post("/s/{sid}/delete")
async def share_owner_action(request: Request, sid: str, body: OwnerBody) -> dict:
    """みんなのグリッドから外す（unlist）／共有ごと消す（delete）。鍵が合わなければ403、共有が無ければ404。"""
    _check_owner_tries(request)
    if not share.valid_id(sid):
        raise HTTPException(404, "共有が見つかりません")
    action = request.url.path.rsplit("/", 1)[-1]
    try:
        await run_in_threadpool(share.unlist if action == "unlist" else share.delete, sid, body.key)
    except FileNotFoundError:
        raise HTTPException(404, "共有が見つかりません（期限切れか、もう消えています）")
    except share.NotOwner:
        raise HTTPException(403, "この端末からは操作できません（共有したときの端末・ブラウザからだけ操作できます）")
    print(f"[share] {action}: 共有した人の操作")
    return {"id": sid, "action": action}


# 「みんなの並びを探す」。**印を付けた共有だけ**が対象（backend/shareindex.py）。
# `/shares/{fname}` と経路がぶつからないよう、JSONは `/find.json` にしてある
# 文章のページ（使い方・コラム・プライバシーポリシー・利用規約・運営者）。backend/pages.py。言語は共有ページと同じ決め方
@app.get("/guide", response_class=HTMLResponse)
@app.get("/howto", response_class=HTMLResponse)
@app.get("/articles", response_class=HTMLResponse)
@app.get("/privacy", response_class=HTMLResponse)
@app.get("/terms", response_class=HTMLResponse)
@app.get("/about", response_class=HTMLResponse)
@app.get("/updates", response_class=HTMLResponse)
async def text_page(request: Request) -> HTMLResponse:
    kind = request.url.path.strip("/")
    return HTMLResponse(pages.page_html(kind, base_url_for(request), app_url_for(request), _lang_for(request), nonce=request.state.csp_nonce),
                        headers={"Cache-Control": "public, max-age=3600"})


@app.get("/articles/{slug}", response_class=HTMLResponse)
async def article_page(request: Request, slug: str) -> HTMLResponse:
    """コラム1本（backend/articles.py）。本文は日本語だけ"""
    page = pages.article_html(slug, base_url_for(request), app_url_for(request), _lang_for(request))
    if page is None:
        raise HTTPException(404, "コラムが見つかりません")
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/find", response_class=HTMLResponse)
async def find_page(request: Request, q: str = "") -> HTMLResponse:
    _note_src(request)
    q = (q or "").strip()[:80]
    varied = [] if q else shareindex.varied()
    rows = shareindex.search(q) if q else shareindex.newest(skip={r["id"] for r in varied})
    return HTMLResponse(share.find_html(q, rows, base_url_for(request), app_url_for(request),
                                        _lang_for(request), shareindex.count(), varied, nonce=request.state.csp_nonce,
                                        popular=None if q else shareindex.popular(),
                                        rare=None if q else shareindex.rare()))


@app.get("/find.json")
async def find_json(q: str = "", limit: int = 40) -> dict:
    q = (q or "").strip()[:80]
    limit = max(1, min(100, limit))
    if q:
        return {"q": q, "total": shareindex.count(), "ready": shareindex.ready(),
                "results": shareindex.search(q, limit)}
    varied = shareindex.varied()
    return {"q": q, "total": shareindex.count(), "ready": shareindex.ready(), "varied": varied,
            "popular": shareindex.popular(), "rare": shareindex.rare(),
            "results": shareindex.newest(limit, skip={r["id"] for r in varied})}


@app.get("/s/{sid}", response_class=HTMLResponse)
async def share_page(request: Request, sid: str) -> HTMLResponse:
    _note_src(request)   # 共有ページにも印を付けられる（投稿に貼るのはこちらのことが多い）
    # share.loadはR2への同期GET。ループ内で呼ぶと閲覧が重なったときにサーバー全体が止まり、
    # Renderのヘルスチェック（5秒）に落ちて再起動される
    snap = await run_in_threadpool(share.load, sid)
    if not snap:
        shareindex.forget(sid)   # 期限より前に消した共有（scripts/delete_share.py）を「みんなのグリッド」から外す
        # JSONの404だとXから開いた人に何が起きたか伝わらない。案内ページ（期限切れ・作り直し）を返す
        return HTMLResponse(share.expired_html(sid, base_url_for(request), app_url_for(request), _lang_for(request)), status_code=410)   # 消えた共有は410（Gone）
    # 試聴できるマスの位置（割り付けの計算。初回はフォントを読むので数十ms。ループの外で）
    boxes = await run_in_threadpool(share.cell_boxes, snap)
    return HTMLResponse(share.page_html(snap, base_url_for(request), app_url_for(request), _lang_for(request),
                                        nonce=request.state.csp_nonce, boxes=boxes))
