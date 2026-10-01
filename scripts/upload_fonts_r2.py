"""分割フォント（fonts/split/*.woff2）をR2に上げる。

使い方:
  .venv/Scripts/python scripts/upload_fonts_r2.py [--force]

フォントは新規の訪問1回あたり210KB（実測）で、Renderの転送量の大半を占めていた。
Render前段のCloudflareはWeb Serviceの応答をキャッシュしないため、訪問のたびに
サーバーから出ていく。R2は転送量が無料なので、断片だけをそちらから配る。

バックエンドは /fonts-css/<name> でCSSのsrcをR2の公開URLに差し替えて返す
（FONTS_FROM_R2=0で従来どおりサーバーから配る）。

R2のキーはfonts/<ファイル名>。ファイル名にハッシュが入っているので、内容が変われば
別のキーになり、古いものは共有と同じライフサイクルで消える。
既に同じキーがあれば上げ直さない（--forceで上書き）。
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

PREFIX = "fonts/"
CTYPE = "font/woff2"


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

    # 分割フォント（断片）＋ ピクセルフォント（Silkscreen）。Silkscreenは分割していないので
    # fonts/ 直下にあり、本体と共有ページの両方が読む。R2に置かないとサーバーから出続ける
    files = (sorted((ROOT / "fonts" / "split").glob("*.woff2")) + sorted((ROOT / "fonts").glob("Silkscreen-*.woff2"))
             + sorted((ROOT / "fonts").glob("TrackmentoMark-*.woff2")))
    if not files:
        print("fonts/split/*.woff2がありません（python scripts/build_fonts.pyで生成）", file=sys.stderr)
        return 1

    have: set[str] = set()
    if not args.force:
        # **fonts/ だけ一覧する**（バケット全体は20万件あり、一覧に2分かかる。2026-09-19）
        have = {k for k, _, _ in st.list_objects(PREFIX)}

    up = skip = 0
    total = 0
    for f in files:
        key = PREFIX + f.name
        # ロゴのフォントは名前を変えずに作り直すので、毎回上げ直す（数KB）
        if key in have and not f.name.startswith("TrackmentoMark-"):
            skip += 1
            continue
        data = f.read_bytes()
        st.put(key, data, CTYPE)
        up += 1
        total += len(data)
        if up % 50 == 0:
            print(f"  {up}件…")

    print(f"上げた{up}件（{total / 1024 / 1024:.1f} MB）、そのまま{skip}件")
    if up:
        print(f"公開URLの例: {st.public_url(PREFIX + files[0].name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
