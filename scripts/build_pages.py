"""GitHub Pages 用の静的ファイルを組み立てる。

  python scripts/build_pages.py --api https://your-backend.example.com [--out dist]

- frontend/index.html をコピーし、<meta name="trackmento-api"> にバックエンドの URL を埋め込む
- fonts/ を同梱（フロントは fonts/ を相対パスで読む）
- .nojekyll を置く（_ で始まるファイル対策）
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build(api: str, out: Path) -> None:
    api = api.strip().rstrip("/")
    if api and not api.startswith(("http://", "https://")):
        raise SystemExit(f"--api は http(s):// から始まる URL にしてください: {api}")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    marker = '<meta name="viewport" content="width=device-width, initial-scale=1">'
    if marker not in html:
        raise SystemExit("frontend/index.html に viewport meta が見つかりません")
    html = html.replace(marker, marker + f'\n<meta name="trackmento-api" content="{api}">', 1)
    html = html.replace("__BASE__", api)   # OG 画像はバックエンドが配る /og.png を指す
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    for name in ("og.png", "favicon.ico", "favicon.png", "apple-touch-icon.png"):
        shutil.copy2(ROOT / "frontend" / name, out / name)
    fonts_out = out / "fonts"
    fonts_out.mkdir(exist_ok=True)
    for p in (ROOT / "fonts").glob("*"):
        if p.suffix.lower() in (".ttf", ".txt"):
            shutil.copy2(p, fonts_out / p.name)
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"built: {out}  (api={api or '(same origin)'})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="", help="バックエンドの URL（例: https://trackmento.onrender.com）。空なら同一オリジン")
    ap.add_argument("--out", default="dist", help="出力先ディレクトリ")
    a = ap.parse_args()
    build(a.api, Path(a.out))
