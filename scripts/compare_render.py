"""サーバー描画（backend/render.py）とブラウザ描画（frontend の renderShareCanvas）を突き合わせる。

レイアウト・色・文字の省略規則は 2 か所に同じものを書いてあり、**片方だけ直すとずれる**。
定数が揃っていても計算の途中で食い違うことがあるので、実際に同じ並びを両方で描いて比べる。

使い方（サーバーは公開モードで、共有の上限を外して立てる）:

    PUBLIC_MODE=1 SHARE_BUDGET_GB=0 SHARE_LIMIT_PER_DAY=0 SHARE_LIMIT_PER_IP_DAY=0 \
      PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

    # 1) 比べたい並びでサーバー描画の共有を作る
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py make 16 16 1:1
    #    曲名リストの流し込みを比べるときは fill を足して全マス埋める
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py make 16 16 16:9 fill
    # 2) 出た URL をブラウザで開き「トラックを共有」を押す（ブラウザ描画の共有ができる）
    # 3) 2 つの共有 ID を比べる
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py diff <サーバーのID> <ブラウザのID>
    # 4) 作ったテスト共有を R2 から消す（残すと本番の保存容量を食う）
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py clean <ID> <ID> ...

見方: 差は**輪郭だけ**なら正常（文字のラスタライズと JPEG の違い）。マスや文字の位置がずれていれば
面として差が出るので、ぼかしたあとにも差が残る。実測（2026-09-14、4x4 / 12x20 / 16x16）では
ぼかし後の「差 > 32」が 0.00〜0.10% だった。ここが数 % に跳ねたらレイアウトがずれている。
"""
from __future__ import annotations

import io
import json
import pathlib
import sys

import httpx
from PIL import Image, ImageChops, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8000"
NO_COVER_CELL = {"source": "manual", "title": "ジャケット無しの曲", "artist": "テスト", "album": None,
                 "image": "/no-cover.png", "thumb": "/no-cover.png", "external_url": None}


def make(cols: int, rows: int, ratio: str, fill: bool = False) -> None:
    """grids/default.json の曲を使って比較用の並びを作り、サーバー描画の共有を 1 件作る。

    fill=True なら曲を繰り返して全部のマスを埋める。曲名リストの流し込み（曲が多いときだけ
    切り替わる）を比べるには、マスが埋まっていないと再現しない。
    """
    src = json.loads((ROOT / "grids" / "default.json").read_text(encoding="utf-8"))
    tracks = [c for c in src["cells"] if c] + [NO_COVER_CELL]   # うちのアイコンの経路も通す
    cells: list[dict | None] = [None] * (cols * rows)
    if fill:
        for i in range(cols * rows):
            cells[i] = tracks[i % len(tracks)]
    else:
        for i, t in enumerate(tracks[: cols * rows]):
            cells[i] = t
    name = f"u-rendercmp{cols}x{rows}{'full' if fill else ''}"
    doc = {"app": "trackmento", "version": 1, "name": name, "cols": cols, "rows": rows,
           "cells": cells, "stash": [], "title": "描画くらべ",
           "options": {"ratio": ratio, "showTitle": True, "sidebar": True, "numbers": True,
                       "bg": "mustard", "bgCustom": None, "margin": 16, "gap": 16}}
    with httpx.Client(timeout=300) as c:
        c.put(f"{BASE}/grids/{name}", json=doc).raise_for_status()
        d = c.post(f"{BASE}/share", json={"grid": name}).json()
    print(f"サーバー描画: {d['id']}  {d.get('width')}x{d.get('height')}")
    print(f"次: ブラウザで {BASE}/?share={d['id']} を開き「トラックを共有」を押す")


def _load(sid: str) -> Image.Image:
    r = httpx.get(f"{BASE}/shares/{sid}.jpg", timeout=300, follow_redirects=True)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def diff(srv: str, web: str) -> int:
    a, b = _load(srv), _load(web)
    print(f"サーバー描画 {a.size} / ブラウザ描画 {b.size}")
    if a.size != b.size:
        print("  大きさが違う（端末ごとの上限の差）。合わせてから比べる")
        b = b.resize(a.size, Image.LANCZOS)
    n = a.size[0] * a.size[1]
    raw = ImageChops.difference(a, b).convert("L")
    soft = ImageChops.difference(a.filter(ImageFilter.GaussianBlur(3)), b.filter(ImageFilter.GaussianBlur(3))).convert("L")
    rh, sh = raw.histogram(), soft.histogram()
    over = lambda h, t: sum(h[t + 1 :]) / n * 100   # noqa: E731
    print(f"そのまま: 差>8 {over(rh, 8):.2f}%  差>32 {over(rh, 32):.2f}%  差>128 {over(rh, 128):.2f}%")
    print(f"ぼかし後: 差>32 {over(sh, 32):.2f}%  ← ここが 1% を超えるならレイアウトがずれている")
    out = ROOT / "outputs" / f"compare-{srv}-{web}.jpg"
    out.parent.mkdir(exist_ok=True)
    w, h = a.size
    sz = (900, max(1, round(h * 900 / w)))
    canvas = Image.new("RGB", (sz[0], sz[1] * 3 + 20), (255, 255, 255))
    canvas.paste(a.resize(sz, Image.LANCZOS), (0, 0))
    canvas.paste(b.resize(sz, Image.LANCZOS), (0, sz[1] + 10))
    canvas.paste(raw.point(lambda v: min(255, v * 6)).convert("RGB").resize(sz, Image.LANCZOS), (0, sz[1] * 2 + 20))
    canvas.save(out, "JPEG", quality=88)
    print(f"比較画像: {out}（上=サーバー 中=ブラウザ 下=差分を 6 倍に強調）")
    return 0 if over(sh, 32) < 1.0 else 1


def clean(ids: list[str]) -> None:
    """作ったテスト共有を R2 から消す。ID を明示するので一括削除にはならない。"""
    import os
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    sys.path.insert(0, str(ROOT))
    from backend import storage
    st = storage.get_storage()
    for sid in ids:
        for key in (f"{sid}.jpg", f"{sid}-og.jpg", f"{sid}.json", f"{sid}.png"):
            if st.exists(key):
                st.delete(key)
                print("  削除:", key)
    for p in (ROOT / "grids").glob("u-rendercmp*.json"):
        p.unlink()
        print("  テストグリッド削除:", p.name)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "make":
        args = [a for a in sys.argv[2:] if a != "fill"]
        make(int(args[0]), int(args[1]), args[2] if len(args) > 2 else "16:9", "fill" in sys.argv[2:])
        return 0
    if cmd == "diff":
        return diff(sys.argv[2], sys.argv[3])
    if cmd == "clean":
        clean(sys.argv[2:])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
