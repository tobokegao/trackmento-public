"""切り出した CSS と JS（frontend/dist/app.<hash>.{css,js}）を R2 に上げる。

使い方:
  .venv/Scripts/python scripts/build_app.py
  .venv/Scripts/python scripts/upload_app_r2.py [--force]

index.html は 424,697 バイトあり、その 93% が CSS と JS。初回訪問とデプロイ直後は
br 圧縮後 130KB がまるごと Render から出ていく。Render の帯域は Hobby プランの込みが月 5GB だけで
（2026-09-20 時点で 143.33GB・$20.85）、出費の最大項だった。R2 は転送量が無料なので、
どの訪問者にも同じ CSS と JS だけをそちらから配る。

R2 のキーは app/<ファイル名>。ファイル名に内容のハッシュが入っているので、内容が変われば別のキーになる。
**古いものは消さない**（配布済みの殻がまだ古い名前を指しているため）。fonts/ と同じく
r2_prune.py の KEEP_PREFIXES に入れて、共有の掃除に巻き込まれないようにしてある。
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
CTYPE = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="既にあるものも上げ直す")
    args = ap.parse_args()

    st = storage.get_storage()
    if not st.is_remote:
        print("R2 が設定されていません（.env の R2_* を確認）", file=sys.stderr)
        return 1
    if not st.public_url(""):
        print("R2_PUBLIC_URL がありません。公開 URL が無いと R2 から配れません", file=sys.stderr)
        return 1

    files = sorted(DIST.glob("app.*.css")) + sorted(DIST.glob("app.*.js"))
    if not files:
        print("frontend/dist/app.*.{css,js} がありません（python scripts/build_app.py で生成）", file=sys.stderr)
        return 1

    have: set[str] = set()
    if not args.force:
        # **app/ だけ一覧する**（バケット全体は 21 万件あり、一覧に 2 分かかる）
        have = {k for k, _, _ in st.list_objects(PREFIX)}

    up = skip = 0
    for f in files:
        key = PREFIX + f.name
        if key in have:
            print(f"  そのまま: {f.name}")
            skip += 1
            continue
        st.put(key, f.read_bytes(), CTYPE[f.suffix])
        print(f"  上げた: {f.name}  {f.stat().st_size / 1024:.0f} KB")
        up += 1

    base = st.public_url(PREFIX).rstrip("/")
    print(f"上げた {up} 件 / そのまま {skip} 件  →  {base}/")
    print("**デプロイより先にこれを終わらせること**。殻が指すファイルが R2 に無いと、"
          "サーバーは殻を使わず 1 枚の index.html を配る（壊れはしないが、効果が出ない）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
