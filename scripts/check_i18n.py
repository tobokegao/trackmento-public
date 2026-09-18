"""frontend/index.html の日本語の文言と EN 表のずれを見つける。

EN 表は「日本語の文面そのもの」を鍵にしているので、**文言を 1 文字でも直すと鍵が合わなくなり、
英語表示に切り替えてもそこだけ日本語のまま残る**（例外も警告も出ないので気付きにくい）。
画面の文字を変えたら、build_fonts.py と一緒にこれも回すこと。

    PYTHONUTF8=1 .venv/Scripts/python scripts/check_i18n.py

終了コード 0 = ずれなし、1 = ずれあり。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Comment

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "index.html"
JA = re.compile(r"[぀-ヿ一-鿿]")
TMPL_EXPR = re.compile(r"\$\{[^{}]*\}")

# ラベル表（SOURCE_LABEL / SWATCHES）の値。tr(SOURCE_LABEL[s]) のように変数で渡すため、
# リテラルは tr で包まないし、静的にも追えない。英訳が要る側なので「使っている」扱いにする
LABELS = {"ニコニコ動画", "手入力", "クリーム", "黒", "マスタード", "セルリアン", "朱赤", "ラベンダー", "ミント", "ピンク",
          # 作者の作品名（曲の題そのものなので訳さない。OWN_TRACKS の値）
          "おかねがたりないときのうた",
          "アイボリー", "チャコール",
          "ミッドナイト", "チョーク", "アンバー", "アジュール", "フレア", "バイオレット", "ジェイド", "マゼンタ", "ナイト",
          "レモン", "ウルトラマリン", "コーラル", "スカイ", "リーフ", "ローズ",
          "リソ", "ポップ"}   # パレットの名前（表の値として tr() に渡す）
# 切り替えボタン自身の文字。英語表示のときに出す日本語なので、包むと逆になる
# 文面ではないもの（区切り記号など）は包まなくてよい
ALLOW_BARE = {"日本語", "日本語に切り替える", "・"}

_STR = re.compile(r'"((?:[^"\\\n]|\\.)*)"' + "|" + r"'((?:[^'\\\n]|\\.)*)'" + "|" + r"`((?:[^`\\]|\\.)*)`", re.S)
_TR_PLAIN = re.compile(r'tr\(\s*"((?:[^"\\\n]|\\.)*)"\s*\)' + "|" + r"tr\(\s*'((?:[^'\\\n]|\\.)*)'\s*\)", re.S)
_TR_TMPL = re.compile(r"tr`((?:[^`\\]|\\.)*)`", re.S)


def _en_span(html: str) -> tuple[int, int]:
    """EN 表の `{` から対応する `}` までの位置。閉じ括弧のインデントに頼ると表の外の `};` を
    拾って切り出しに失敗するので、文字列の中を避けながら括弧を数える。"""
    i = html.index("  const EN = {") + len("  const EN = ")
    depth, k, in_str, esc = 0, i, False, False
    while k < len(html):
        c = html[k]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i, k + 1
        k += 1
    raise ValueError("EN 表の終わりが見つかりません")


def _en_table(html: str) -> dict[str, str]:
    a, b = _en_span(html)
    return json.loads(html[a:b])


def _html_strings(html: str) -> list[str]:
    """画面に直接書いてある文言（テキストと属性）。"""
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style"]):
        t.decompose()
    out: list[str] = []
    for n in soup.find_all(string=True):
        if isinstance(n, Comment):
            continue
        s = str(n).strip()
        if s and JA.search(s):
            out.append(s)
    for el in soup.find_all(True):
        for a in ("placeholder", "aria-label", "title", "content", "alt", "value"):
            v = el.get(a)
            if isinstance(v, str) and JA.search(v.strip()):
                out.append(v.strip())
    return out


def _js(html: str) -> str:
    """EN 表とコメントを除いた JS。"""
    js = "\n".join(b for b in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S) if len(b) > 2000)
    a, b = _en_span(js)
    js = js[: a - len("  const EN = ")] + js[b:]
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    # **作者の曲の一覧は文言ではなくデータ**（曲名そのもの）。`scripts/build_own_tracks.py` が
    # Bandcamp から作るので、日本語の曲名が並ぶ。翻訳の対象ではないので見ない
    js = re.sub(r"const OWN_TRACKS = \[[\s\S]*?\n  \];", "", js)
    # 折る位置の表（中黒や括弧の並び）は画面の文言ではない
    js = re.sub(r'const BREAK_AFTER = "[^"]*", BREAK_BEFORE = "[^"]*";', "", js)
    js = re.sub(r'const NO_HEAD = "[^"]*"', "", js)   # 行頭に来てはいけない字の表（禁則。文言ではない）
    return re.sub(r"(?m)^\s*//.*$", "", js)


def _key(s: str) -> str:
    """タグ付きテンプレートの鍵（raw を "{}" でつないだもの）。"""
    return TMPL_EXPR.sub("{}", s)


def _bare(js: str, where: str = "") -> list[str]:
    """tr で包まれていない日本語のリテラルを、出現箇所ごとに探す。
    テンプレートの中の ${…} も中を見る（そこに直接書いた文面も包む必要があるため）。"""
    out: list[str] = []
    for m in _STR.finditer(js):
        s = next(g for g in m.groups() if g is not None)
        quote = js[m.start()]
        head = js[: m.start()].rstrip()
        ok = head.endswith("tr(") if quote in "\"'" else head.endswith("tr")
        if quote == "`":
            # テンプレートの中の式に直接書いた文面も見る（tr`…${x ? "日本語" : "y"}…`）
            for expr in TMPL_EXPR.findall(s):
                out += _bare(expr, where=" ←テンプレートの中")
        if JA.search(s) and not ok and s not in LABELS and s not in ALLOW_BARE:
            out.append(f"tr で包み忘れ{where}: {s[:70]}")
    return out


def main() -> int:
    html = SRC.read_text(encoding="utf-8")
    en = _en_table(html)
    js = _js(html)
    problems: list[str] = []

    # tr で包んである文面（テンプレートの中に入れ子で書いたものも拾う）
    wrapped_plain = {g for m in _TR_PLAIN.finditer(js) for g in m.groups() if g}
    wrapped_tmpl = {m.group(1) for m in _TR_TMPL.finditer(js)}
    wrapped = wrapped_plain | wrapped_tmpl

    html_strings = list(dict.fromkeys(_html_strings(html)))
    for s in html_strings:
        if s not in en:
            problems.append(f"画面の文言に英訳が無い: {s[:70]}")

    for s in sorted(wrapped):
        if _key(s) not in en:
            problems.append(f"tr で包んであるが英訳が無い: {s[:70]}")

    # 包み忘れは**出現箇所ごと**に見る。値で見ると、同じ文面が別の行で包まれているだけで
    # 包み忘れを見逃す（実際にそれで検知できていなかった）
    problems += _bare(js)

    used = {_key(s) for s in wrapped} | set(html_strings) | LABELS
    for k in en:
        if k not in used:
            problems.append(f"英訳が余っている（元の文言が消えたか変わった）: {k[:70]}")

    if problems:
        print(f"ずれ {len(problems)} 件")
        for p in dict.fromkeys(problems):
            print("  -", p)
        return 1
    print(f"ずれなし（英訳 {len(en)} 件、画面の文言 {len(html_strings)} 件と JS の tr {len(wrapped)} 件を照合）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
