"""「変更したら回すもの」（CLAUDE.mdの表）を1本にまとめた門。コミットとpushの前に自動で回る。

    PYTHONUTF8=1 .venv/Scripts/python scripts/check.py            # 変えたファイルに応じて回す（コミット前の既定）
    PYTHONUTF8=1 .venv/Scripts/python scripts/check.py --all      # 手元で回せるものを全部
    PYTHONUTF8=1 .venv/Scripts/python scripts/check.py --r2       # 配る物がR2にあるか（push前）

背景（2026-09-27）: 表の手順は人（とClaude）が覚えて回す形で、忘れると本番が壊れる
（フォントやCSS / JSの上げ忘れ → 本番で404）。「内側で速く気づき、外側で確実に止める」
という考え方に沿い、機械で言えることはここで止める。フックは `.githooks/pre-commit` と `pre-push`、
CIは `.github/workflows/check.yml`。

止める（NG）もの:
  - frontend/index.htmlを変えたのに、殻（frontend/dist/index.html）を組み直していない
  - 画面の固定文字が、分割フォントの先頭断片に入っていない（build_fonts.pyの回し忘れ）
  - check_i18n.py / check_trim.py / check_consistency.pyが落ちる
  - --r2: 殻が指すCSS / JS、fonts.<hash>.cssが指す断片がR2に無い（上げ忘れ → 本番で404）

知らせるだけのもの: compare_render.pyとcompare_trim.py。サーバーを立て、ブラウザでの操作も
要るので自動では回せない。該当するファイルを変えたときに、回すよう表示する。
足した行に英数字と日本語のあいだの半角スペースが残っているときも知らせる（曲名のデータにはありうるので止めない）。

わざと通したいときは `git commit --no-verify` / `git push --no-verify`。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
PY = sys.executable
INDEX = "frontend/index.html"
SHELL = ROOT / "frontend" / "dist" / "index.html"
SPLIT = ROOT / "fonts" / "split"

# 描画の二重実装に当たる名前。index.htmlの差分にこれが出たらcompare_render.pyを促す
RENDER_NAMES = re.compile(r"renderShareCanvas|rowPlan|planRows|splitTitle|sidebar|wrapPlan|WRAP_|slabPlan|slabFrame|SLAB_"
                          r"|flowRows|FLOW_|coverBlurPad|blurMargin|CELL_W|CELL_H_BY_RATIO|GAP_PX|MAX_SIDE\b")
TRIM_NAMES = re.compile(r"trimName|nkey")

ng: list[str] = []
notes: list[str] = []


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout


def run(script: str, label: str) -> None:
    r = subprocess.run([PY, str(ROOT / "scripts" / script)], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
    if r.returncode == 0:
        print(f"  OK  {label}")
        return
    out = (r.stdout + r.stderr).strip().splitlines()
    ng.append(f"{label}が落ちた（{script}）\n" + "\n".join("      " + ln for ln in out[-15:]))


def check_shell() -> None:
    """殻が今のindex.htmlから組んだものと同じか。違えば古いCSS / JSが配られ続ける"""
    import build_app
    *_, shell = build_app.split((ROOT / INDEX).read_text(encoding="utf-8"))
    have = SHELL.read_text(encoding="utf-8") if SHELL.is_file() else ""
    if shell != have:
        ng.append("殻が古い。scripts/build_app.py → scripts/upload_app_r2.pyを回し、frontend/dist/index.htmlもコミットする")
    else:
        print("  OK  殻（frontend/dist/index.html）")


def _css_entries() -> list[tuple[str, set[int]]]:
    """fonts.<hash>.cssの (断片のファイル名, unicode-rangeのコードポイント) を返す。配る側（main.py）と同じく最後の1枚を読む"""
    css = sorted(SPLIT.glob("fonts.*.css"))
    if not css:
        return []
    out = []
    for name, ranges in re.findall(r'url\("/fonts/split/([^"]+)"\)[^;]*;\s*unicode-range:\s*([^;]+);', css[-1].read_text(encoding="utf-8")):
        cps: set[int] = set()
        for part in ranges.split(","):
            lo, _, hi = part.strip()[2:].partition("-")
            cps.update(range(int(lo, 16), int(hi or lo, 16) + 1))
        out.append((name, cps))
    return out


def check_fonts() -> None:
    """画面の固定文字が各フォントの先頭断片に入っているか。入っていなければbuild_fonts.pyを回していない。
    （壊れはしないが、字が数十の断片に散らばって初回の読み込みが跳ねる。2026-09の実測で50断片・1.2MB）"""
    from fontTools.ttLib import TTFont
    import build_fonts as bf
    entries = _css_entries()
    if not entries:
        ng.append("fonts/split/fonts.<hash>.cssが無い。scripts/build_fonts.pyを回す")
        return
    missing_files = [n for n, _ in entries if not (SPLIT / n).is_file()]
    if missing_files:
        ng.append(f"fonts.cssが指す断片が{len(missing_files)}個無い（例: {missing_files[0]}）。scripts/build_fonts.pyを回す")
        return
    ui = bf._ui_chars()
    lacking: dict[str, str] = {}
    for src, _family, _weight, extra in bf.SOURCES:
        stem = Path(src).stem
        core = next((cps for n, cps in entries if n.startswith(f"{stem}.000.")), None)
        if core is None:
            ng.append(f"{stem}の先頭断片がfonts.cssに無い。scripts/build_fonts.pyを回す")
            continue
        only, exclude = extra.get("only"), extra.get("exclude", [])
        need = {cp for cp in TTFont(bf.FONTS / src).getBestCmap()
                if cp >= 0x20 and cp in ui and (only is None or bf._in(cp, only)) and not bf._in(cp, exclude)}
        if need - core:
            lacking[stem] = "".join(chr(c) for c in sorted(need - core)[:10])
    if lacking:
        ng.append("固定文字が先頭断片に無い（" + "・".join(f"{k}: {v}" for k, v in lacking.items())
                  + "）。scripts/build_fonts.py → scripts/upload_fonts_r2.py → build_app.pyを回す")
    else:
        print("  OK  分割フォント（固定文字が先頭断片に入っている）")


def _load_env() -> None:
    env = ROOT / ".env"
    for line in env.read_text(encoding="utf-8").splitlines() if env.is_file() else []:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def check_r2() -> None:
    """配る物がR2にあるか。手元に鍵があれば一覧（数回の呼び出し）で、無ければ公開URLへのHEADで見る"""
    shell = SHELL.read_text(encoding="utf-8") if SHELL.is_file() else ""
    keys = [f"app/{n}" for n in re.findall(r'"app/(app\.[0-9a-f]{8}\.(?:css|js))"', shell)]
    keys += [f"app/{n}" for n in re.findall(r'"app/(banners/[\w.-]+\.(?:gif|png))"', shell)]   # 画面に貼る絵
    keys += [f"fonts/{n}" for n, _ in _css_entries()]
    if not keys:
        ng.append("R2に上げる物が見つからない（殻とfonts.cssを確かめる）")
        return
    _load_env()
    have: set[str] | None = None
    try:
        from backend.storage import get_storage
        st = get_storage()
        if st.is_remote:
            have = {k for pre in ("app/", "fonts/") for k, _, _ in st.list_objects(pre)}
    except Exception as e:   # 鍵が無い・つながらない → HEADに切り替える
        print(f"  （R2の一覧が取れないので公開URLで確かめる: {type(e).__name__}）")
    if have is not None:
        missing = [k for k in keys if k not in have]
    else:
        # 全部（800個ほど）をHEADすると公開ドメインが詰まって40秒でタイムアウトした（2026-09-27）。
        # CSS / JSと各フォントの先頭断片（画面の字が入る側）だけ見る。つながらなければ止めずに知らせる
        import httpx
        keys = [k for k in keys if k.startswith("app/") or ".000." in k]
        base = (os.getenv("R2_PUBLIC_URL") or "https://img.trackmento.com").rstrip("/")
        try:
            with httpx.Client(timeout=10) as c, ThreadPoolExecutor(4) as ex:
                codes = list(ex.map(lambda k: c.head(f"{base}/{k}").status_code, keys))
        except httpx.HTTPError as e:
            notes.append(f"R2を確かめられなかった（{type(e).__name__}）。scripts/check.py --r2をあとで回す")
            return
        missing = [k for k, code in zip(keys, codes) if code != 200]
    if missing:
        which = [s for pre, s in (("app/", "upload_app_r2.py"), ("fonts/", "upload_fonts_r2.py"))
                 if any(k.startswith(pre) for k in missing)]
        ng.append(f"R2に無いものが{len(missing)}個（例: {missing[0]}）。本番で404になる。"
                  + " と ".join(f"scripts/{s}" for s in which) + " を回す")
    else:
        print(f"  OK  R2（{len(keys)}個すべてある）")


# 英字・数字（と差し込みの {}・${…}）と日本語のあいだの半角スペース。2026-10-01から詰める書き方（docs/ui.mdの「画面の言葉」）
_J = r"[぀-ヿ㐀-鿿＀-￯　-〿]"
SPACED = re.compile(rf"{_J} (?:[A-Za-z0-9]|\$\{{|\{{(?=[^{{}}\n]{{0,40}}\}}))|(?:[A-Za-z0-9]|\}}) {_J}")
SPACED_KEEP = ("scripts/check_trim.py", "scripts/compare_trim.py", "promo/", "trackmento-spec.md")   # 曲名のデータと昔の記録


def check_spacing(files: list[str]) -> None:
    """足した行に、英数字と日本語のあいだの半角スペースが残っていないか。止めずに知らせるだけ（曲名の中にはありうるため）"""
    targets = [f for f in files if not f.startswith(SPACED_KEEP)]
    if not targets:
        return
    hits = [ln[1:].strip() for ln in git("diff", "--cached", "-U0", "--", *targets).splitlines()
            if ln.startswith("+") and not ln.startswith("+++") and SPACED.search(ln)
            and not re.search(r"^\+\s*\[\s*[\"'].*https?://", ln)]
    if hits:
        notes.append(f"英数字と日本語のあいだに半角スペースが{len(hits)}行（例: {hits[0][:60]}）。"
                     "詰める書き方にそろえる（曲名などのデータならそのままでよい）")


def changed_files() -> list[str]:
    return [f for f in git("diff", "--cached", "--name-only").splitlines() if f]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="手元で回せるものを全部回す")
    ap.add_argument("--r2", action="store_true", help="配る物がR2にあるかを見る（push前）")
    a = ap.parse_args()

    if a.r2:
        print("R2の点検")
        check_r2()
    else:
        files = None if a.all else changed_files()
        touched = (lambda *pats: True) if files is None else \
            (lambda *pats: any(f == p or f.startswith(p.rstrip("*")) for f in files for p in pats))
        diff = git("diff", "--cached", "-U0", "--", INDEX) if files is not None and INDEX in files else ""
        print("点検（" + ("全部" if files is None else f"変えたファイル{len(files)}個") + "）")

        if touched(INDEX, "frontend/dist/", "scripts/build_app.py"):
            check_shell()
        if touched(INDEX, "fonts/", "scripts/build_fonts.py"):
            check_fonts()
        if touched(INDEX):
            run("check_i18n.py", "英語の対訳表")
        if touched("backend/names.py", "scripts/check_trim.py") or TRIM_NAMES.search(diff):
            run("check_trim.py", "曲名の刈り込み")
            if files is not None:
                notes.append("刈り込みを変えたので、サーバーを立ててscripts/compare_trim.pyも回す")
        if files is not None and (touched("backend/render.py") or RENDER_NAMES.search(diff)):
            notes.append("描画を変えたのでscripts/compare_render.pyで突き合わせる（手順はファイルの頭）")
        if files is None or files:
            run("check_consistency.py", "文書とコードの突き合わせ")
        if files:
            check_spacing(files)

    for n in notes:
        print(f"  --  {n}")
    if ng:
        print("\nNG:")
        for m in ng:
            print(f"  - {m}")
        print("\nわざと通すなら --no-verify（理由をコミットに書く）")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
