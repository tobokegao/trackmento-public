"""運用ボード（scripts/board/index.html）に JF ドット東雲ゴシック16 を刈り込んで埋め込む。

2026-09-24 に DotGothic16 → マルモニカ → 東雲ゴシック16 と替えた（DotGothic16 は英字の上辺が波打ち、
マルモニカは縦長。東雲は 16×16 の正方形で英字の上辺もそろう）。ライセンスは fonts/LICENSE-JF-Dot-Shinonome16.txt（実質パブリックドメイン）。

Claude のアプリの中では Google Fonts が読み込まれないので、ページの最後の
<style id="fonts"> に data: で入れる（2026-09-24、board-retro）。
刈り込む字は、ページ・status.json・board_data.py に出てくる字と、JIS 第 1 水準・かな・ASCII。
db から来る文言に第 2 水準の字が増えて代わりのフォントで出るようになったら、これを回し直す。

    PYTHONUTF8=1 .venv/Scripts/python scripts/board_font.py
"""
import base64
import io
import re
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "scripts/board/index.html"
SOURCES = [PAGE, ROOT / "scripts/board/status.json", ROOT / "scripts/board_data.py"]


def wanted_chars() -> set[str]:
    chars: set[str] = set()
    for f in SOURCES:
        text = f.read_text(encoding="utf-8")
        # 前回埋め込んだ base64 は字の集まりに数えない
        chars |= set(re.sub(r'\n<style id="fonts">.*?</style>', "", text, flags=re.S))
    chars |= {chr(c) for c in range(0x20, 0x7F)}
    chars |= {chr(c) for c in range(0x3000, 0x3100)}   # 記号・かな
    chars |= {chr(c) for c in range(0xFF01, 0xFF5F)}   # 全角の英数と記号
    for hi in range(0xB0, 0xD0):                       # JIS 第 1 水準
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(bytes([hi, lo]).decode("euc_jp"))
            except UnicodeDecodeError:
                pass
    return chars


def main() -> None:
    font = TTFont(ROOT / "fonts/JF-Dot-Shinonome16.ttf")
    cmap = font.getBestCmap()
    keep = sorted(ord(c) for c in wanted_chars() if len(c) == 1 and ord(c) in cmap)
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    sub = subset.Subsetter(options=opts)
    sub.populate(unicodes=keep)
    sub.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    block = (
        '\n<style id="fonts">\n'
        "/* JF ドット東雲ゴシック16（実質パブリックドメイン、fonts/LICENSE-JF-Dot-Shinonome16.txt）を scripts/board_font.py で刈り込んだもの。"
        "字を大きく足したら回し直す */\n"
        '@font-face { font-family: "Shinonome16"; src: url("data:font/woff2;base64,'
        + b64
        + '") format("woff2"); font-display: block; }\n</style>\n'
    )
    page = PAGE.read_text(encoding="utf-8")
    page = re.sub(r'\n<style id="fonts">.*?</style>\n', "", page, flags=re.S)
    PAGE.write_text(page.rstrip("\n") + "\n" + block, encoding="utf-8")
    print(f"{len(keep)} 字、woff2 {len(buf.getvalue()):,} バイト")


if __name__ == "__main__":
    main()
