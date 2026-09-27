"""縦の短い動画（Instagram・TikTok 向け、XClipTall）の頭に出す見出しを書き出す。

見出しは「使い方の動画」（backend/howto.py）の問いをそのまま使う（添削済みで、/howto と言葉がそろう）。
/howto に載せていない動画だけ、下の EXTRA に手で書く。

  PYTHONUTF8=1 ../.venv/Scripts/python x_titles.py     # promo/ で実行 → public/xclips-titles.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from backend import howto  # noqa: E402

# /howto に無いもの（見た目の紹介・ほかの問いと重なるもの・/howto 自体の知らせ）
EXTRA = {
    "p-os9": ("見た目は Mac OS 9 風", "Styled after Mac OS 9"),
    "p-logo": ("ロゴはピクセルの字と 6 色の帯", "A pixel-font logo with six color bands"),
    "p-counts": ("小さな数もピクセルの字で", "Even the small numbers are pixel type"),
    "lang": ("画面をまるごと英語にできますか？", "Can I switch the whole screen to English?"),
    "zoom-wheel": ("「大きく見る」で拡大・縮小するには？", "How do I zoom in the big view?"),
    "howto-intro": ("使い方を動画で見られます", "How-to videos for every feature"),
}


def main() -> None:
    out = {i[0]: {"ja": i[1], "en": i[3]} for _, _, items in howto.SECTIONS for i in items}
    out.update({k: {"ja": ja, "en": en} for k, (ja, en) in EXTRA.items()})
    path = HERE / "public" / "xclips-titles.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{path.relative_to(HERE)} に {len(out)} 件")


if __name__ == "__main__":
    main()
