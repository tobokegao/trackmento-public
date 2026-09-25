"""X 向けの短い動画の撮影（promo/x_clips.mjs）で本番の R2 に上げた画像を消す。

    PYTHONUTF8=1 .venv/Scripts/python scripts/clean_x_uploads.py

背景の画像の場面は画面から /upload を通るので、見本の画像が R2 の uploads/ に残る
（手元のサーバーも .env の R2 を使うため）。撮影が記録した promo/public/xclips/<id>/uploads.json の
分だけを消し、消したら記録も消す。**利用者の画像には触れない**（記録に無いものは消さない）。
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import storage, uploads  # noqa: E402


def main() -> None:
    st = storage.get_storage()
    for rec in sorted((ROOT / "promo" / "public" / "xclips").glob("*/uploads.json")):
        urls = [u for u in json.loads(rec.read_text(encoding="utf-8")) if uploads.is_upload_url(u)]
        keys = [f"uploads/{u[len(uploads.PREFIX):]}" for u in urls]
        n = st.delete_many(keys) if keys and st.is_remote else 0
        print(f"{rec.parent.name}: {n} / {len(keys)} 件を消した")
        rec.unlink()


if __name__ == "__main__":
    main()
