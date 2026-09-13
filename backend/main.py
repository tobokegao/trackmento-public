"""FastAPI エントリポイント。起動: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
import time
from datetime import datetime, timezone
from collections import defaultdict, deque

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import grids, housekeeping, imgtools, netguard, render, share, storage, uploads
from backend.cache import cache
from backend.logutil import brief
from backend.config import (app_url_for, base_url_for, cors_origins, frontend_url, max_cells, public_base_url, public_mode,
                            rate_limit_per_minute, share_budget_bytes, share_limits, share_retention_days, trust_proxy)
from backend.grids import GridDoc, GridOptions
from backend.merge import merge
from backend.models import Track
from backend.sources import bandcamp, discogs, fromurl, itunes, musicbrainz, otodb, playlist, soundcloud, video

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OUTPUTS = ROOT / "outputs"
GRIDS = ROOT / "grids"
FRONTEND = ROOT / "frontend"
FONTS = ROOT / "fonts"

# /image-proxy が取得を許可するホスト（末尾一致）
IMAGE_HOST_ALLOWLIST = (
    "mzstatic.com",            # iTunes
    "sndcdn.com",              # SoundCloud
    "ytimg.com",               # YouTube サムネイル
    "nimg.jp",                 # ニコニコ動画サムネイル（nicovideo.cdn.nimg.jp）
    "nicovideo.jp",
    "hdslb.com",               # bilibili カバー画像
    "scdn.co",                 # Spotify ジャケット
    "spotifycdn.com",
    "otodb.net",               # otoDB サムネイル（cdn.otodb.net）
    "coverartarchive.org",     # MusicBrainz CAA
    "archive.org",
    "discogs.com",             # Discogs
    "bcbits.com",              # Bandcamp
    "bandcamp.com",
)
IMAGE_MAX_BYTES = 15 * 1024 * 1024
SOURCE_TIMEOUT = 20   # 1 ソースあたりの検索の上限秒。超えたソースは「失敗」扱いにして他の結果を返す
FAIL_TTL = 60         # 失敗した検索を覚えておく秒数（同じ検索の連打を外部に流さない）
_fail_log: dict[str, list] = {}   # (ソース名 + 理由) → [最後に出した時刻, その後の省略件数]。同じ失敗は 60 秒に 1 行


def _log_search_failure(name: str, reason: str) -> None:
    """同じソース・同じ理由の失敗は 60 秒に 1 行にまとめる（iTunes の遮断中などは毎秒出て読めなくなる）。"""
    key = f"{name}:{reason}"
    now = time.monotonic()
    ent = _fail_log.get(key)
    if ent and now - ent[0] < 60:
        ent[1] += 1
        return
    extra = f"（ほか {ent[1]} 件を省略）" if ent and ent[1] else ""
    _fail_log[key] = [now, 0]
    print(f"[search] {name} failed: {reason}{extra}")
_recent_fail: dict[tuple[str, str, str], tuple[float, str]] = {}   # (source, q, artist) → (時刻, busy|error)

# source 省略時はこの順で並べ、重複は先のソースを残す: iTunes > MusicBrainz > Discogs
# （iTunes は速くて安定、MusicBrainz は 1 秒 1 回の制限を全員で共有するため混雑しやすい）
SOURCES = {"itunes": itunes.search, "musicbrainz": musicbrainz.search}
if discogs.enabled():
    SOURCES["discogs"] = discogs.search
DEFAULT_SOURCES = tuple(SOURCES)
SOURCES["otodb"] = otodb.search   # 音MAD データベース。ALL には含めず、明示選択のときだけ


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
    print(f"[storage] 共有の保存先: {st.name}" + (f"（公開 URL: {st.public_url('') or '無し → バックエンドが中継'}）" if st.is_remote else ""))
    pruned = await asyncio.to_thread(cache.prune)
    if any(pruned.values()):
        print(f"[cache] pruned {pruned}")
    removed = render.prune_outputs()
    if removed:
        print(f"[outputs] removed {removed} old files")
    print(f"[public] PNG の URL は {public_base_url()}/outputs/... で返します（.env の PUBLIC_BASE_URL）")
    app.state.started_at = time.time()
    monitor = asyncio.create_task(_load_monitor()) if public_mode() else None
    seed = asyncio.create_task(_seed_share_count()) if public_mode() and st.is_remote else None
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=10),   # MusicBrainz や roxy は遅いことがある
        follow_redirects=True,
        headers={"User-Agent": os.getenv("MB_USER_AGENT", "musicgrid-local/0.1")},
    )
    try:
        yield
    finally:
        if monitor:
            monitor.cancel()
        if seed:
            seed.cancel()
        await app.state.http.aclose()
        cache.close()


app = FastAPI(title="MusicGrid Local", lifespan=lifespan)


@functools.lru_cache(maxsize=1)
def _r2_origin() -> str:
    """R2 の公開 URL のオリジン（CSP に足すための " https://…" 形式）。R2 を使っていなければ空文字。"""
    st = storage.get_storage()
    if not st.is_remote:
        return ""
    from urllib.parse import urlsplit
    p = urlsplit(st.public_url("") or "")
    return f" {p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""

# ---------- 描画は専用の 1 本の低優先度スレッドで直列に ----------
# 無料ホスト（0.1 vCPU）では描画（画像デコード・PNG 圧縮）が重なるとイベントループが CPU を取れず、
# Render のヘルスチェック（5 秒）に落ちて再起動される。同時に 1 件だけ描き、待ちが多ければ 503 で断る
from concurrent.futures import ThreadPoolExecutor

_RENDER_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="render", initializer=render.lower_thread_priority)
MAX_RENDER_QUEUE = 2   # サーバー描画（フォールバック）は 1 件 40〜80 秒かかる。待たせるより早めに断る
_render_waiting = [0]


async def run_render(fn, *args):
    if _render_waiting[0] >= MAX_RENDER_QUEUE:
        raise HTTPException(503, "共有の生成が混み合っています。30 秒ほど待ってからもう一度お試しください", headers={"Retry-After": "30"})
    _render_waiting[0] += 1
    try:
        return await asyncio.get_running_loop().run_in_executor(_RENDER_POOL, functools.partial(fn, *args))
    finally:
        _render_waiting[0] -= 1


# ---------- 負荷の診断ログ（公開モード）。IP・検索語は含めない ----------
_stats: dict[str, list] = {}   # パス種別 → [件数, 合計秒, 最大秒, 5xx 件数]


def _stat_key(path: str) -> str:
    for prefix in ("/grids/", "/s/", "/shares/", "/uploads/", "/outputs/"):
        if path.startswith(prefix):
            return prefix + "*"
    return path


async def _load_monitor():
    """1 秒ごとにループの遅れを測り（0.5 秒超なら記録）、60 秒ごとにリクエスト集計を出す。"""
    tick = 0
    while True:
        t0 = time.monotonic()
        await asyncio.sleep(1.0)
        lag = time.monotonic() - t0 - 1.0
        if lag > 0.5:
            print(f"[loop] lag={lag:.1f}s render_queue={_render_waiting[0]}")
        tick += 1
        if tick % 600 == 0:
            # 10 分ごとに gc ＋ malloc_trim。画像中継や R2 一覧の一時バッファを glibc が抱え込み、RSS が下がらないため
            await asyncio.to_thread(render._release_memory)
        if tick % 60 == 0 and _stats:
            items = sorted(_stats.items(), key=lambda kv: -kv[1][1])
            print("[stats] " + " ".join(f"{k}:{v[0]}件/{v[1]:.1f}s/max{v[2]:.1f}s" + (f"/5xx{v[3]}" if v[3] else "") for k, v in items[:10]))
            _stats.clear()


def _wants_html(request: Request) -> bool:
    """ブラウザのアドレスバーやリンクから直接開いた要求か（fetch は Accept: */* なので JSON のまま）。"""
    return request.method in ("GET", "HEAD") and "text/html" in request.headers.get("accept", "")


def _error_response(request: Request, status: int, detail: str, headers: dict | None = None) -> Response:
    """エラーは fetch には JSON、ブラウザ遷移には案内ページ（存在しない URL・期限切れの画像・429・500 で {"detail": …} を見せない）。"""
    if _wants_html(request):
        return HTMLResponse(share.notice_html(status, base_url_for(request), app_url_for(request), detail), status_code=status, headers=headers)
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
    """raise HTTPException(...) と、ルートに無いパスの 404・メソッド違いの 405。"""
    return _error_response(request, exc.status_code, str(exc.detail), exc.headers)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> Response:
    """想定外の例外も JSON（ブラウザ遷移なら案内ページ）で返す（フロントが「Internal Server Error」の生テキストを JSON として
    読もうとして失敗しないように）。原因はサーバーログに残す。"""
    import traceback
    if isinstance(exc, ClientDisconnect):   # 利用者が送信途中で離脱しただけ（アプリ内ブラウザや回線切替）。トレースバック不要
        print(f"[error] {request.method} {request.url.path}: 送信途中で切断")
        return JSONResponse({"detail": "送信が途中で切れました"}, status_code=400)
    print(f"[error] {request.method} {request.url.path}: {exc!r}")
    print("".join(traceback.format_exception(exc)))
    return _error_response(request, 500, f"サーバー内部でエラーが起きました（{type(exc).__name__}）。時間をおいて再試行しても直らない場合は連絡先へ")


if cors_origins():
    # GitHub Pages など別オリジンのフロントから呼べるようにする（Cookie は使わないので credentials は不要）
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"], max_age=600)

# ---------- 簡易レートリミット（IP ごと・1 分間の回数。公開時の連打・スクレイピング対策） ----------
_RATE_PATHS = ("/search", "/from-url", "/from-playlist", "/bandcamp", "/upload", "/share", "/share/upload", "/render", "/grids")
_hits: dict[str, deque] = defaultdict(deque)
# 共有の 1 日あたり回数（IP ごと／全体）。プロセス内カウンタ。日付が変わるとリセット
_share_day = {"date": "", "per_ip": defaultdict(int), "total": 0}


_IP_SALT = secrets.token_bytes(16)   # 起動ごとに変わる。IP を復元できない形で数えるためだけに使う


def _client_ip(request: Request) -> str:
    """回数制限のキー。生の IP は保持せず、プロセス限りの乱数と混ぜたハッシュにする。
    TRUST_PROXY=1 のときはプロキシが付けたヘッダから利用者の IP を取る。
    Render は Cloudflare の後ろにいるので、X-Forwarded-For の末尾は Cloudflare のエッジ IP になる。
    末尾を使うと利用者全員が数個のキーに集約され、初めての人でも「1 日 20 回」に当たってしまう。
    そこで Cloudflare が必ず付け直す CF-Connecting-IP（無ければ True-Client-IP）を優先し、
    どちらも無ければ X-Forwarded-For の先頭（Render の仕様: 先頭が利用者の IP）を使う。
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
        print(f"[share] quota: 端末の上限 {per_ip} 回 → 429")
        raise HTTPException(429, f"この端末からの共有は 1 日 {per_ip} 回までです。明日またお試しください")
    if per_day and _share_day["total"] >= per_day:
        print(f"[share] quota: 全体の上限 {per_day} 回（本日 {_share_day['total']} 件）→ 429")
        raise HTTPException(429, f"本日の共有回数がサーバー全体の上限（{per_day} 回）に達しました。明日またお試しください")


async def _seed_share_count() -> None:
    """起動時に今日の共有数を保存先の一覧から数え、全体カウンタに入れる（プロセス内カウンタはデプロイ・再起動で 0 に戻るため。
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
    print(f"[share] 本日の共有数を復元: {_share_day['total']} 件（上限 {share_limits()[1] or '無制限'}）")


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
        s = _stats.setdefault(_stat_key(request.url.path), [0, 0.0, 0.0, 0])
        s[0] += 1
        s[1] += dt
        s[2] = max(s[2], dt)
        if status >= 500:
            s[3] += 1


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # 大きすぎるボディは読む前に断る（メモリ・ディスク消費を抑える）。ブラウザの fetch は必ず Content-Length を付ける
    if request.method in ("POST", "PUT"):
        cap = _BODY_LIMIT_UPLOAD if request.url.path in ("/upload", "/share/upload") else _BODY_LIMIT_JSON
        cl = request.headers.get("content-length")
        if cl is None or not cl.isdigit():
            return JSONResponse({"detail": "Content-Length が必要です"}, status_code=411)
        if int(cl) > cap:
            return JSONResponse({"detail": f"リクエストが大きすぎます（{cap // (1024*1024)}MB まで）"}, status_code=413)
    request.state.csp_nonce = secrets.token_urlsafe(16)
    limit = rate_limit_per_minute()
    if limit and request.url.path.startswith(_RATE_PATHS):
        ip = _client_ip(request)   # プロキシのヘッダを信頼するのは TRUST_PROXY=1 のときだけ
        now = time.monotonic()
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return JSONResponse({"detail": "リクエストが多すぎます。1 分ほど待ってからもう一度お試しください"}, status_code=429, headers={"Retry-After": "60"})
        q.append(now)
        if len(_hits) > 5000:  # メモリが膨らまないように古い IP を捨てる
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60][:1000]:
                _hits.pop(k, None)
    response = await call_next(request)
    if request.url.path.startswith("/fonts/"):
        # 同梱フォント（合計 2.6 MB の WOFF2）は変わらないので長くキャッシュさせる。アプリ内ブラウザでも 2 回目以降は読み直さない
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    # CSP: スクリプトはこのサーバーが埋めた nonce 付きのものだけ。画像は同一オリジン＋R2 の公開 URL（https:）＋Canvas の blob/data
    # 304 には付けない: ブラウザは 304 のヘッダーでキャッシュ済み応答のヘッダーを更新するので、新しい nonce の CSP が
    # 古い本文（古い nonce）に適用されてスクリプトが止まる。付けなければキャッシュ済みの CSP（本文と一致）がそのまま残る
    if response.status_code != 304:
      # フォントと画像を R2 から配るときは、その公開 URL だけを font-src / connect-src に足す
      # （外部の任意のホストを開くわけではない。自分のバケット 1 つだけ）
      r2 = _r2_origin()
      response.headers.setdefault("Content-Security-Policy",
        f"default-src 'self'; script-src 'nonce-{request.state.csp_nonce}'; style-src 'self' 'unsafe-inline'; "
        # connect-src: iTunes と MusicBrainz（＋Cover Art Archive → archive.org へリダイレクト）の検索はブラウザから直接叩く
        # （サーバーの共有 IP が Apple に遮断され、MusicBrainz にはレート制限されるため）
        f"img-src 'self' data: blob: https:; connect-src 'self' https://itunes.apple.com https://musicbrainz.org https://coverartarchive.org https://archive.org https://*.archive.org https://*.mzstatic.com{r2}; font-src 'self'{r2}; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'self'")
    if public_mode() and request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response
app.mount("/outputs", StaticFiles(directory=OUTPUTS, check_dir=False), name="outputs")
app.mount("/fonts", StaticFiles(directory=FONTS, check_dir=False), name="fonts")
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
    # R2 のときはバックエンドが中継する（JSON は CORS を気にせず読めるように常にこちら。PNG は公開 URL があればそちらを案内）
    @app.get("/shares/{fname}")
    async def share_file(fname: str) -> Response:
        sid, _, ext = fname.rpartition(".")
        if ext == "jpg" and sid.endswith("-og"):
            sid = sid[:-3]
        if ext not in ("png", "json", "jpg") or not share.valid_id(sid):
            raise HTTPException(404, "not found")
        data = await run_in_threadpool(storage.get_storage().get, fname)
        if data is None:
            raise HTTPException(404, "この共有は見つかりません（期限切れの可能性）")
        # JSON は charset を明示する（付けないと端末によっては既定の文字コードで開かれ、曲名が文字化けする）
        return Response(content=data, media_type={"png": "image/png", "jpg": "image/jpeg"}.get(ext, "application/json;charset=utf-8"),
                        headers={"Cache-Control": "public, max-age=86400"})


_FONT_CSS_FALLBACK = """
@font-face { font-family: "IBM Plex Sans JP"; font-weight: 400; font-style: normal; font-display: swap; src: url("fonts/IBMPlexSansJP-Regular.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Sans JP"; font-weight: 700; font-style: normal; font-display: swap; src: url("fonts/IBMPlexSansJP-Bold.woff2") format("woff2"); }
@font-face { font-family: "DotGothic16"; font-weight: 400; font-style: normal; font-display: swap; src: url("fonts/DotGothic16-Regular.woff2") format("woff2"); }
"""


FONTS_R2_PREFIX = "fonts/"
# フォントを R2 から配るか（既定は有効）。公開 URL と R2 が無ければ自動でこのサーバーから配る
FONTS_FROM_R2 = os.getenv("FONTS_FROM_R2", "1") not in ("0", "false", "no")


def _fonts_r2_base() -> str:
    """R2 に置いたフォントの公開 URL の先頭。使えないときは空文字。"""
    if not FONTS_FROM_R2:
        return ""
    st = storage.get_storage()
    if not st.is_remote:
        return ""
    return (st.public_url(FONTS_R2_PREFIX) or "").rstrip("/")


@app.get("/fonts-css/{name}")
async def fonts_css(name: str) -> Response:
    """分割フォントの CSS。中の src を R2 の公開 URL に差し替えて返す。

    フォントは新規の訪問 1 回あたり 210KB（実測）で、Render の転送量の大半を占めていた。
    前段の Cloudflare は Web Service の応答をキャッシュしないため、訪問のたびにここから出ていく。
    R2 は転送量が無料なので、断片の URL だけそちらに向ける（CSS 自体は 12KB と小さい）。
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
    """分割フォントの @font-face を読む <link>（scripts/build_fonts.py が生成した fonts/split/fonts.<hash>.css。
    ハッシュ名なので 1 年キャッシュに乗る）。無ければフル版の @font-face を埋め込む。"""
    hashed = sorted((FONTS / "split").glob("fonts.*.css")) if (FONTS / "split").is_dir() else []
    if hashed:
        # 断片を R2 から配るときは、src を書き換えた CSS を返す /fonts-css/ 経由にする
        path = f"fonts-css/{hashed[-1].name}" if _fonts_r2_base() else f"fonts/split/{hashed[-1].name}"
        return f'<link rel="stylesheet" href="{path}">'
    print("[fonts] fonts/split/fonts.<hash>.css が無いのでフル版のフォントを配ります（python scripts/build_fonts.py で生成）")
    return f"<style>{_FONT_CSS_FALLBACK}</style>"


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    # OG タグの絶対 URL（__BASE__）をこのサーバーの URL に置き換えて配る
    html = (FRONTEND / "index.html").read_text(encoding="utf-8").replace("__BASE__", base_url_for(request))
    html = html.replace("__PUBLIC__", "1" if public_mode() else "0")   # /status が遮断されても公開モードだと分かるように
    html = html.replace("__RETENTION__", str(share_retention_days()))   # 共有が消えるまでの日数（説明文）
    html = html.replace("<!--__FONT_LINK__-->", _font_head(), 1)   # 分割フォントの @font-face（<link>）
    # Google Search Console の所有権確認（HTML タグ方式）。GOOGLE_SITE_VERIFICATION が無ければタグごと消す
    token = os.getenv("GOOGLE_SITE_VERIFICATION", "").strip()
    html = html.replace("<!--__VERIFY__-->", f'<meta name="google-site-verification" content="{token}">' if token else "", 1)
    # ETag は nonce を入れる前の内容から作る（nonce は毎回変わる）。ブラウザが同じ ETag を持っていれば 304 で本文（約 40KB）を省く。
    # 304 には CSP ヘッダーを付けない（付けるとキャッシュ済み本文の nonce と食い違ってスクリプトが止まる。middleware 側で除外）
    etag = '"' + hashlib.sha256(html.encode("utf-8")).hexdigest()[:16] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    html = html.replace("<script>", f'<script nonce="{request.state.csp_nonce}">', 1)   # CSP（script-src 'nonce-…'）用
    return HTMLResponse(html, headers={"Cache-Control": "no-cache", "ETag": etag})   # no-cache = 毎回 ETag で確認（更新をすぐ配る）


@app.get("/ads.txt")
async def ads_txt() -> Response:
    """AdSense に出す広告枠の販売許可（IAB の ads.txt）。ルート直下に置く決まり。
    公開されることが前提のファイルなので、publisher ID を書いてよい。"""
    body = "google.com, pub-6662407728160305, DIRECT, f08c47fec0942fa0\n"
    return Response(body, media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/robots.txt")
async def robots(request: Request) -> Response:
    """トップは索引してよい。API・画像・共有の中身はクロール対象から外す"""
    body = "\n".join([
        "User-agent: *",
        "Allow: /$",
        "Disallow: /search", "Disallow: /from-url", "Disallow: /from-playlist", "Disallow: /image-proxy", "Disallow: /grids", "Disallow: /shares",
        "Disallow: /uploads", "Disallow: /outputs", "Disallow: /health", "Disallow: /render", "Disallow: /upload", "Disallow: /share",
        f"Sitemap: {base_url_for(request)}/sitemap.xml", "",
    ])
    return Response(body, media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/sitemap.xml")
async def sitemap(request: Request) -> Response:
    base = base_url_for(request)
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{base}/</loc><changefreq>weekly</changefreq></url></urlset>\n")
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


@app.get("/no-cover.png")
async def no_cover_png() -> FileResponse:
    """ジャケットが無い曲のマスに使う画像（scripts/build_icons.py が作る）。"""
    return FileResponse(FRONTEND / "no-cover.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/apple-touch-icon.png")
async def apple_touch_icon() -> FileResponse:
    return FileResponse(FRONTEND / "apple-touch-icon.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/health")
@app.get("/status")   # Web はこちらを使う。EasyPrivacy に「||onrender.com/health」があり、広告ブロッカー入りのブラウザ（Vivaldi など）は /health を遮断する
async def health() -> dict:
    # started_at / uptime_s: デプロイ無しの再起動（ディスク初期化）をログ無しで切り分けるため
    # itunes_server: サーバー経由の iTunes が Apple に制限されているか（Web はブラウザから直接叩くので参考情報）
    common = {
        "ok": True,
        "sources": sorted(SOURCES),
        "started_at": datetime.fromtimestamp(app.state.started_at, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "uptime_s": int(time.time() - app.state.started_at),
        "itunes_server": "blocked" if itunes.is_blocked() else "ok",
        "itunes_proxy": bool(itunes.proxy_url()),   # サーバー側 iTunes を Cloudflare Workers 経由にしているか
        "frontend_url": frontend_url(),
        "storage": storage.get_storage().name,
    }
    if public_mode():
        # 公開時は内部情報（キャッシュのパス、内部 IP、グリッド名）を出さない。
        # 常駐メモリはログにだけ出す。Render のヘルスチェック（約 5 秒おき）でも呼ばれるので、出力は 60 秒に 1 回に間引く
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


@app.get("/search")
async def search(
    q: str = Query("", description="曲名", max_length=200),
    artist: str = Query("", description="アーティスト名", max_length=200),
    source: str | None = Query(None, description="itunes|musicbrainz|discogs|otodb。省略時は横断（otodb は含まない）"),
    nocache: bool = Query(False, description="true でキャッシュを使わず取り直す（公開モードでは無視）"),
) -> JSONResponse:
    if public_mode():
        nocache = False
    if not (q.strip() or artist.strip()):
        raise HTTPException(400, "q または artist を指定してください")
    if source:
        names = [s for s in source.split(",") if s]
        unknown = [s for s in names if s not in SOURCES]
        if unknown:
            raise HTTPException(400, f"未知のソース: {unknown}")
    else:
        names = list(DEFAULT_SOURCES)

    results, failed = await search_sources(names, q, artist, nocache=nocache)
    out: list[Track] = []
    for res in results:
        out.extend(res)
    tracks = merge(out) if len(names) > 1 else out
    headers = {}
    if failed:
        # 失敗したソースをフロントに知らせる（ヘッダは ASCII のみ）。例: "musicbrainz=busy,itunes=error"
        headers["X-Search-Failed"] = ",".join(f"{n}={k}" for n, k in failed.items())
    return JSONResponse([t.model_dump() for t in tracks], headers=headers)


async def search_sources(names: list[str], q: str, artist: str, *, nocache: bool = False) -> tuple[list[list[Track]], dict[str, str]]:
    """ソースごとにキャッシュを引き、無いものだけ並列で取りに行く。失敗したソースは空扱いにし、名前と理由（busy/error）を返す。"""
    failed: dict[str, str] = {}
    results: list[list[Track] | None] = [None] * len(names)
    now = time.monotonic()
    if not nocache:
        for i, name in enumerate(names):
            hit = await asyncio.to_thread(cache.get_search, name, q, artist)
            if hit is not None:
                results[i] = [Track.model_validate(t) for t in hit]
                continue
            # 直前に失敗した同じ検索は外部に聞き直さない（同じ検索の連打で iTunes / MusicBrainz を叩き続けないため）
            recent = _recent_fail.get((name, q, artist))
            if recent and now - recent[0] < FAIL_TTL:
                results[i] = []
                failed[name] = recent[1]
    misses = [i for i, r in enumerate(results) if r is None]
    if misses:
        client = app.state.http
        fetched = await asyncio.gather(
            *(asyncio.wait_for(SOURCES[names[i]](q, artist, client=client), timeout=SOURCE_TIMEOUT) for i in misses), return_exceptions=True
        )
        for i, res in zip(misses, fetched):
            if isinstance(res, BaseException):
                # 1ソースの失敗で全体を落とさない。失敗は永続キャッシュには入れず、FAIL_TTL 秒だけ覚える
                _log_search_failure(names[i], brief(res))
                results[i] = []
                failed[names[i]] = "busy" if isinstance(res, (musicbrainz.SourceBusy, itunes.SourceBlocked, asyncio.TimeoutError)) or "503" in str(res) else "error"
                _recent_fail[(names[i], q, artist)] = (now, failed[names[i]])
                if len(_recent_fail) > 500:
                    for k in [k for k, v in _recent_fail.items() if now - v[0] >= FAIL_TTL]:
                        del _recent_fail[k]
                continue
            results[i] = res
            if res:  # 空は保存しない（後からデータが増えたときや一時的な失敗で 0 件が固定されないように）
                await asyncio.to_thread(cache.set_search, names[i], q, artist, [t.model_dump() for t in res])
    return [r or [] for r in results], failed


class BandcampBody(BaseModel):
    url: str = Field(max_length=2048)


@app.post("/from-playlist", response_model=list[Track])
async def from_playlist(body: BandcampBody) -> list[Track]:
    """プレイリスト（まとめ）の URL から複数曲を取る。ニコニコのマイリスト、SoundCloud のセット、
    bilibili の収藏夹、Spotify のプレイリストなど。単体の URL は /from-url のまま。"""
    url = body.url.strip()
    if not playlist.is_playlist(url):
        raise HTTPException(400, "プレイリストの URL ではありません")
    try:
        return await playlist.fetch(url, client=app.state.http)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"{playlist.label(url)} が {e.response.status_code} を返しました") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"取得失敗: {e}") from e


@app.post("/from-url", response_model=Track)
@app.post("/bandcamp", response_model=Track)   # 旧名。互換のため残す
async def from_url(body: BandcampBody) -> Track:
    """Bandcamp / SoundCloud / YouTube / ニコニコ動画 / bilibili / Spotify の URL からジャケット（サムネイル）・曲名・アーティストを取る。"""
    url = body.url.strip()
    label, _ = fromurl.resolve(url)
    try:
        return await fromurl.fetch(url, client=app.state.http)   # 直接取れなければ roxy にフォールバックする
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"{label} が {e.response.status_code} を返しました") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"取得失敗: {e}") from e


def _host_allowed(url: str) -> bool:
    """許可ホスト（末尾一致）か公開アドレスだけ。私設・ループバック宛て（SSRF）は拒否。リダイレクト先も netguard が検査する。"""
    return netguard.url_ok(url, IMAGE_HOST_ALLOWLIST)


IMAGE_R2_PREFIX = "imgcache/"
# 画像を R2 へ寄せるか（既定は有効）。R2 が無い・公開 URL が無い環境では自動で無効になる
IMAGE_TO_R2 = os.getenv("IMAGE_TO_R2", "1") not in ("0", "false", "no")
_IMG_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def _image_r2_key(url: str, ctype: str) -> str:
    """取得元 URL から R2 のキーを作る。同じ画像は同じキーになる。"""
    return f"{IMAGE_R2_PREFIX}{hashlib.sha1(url.encode('utf-8')).hexdigest()[:20]}.{_IMG_EXT.get(ctype, 'bin')}"


async def _image_r2_redirect(url: str) -> Response | None:
    """R2 に寄せ済みならそこへ 302。まだなら None（呼び出し元が本体を返す）。

    画像 1 枚 77KB に対してリダイレクトの応答は数百バイトなので、Render の転送量（課金対象）が
    ほぼ無くなる。ブラウザは fetch + createImageBitmap で読むため、R2 側の CORS と
    CSP の connect-src（_r2_origin）が要る。どちらもフォントを R2 に移したときに整えてある。
    """
    if not IMAGE_TO_R2:
        return None
    key = await asyncio.to_thread(cache.get_image_r2key, url)
    if not key:
        return None
    public = storage.get_storage().public_url(key)
    if not public:
        return None
    return RedirectResponse(public, status_code=302, headers={"Cache-Control": "public, max-age=86400"})


async def _image_to_r2(url: str, ctype: str, data: bytes) -> None:
    """画像を R2 に置き、次からは 302 で返せるようにする。失敗しても本体は返せるので握りつぶす。"""
    st = storage.get_storage()
    if not IMAGE_TO_R2 or not st.is_remote or not st.public_url(""):
        return
    key = _image_r2_key(url, ctype)
    try:
        await asyncio.to_thread(st.put, key, data, ctype)
        await asyncio.to_thread(cache.mark_image_r2, url, key)
    except Exception as e:
        print(f"[error] 画像を R2 に置けませんでした: {type(e).__name__}: {e}")


@app.get("/image-proxy")
async def image_proxy(url: str = Query(..., description="取得する画像URL", max_length=2048),
                      px: int = Query(0, ge=0, le=2000, description="欲しい実寸（マスが小さいときだけ指定する）")) -> Response:
    """外部画像を同一オリジンで返す（Canvas の CORS/tainted 回避）。取得結果は SQLite にキャッシュ。

    二度目以降は本体を返さず R2 へ 302 で送る（_image_r2_redirect）。IMAGE_TO_R2=0 で止められる。
    """
    if uploads.is_upload_url(url):
        got = await run_in_threadpool(uploads.read_bytes, url)
        if got is None:
            raise HTTPException(404, "アップロード画像が見つかりません（期限切れの可能性）")
        return Response(content=got[0], media_type=got[1], headers={"Cache-Control": "public, max-age=86400"})
    if not await asyncio.to_thread(_host_allowed, url):   # 許可ホスト以外は名前解決（同期）を伴うのでスレッドで
        raise HTTPException(403, "このホストの画像は取得できません（私設アドレスや解決できないホスト）")
    # 保存済みのグリッドが持つ大きすぎる URL（iTunes の 1000x1000、Bandcamp と bilibili の原寸）を
    # 欲しい実寸に合わせて取り直す。ホストは変わらないので検査の後でよい。
    # px はマスが小さいとき（8x8 以上）にブラウザが指定する。既定は書き出しのマスと同じ 600
    want = max(100, min(600, px or 600))
    for _src in (itunes, bandcamp, video, soundcloud, musicbrainz):
        url = _src.clamp_size(url, want)
    # otoDB だけは URL に大きさを指定できないので、取ったあとにこちらで縮める。
    # 大きさごとに別のキャッシュになるので、刻みを 200px 単位にして種類を 3 つ（200/400/600）に抑える
    shrink_px = min(600, -(-want // 200) * 200) if otodb.is_otodb_image(url) else 0
    ckey = f"{url}#px={shrink_px}" if shrink_px else url   # キャッシュと R2 のキー。取得元は url のまま
    if (redirect := await _image_r2_redirect(ckey)) is not None:
        return redirect
    hit = await asyncio.to_thread(cache.get_image, ckey)
    if hit:
        ctype, data = hit
        await _image_to_r2(ckey, ctype, data)   # 既にキャッシュ済みの分も、一度返すついでに R2 へ寄せる
    else:
        # 配信元からの取得の同時本数を IMAGE_PROXY_CONCURRENCY で絞る（既定 16）。
        # 取りこぼすと 503 になるので、CPU の割当を変えたらこちらも見直す（0.1 vCPU の頃は 8 本だった）
        try:
            await asyncio.wait_for(_PROXY_SEM.acquire(), timeout=20)
        except asyncio.TimeoutError:
            raise HTTPException(503, "画像の取得が混み合っています", headers={"Retry-After": "5"})
        try:
            ctype, data = await fetch_image(url)
            if imgtools.is_video_thumb(url):
                # 動画サムネイルの黒帯（レターボックス）を落とす。プレビューと書き出しで同じ見た目になる
                data, ctype = await asyncio.to_thread(imgtools.trim_letterbox_bytes, data, ctype)
            if shrink_px:
                data, ctype = await asyncio.to_thread(imgtools.shrink_bytes, data, ctype, shrink_px)
            await asyncio.to_thread(cache.set_image, ckey, ctype, data)
        finally:
            _PROXY_SEM.release()
        await _image_to_r2(ckey, ctype, data)
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})


_PROXY_SEM = asyncio.Semaphore(max(1, int(os.getenv("IMAGE_PROXY_CONCURRENCY", "16"))))


async def fetch_image(url: str) -> tuple[str, bytes]:
    """画像を取得して (content-type, bytes) を返す。失敗は HTTPException。"""
    client: httpx.AsyncClient = app.state.http
    try:
        # 画像 CDN の中には汎用 UA を弾くものがある（Wikimedia 等）ためブラウザ風にする。リダイレクトは 1 ホップずつ宛先を検査
        r = await netguard.safe_get(client, url, allowlist=IMAGE_HOST_ALLOWLIST,
                                    headers={"User-Agent": "Mozilla/5.0 (compatible; trackmento/0.1)", "Accept": "image/*,*/*;q=0.8"})
    except netguard.BlockedURL as e:
        raise HTTPException(403, str(e)) from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"取得失敗: {e}") from e
    if r.status_code != 200:
        raise HTTPException(502, f"画像サーバーが {r.status_code} を返しました")
    ctype = r.headers.get("content-type", "").split(";")[0].strip()
    if not ctype.startswith("image/"):
        raise HTTPException(415, f"画像ではありません: {ctype}")
    if len(r.content) > IMAGE_MAX_BYTES:
        raise HTTPException(413, "画像が大きすぎます")
    return ctype, r.content


