"""FastAPI エントリポイント。起動: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
import time
from collections import defaultdict, deque

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import grids, housekeeping, imgtools, netguard, render, share, storage, uploads
from backend.cache import cache
from backend.config import (app_url_for, base_url_for, cors_origins, frontend_url, max_cells, public_base_url, public_mode,
                            rate_limit_per_minute, share_budget_bytes, share_limits, trust_proxy)
from backend.grids import GridDoc, GridOptions
from backend.merge import merge
from backend.models import Track
from backend.sources import discogs, fromurl, itunes, musicbrainz, otodb

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
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=10),   # MusicBrainz や roxy は遅いことがある
        follow_redirects=True,
        headers={"User-Agent": os.getenv("MB_USER_AGENT", "musicgrid-local/0.1")},
    )
    try:
        yield
    finally:
        await app.state.http.aclose()
        cache.close()


app = FastAPI(title="MusicGrid Local", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """想定外の例外も JSON で返す（フロントが「Internal Server Error」の生テキストを JSON として読もうとして失敗しないように）。
    原因はサーバーログに残す。"""
    import traceback
    print(f"[error] {request.method} {request.url.path}: {exc!r}")
    print("".join(traceback.format_exception(exc)))
    return JSONResponse({"detail": f"サーバー内部でエラーが起きました（{type(exc).__name__}）。時間をおいて再試行しても直らない場合は連絡先へ"}, status_code=500)


if cors_origins():
    # GitHub Pages など別オリジンのフロントから呼べるようにする（Cookie は使わないので credentials は不要）
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"], max_age=600)

# ---------- 簡易レートリミット（IP ごと・1 分間の回数。公開時の連打・スクレイピング対策） ----------
_RATE_PATHS = ("/search", "/from-url", "/bandcamp", "/upload", "/share", "/render", "/grids")
_hits: dict[str, deque] = defaultdict(deque)
# 共有の 1 日あたり回数（IP ごと／全体）。プロセス内カウンタ。日付が変わるとリセット
_share_day = {"date": "", "per_ip": defaultdict(int), "total": 0}


def _client_ip(request: Request) -> str:
    ip = request.client.host if request.client else "?"
    if trust_proxy():
        xff = [v.strip() for v in (request.headers.get("x-forwarded-for") or "").split(",") if v.strip()]
        if xff:
            ip = xff[-1]
    return ip


def _check_share_quota(request: Request) -> None:
    per_ip, per_day = share_limits()
    if not per_ip and not per_day:
        return
    today = time.strftime("%Y-%m-%d")
    if _share_day["date"] != today:
        _share_day.update(date=today, per_ip=defaultdict(int), total=0)
    ip = _client_ip(request)
    if per_ip and _share_day["per_ip"][ip] >= per_ip:
        raise HTTPException(429, f"この端末からの共有は 1 日 {per_ip} 回までです。明日またお試しください")
    if per_day and _share_day["total"] >= per_day:
        raise HTTPException(429, f"本日の共有回数がサーバー全体の上限（{per_day} 回）に達しました。明日またお試しください")


def _count_share(request: Request) -> None:
    _share_day["per_ip"][_client_ip(request)] += 1
    _share_day["total"] += 1


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    limit = rate_limit_per_minute()
    if limit and request.url.path.startswith(_RATE_PATHS):
        ip = _client_ip(request)   # プロキシを信頼するのは TRUST_PROXY=1 のときだけ（先頭は偽装できるので末尾）
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
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
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
        if ext not in ("png", "json") or not share.valid_id(sid):
            raise HTTPException(404, "not found")
        data = await run_in_threadpool(storage.get_storage().get, fname)
        if data is None:
            raise HTTPException(404, "この共有は見つかりません（期限切れの可能性）")
        return Response(content=data, media_type="image/png" if ext == "png" else "application/json",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    # OG タグの絶対 URL（__BASE__）をこのサーバーの URL に置き換えて配る
    html = (FRONTEND / "index.html").read_text(encoding="utf-8").replace("__BASE__", base_url_for(request))
    return HTMLResponse(html)


@app.get("/og.png")
async def og_image() -> FileResponse:
    return FileResponse(FRONTEND / "og.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/health")
async def health() -> dict:
    if public_mode():
        # 公開時は内部情報（キャッシュのパス、内部 IP、グリッド名）を出さない
        return {"ok": True, "sources": sorted(SOURCES), "public": True, "frontend_url": frontend_url(), "storage": storage.get_storage().name}
    return {
        "ok": True,
        "sources": sorted(SOURCES),
        "cache": await asyncio.to_thread(cache.stats),
        "public_base_url": public_base_url(),
        "public": False,
        "frontend_url": frontend_url(),
        "storage": storage.get_storage().name,
        "grids": grids.list_names(),
    }


@app.get("/search")
async def search(
    q: str = Query("", description="曲名"),
    artist: str = Query("", description="アーティスト名"),
    source: str | None = Query(None, description="itunes|musicbrainz|discogs|otodb。省略時は横断（otodb は含まない）"),
    nocache: bool = Query(False, description="true でキャッシュを使わず取り直す"),
) -> JSONResponse:
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
    if not nocache:
        for i, name in enumerate(names):
            hit = await asyncio.to_thread(cache.get_search, name, q, artist)
            if hit is not None:
                results[i] = [Track.model_validate(t) for t in hit]
    misses = [i for i, r in enumerate(results) if r is None]
    if misses:
        client = app.state.http
        fetched = await asyncio.gather(
            *(asyncio.wait_for(SOURCES[names[i]](q, artist, client=client), timeout=SOURCE_TIMEOUT) for i in misses), return_exceptions=True
        )
        for i, res in zip(misses, fetched):
            if isinstance(res, BaseException):
                # 1ソースの失敗で全体を落とさない。失敗はキャッシュしない
                print(f"[search] {names[i]} failed: {res!r}")
                results[i] = []
                failed[names[i]] = "busy" if isinstance(res, (musicbrainz.SourceBusy, asyncio.TimeoutError)) or "503" in str(res) else "error"
                continue
            results[i] = res
            if res:  # 空は保存しない（後からデータが増えたときや一時的な失敗で 0 件が固定されないように）
                await asyncio.to_thread(cache.set_search, names[i], q, artist, [t.model_dump() for t in res])
    return [r or [] for r in results], failed


class BandcampBody(BaseModel):
    url: str


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


@app.get("/image-proxy")
async def image_proxy(url: str = Query(..., description="取得する画像URL")) -> Response:
    """外部画像を同一オリジンで返す（Canvas の CORS/tainted 回避）。取得結果は SQLite にキャッシュ。"""
    if uploads.is_upload_url(url):
        got = await run_in_threadpool(uploads.read_bytes, url)
        if got is None:
            raise HTTPException(404, "アップロード画像が見つかりません（期限切れの可能性）")
        return Response(content=got[0], media_type=got[1], headers={"Cache-Control": "public, max-age=86400"})
    if not _host_allowed(url):
        raise HTTPException(403, "このホストの画像は取得できません（私設アドレスや解決できないホスト）")
    hit = await asyncio.to_thread(cache.get_image, url)
    if hit:
        ctype, data = hit
    else:
        ctype, data = await fetch_image(url)
        if imgtools.is_video_thumb(url):
            # 動画サムネイルの黒帯（レターボックス）を落とす。プレビューと書き出しで同じ見た目になる
            data, ctype = await asyncio.to_thread(imgtools.trim_letterbox_bytes, data, ctype)
        await asyncio.to_thread(cache.set_image, url, ctype, data)
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})


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
    return doc


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
        path, im = await run_in_threadpool(render.render_to_file, doc)
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
    return {"url": url, "absolute": f"{base_url_for(request)}{url}", "name": file.filename}


# ---------- トラックを共有（PNG + 並びのスナップショット + 共有ページ） ----------
@app.post("/share")
async def share_grid(request: Request, body: RenderBody = Body(default_factory=RenderBody)) -> dict:
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
    _check_share_quota(request)
    try:
        info = await run_in_threadpool(share.create, doc, share_budget_bytes() if (public_mode() or storage.get_storage().is_remote) else 0)
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
    png_abs = info["png"] if info["png"].startswith("http") else f"{base}{info['png']}"
    return {**info, "url": f"{base}/s/{info['id']}", "png_url": png_abs}


@app.get("/s/{sid}", response_class=HTMLResponse)
async def share_page(request: Request, sid: str) -> HTMLResponse:
    snap = share.load(sid)
    if not snap:
        raise HTTPException(404, "この共有は見つかりません")
    return HTMLResponse(share.page_html(snap, base_url_for(request), app_url_for(request)))
