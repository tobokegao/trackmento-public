"""note に貼り付けるための HTML を作る。

    PYTHONUTF8=1 .venv/Scripts/python scripts/build_note_paste.py

`outputs/note/note-article.md` を、**note のエディタが受け取れる部品だけ**に変換して
`outputs/note/note-paste.html` に書き出す。ブラウザでこのページを開き、全選択してコピー →
note の本文に貼ると、見出し・太字・箇条書き・引用・区切り線がそのまま入る。

note に無いもの（と、その扱い）:

- **表**が無い → 画像にして貼る（`scripts/shoot_tables.py` が作る `table-*.png`）
- **小見出しは 2 段まで** → `####` は太字の段落にする
- **画像は貼り付けでは入らない**（外部の画像は落ちる）→ 置き場所に「【画像】ファイル名」の
  行を出しておき、note のエディタでその位置に上げ直してもらう
- **文中のリンクは貼り付けで落ちる**（2026-09-17 に確認。a が文字だけになる）→ リンクのある段落の
  すぐ下に「【リンク】「文字」に URL」の行を出し、note のエディタで付け直してもらう
"""
from __future__ import annotations

import html
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "outputs" / "note" / "note-article.md"
OUT = ROOT / "outputs" / "note" / "note-paste.html"
# 表は画像にする。md の何個目の表がどの画像か
TABLE_IMG = ["table-services.png", "table-cost.png"]


def inline(s: str) -> str:
    """太字・コード・リンクだけ HTML にする（それ以外は文字として escape）。"""
    out, i = [], 0
    pat = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)")
    for m in pat.finditer(s):
        out.append(html.escape(s[i:m.start()]))
        if m.group(1) is not None:
            # 太字の中のリンク（**[名前](URL)**）も a にする。escape だけだと記法が文字のまま貼られる
            out.append(f"<b>{inline(m.group(1))}</b>")
        elif m.group(2) is not None:
            out.append(f"<code>{html.escape(m.group(2))}</code>")
        else:
            out.append(f'<a href="{html.escape(m.group(4), quote=True)}">{html.escape(m.group(3))}</a>')
        i = m.end()
    out.append(html.escape(s[i:]))
    return "".join(out)


LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")


def link_marks(text: str) -> list[str]:
    """文中のリンクごとに目印の行を作る。**note に貼るとリンクが落ちる**（「ここ」などが文字だけになった）ので、
    貼ったあとに手で付け直せるよう、文字と URL を黄色い行で添える。"""
    return [f'<p class="ph">【リンク】「{html.escape(t)}」に {html.escape(u)}</p>' for t, u in LINK_RE.findall(text)]


ARTIFACT_USAGE = (
    '<p class="ph" style="background:#d7f0ff"><b>使い方</b>: この画面を全選択してコピー → note の本文に貼り付け。'
    '見出し・太字・箇条書き・区切り線はそのまま入ります。<b>黄色い行は目印</b>です。'
    '【画像】はその位置に画像を上げ、【リンク】はすぐ上の文の該当する文字にリンクを付けてから消してください'
    '（note に貼るとリンクは落ちます）。</p>\n'
)


def write_artifact(html: str, out: pathlib.Path) -> None:
    """アーティファクト（claude.ai に置く版）。head を外し、先頭に使い方の行を足す。
    公開先が doctype と head を付けるので、こちらは <title> と <style> から始める。"""
    head, body = html.split("<body>", 1)
    body = body.replace("</body></html>", "").replace("</body>", "").replace("</html>", "")
    style = re.search(r"<style>.*?</style>", head, re.S).group(0)
    out.write_text("<title>note 貼り付け用の下書き</title>\n" + style + "\n" + ARTIFACT_USAGE + body, encoding="utf-8")


def main() -> int:
    lines = SRC.read_text(encoding="utf-8").splitlines()
    body: list[str] = []
    buf: list[str] = []          # 段落の途中
    ul: list[str] = []           # 箇条書きの途中
    ol: list[str] = []
    table = 0                    # 何個目の表か
    in_table = False

    def flush_p():
        if buf:
            text = " ".join(buf).strip()
            body.append("<p>" + inline(text) + "</p>")
            body.extend(link_marks(text))
            buf.clear()

    def flush_list():
        nonlocal ul, ol
        if ul:
            body.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in ul) + "</ul>")
            body.extend(m for x in ul for m in link_marks(x))
            ul = []
        if ol:
            body.append("<ol>" + "".join(f"<li>{inline(x)}</li>" for x in ol) + "</ol>")
            body.extend(m for x in ol for m in link_marks(x))
            ol = []

    for raw in lines:
        s = raw.rstrip()
        # 表（| で始まる行）は画像に差し替える
        if s.startswith("|"):
            flush_p(); flush_list()
            if not in_table:
                in_table = True
                name = TABLE_IMG[table] if table < len(TABLE_IMG) else f"table-{table + 1}.png"
                body.append(f'<p class="ph">【画像】{name}（表は note に無いので画像で貼る）</p>')
                table += 1
            continue
        in_table = False
        if not s:
            flush_p(); flush_list()
            continue
        if s.startswith("#### "):
            flush_p(); flush_list()
            body.append("<p><b>" + inline(s[5:]) + "</b></p>")
        elif s.startswith("### "):
            flush_p(); flush_list()
            body.append("<h3>" + inline(s[4:]) + "</h3>")
        elif s.startswith("## "):
            flush_p(); flush_list()
            body.append("<h2>" + inline(s[3:]) + "</h2>")
        elif s.startswith("# "):
            flush_p(); flush_list()
            body.append('<p class="ph">【記事タイトル】' + inline(s[2:]) + "</p>")
        elif s.startswith("---"):
            flush_p(); flush_list()
            body.append("<hr>")
        elif s.startswith("!["):
            flush_p(); flush_list()
            m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", s)
            if m:
                body.append(f'<p class="ph">【画像】{html.escape(m.group(2))}</p>')
        elif s.startswith("*") and s.endswith("*") and not s.startswith("**"):
            flush_p(); flush_list()
            body.append('<p class="cap">（キャプション）' + inline(s[1:-1]) + "</p>")
        elif re.match(r"^\d+\. ", s):
            flush_p()
            ol.append(re.sub(r"^\d+\. ", "", s))
        elif s.startswith("- "):
            flush_p()
            ul.append(s[2:])
        else:
            flush_list()
            buf.append(s)
    flush_p(); flush_list()

    OUT.write_text(f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>note 貼り付け用</title>
<style>
 body {{ font-family: system-ui, sans-serif; line-height: 1.9; max-width: 44rem; margin: 0 auto; padding: 24px; }}
 h2 {{ font-size: 1.4rem; margin: 2em 0 .4em; }}
 h3 {{ font-size: 1.1rem; margin: 1.6em 0 .3em; }}
 hr {{ border: 0; border-top: 2px solid #ccc; margin: 2em 0; }}
 .ph {{ background: #ffe9a8; padding: 4px 8px; font-size: .9rem; }}
 .cap {{ color: #666; font-size: .9rem; }}
 code {{ background: #eee; padding: 0 4px; }}
</style></head>
<body>
{chr(10).join(body)}
</body></html>
""", encoding="utf-8")
    art = OUT.with_name("note-paste-artifact.html")
    write_artifact(OUT.read_text(encoding="utf-8"), art)
    print(f"{OUT} を書きました（{len(body)} ブロック、表 {table} 個）。アーティファクト版: {art.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
