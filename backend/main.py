"""FastAPI エントリポイント。起動: uvicorn backend.main:app --reload"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

app = FastAPI(title="MusicGrid Local")

OUTPUTS = ROOT / "outputs"
OUTPUTS.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUTPUTS), name="outputs")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
