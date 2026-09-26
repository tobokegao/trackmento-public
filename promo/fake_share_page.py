"""X 向けの短い動画（o-share-open）で使う、架空の共有ページと共有画像を作る。

    PYTHONUTF8=1 .venv/Scripts/python promo/fake_share_page.py <並びの JSON> <出力フォルダ>

本物の共有を本番の R2 に置かずに「共有ページ → TRACKMENTO で開く」を撮るため（2026-09-26）。
並びをサーバーの描画（render.render）で絵にし、サイトと同じ share.page_html で共有ページを組んで、
<出力フォルダ>/page.html と image.jpg を書く。撮影側がその 2 つで /s/<id> と画像の URL を差し替える。
曲名もサムネも架空（promo/fake_covers.py の絵。手元の uploads/ にある）。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import render, share  # noqa: E402
from backend.grids import GridDoc  # noqa: E402


def main() -> None:
    snap = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    doc = GridDoc.model_validate({k: v for k, v in snap.items() if k in GridDoc.model_fields})
    im = render.render(doc)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=88)
    (out / "image.jpg").write_bytes(buf.getvalue())
    html = share.page_html({**snap, "ext": "jpg"}, "http://127.0.0.1:8000", "http://127.0.0.1:8000", "ja")
    (out / "page.html").write_text(html, encoding="utf-8")
    print(share.image_url(snap["id"], "jpg"))


if __name__ == "__main__":
    main()
