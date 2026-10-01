"""切り出したCSSとJS（frontend/dist/app.<hash>.{css,js}）をR2に上げる。

使い方:
  .venv/Scripts/python scripts/build_app.py
  .venv/Scripts/python scripts/upload_app_r2.py [--force]

index.htmlは424,697バイトあり、その93% がCSSとJS。初回訪問とデプロイ直後は
br圧縮後130KBがまるごとRenderから出ていく。Renderの帯域はHobbyプランの込みが月5GBだけで
（2026-09-20時点で143.33GB・$20.85）、出費の最大項だった。R2は転送量が無料なので、
どの訪問者にも同じCSSとJSだけをそちらから配る。

R2のキーはapp/<ファイル名>。ファイル名に内容のハッシュが入っているので、内容が変われば別のキーになる。
**古いものは消さない**（配布済みの殻がまだ古い名前を指しているため）。fonts/ と同じく
r2_prune.pyのKEEP_PREFIXESに入れて、共有の掃除に巻き込まれないようにしてある。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import os  # noqa: E402

for _line in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").is_file() else []:
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from backend import storage  # noqa: E402

PREFIX = "app/"
DIST = ROOT / "frontend" / "dist"
CTYPE = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".gif": "image/gif", ".png": "image/png"}
BANNERS = ROOT / "frontend" / "banners"   # 画面に貼る絵。キーはapp/banners/<名前>（名前に中身のハッシュが入っている）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="既にあるものも上げ直す")
    args = ap.parse_args()

    st = storage.get_storage()
    if not st.is_remote:
        print("R2が設定されていません（.envのR2_* を確認）", file=sys.stderr)
        return 1
    if not st.public_url(""):
        print("R2_PUBLIC_URLがありません。公開URLが無いとR2から配れません", file=sys.stderr)
        return 1

    files = sorted(DIST.glob("app.*.css")) + sorted(DIST.glob("app.*.js"))
    banners = sorted(BANNERS.glob("*.gif")) + sorted(BANNERS.glob("*.png"))
    if not files:
        print("frontend/dist/app.*.{css,js}がありません（python scripts/build_app.pyで生成）", file=sys.stderr)
        return 1

    have: set[str] = set()
    if not args.force:
        # **app/ だけ一覧する**（バケット全体は21万件あり、一覧に2分かかる）
        have = {k for k, _, _ in st.list_objects(PREFIX)}

    up = skip = 0
    for f in files + banners:
        key = PREFIX + ("banners/" if f.parent == BANNERS else "") + f.name
        if key in have:
            print(f"  そのまま: {f.name}")
            skip += 1
            continue
        st.put(key, f.read_bytes(), CTYPE[f.suffix])
        print(f"  上げた: {f.name}  {f.stat().st_size / 1024:.0f} KB")
        up += 1

    base = st.public_url(PREFIX).rstrip("/")
    print(f"上げた{up}件 / そのまま{skip}件  →  {base}/")
    print("**デプロイより先にこれを終わらせること**。殻が指すファイルがR2に無いと、"
          "サーバーは殻を使わず1枚のindex.htmlを配る（壊れはしないが、効果が出ない）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