# ---------- グリッド JSON（CLI と Web で共有） ----------
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
        raise HTTPException(404, f"グリッド {name} はまだありません")
    try:
        return grids.load(name)
    except ValueError as e:
        raise HTTPException(500, str(e)) from e


@app.put("/grids/{name}", response_model=GridDoc)
async def grid_put(name: str, doc: GridDoc) -> GridDoc:
    """Web の自動保存と JSON 読み込みが呼ぶ。savedAt が無ければ今の時刻を入れる。"""
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


def _rss_mb() -> float | None:
    """このプロセスの常駐メモリ（MB）。Linux 以外は None。"""
    try:
        with open("/proc/self/statm") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError, AttributeError, IndexError):
        return None


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
    # 以下は省略可。指定したものだけグリッドのオプションを上書きし、グリッド JSON にも保存する
    size: str | None = None          # "3x3"
    ratio: str | None = None
    sidebar: bool | None = None
    title: str | None = None
    showTitle: bool | None = None
    numbers: bool | None = None
    bg: str | None = None
    bgCustom: str | None = None
    margin: int | None = None
    gap: int | None = None
    # Web が /share で並びをそのまま送る用。サーバーのディスクが消えていても（Render の再起動など）共有できるようにする
    doc: GridDoc | None = None


def _check_cells(doc: GridDoc) -> None:
    limit = max_cells()
    if limit and doc.size > limit:
        raise HTTPException(400, f"公開サーバーでは 1 枚あたり {limit} マスまでです（今は {doc.cols}×{doc.rows}）")


