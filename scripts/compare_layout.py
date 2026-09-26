"""サーバー描画（backend/render.py）とブラウザ描画（frontend の layout）の**割り付けの値**を、
並び × 比率でまとめて突き合わせる。

`scripts/compare_render.py` は絵を見比べるので確かだが 1 件ずつしか回せない。こちらは
割り付けの数値（枠・縮尺・文字の大きさ・行数・塊の位置）を数百件まとめて比べる。

    # サーバーを公開モードで立てたうえで
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_layout.py 260
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_layout.py 260 --holes   # 末尾の空き段・途中の空きマスがある並び（2026-09-26）

**曲の中身をそろえること**が肝心（曲名の長さで折り返しの行数が変わり、そこから文字の大きさが決まる）。
ここでは `grids/default.json` の曲を両方に渡す。

**出力の大きさもそろえること**（`MAX_SIDE`）。組み方は「出力での文字の大きさ」で決まるので、
片方が 2400px・片方が 8000px だと**別の組み方になって当然**で、突き合わせの意味が無くなる
（`.env` に `PUBLIC_MODE` が無いと `max_side()` が 8000 を返し、ブラウザ側の 2400 と食い違って
191/200 が「ずれ」と出ていた。2026-09-21）。ここで両方に同じ値を渡して揃える。
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

# 突き合わせに使う出力の最大辺。**`backend` を読み込む前に立てること**（`max_side()` が起動時に見る）。
# 同じ値を `promo/dump_layouts.mjs` にも渡すので、ここを変えれば両方が変わる
MAX_SIDE = int(os.getenv("COMPARE_MAX_SIDE", "2400"))
os.environ["MAX_SIDE"] = str(MAX_SIDE)
# 余白の段（normal / wide / xwide）。両方に同じ段を渡す（2026-09-24 にスライダーから 3 段に替えた）
PAD = os.getenv("COMPARE_PAD", "normal")

from backend import render as R  # noqa: E402
from backend.grids import GridDoc  # noqa: E402

FIELDS = ["W", "H", "scale", "font", "line_h", "ox", "oy", "title_size", "title_h",
          "wrap", "wrap_pad", "wrap_top", "segs", "cols", "side", "flow", "inline", "title_x", "row_inline", "sb_top"]


def holed(c: int, r: int, i: int) -> bool:
    """`--holes` のときに曲を入れるマスか（promo/dump_layouts.mjs の holed と同じ）。
    右と下の端を空け（末尾の空き段を落とす `_cropped` を通す）、途中にも空きを混ぜる。2026-09-26"""
    row, col = divmod(i, c)
    return row < max(1, -(-r * 6 // 10)) and col < max(1, -(-c * 7 // 10)) and (i % 3 != 1 or i == 0)
SIDES = (1, 2, 3, 5, 8, 12, 16, 20, 26, 31, 32)
RATIOS = ("1:1", "4:5", "9:16", "16:9", "free")
CELL_RATIOS = ("1:1", "16:9")     # マスの形


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 200
    # `--tracks <json>` で曲を差し替えられる（長い題で 3 行に折れる並びなど、default.json に無い中身を試すとき）
    tracks_path = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--tracks=")), None)
    random.seed(7)
    # **マスの形も回す**（16:9 は塊の高さが変わるので割り付けが別物になる）
    combos = [[c, r, q, cq] for cq in CELL_RATIOS for q in RATIOS for c in SIDES for r in SIDES if c * r <= 256]
    random.shuffle(combos)
    combos = combos[:n]
    if "--small" in sys.argv:
        # 1〜6 マス四方 × 比率 5 種（180 通り）。1 行型（曲名とアーティスト名を 1 行に並べる）は
        # 曲が少ない並びでしか出ないので、ランダムの 200 通りにはほとんど入らない
        combos = [[c, r, q, cq] for cq in CELL_RATIOS for q in RATIOS for c in range(1, 7) for r in range(1, 7)]

    src = json.loads((ROOT / "grids" / "default.json").read_text(encoding="utf-8"))
    tracks = [c for c in src["cells"] if c]
    if tracks_path:
        tracks = json.loads(pathlib.Path(tracks_path).read_text(encoding="utf-8"))
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "combos.json").write_text(json.dumps(combos), encoding="utf-8")
    (tmp / "tracks.json").write_text(json.dumps(tracks, ensure_ascii=False), encoding="utf-8")
    holes = "--holes" in sys.argv
    r = subprocess.run(["node", str(ROOT / "promo" / "dump_layouts.mjs"), str(tmp / "js.json"),
                        str(tmp / "combos.json"), str(tmp / "tracks.json"), str(MAX_SIDE), PAD, "holes" if holes else ""],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        return 1
    js = {(c, rr, q, cq): row for c, rr, q, cq, *row in json.loads((tmp / "js.json").read_text(encoding="utf-8"))}

    bad = 0
    for c, rr, q, cq in combos:
        cells = [tracks[i % len(tracks)] for i in range(c * rr)]
        if holes:   # 末尾の空き段と途中の空きマスを混ぜる（`holed`）。曲は入れるマスの順に配る
            k, cells = 0, []
            for i in range(c * rr):
                cells.append(tracks[k % len(tracks)] if holed(c, rr, i) else None)
                k += 1 if cells[-1] else 0
        doc = GridDoc(**{**src, "name": "t", "cols": c, "rows": rr, "cells": cells, "stash": [],
                         "title": "私を構成する9選",
                         "options": {**src.get("options", {}), "ratio": q, "showTitle": True,
                                     "sidebar": True, "numbers": False, "margin": 16, "pad": PAD, "gap": 16,
                                     "bg": "mustard", "bgCustom": None, "cellRatio": cq}})
        L = R.layout(doc)
        py = [L.W, L.H, round(L.scale * 1e9), L.font_s, L.line_h, L.ox, L.oy, L.title_size, L.title_h,
              1 if L.wrap else 0, L.wrap_pad, L.wrap_top, len(L.wrap_segs), L.sb_cols,
              L.side, 1 if L.sb_flow else 0, 1 if L.sb_inline else 0, L.wrap_tx, 1 if L.wrap_inline else 0, L.sb_top]
        got = js.get((c, rr, q, cq))
        if got != py:
            bad += 1
            if bad <= 12:
                print(f"{c}x{rr} {q} マス{cq}: " + ", ".join(
                    f"{FIELDS[i]} サーバー={py[i]} ブラウザ={got[i]}" for i in range(len(py)) if py[i] != got[i]))
    print(f"食い違い {bad} / {len(combos)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
