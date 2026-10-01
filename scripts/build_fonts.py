"""日本語フォントをunicode-rangeで分割したWOFF2に作り直す（Google Fontsと同じ配信方式）。

  python scripts/build_fonts.py            # fonts/split/ に分割WOFF2とfonts.cssを生成
  python scripts/build_fonts.py --check    # 生成物の件数と合計サイズを表示するだけ

背景: IBM Plex Sans JP（1.1MB）とDotGothic16（0.5MB）を全訪問者に丸ごと配っていて、公開サイトの転送量の主因だった。
分割すると、ブラウザは画面（と共有画像）に出る文字を含む断片だけを取るので、実効50〜200KBになる。

生成物:
  fonts/split/<フォント名>.<番号>.<内容ハッシュ>.woff2  … 断片（ファイル名にハッシュがあるので1年キャッシュしてよい）
  fonts/split/fonts.<ハッシュ>.css                    … @font-face（unicode-range付き）。backend/main.pyがindex.htmlに <link> で入れる
サーバー描画（PIL）は従来どおりfonts/*.ttfを使う。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
OUT = FONTS / "split"

# PCの操作部品の字（15px）。英数字は東雲ゴシック14、それ以外はGalmuri14を2目下げたもの（scripts/make_pc_dot_font.py）。
# 同じfamilyに2つのfaceをunicode-rangeで分けて入れる。範囲が重なるとどちらが選ばれるかがブラウザ任せになるので、
# Galmuriからは英数字の範囲を抜く（2026-09-24）。東雲に回すのはASCIIだけ。Latin-1（× ° ± など）は東雲ではJISの全角の字形で、
# 「Grid (columns × rows)」の × が大きく見えたのでGalmuriに任せる
PC_DOT_LATIN = [(0x0020, 0x007E)]

# (元ファイル, CSSのfamily, weight, 追加の指定)
#   only    … この範囲の字だけ入れる
#   exclude … この範囲の字を入れない
#   descriptors … @font-faceに足す記述子
SOURCES = [
    ("IBMPlexSansJP-Regular.ttf", "IBM Plex Sans JP", 400, {}),
    ("IBMPlexSansJP-Bold.ttf", "IBM Plex Sans JP", 700, {}),
    ("JF-Dot-MPlus12.ttf", "JF Dot MPlus12", 400, {}),   # 操作部品のドット字（2026-09-24にDotGothic16から）。スマホは12pxのまま
    # 東雲14は14pxの升目。PCの字の大きさは15pxなので14/15に縮めて1目 = 1pxにする（ほかの大きさではにじむ）
    ("JF-Dot-Shinonome14.ttf", "TM Dot PC", 400, {"only": PC_DOT_LATIN, "descriptors": "size-adjust: 93.3333%;"}),
    ("Galmuri14-Down2.ttf", "TM Dot PC", 400, {"exclude": PC_DOT_LATIN}),
]
# 先頭の断片にまとめる範囲（UIの固定文字が入る: ラテン・記号・かな・全角英数）。ここに無い文字（主に漢字）は
# コードポイントBLOCK幅ごとの断片にする
# ギリシャ・キリル・数学記号・罫線・囲み文字などはUIに無く曲名にも稀なので先頭に入れない（必要な断片が随時読まれる）。
# 先頭を小さく保つのが新規訪問者ごとの転送量に直結する
CORE_RANGES = [
    (0x0020, 0x007E), (0x00A0, 0x00FF),        # ASCII・Latin-1
    (0x2010, 0x2027), (0x2030, 0x203B),        # ダッシュ・引用符・… ‰ ※ など
    (0x3000, 0x30FF), (0x31F0, 0x31FF),        # 句読点・記号・ひらがな・カタカナ
    (0xFF01, 0xFF5E), (0xFF61, 0xFF9F),        # 全角英数・半角カナ
]
BLOCK = 128   # 漢字などの断片はコードポイント128幅ごと（IBM Plex Sans JPで1断片3〜8KB、約170断片）。曲名の漢字は散らばるので断片は小さいほど無駄が少ない
# 画面の固定文字（ラベル・説明文）に出る文字は全部先頭の断片に入れる。これが無いとUIの漢字が数十の断片に散らばり、
# 初回表示で50断片・1.2MBを読んでしまう（実測）。曲名など利用者の文字だけが追加の断片を引く
UI_TEXT_FILES = [ROOT / "frontend" / "index.html"]


# ソースのコメントは画面に出ないので、先頭断片に入れる文字からは外す。
# index.htmlには日本語のコメントが多く、入れたままだと先頭断片が4割ほど無駄に太る
# （実測: 日本語の文字種597 → 362）。取りこぼしても、その文字は別の断片から読まれるだけで壊れない。
# 逆に「コメントでないものを誤って消す」と先頭断片から抜けてしまうので、判定は控えめにする
_COMMENT_PATTERNS = (
    re.compile(r"<!--.*?-->", re.S),                   # HTML
    re.compile(r"/\*.*?\*/", re.S),                    # CSS / JSのブロック
    re.compile(r"^[ \t]*//.*$", re.M),                 # 行頭からの行コメント
    # 行末の行コメント。直前が区切り文字のときだけ拾い、引用符を含む行は避ける
    # （"https://…" の // は直前が : なので当たらない）
    re.compile(r"(?<=[;,{})\s])//[^\n\"'`]*$", re.M),
)


def _strip_comments(src: str) -> str:
    for pat in _COMMENT_PATTERNS:
        src = pat.sub(" ", src)
    return src


def _ui_chars() -> set[int]:
    chars: set[int] = set()
    for p in UI_TEXT_FILES:
        chars.update(ord(c) for c in _strip_comments(p.read_text(encoding="utf-8")))
    return chars


def _in_core(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in CORE_RANGES)


def _ranges_css(cps: list[int]) -> str:
    """連続するコードポイントをまとめてU+4E00-4EFF, U+4F01の形にする。"""
    cps = sorted(set(cps))
    parts: list[str] = []
    start = prev = cps[0]
    for cp in cps[1:] + [None]:
        if cp is not None and cp == prev + 1:
            prev = cp
            continue
        parts.append(f"U+{start:04X}" if start == prev else f"U+{start:04X}-{prev:04X}")
        if cp is None:
            break
        start = prev = cp
    return ", ".join(parts)


def _in(cp: int, ranges) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def build_one(src: Path, family: str, weight: int, extra: dict) -> list[tuple[str, int, str]]:
    """1フォントを分割。(ファイル名, バイト数, unicode-range) のリストを返す。"""
    from fontTools import subset
    from fontTools.ttLib import TTFont

    base = src.stem
    font = TTFont(src)
    cmap = font.getBestCmap()
    only, exclude = extra.get("only"), extra.get("exclude", [])
    cps = sorted(cp for cp in cmap if cp >= 0x20 and (only is None or _in(cp, only)) and not _in(cp, exclude))
    ui = _ui_chars()
    core = [cp for cp in cps if _in_core(cp) or cp in ui]
    rest = [cp for cp in cps if not (_in_core(cp) or cp in ui)]
    # 漢字などはコードポイントのBLOCK幅ごとに1断片。unicode-rangeを「U+4E00-4FFF」のような1区間で書けるので
    # CSSが小さく済む（文字の有無で細切れにするとCSSが140KBになった）
    blocks: dict[int, list[int]] = {}
    for cp in rest:
        blocks.setdefault(cp // BLOCK, []).append(cp)
    # 断片のunicode-rangeはBLOCK幅の区間から「先頭の断片に入れた文字」を抜いたもの。抜かないと、UIの漢字に対して
    # ブラウザが（後で定義された）区間の断片も取りに行き、二重に読んでしまう（実測で初回57断片）
    core_set = set(core)
    groups: list[tuple[list[int], str | None]] = [(core, None)]
    for b in sorted(blocks):
        span = [cp for cp in range(b * BLOCK, b * BLOCK + BLOCK)
                if cp not in core_set and not _in(cp, exclude) and (only is None or _in(cp, only))]
        groups.append((blocks[b], _ranges_css(span)))

    # 古い生成物を消す（ハッシュ名なので溜まる）
    for old in OUT.glob(f"{base}.*.woff2"):
        old.unlink()

    out: list[tuple[str, int, str]] = []
    for i, (group, block_range) in enumerate(groups):
        if not group:
            continue
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["*"]      # カーニング・合字などは残す
        opts.notdef_outline = True
        opts.name_IDs = ["*"]
        opts.hinting = False
        f = TTFont(src, recalcTimestamp=False)   # head.modifiedを更新しない（更新すると毎回ハッシュが変わり、全断片のキャッシュが無効になる）
        sub = subset.Subsetter(options=opts)
        sub.populate(unicodes=group)
        sub.subset(f)
        f.flavor = "woff2"
        buf = io.BytesIO()
        f.save(buf)
        data = buf.getvalue()
        digest = hashlib.sha256(data).hexdigest()[:8]
        name = f"{base}.{i:03d}.{digest}.woff2"
        (OUT / name).write_bytes(data)
        out.append((name, len(data), block_range or _ranges_css(group)))
        print(f"  {name}  {len(data) / 1024:6.1f} KB  {len(group)}文字", file=sys.stderr)
    return out


def write_css(entries: list[tuple[str, int, str, str, int, str]]) -> str:
    lines = ["/* scripts/build_fonts.pyが生成。手で編集しない。unicode-range付きの断片フォント */"]
    for name, _, ranges, family, weight, desc in entries:
        # URLはルート相対。このCSSは /fonts/split/ から <link> で読まれるので、相対だと /fonts/split/fonts/split/… になる
        lines.append(
            f'@font-face {{ font-family: "{family}"; font-weight: {weight}; font-style: normal; font-display: swap; '
            f'src: url("/fonts/split/{name}") format("woff2"); unicode-range: {ranges};{" " + desc if desc else ""} }}'
        )
    css = "\n".join(lines) + "\n"
    for old in OUT.glob("fonts.*.css"):
        old.unlink()
    (OUT / "fonts.css").write_text(css, encoding="utf-8", newline="\n")
    # 内容ハッシュ付きの同じものを別名で置く。index.htmlからは <link> で読み、/fonts/ の1年キャッシュに乗せる
    # （index.html自体はno-cacheで毎回配るので、CSSを埋め込むと毎回140KB分が転送される）
    digest = hashlib.sha256(css.encode("utf-8")).hexdigest()[:8]
    (OUT / f"fonts.{digest}.css").write_text(css, encoding="utf-8", newline="\n")
    return css


# 曲名の描く前の掃除（frontendのoneLine）が使うIBM Plex Sans JPのcmap。backend/render.pyの _cmapと同じ2本の和集合。
# ブラウザは無い字を代替フォントで測るので、cmapを持たないとサーバー描画（無い字を落とす）と字幅がずれる（2026-09-24）
CMAP_FONTS = ("IBMPlexSansJP-Regular.ttf", "IBMPlexSansJP-Bold.ttf")
CMAP_RE = re.compile(r"/\*__PLEX_CMAP__\*/.*?/\*__PLEX_CMAP_END__\*/", re.S)


def _base36(n: int) -> str:
    d = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = d[r] + out
        if not n:
            return out


def write_cmap_js() -> bool:
    """index.htmlのPLEX_CMAP_BLOCKS / PLEX_CMAP_BITSを作り直す。128字の区間ごとに、字のある区間だけ16バイトのビット列を持つ
    （全BMPのビット列8KBより小さい。16進で約6.9KB）。
    **base64にしない**: 大文字の並びが偶然「AKIA＋英大文字16字」（AWSの鍵の形）になり、コミットの見張り（scripts/scan_secrets.sh）に止められた。
    小文字の16進なら既知の鍵の形に当たらない。中身が同じなら書かない（戻り値は書いたか）"""
    from fontTools.ttLib import TTFont
    cps: set[int] = set()
    for name in CMAP_FONTS:
        with TTFont(str(FONTS / name), lazy=True) as tt:
            cps |= set(tt.getBestCmap().keys())
    blocks: dict[int, bytearray] = {}
    for cp in cps:
        bm = blocks.setdefault(cp >> 7, bytearray(16))
        bm[(cp & 127) >> 3] |= 1 << (cp & 7)
    order = sorted(blocks)
    js = ('/*__PLEX_CMAP__*/const PLEX_CMAP_BLOCKS = "' + ",".join(_base36(b) for b in order)
          + '", PLEX_CMAP_BITS = "' + b"".join(blocks[b] for b in order).hex()
          + '";/*__PLEX_CMAP_END__*/')
    html_path = UI_TEXT_FILES[0]
    html = html_path.read_text(encoding="utf-8")
    if not CMAP_RE.search(html):
        raise SystemExit("index.htmlに /*__PLEX_CMAP__*/ の印がありません")
    new = CMAP_RE.sub(lambda _: js, html, count=1)
    if new == html:
        return False
    html_path.write_text(new, encoding="utf-8", newline="\n")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="生成物を数えるだけ")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if a.check:
        files = sorted(OUT.glob("*.woff2"))
        total = sum(p.stat().st_size for p in files)
        print(f"{len(files)}断片, 合計{total / 1024:.0f} KB, fonts.css {'あり' if (OUT / 'fonts.css').exists() else '無し'}")
        return 0
    entries = []
    for fname, family, weight, extra in SOURCES:
        src = FONTS / fname
        print(f"{fname}:", file=sys.stderr)
        for name, size, ranges in build_one(src, family, weight, extra):
            entries.append((name, size, ranges, family, weight, extra.get("descriptors", "")))
    css = write_css(entries)
    if write_cmap_js():
        print("index.htmlのPLEX_CMAPを作り直しました（build_app.pyも回す）", file=sys.stderr)
    total = sum(e[1] for e in entries)
    print(f"{len(entries)}断片, 合計{total / 1024:.0f} KB, fonts.css {len(css)}文字")
    return 0


if __name__ == "__main__":
    sys.exit(main())
