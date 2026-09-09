"""FastAPI エントリポイント。起動: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import grids, render, share, uploads
from backend.cache import cache
from backend.config import public_base_url
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

# ALL（source 省略時）はこの順で並べ、重複は先のソースを残す: MusicBrainz > Discogs > iTunes
SOURCES = {"musicbrainz": musicbrainz.search}
if discogs.enabled():
    SOURCES["discogs"] = discogs.search
SOURCES["itunes"] = itunes.search
DEFAULT_SOURCES = tuple(SOURCES)
SOURCES["otodb"] = otodb.search   # 音MAD データベース。ALL には含めず、明示選択のときだけ


@asynccontextmanager
async def lifespan(app: FastAPI):
    OUTPUTS.mkdir(exist_ok=True)
    GRIDS.mkdir(exist_ok=True)
    uploads.UPLOADS.mkdir(exist_ok=True)
    share.SHARES.mkdir(exist_ok=True)
    pruned = await asyncio.to_thread(cache.prune)
    if any(pruned.values()):
        print(f"[cache] pruned {pruned}")
    removed = render.prune_outputs()
    if removed:
        print(f"[outputs] removed {removed} old files")
    print(f"[public] PNG の URL は {public_base_url()}/outputs/... で返します（.env の PUBLIC_BASE_URL）")
    app.state.http = httpx.AsyncClient(
        timeout=15,
        follow_redirects=True,
        headers={"User-Agent": os.getenv("MB_USER_AGENT", "musicgrid-local/0.1")},
    )
    try:
        yield
    finally:
        await app.state.http.aclose()
        cache.close()


app = FastAPI(title="MusicGrid Local", lifespan=lifespan)
app.mount("/outputs", StaticFiles(directory=OUTPUTS, check_dir=False), name="outputs")
app.mount("/fonts", StaticFiles(directory=FONTS, check_dir=False), name="fonts")
app.mount("/uploads", StaticFiles(directory=uploads.UPLOADS, check_dir=False), name="uploads")
app.mount("/shares", StaticFiles(directory=share.SHARES, check_dir=False), name="shares")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "sources": sorted(SOURCES),
        "cache": await asyncio.to_thread(cache.stats),
        "public_base_url": public_base_url(),
        "grids": grids.list_names(),
    }


@app.get("/search", response_model=list[Track])
async def search(
    q: str = Query("", description="曲名"),
    artist: str = Query("", description="アーティスト名"),
    source: str | None = Query(None, description="itunes|musicbrainz|discogs|otodb。省略時は横断（otodb は含まない）"),
    nocache: bool = Query(False, description="true でキャッシュを使わず取り直す"),
) -> list[Track]:
    if not (q.strip() or artist.strip()):
        raise HTTPException(400, "q または artist を指定してください")
    if source:
        names = [s for s in source.split(",") if s]
        unknown = [s for s in names if s not in SOURCES]
        if unknown:
            raise HTTPException(400, f"未知のソース: {unknown}")
    else:
        names = list(DEFAULT_SOURCES)

    out: list[Track] = []
    for name, res in zip(names, await search_sources(names, q, artist, nocache=nocache)):
        out.extend(res)
    return merge(out) if len(names) > 1 else out


async def search_sources(names: list[str], q: str, artist: str, *, nocache: bool = False) -> list[list[Track]]:
    """ソースごとにキャッシュを引き、無いものだけ並列で取りに行く。失敗したソースは空扱い。"""
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
            *(SOURCES[names[i]](q, artist, client=client) for i in misses), return_exceptions=True
        )
        for i, res in zip(misses, fetched):
            if isinstance(res, BaseException):
                # 1ソースの失敗で全体を落とさない。失敗はキャッシュしない
                print(f"[search] {names[i]} failed: {res!r}")
                results[i] = []
                continue
            results[i] = res
            if res:  # 空は保存しない（後からデータが増えたときや一時的な失敗で 0 件が固定されないように）
                await asyncio.to_thread(cache.set_search, names[i], q, artist, [t.model_dump() for t in res])
    return [r or [] for r in results]


class BandcampBody(BaseModel):
    url: str


@app.post("/from-url", response_model=Track)
@app.post("/bandcamp", response_model=Track)   # 旧名。互換のため残す
async def from_url(body: BandcampBody) -> Track:
    """Bandcamp / SoundCloud / YouTube / ニコニコ動画 / bilibili / Spotify の URL からジャケット（サムネイル）・曲名・アーティストを取る。"""
    url = body.url.strip()
    label, fetch = fromurl.resolve(url)
    try:
        return await fetch(url, client=app.state.http)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"{label} が {e.response.status_code} を返しました") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"取得失敗: {e}") from e


def _is_public_host(host: str) -> bool:
    """手入力の画像URL向け。私設・ループバック・リンクローカル宛て（SSRF）を拒否する。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return bool(infos)


