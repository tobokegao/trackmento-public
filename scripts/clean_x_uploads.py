"""X 向けの短い動画の撮影（promo/x_clips.mjs）で本番の R2 に上げた画像を消す。

    PYTHONUTF8=1 .venv/Scripts/python scripts/clean_x_uploads.py

背景の画像の場面は画面から /upload を通り、「トラックを共有」も押すので、見本の画像が R2 の uploads/ に、
共有が R2 のいちばん上（<id>.jpg など）に残る（手元のサーバーも .env の R2 を使うため）。
撮影が記録した promo/public/xclips/<id>/uploads.json の分だけを消し、消したら記録も消す。
**利用者の画像や共有には触れない**（記録に無いものは消さない）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import storage, uploads  # noqa: E402


def main() -> None:
    st = storage.get_storage()
    for rec in sorted((ROOT / "promo" / "public" / "xclips").glob("*/uploads.json")):
        got = json.loads(rec.read_text(encoding="utf-8"))
        if isinstance(got, list):   # 共有を記録する前の形
            got = {"uploads": got, "shares": []}
        keys = [f"uploads/{u[len(uploads.PREFIX):]}" for u in got.get("uploads", []) if uploads.is_upload_url(u)]
        for sid in got.get("shares", []):
            if re.fullmatch(r"[0-9a-f]{12}", sid or ""):   # 共有の ID の形（ほかの鍵を消さない）
                keys += [f"{sid}.jpg", f"{sid}-og.jpg", f"{sid}.json", f"{sid}.png"]
        n = st.delete_many(keys) if keys and st.is_remote else 0
        print(f"{rec.parent.name}: {n} / {len(keys)} 件を消した（画像 {len(got.get('uploads', []))}・共有 {len(got.get('shares', []))}）")
        rec.unlink()


if __name__ == "__main__":
    main()
