"""日本語フォントを unicode-range で分割した WOFF2 に作り直す（Google Fonts と同じ配信方式）。

  python scripts/build_fonts.py            # fonts/split/ に分割 WOFF2 と fonts.css を生成
  python scripts/build_fonts.py --check    # 生成物の件数と合計サイズを表示するだけ

背景: IBM Plex Sans JP（1.1MB）と DotGothic16（0.5MB）を全訪問者に丸ごと配っていて、公開サイトの転送量の主因だった。
分割すると、ブラウザは画面（と共有画像）に出る文字を含む断片だけを取るので、実効 50〜200KB になる。

生成物:
  fonts/split/<フォント名>.<番号>.<内容ハッシュ>.woff2  … 断片（ファイル名にハッシュがあるので 1 年キャッシュしてよい）
  fonts/split/fonts.<ハッシュ>.css                    … @font-face（unicode-range 付き）。backend/main.py が index.html に <link> で入れる
サーバー描画（PIL）は従来どおり fonts/*.ttf を使う。
"""
from __future__ import annotations

import argparse
import hashlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
OUT = FONTS / "split"

# (元ファイル, CSS の family, weight)
SOURCES = [
    ("IBMPlexSansJP-Regular.ttf", "IBM Plex Sans JP", 400),
    ("IBMPlexSansJP-Bold.ttf", "IBM Plex Sans JP", 700),
    ("DotGothic16-Regular.ttf", "DotGothic16", 400),
]
# 先頭の断片にまとめる範囲（UI の固定文字が入る: ラテン・記号・かな・全角英数）。ここに無い文字（主に漢字）は
# コードポイント BLOCK 幅ごとの断片にする
CORE_RANGES = [
    (0x0000, 0x024F), (0x02B0, 0x02FF), (0x0370, 0x03FF), (0x0400, 0x04FF),
    (0x2000, 0x206F), (0x20A0, 0x20CF), (0x2100, 0x214F), (0x2150, 0x218F), (0x2190, 0x21FF),
    (0x2200, 0x22FF), (0x2300, 0x23FF), (0x2460, 0x24FF), (0x2500, 0x257F), (0x2580, 0x259F),
    (0x25A0, 0x25FF), (0x2600, 0x26FF), (0x2700, 0x27BF), (0x3000, 0x30FF), (0x31F0, 0x31FF),
    (0x3200, 0x32FF), (0x3300, 0x33FF), (0xFE10, 0xFE1F), (0xFE30, 0xFE4F), (0xFF00, 0xFFEF),
]
BLOCK = 128   # 漢字などの断片はコードポイント 128 幅ごと（IBM Plex Sans JP で 1 断片 3〜8KB、約 170 断片）。曲名の漢字は散らばるので断片は小さいほど無駄が少ない
# 画面の固定文字（ラベル・説明文）に出る文字は全部先頭の断片に入れる。これが無いと UI の漢字が数十の断片に散らばり、
# 初回表示で 50 断片・1.2MB を読んでしまう（実測）。曲名など利用者の文字だけが追加の断片を引く
UI_TEXT_FILES = [ROOT / "frontend" / "index.html"]


def _ui_chars() -> set[int]:
    chars: set[int] = set()
    for p in UI_TEXT_FILES:
        chars.update(ord(c) for c in p.read_text(encoding="utf-8"))
    return chars


def _in_core(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in CORE_RANGES)


def _ranges_css(cps: list[int]) -> str:
    """連続するコードポイントをまとめて U+4E00-4EFF, U+4F01 の形にする。"""
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


def build_one(src: Path, family: str, weight: int) -> list[tuple[str, int, str]]:
    """1 フォントを分割。(ファイル名, バイト数, unicode-range) のリストを返す。"""
    from fontTools import subset
    from fontTools.ttLib import TTFont

    base = src.stem
    font = TTFont(src)
    cmap = font.getBestCmap()
    cps = sorted(cp for cp in cmap if cp >= 0x20)
    ui = _ui_chars()
    core = [cp for cp in cps if _in_core(cp) or cp in ui]
    rest = [cp for cp in cps if not (_in_core(cp) or cp in ui)]
    # 漢字などはコードポイントの BLOCK 幅ごとに 1 断片。unicode-range を「U+4E00-4FFF」のような 1 区間で書けるので
    # CSS が小さく済む（文字の有無で細切れにすると CSS が 140KB になった）
    blocks: dict[int, list[int]] = {}
    for cp in rest:
        blocks.setdefault(cp // BLOCK, []).append(cp)
    # 断片の unicode-range は BLOCK 幅の区間から「先頭の断片に入れた文字」を抜いたもの。抜かないと、UI の漢字に対して
    # ブラウザが（後で定義された）区間の断片も取りに行き、二重に読んでしまう（実測で初回 57 断片）
    core_set = set(core)
    groups: list[tuple[list[int], str | None]] = [(core, None)]
    for b in sorted(blocks):
        span = [cp for cp in range(b * BLOCK, b * BLOCK + BLOCK) if cp not in core_set]
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
        f = TTFont(src)
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
        print(f"  {name}  {len(data) / 1024:6.1f} KB  {len(group)} 文字", file=sys.stderr)
    return out


def write_css(entries: list[tuple[str, int, str, str, int]]) -> str:
    lines = ["/* scripts/build_fonts.py が生成。手で編集しない。unicode-range 付きの断片フォント */"]
    for name, _, ranges, family, weight in entries:
        # URL はルート相対。この CSS は /fonts/split/ から <link> で読まれるので、相対だと /fonts/split/fonts/split/… になる
        lines.append(
            f'@font-face {{ font-family: "{family}"; font-weight: {weight}; font-style: normal; font-display: swap; '
            f'src: url("/fonts/split/{name}") format("woff2"); unicode-range: {ranges}; }}'
        )
    css = "\n".join(lines) + "\n"
    for old in OUT.glob("fonts.*.css"):
        old.unlink()
    (OUT / "fonts.css").write_text(css, encoding="utf-8", newline="\n")
    # 内容ハッシュ付きの同じものを別名で置く。index.html からは <link> で読み、/fonts/ の 1 年キャッシュに乗せる
    # （index.html 自体は no-cache で毎回配るので、CSS を埋め込むと毎回 140KB 分が転送される）
    digest = hashlib.sha256(css.encode("utf-8")).hexdigest()[:8]
    (OUT / f"fonts.{digest}.css").write_text(css, encoding="utf-8", newline="\n")
    return css


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="生成物を数えるだけ")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    if a.check:
        files = sorted(OUT.glob("*.woff2"))
        total = sum(p.stat().st_size for p in files)
        print(f"{len(files)} 断片, 合計 {total / 1024:.0f} KB, fonts.css {'あり' if (OUT / 'fonts.css').exists() else '無し'}")
        return 0
    entries = []
    for fname, family, weight in SOURCES:
        src = FONTS / fname
        print(f"{fname}:", file=sys.stderr)
        for name, size, ranges in build_one(src, family, weight):
            entries.append((name, size, ranges, family, weight))
    css = write_css(entries)
    total = sum(e[1] for e in entries)
    print(f"{len(entries)} 断片, 合計 {total / 1024:.0f} KB, fonts.css {len(css)} 文字")
    return 0


if __name__ == "__main__":
    sys.exit(main())
