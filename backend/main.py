"""FastAPI エントリポイント。起動: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.merge import merge
from backend.models import Track
from backend.sources import bandcamp, itunes, lastfm, musicbrainz

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OUTPUTS = ROOT / "outputs"
GRIDS = ROOT / "grids"
FRONTEND = ROOT / "frontend"

# /image-proxy が取得を許可するホスト（末尾一致）
IMAGE_HOST_ALLOWLIST = (
    "mzstatic.com",            # iTunes
    "lastfm.freetls.fastly.net",  # Last.fm
    "last.fm",
    "coverartarchive.org",     # MusicBrainz CAA
    "archive.org",
    "discogs.com",             # Discogs
    "bcbits.com",              # Bandcamp
    "bandcamp.com",
)
IMAGE_MAX_BYTES = 15 * 1024 * 1024

SOURCES = {"itunes": itunes.search}
if lastfm.enabled():
    SOURCES["lastfm"] = lastfm.search
SOURCES["musicbrainz"] = musicbrainz.search
DEFAULT_SOURCES = tuple(SOURCES)  # source 省略時はこれらを並列で叩いてマージ


@asynccontextmanager
async def lifespan(app: FastAPI):
    OUTPUTS.mkdir(exist_ok=True)
    GRIDS.mkdir(exist_ok=True)
    app.state.http = httpx.AsyncClient(
        timeout=15,
        follow_redirects=True,
        headers={"User-Agent": os.getenv("MB_USER_AGENT", "musicgrid-local/0.1")},
    )
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(title="MusicGrid Local", lifespan=lifespan)
app.mount("/outputs", StaticFiles(directory=OUTPUTS, check_dir=False), name="outputs")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "sources": sorted(SOURCES)}


@app.get("/search", response_model=list[Track])
async def search(
    q: str = Query("", description="曲名"),
    artist: str = Query("", description="アーティスト名"),
    source: str | None = Query(None, description="itunes|lastfm|musicbrainz|discogs。省略時は横断"),
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

    client = app.state.http
    results = await asyncio.gather(
        *(SOURCES[n](q, artist, client=client) for n in names), return_exceptions=True
    )
    out: list[Track] = []
    for name, res in zip(names, results):
        if isinstance(res, BaseException):
            # 1ソースの失敗で全体を落とさない
            print(f"[search] {name} failed: {res!r}")
            continue
        out.extend(res)
    return merge(out) if len(names) > 1 else out


class BandcampBody(BaseModel):
    url: str


@app.post("/bandcamp", response_model=Track)
async def bandcamp_lookup(body: BandcampBody) -> Track:
    """Bandcamp のトラック／アルバム URL からジャケット・曲名・アーティストを取る。"""
    try:
        return await bandcamp.fetch(body.url.strip(), client=app.state.http)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Bandcamp が {e.response.status_code} を返しました") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"取得失敗: {e}") from e


def _host_allowed(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    return any(host == d or host.endswith("." + d) for d in IMAGE_HOST_ALLOWLIST)


@app.get("/image-proxy")
async def image_proxy(url: str = Query(..., description="取得する画像URL")) -> Response:
    """外部画像を同一オリジンで返す（Canvas の CORS/tainted 回避）。"""
    if not _host_allowed(url):
        raise HTTPException(403, "許可されていないホストです")
    client: httpx.AsyncClient = app.state.http
    try:
        r = await client.get(url)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"取得失敗: {e}") from e
    if r.status_code != 200:
        raise HTTPException(r.status_code, "upstream error")
    ctype = r.headers.get("content-type", "")
    if not ctype.startswith("image/"):
        raise HTTPException(415, f"画像ではありません: {ctype}")
    if len(r.content) > IMAGE_MAX_BYTES:
        raise HTTPException(413, "画像が大きすぎます")
    return Response(
        content=r.content,
        media_type=ctype,
        headers={"Cache-Control": "public, max-age=86400"},
    )
