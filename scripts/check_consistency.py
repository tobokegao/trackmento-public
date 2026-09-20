"""文書・画面の記述が、コードの実態とずれていないかを機械的に見る（2026-09-20 に作った）。

コミットやプッシュの前に回す。**機械で確実に言えることだけ**を見る道具で、
「書いてあることが今も正しいか」の判断は人（と `/consistency-check` スキル）の側に残す。
誤検知が出ると回されなくなるので、迷う検査は入れない。

    PYTHONUTF8=1 .venv/Scripts/python scripts/check_consistency.py [--json]

見るもの:

1. **参照されているファイルが実在するか** … 文書の中のバッククォートに囲まれたパス
   （`backend/render.py` など）。2026-09-20 に `docs/` を分けたとき、切れた参照が 3 本出た
2. **マスの上限が 4 か所でそろっているか** … ずれると並びが黙って潰れる（CLAUDE.md の覚え書き）
3. **同じ数字が文書とコードで一致するか** … プレイリストの上限・JPEG の品質・画像の画素数。
   画面の案内が「最大 256 曲」のままだった（実際は 500）のを拾えなかったので入れた
4. **サイト内ページの「最終更新」が、更新情報のいちばん新しい日付より古くないか**
5. **移転前の URL が現役の説明として残っていないか**（`trackmento.onrender.com`）
6. **どこからも参照されていないスクリプト** … 使い捨ての調査スクリプトを置かない方針の確認

NG があれば終了コード 1。
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 文書（人が書き、古くなりうるもの）
DOCS = ["README.md", "CLAUDE.md", "video-notes.md",   # trackmento-spec.md は初期仕様の記録なので見ない
        *sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "docs").glob("*.md")),
        *sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / ".claude" / "skills").rglob("SKILL.md"))]

# 移転前の URL を現役の説明として書いてよいファイル（引っ越しの記録・受け皿の実装）
OLD_URL_OK = {"docs/ops.md", "docs/history.md", "backend/config.py", "backend/main.py", "render.yaml",
              "backend/pages.py", "frontend/index.html", "scripts/check_consistency.py"}

# 参照の有無を見るスクリプト（使い捨てを置かない方針の確認）
SCRIPT_DIRS = ["promo", "scripts"]


def read(path: str) -> str:
    try:
        return io.open(ROOT / path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return ""


_ALL: list[str] = []


def _somewhere(ref: str) -> bool:
    """`sources/itunes.py` のように上の階層を省いた書き方も、リポジトリ内にあれば良しとする。"""
    if not _ALL:
        _ALL.extend(tracked())
    return any(p == ref or p.endswith("/" + ref) for p in _ALL)


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    return [p for p in out.split("\n") if p and not p.startswith("promo/node_modules")]


# ---- 1. 参照されているファイルが実在するか ----
_PATH_RE = re.compile(r"`([A-Za-z0-9_.][A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+\.(?:py|md|mjs|ts|tsx|html|json|ya?ml|js|sh|txt|css))`")
# ディレクトリの区切りを含むものだけ見る（`index.html` のような一般名は対象外）。
# 末尾に `*` が付く書き方（`backend/sources/*`）や、説明のための例示は拾わない
_PATH_SKIP = ("http://", "https://", "your-", "<", ">", "*")


def check_paths() -> list[str]:
    ng = []
    for doc in DOCS:
        body = read(doc)
        for m in _PATH_RE.finditer(body):
            ref = m.group(1)
            if any(s in ref for s in _PATH_SKIP):
                continue
            if (ROOT / ref).exists() or _somewhere(ref):
                continue
            line = body[:m.start()].count("\n") + 1
            ng.append(f"{doc}:{line} 参照先が無い: {ref}")
    return ng


# ---- 2. マスの上限（4 か所） ----
def check_cells() -> list[str]:
    fe = read("frontend/index.html")
    grids = read("backend/grids.py")
    config = read("backend/config.py")

    def one(pat: str, body: str, what: str) -> int | None:
        m = re.search(pat, body)
        if not m:
            ng.append(f"上限の定義が見つからない: {what}")
            return None
        return int(m.group(1))

    ng: list[str] = []
    side_fe = one(r"MAX_SIDE_CELLS\s*=\s*(\d+)", fe, "index.html の MAX_SIDE_CELLS")
    total_fe = one(r"MAX_CELLS\s*=\s*(\d+)", fe, "index.html の MAX_CELLS")
    cols = one(r"MAX_COLS\s*=\s*(?:MAX_ROWS\s*=\s*)?(\d+)", grids, "grids.py の MAX_COLS")
    rows = one(r"MAX_ROWS\s*=\s*(?:MAX_COLS\s*=\s*)?(\d+)", grids, "grids.py の MAX_ROWS")
    m = re.search(r'def max_cells.*?os\.getenv\("MAX_CELLS",\s*"(\d+)"', config, re.S)
    total_cfg = int(m.group(1)) if m else None
    if total_cfg is None:
        ng.append("上限の定義が見つからない: config.py の max_cells()")

    if None not in (side_fe, cols, rows) and not (side_fe == cols == rows):
        ng.append(f"1 辺の上限がずれている: index.html {side_fe} / grids.py {cols}x{rows}")
    if None not in (total_fe, total_cfg) and total_fe != total_cfg:
        ng.append(f"総数の上限がずれている: index.html {total_fe} / config.py {total_cfg}")
    return ng


# ---- 3. 同じ数字が文書とコードで一致するか ----
def _int_of(path: str, pat: str) -> int | None:
    m = re.search(pat, read(path))
    return int(m.group(1)) if m else None


def check_numbers() -> list[str]:
    ng: list[str] = []
    items = []

    max_items = _int_of("backend/sources/playlist.py", r"^MAX_ITEMS\s*=\s*(\d+)")
    if max_items:
        items.append((r"最大\s*([\d,]+)\s*曲", max_items, "プレイリストの上限（playlist.py の MAX_ITEMS）"))

    jpeg = _int_of("backend/share.py", r"^JPEG_QUALITY\s*=\s*(\d+)")
    if jpeg:
        items.append((r"JPEG\s*品質\s*([\d,]+)", jpeg, "JPEG の品質（share.py の JPEG_QUALITY）"))

    px = _int_of("backend/render.py", r"MAX_IMAGE_PIXELS\s*=\s*([\d_]+)".replace("_", "_"))
    if px is None:
        m = re.search(r"MAX_IMAGE_PIXELS\s*=\s*([\d_]+)", read("backend/render.py"))
        px = int(m.group(1).replace("_", "")) if m else None
    if px:
        items.append((r"([\d,]+)\s*万ピクセル", px // 10000, "画像の画素数の上限（render.py の MAX_IMAGE_PIXELS）"))

    # 画面（利用者に見えるもの）も対象に入れる
    for doc in DOCS + ["frontend/index.html", "backend/pages.py"]:
        body = read(doc)
        for pat, want, what in items:
            for m in re.finditer(pat, body):
                got = int(m.group(1).replace(",", ""))
                if got == want:
                    continue
                line = body[:m.start()].count("\n") + 1
                ng.append(f"{doc}:{line} {what} は {want} なのに「{m.group(0)}」と書いてある")
    return ng


# ---- 4. サイト内ページの「最終更新」 ----
def check_updated() -> list[str]:
    body = read("backend/pages.py")
    m = re.search(r'UPDATED\s*=\s*\{"ja":\s*"最終更新:\s*(\d+)年(\d+)月(\d+)日', body)
    c = re.search(r'CHANGES[^=]*=\s*\[\s*\(\s*"(\d{4})-(\d{2})-(\d{2})"', body)
    if not (m and c):
        return ["backend/pages.py の UPDATED か CHANGES の形が変わった（この検査を直す）"]
    upd = tuple(int(x) for x in m.groups())
    new = tuple(int(x) for x in c.groups())
    if upd < new:
        return [f"backend/pages.py の「最終更新」({upd[0]}-{upd[1]:02d}-{upd[2]:02d}) が、"
                f"更新情報のいちばん新しい日付 ({new[0]}-{new[1]:02d}-{new[2]:02d}) より古い"]
    return []


# ---- 5. 移転前の URL ----
def check_old_url() -> list[str]:
    ng = []
    for path in tracked():
        if path in OLD_URL_OK or not path.endswith((".md", ".py", ".html", ".ts", ".mjs", ".yml", ".yaml")):
            continue
        body = read(path)
        for i, line in enumerate(body.split("\n"), 1):
            if "trackmento.onrender.com" in line and not any(w in line for w in ("移転", "引っ越し", "受け皿", "旧")):
                ng.append(f"{path}:{i} 移転前の URL が残っている（本番は trackmento.com）")
    return ng


# ---- 6. どこからも参照されていないスクリプト ----
def check_unreferenced() -> list[str]:
    paths = tracked()
    bodies = {p: read(p) for p in paths if p.endswith((".md", ".py", ".mjs", ".ts", ".tsx", ".html", ".json", ".yml", ".yaml", ".sh"))}
    ng = []
    for path in paths:
        if not path.endswith((".mjs", ".py", ".sh")):
            continue
        if path.split("/")[0] not in SCRIPT_DIRS:
            continue
        name = path.split("/")[-1]
        if any(name in b for p, b in bodies.items() if p != path):
            continue
        ng.append(f"{path} はどこからも参照されていない（使い捨てなら消す。残すなら文書から名指しする）")
    return ng


CHECKS = [
    ("参照先の実在", check_paths),
    ("マスの上限（4 か所）", check_cells),
    ("文書とコードの数字", check_numbers),
    ("サイト内ページの最終更新", check_updated),
    ("移転前の URL", check_old_url),
    ("参照の無いスクリプト", check_unreferenced),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="文書とコードの食い違いを見る")
    ap.add_argument("--json", action="store_true", help="結果を JSON で出す")
    args = ap.parse_args()

    result, total = {}, 0
    for name, fn in CHECKS:
        ng = fn()
        result[name] = ng
        total += len(ng)

    if args.json:
        print(json.dumps({"ng": total, "checks": result}, ensure_ascii=False, indent=2))
        return 1 if total else 0

    for name, ng in result.items():
        mark = "NG" if ng else "OK"
        print(f"[{mark}] {name}" + (f"（{len(ng)} 件）" if ng else ""))
        for line in ng:
            print(f"     - {line}")
    print()
    print(f"食い違い {total} 件" if total else "食い違いなし")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
