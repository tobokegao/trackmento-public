"""使い方の動画（/howto）の動画を R2 に上げ、id → キーの表（backend/howto_videos.json）を書く。

使い方:
  PYTHONUTF8=1 .venv/Scripts/python scripts/upload_howto_r2.py [--dry-run]

- 元は X 向けに書き出した `promo/out/x/<id>.mp4`（`cd promo && node render_x.mjs <id>`）。載せるのは
  `backend/howto.py` の SECTIONS にある id だけ。**mp4 が無い id は表に入れない**（ページにも出ない）
- R2 のキーは `howto/<id>.<中身のハッシュ 10 桁>.mp4`。撮り直すと別のキーになるので、古いキャッシュを踏まない。
  既に同じキーがあれば上げ直さない
- `howto/` は `scripts/r2_prune.py` の KEEP_PREFIXES（古くても消さない）。撮り直して要らなくなった古いキーは
  この表に無いものとして一覧に出すだけで、消すのは手で（`--prune` を付けたときだけ消す）
- 表（backend/howto_videos.json）はコミットする。本番はこの表を読んで R2 の URL を組む
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

for _line in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if (ROOT / ".env").is_file() else []:
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _, _v = _line.partition("=")
        os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

from backend import howto, storage  # noqa: E402

PREFIX = "howto/"
SRC = ROOT / "promo" / "out" / "x"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="上げずに、上げるものと表だけ見せる")
    ap.add_argument("--prune", action="store_true", help="表に無い howto/ のキー（撮り直す前の古い動画）を消す")
    args = ap.parse_args()

    st = storage.get_storage()
    if not st.is_remote or not st.public_url(""):
        print("R2 が設定されていないか、R2_PUBLIC_URL がありません（.env の R2_* を確認）", file=sys.stderr)
        return 1

    have = {k for k, _, _ in st.list_objects(PREFIX)}
    table: dict[str, str] = {}
    up = skip = 0
    total = 0
    missing = []
    for vid in howto.ids():
        f = SRC / f"{vid}.mp4"
        if not f.is_file():
            missing.append(vid)
            continue
        data = f.read_bytes()
        key = f"{PREFIX}{vid}.{hashlib.sha256(data).hexdigest()[:10]}.mp4"
        table[vid] = key
        if key in have:
            skip += 1
            continue
        if not args.dry_run:
            st.put(key, data, "video/mp4")
        up += 1
        total += len(data)

    stale = sorted(have - set(table.values()))
    verb = "上げる" if args.dry_run else "上げた"
    print(f"{verb} {up} 本（{total / 1024 / 1024:.1f} MB）、そのまま {skip} 本")
    if missing:
        print(f"mp4 が無いので載せない {len(missing)} 本: {', '.join(missing)}")
    if stale:
        print(f"表に無い古いキー {len(stale)} 件" + ("（消した）" if args.prune and not args.dry_run else "（--prune で消す）"))
        if args.prune and not args.dry_run:
            for k in stale:
                st.delete(k)
    if not args.dry_run:
        howto.MANIFEST.write_text(json.dumps(table, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"表を書いた: {howto.MANIFEST.relative_to(ROOT)}（{len(table)} 本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
