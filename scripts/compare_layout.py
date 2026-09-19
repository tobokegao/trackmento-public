"""サーバー描画（backend/render.py）とブラウザ描画（frontend の layout）の**割り付けの値**を、
並び × 比率でまとめて突き合わせる。

`scripts/compare_render.py` は絵を見比べるので確かだが 1 件ずつしか回せない。こちらは
割り付けの数値（枠・縮尺・文字の大きさ・行数・塊の位置）を数百件まとめて比べる。

    # サーバーを公開モードで立てたうえで
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_layout.py 260

**曲の中身をそろえること**が肝心（曲名の長さで折り返しの行数が変わり、そこから文字の大きさが決まる）。
ここでは `grids/default.json` の曲を両方に渡す。
"""
from __future__ import annotations

import json
import pathlib
import random
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import render as R  # noqa: E402
from backend.grids import GridDoc  # noqa: E402

FIELDS = ["W", "H", "scale", "font", "line_h", "ox", "oy", "title_size", "title_h",
          "wrap", "wrap_pad", "wrap_top", "segs", "cols", "side", "flow", "inline"]
SIDES = (1, 2, 3, 5, 8, 12, 16, 20, 26, 31, 32)
RATIOS = ("1:1", "4:5", "9:16", "16:9", "free")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 200
    # `--tracks <json>` で曲を差し替えられる（長い題で 3 行に折れる並びなど、default.json に無い中身を試すとき）
    tracks_path = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--tracks=")), None)
    random.seed(7)
    combos = [[c, r, q] for q in RATIOS for c in SIDES for r in SIDES if c * r <= 256]
    random.shuffle(combos)
    combos = combos[:n]
    if "--small" in sys.argv:
        # 1〜6 マス四方 × 比率 5 種（180 通り）。1 行型（曲名とアーティスト名を 1 行に並べる）は
        # 曲が少ない並びでしか出ないので、ランダムの 200 通りにはほとんど入らない
        combos = [[c, r, q] for q in RATIOS for c in range(1, 7) for r in range(1, 7)]

    src = json.loads((ROOT / "grids" / "default.json").read_text(encoding="utf-8"))
    tracks = [c for c in src["cells"] if c]
    if tracks_path:
        tracks = json.loads(pathlib.Path(tracks_path).read_text(encoding="utf-8"))
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "combos.json").write_text(json.dumps(combos), encoding="utf-8")
    (tmp / "tracks.json").write_text(json.dumps(tracks, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "promo" / "dump_layouts.mjs"), str(tmp / "js.json"),
                        str(tmp / "combos.json"), str(tmp / "tracks.json")],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        return 1
    js = {(c, rr, q): row for c, rr, q, *row in json.loads((tmp / "js.json").read_text(encoding="utf-8"))}

    bad = 0
    for c, rr, q in combos:
        cells = [tracks[i % len(tracks)] for i in range(c * rr)]
        doc = GridDoc(**{**src, "name": "t", "cols": c, "rows": rr, "cells": cells, "stash": [],
                         "title": "私を構成する9選",
                         "options": {**src.get("options", {}), "ratio": q, "showTitle": True,
                                     "sidebar": True, "numbers": False, "margin": 16, "gap": 16,
                                     "bg": "mustard", "bgCustom": None}})
        L = R.layout(doc)
        py = [L.W, L.H, round(L.scale * 1e9), L.font_s, L.line_h, L.ox, L.oy, L.title_size, L.title_h,
              1 if L.wrap else 0, L.wrap_pad, L.wrap_top, len(L.wrap_segs), L.sb_cols,
              L.side, 1 if L.sb_flow else 0, 1 if L.sb_inline else 0]
        got = js.get((c, rr, q))
        if got != py:
            bad += 1
            if bad <= 12:
                print(f"{c}x{rr} {q}: " + ", ".join(
                    f"{FIELDS[i]} サーバー={py[i]} ブラウザ={got[i]}" for i in range(len(py)) if py[i] != got[i]))
    print(f"食い違い {bad} / {len(combos)}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