def apply_render_options(doc: GridDoc, body: RenderBody) -> bool:
    """body の指定を doc に反映。変更があれば True。"""
    changed = False
    if body.size:
        try:
            c, r = (int(v) for v in body.size.lower().split("x"))
        except ValueError as e:
            raise HTTPException(400, "size は 3x3 のように指定してください") from e
        if (c, r) != (doc.cols, doc.rows):
            doc.resize(max(1, min(grids.MAX_COLS, c)), max(1, min(grids.MAX_ROWS, r)))
            changed = True
    if body.title is not None and body.title != doc.title:
        doc.title = body.title[:60]
        changed = True
    opts = doc.options.model_dump()
    for k in ("ratio", "sidebar", "showTitle", "numbers", "bg", "bgCustom", "margin", "gap"):
        v = getattr(body, k)
        if v is not None and v != opts.get(k):
            opts[k] = v
            changed = True
    if body.bgCustom and body.bg is None:
        opts["bg"] = "custom"
    if changed:
        try:
            doc.options = GridOptions.model_validate(opts)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return changed


@app.post("/render")
async def render_grid(request: Request, body: RenderBody = Body(default_factory=RenderBody)) -> dict:
    if public_mode():
        raise HTTPException(404, "公開モードでは /render は使えません（「トラックを共有」を使ってください）")
    name = _grid_name(body.grid)
    try:
        doc = grids.load(name)
    except ValueError as e:
        raise HTTPException(500, str(e)) from e
    if not any(doc.cells):
        raise HTTPException(400, f"グリッド {name} に曲がありません")
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
    """PC やスマホの画像ファイルを uploads/ に保存し、Track.image に入れる相対 URL を返す。"""
    data = await file.read(uploads.MAX_BYTES + 1)
    if len(data) > uploads.MAX_BYTES:
        raise HTTPException(413, "画像が大きすぎます（15MB まで）")
    if not data:
        raise HTTPException(400, "ファイルが空です")
    try:
        url = await run_in_threadpool(uploads.save_image_bytes, data)
    except ValueError as e:
        raise HTTPException(415, str(e)) from e
    return {"url": url, "absolute": f"{base_url_for(request)}{url}"}