def _host_allowed(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    if any(host == d or host.endswith("." + d) for d in IMAGE_HOST_ALLOWLIST):
        return True
    return _is_public_host(host)


@app.get("/image-proxy")
async def image_proxy(url: str = Query(..., description="取得する画像URL")) -> Response:
    """外部画像を同一オリジンで返す（Canvas の CORS/tainted 回避）。取得結果は SQLite にキャッシュ。"""
    if uploads.is_upload_url(url):
        p = uploads.local_path(url)
        if not p:
            raise HTTPException(404, "アップロード画像が見つかりません")
        return FileResponse(p, media_type=uploads.content_type(p), headers={"Cache-Control": "public, max-age=86400"})
    if not _host_allowed(url):
        raise HTTPException(403, "このホストの画像は取得できません（私設アドレスや解決できないホスト）")
    hit = await asyncio.to_thread(cache.get_image, url)
    if hit:
        ctype, data = hit
    else:
        ctype, data = await fetch_image(url)
        await asyncio.to_thread(cache.set_image, url, ctype, data)
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})


async def fetch_image(url: str) -> tuple[str, bytes]:
    """画像を取得して (content-type, bytes) を返す。失敗は HTTPException。"""
    client: httpx.AsyncClient = app.state.http
    try:
        # 画像 CDN の中には汎用 UA を弾くものがある（Wikimedia 等）ためブラウザ風にする
        r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; trackmento/0.1)", "Accept": "image/*,*/*;q=0.8"})
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
async def render_grid(body: RenderBody = Body(default_factory=RenderBody)) -> dict:
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
    try:
        path, im = await run_in_threadpool(render.render_to_file, doc)
    except RuntimeError as e:  # フォント欠落など
        raise HTTPException(500, str(e)) from e
    return {
        "url": f"{public_base_url()}/outputs/{path.name}",
        "file": path.name,
        "width": im.width,
        "height": im.height,
        "grid": doc.model_dump(),
    }


# ---------- 手入力用の画像アップロード ----------
@app.post("/upload")
async def upload_image(file: UploadFile = File(...)) -> dict:
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
    return {"url": url, "absolute": f"{public_base_url()}{url}", "name": file.filename}


# ---------- トラックを共有（PNG + 並びのスナップショット + 共有ページ） ----------
@app.post("/share")
async def share_grid(body: RenderBody = Body(default_factory=RenderBody)) -> dict:
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
    try:
        info = await run_in_threadpool(share.create, doc)
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    base = public_base_url()
    return {**info, "url": f"{base}/s/{info['id']}", "png_url": f"{base}{info['png']}"}


@app.get("/s/{sid}", response_class=HTMLResponse)
async def share_page(sid: str) -> HTMLResponse:
    snap = share.load(sid)
    if not snap:
        raise HTTPException(404, "この共有は見つかりません")
    return HTMLResponse(share.page_html(snap, public_base_url()))
