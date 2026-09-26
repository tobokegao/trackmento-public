"""index.html の CSS と JS を、内容ハッシュを付けた別ファイルに切り出す（R2 から配るため）。

  python scripts/build_app.py            # frontend/dist/ に殻・app.<hash>.css・app.<hash>.js を生成
  python scripts/build_app.py --check    # 生成物の有無と大きさを表示するだけ

背景: Render の帯域は出費の最大項で、Hobby プランの込みは月 5GB だけ（2026-09-20 時点で 143.33GB・$20.85）。
index.html は 424,697 バイトあり、その 93% が <style> と <script>。ETag の 304 が効くので再訪は 0 バイトだが、
**初回訪問とデプロイ直後は br 圧縮後 130KB がまるごとサーバーから出ていく**。
CSS と JS はどの訪問者にも同じものなので、内容ハッシュを付けて R2（転送量が無料）から配る。

生成物:
  frontend/dist/index.html        … 殻。サーバーが差し込む値（__BASE__ など）はここに残る
  frontend/dist/app.<hash>.css    … <style id="app-css"> の中身
  frontend/dist/app.<hash>.js     … <script id="app-js"> の中身

**編集する正は frontend/index.html のまま**（1 枚）。これは配るときだけの分割で、
scripts/build_fonts.py が fonts/split/ を作るのと同じ位置づけ。
build_fonts.py と check_i18n.py はどちらも frontend/index.html を読むので影響しない。

殻の中では R2 の公開 URL を持たず、`app/app.<hash>.css` という相対パスで書く。
backend/main.py が配るときに R2 の公開 URL へ差し替える（フォントと同じやり方）。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "index.html"
OUT = ROOT / "frontend" / "dist"
PREFIX = "app/"   # R2 側のキーの接頭辞。main.py の APP_R2_PREFIX と合わせる

# 切り出す 2 つ。id で狙うので、サーバーが URL を差し込む @font-face だけの <style>（id 無し）は残る
CSS_RE = re.compile(r'<style id="app-css">\n(.*?)\n</style>', re.S)
JS_RE = re.compile(r'<script id="app-js">\n(.*?)\n</script>', re.S)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def split(src: str) -> tuple[str, str, str, str, str]:
    """index.html の中身を (css のファイル名, css, js のファイル名, js, 殻) に分ける。書き込みはしない
    （scripts/check.py が「殻が古くないか」を確かめるのにも使う）"""

    css_m = CSS_RE.findall(src)
    js_m = JS_RE.findall(src)
    # **1 個ずつという前提を守らせる**。黙って一部だけ外に出すと、残りが効かない画面が本番に出る
    if len(css_m) != 1:
        raise SystemExit(f'<style id="app-css"> が {len(css_m)} 個ありました（1 個であること）')
    if len(js_m) != 1:
        raise SystemExit(f'<script id="app-js"> が {len(js_m)} 個ありました（1 個であること）')
    css, js = css_m[0], js_m[0]

    # サーバーが差し込む印が外に出ていないか確かめる。出ていると 1 年キャッシュに焼き付いてしまう。
    #
    # **__RETENTION__ だけは JS に残ってよい**。英語の対訳表は日本語の文面を鍵にしていて、その文面に
    # 日数が入る（「共有 URL は __RETENTION__ 日で消えます」）。鍵ごと外に出すしかないので、
    # JS 側が起動時に <meta name="trackmento-retention"> の値で表を作り直す。CSS には出てこない
    for mark in ("__BASE__", "__PUBLIC__", "__MIGRATE__", "__LOGO_FONT__", "__FONT_LINK__", "__VERIFY__"):
        for name, body in (("CSS", css), ("JS", js)):
            if mark in body:
                raise SystemExit(f"{name} の中に {mark} が残っています。殻（HTML）側へ移してください")
    if "__RETENTION__" in css:
        raise SystemExit("CSS の中に __RETENTION__ が残っています。殻（HTML）側へ移してください")
    if "__RETENTION__" in js and 'name="trackmento-retention"' not in js:
        raise SystemExit("JS が __RETENTION__ を含むのに <meta> から読んでいません")

    css_name = f"app.{_digest(css)}.css"
    js_name = f"app.{_digest(js)}.js"

    shell = CSS_RE.sub(lambda _: f'<link rel="stylesheet" href="{PREFIX}{css_name}">', src, count=1)
    # **位置は変えない**（本体の JS は </body> の直前にある）。defer を付けず同じ場所に置けば、
    # 実行の順序は 1 枚で配っていたときと同じになる。nonce はサーバーが id を見て差し込む
    shell = JS_RE.sub(lambda _: f'<script id="app-js" src="{PREFIX}{js_name}"></script>', shell, count=1)
    return css_name, css, js_name, js, shell


def build() -> tuple[str, str, int]:
    """(css のファイル名, js のファイル名, 殻のバイト数) を返す。"""
    css_name, css, js_name, js, shell = split(SRC.read_text(encoding="utf-8"))

    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("app.*.css"):
        old.unlink()
    for old in OUT.glob("app.*.js"):
        old.unlink()
    (OUT / css_name).write_text(css, encoding="utf-8", newline="\n")
    (OUT / js_name).write_text(js, encoding="utf-8", newline="\n")
    (OUT / "index.html").write_text(shell, encoding="utf-8", newline="\n")
    return css_name, js_name, len(shell.encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="生成物を数えるだけ")
    a = ap.parse_args()
    if a.check:
        if not (OUT / "index.html").is_file():
            print("frontend/dist/ がありません（python scripts/build_app.py で生成）")
            return 1
        for p in sorted(OUT.iterdir()):
            print(f"  {p.name}  {p.stat().st_size / 1024:.0f} KB")
        return 0
    css_name, js_name, shell_bytes = build()
    src_bytes = SRC.stat().st_size
    print(f"元: {src_bytes / 1024:.0f} KB", file=sys.stderr)
    print(f"  {OUT.relative_to(ROOT)}/index.html   {shell_bytes / 1024:.0f} KB（これだけがサーバーから出る）", file=sys.stderr)
    for name in (css_name, js_name):
        print(f"  {OUT.relative_to(ROOT)}/{name}  {(OUT / name).stat().st_size / 1024:.0f} KB（R2 から）", file=sys.stderr)
    print("次に: python scripts/upload_app_r2.py", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