# ---------- トラックを共有（PNG + 並びのスナップショット + 共有ページ） ----------
def _doc_for_share(body: RenderBody) -> GridDoc:
    """共有する並びを決める。ブラウザが持っている並び（doc）を正とし、無ければサーバーの JSON を読む。"""
    name = _grid_name(body.grid)
    if body.doc is not None:
        # ブラウザが持っている並びを正とする（サーバー側の JSON は再起動で消えていることがある）
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
        raise HTTPException(400, f"グリッド {name} に曲がありません")
    if apply_render_options(doc, body):
        doc.touch()
        grids.save(doc)
    _check_cells(doc)
    return doc


async def _finish_share(request: Request, coro) -> dict:
    """保存処理（coroutine）を実行し、回数を数え、共有 URL を付けて返す。失敗の扱いは共通。"""
    try:
        info = await coro
    except HTTPException:
        raise   # 待ち行列の上限（503）など
    except share.BudgetExceeded as e:
        raise HTTPException(507, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    except Exception as e:  # R2 への保存失敗など
        import traceback
        print(f"[share] failed: {e!r}")
        print(traceback.format_exc())
        raise HTTPException(502, f"共有の保存に失敗しました（{type(e).__name__}）。少し待ってからもう一度お試しください") from e
    _count_share(request)
    if public_mode() and not storage.get_storage().is_remote:
        housekeeping.prune_shares()   # R2 のときはバケットのライフサイクルルールに任せる
    base = base_url_for(request)
    img_abs = info["image"] if info["image"].startswith("http") else f"{base}{info['image']}"
    return {**info, "url": f"{base}/s/{info['id']}", "image_url": img_abs, "png_url": img_abs}   # png_url は旧キー


@app.post("/share")
async def share_grid(request: Request, body: RenderBody = Body(default_factory=RenderBody)) -> dict:
    """サーバーで描いて共有する（CLI と、ブラウザ描画ができない端末のフォールバック）。"""
    doc = _doc_for_share(body)
    _check_share_quota(request)
    budget = share_budget_bytes() if (public_mode() or storage.get_storage().is_remote) else 0
    return await _finish_share(request, run_render(share.create, doc, budget))


_UPLOAD_SEM = asyncio.Semaphore(3)   # 同時に受け付ける共有アップロード。超えたら待たせず 503（本文を抱えたまま並ぶとメモリが膨らむ）


@app.post("/share/upload")
async def share_upload(request: Request) -> dict:
    """ブラウザで描いた本体画像（JPEG。古いタブからは PNG）とカード用 JPEG を受け取って共有する。サーバーはヘッダ検査と保存だけ
    （無料ホストの 0.1 vCPU では描画がヘルスチェックを止めるため、描画は端末側で行う）。
    フォーム: doc（JSON 文字列）, image（旧名 png）, og"""
    _check_share_quota(request)   # 本文（数 MB）を読む前に断る。上限到達中に受け取ってから 429 にしない
    if _UPLOAD_SEM.locked():
        raise HTTPException(503, "共有が混み合っています。10 秒ほど待ってからもう一度お試しください", headers={"Retry-After": "10"})
    async with _UPLOAD_SEM:
        try:
            form = await request.form()
        except ClientDisconnect:   # 利用者が送信途中で離脱（アプリ内ブラウザや回線切替）。サーバー側の異常ではないので 5xx にしない
            print("[share] 送信途中で切断（利用者側の離脱）")
            raise HTTPException(400, "送信が途中で切れました。もう一度お試しください")
        doc, image, og = form.get("doc"), form.get("image") or form.get("png"), form.get("og")
        if not isinstance(doc, str) or not isinstance(image, StarletteUploadFile) or not isinstance(og, StarletteUploadFile):   # request.form() が返すのは starlette の UploadFile
            raise HTTPException(400, "並び（doc）と画像（image, og）が必要です")
        try:
            raw = json.loads(doc)   # {"grid": "u-…", "doc": {...}}（/share の JSON ボディと同じ形）
            body = RenderBody(grid=raw.get("grid", "default"), doc=GridDoc.model_validate(raw["doc"]))
        except Exception as e:
            raise HTTPException(400, f"並びの JSON が不正です（{type(e).__name__}）") from e
        gdoc = _doc_for_share(body)
        img_b = await image.read(share.MAX_UPLOAD_IMAGE + 1)
        og_b = await og.read(share.MAX_UPLOAD_OG + 1)
        try:
            w, h, ext = await asyncio.to_thread(share.check_uploaded, img_b, og_b)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        _check_share_quota(request)
        budget = share_budget_bytes() if (public_mode() or storage.get_storage().is_remote) else 0
        return await _finish_share(request, run_in_threadpool(share.store, gdoc, img_b, og_b, w, h, budget, ext))


@app.get("/s/{sid}", response_class=HTMLResponse)
async def share_page(request: Request, sid: str) -> HTMLResponse:
    # share.load は R2 への同期 GET。ループ内で呼ぶと閲覧が重なったときにサーバー全体が止まり、
    # Render のヘルスチェック（5 秒）に落ちて再起動される
    snap = await run_in_threadpool(share.load, sid)
    if not snap:
        # JSON の 404 だと X から開いた人に何が起きたか伝わらない。案内ページ（期限切れ・作り直し）を返す
        return HTMLResponse(share.expired_html(sid, base_url_for(request), app_url_for(request)), status_code=404)
    return HTMLResponse(share.page_html(snap, base_url_for(request), app_url_for(request)))
