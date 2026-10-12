"""サーバー描画（backend/render.py）とブラウザ描画（frontendのrenderShareCanvas）を突き合わせる。

レイアウト・色・文字の省略規則は2か所に同じものを書いてあり、**片方だけ直すとずれる**。
定数が揃っていても計算の途中で食い違うことがあるので、実際に同じ並びを両方で描いて比べる。

**ふだんはautoを使う**（2026-10-12）。共有を作らない（R2に書かない）・手で押さない・後片付けが要らない。
サーバーは公開モードで立てておく（ブラウザ側の絵はPlaywrightで開いた画面のCanvasから取る）:

    APP_FROM_R2=0 PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py auto            # 決まった数通りを描き比べる
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py auto 5x4:16:9:labels 3x3:1:1:blur   # 選んで回す
    #    --keep を足すと、両方の絵を実寸のPNGでもoutputs/に残す（細部を切り抜いて確かめるとき）
    #    --tracks=<json> で曲を差し替える（既定はgrids/default.jsonの曲。長い題や長いアーティスト名を試すとき）
    #    書き方は「横x縦:比率:付け足し…」。付け足しは fill / blur / wide / labels / covers（本物のジャケットを使う）

両方とも同じ出力の最大辺（COMPARE_MAX_SIDE、既定2400）で描く。ジャケットは既定でうちの同梱画像に差し替える
（外へ取りに行かないので速く、R2の画像キャッシュにも書かない。割り付けと文字を見るにはこれで足りる）。
**本物の共有画像どうしを比べたいときだけ**、下のmake / diff / cleanを使う（本番のR2に共有ができる）。

使い方（make / diff / clean。サーバーは公開モードで、共有の上限を外して立てる）:

    PUBLIC_MODE=1 SHARE_BUDGET_GB=0 SHARE_LIMIT_PER_DAY=0 SHARE_LIMIT_PER_IP_DAY=0 \
      PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

    # 1) 比べたい並びでサーバー描画の共有を作る
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py make 16 16 1:1
    #    曲名リストの流し込みを比べるときはfillを足して全マス埋める
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py make 16 16 16:9 fill
    #    「ぼかして埋める」を比べるときはblur（マスは正方形のまま）、横長のマスならwideも足す
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py make 3 3 1:1 blur
    #    行の見出しを比べるときはlabels
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py make 5 4 16:9 labels
    # 2) 出たURLをブラウザで開き「トラックを共有」を押す（ブラウザ描画の共有ができる）
    # 3) 2つの共有IDを比べる
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py diff <サーバーのID> <ブラウザのID>
    # 4) 作ったテスト共有をR2から消す（残すと本番の保存容量を食う）
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py clean <ID> <ID> ...

見方: 差は**輪郭だけ**なら正常（文字のラスタライズとJPEGの違い）。マスや文字の位置がずれていれば
面として差が出るので、ぼかしたあとにも差が残る。**3pxのぼかしで1% 未満、または6pxで0.3% 未満**なら正常。
マスが少ないと文字が大きくなり、3pxでは輪郭が消えきらない（2026-09-14の実測で4x4が1.65%。
6pxまで掛けると0.07% になり、行の位置は完全に一致していた）。
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


# 同梱の画像（外へ取りに行かない）。**/no-cover.pngだけ**: /bg-mark.pngは並びの検証（grids.py）で画像として
# 通らずマスが空になり、端の空き段が落ちて枠の大きさから違ってしまう
LOCAL_COVER = "/no-cover.png"
TRACKS_FILE: str | None = None   # autoの --tracks=<json>。曲の中身を差し替える（長いアーティスト名などを試すとき）


def _doc(cols: int, rows: int, ratio: str, fill: bool = False, blur: bool = False, wide: bool = False,
         labels: bool = False, covers: bool = True) -> dict:
    """grids/default.jsonの曲を使って比較用の並びを作る。

    fill=Trueなら曲を繰り返して全部のマスを埋める。曲名リストの流し込み（曲が多いときだけ
    切り替わる）を比べるには、マスが埋まっていないと再現しない。
    labels=Trueなら行の見出し（各行の左端の札。2026-10-11）を付ける。長くて「…」になる行も混ぜる。
    covers=Falseならジャケットを同梱の画像に差し替える（曲名とアーティスト名はそのまま）
    """
    if TRACKS_FILE:
        tracks = json.loads(pathlib.Path(TRACKS_FILE).read_text(encoding="utf-8"))
    else:
        src = json.loads((ROOT / "grids" / "default.json").read_text(encoding="utf-8"))
        tracks = [c for c in src["cells"] if c] + [NO_COVER_CELL]   # うちのアイコンの経路も通す
    if not covers:
        tracks = [{**t, "image": LOCAL_COVER, "thumb": LOCAL_COVER} for t in tracks]
    cells: list[dict | None] = [None] * (cols * rows)
    if fill:
        for i in range(cols * rows):
            cells[i] = tracks[i % len(tracks)]
    else:
        for i, t in enumerate(tracks[: cols * rows]):
            cells[i] = t
    name = f"u-rendercmp{cols}x{rows}{'full' if fill else ''}{'blur' if blur else ''}{'wide' if wide else ''}{'lab' if labels else ''}"
    doc = {"app": "trackmento", "version": 1, "name": name, "cols": cols, "rows": rows,
           "cells": cells, "stash": [], "title": "描画くらべ",
           "rowLabels": (["中学", "高校", "大人", "今", "とても長い見出しの行です"] * 7)[:rows] if labels else [],
           "options": {"ratio": ratio, "showTitle": True, "sidebar": True, "numbers": True,
                       "bg": "mustard", "bgCustom": None, "margin": 16, "gap": 16,
                       "cellRatio": "16:9" if wide else "1:1", "cellFit": "blur" if blur else "crop"}}
    return doc


def make(cols: int, rows: int, ratio: str, fill: bool = False, blur: bool = False, wide: bool = False,
         labels: bool = False) -> None:
    """比較用の並びでサーバー描画の共有を1件作る（本番のR2に書く。ふだんはautoを使う）。"""
    doc = _doc(cols, rows, ratio, fill, blur, wide, labels)
    name = doc["name"]
    with httpx.Client(timeout=300) as c:
        c.put(f"{BASE}/grids/{name}", json=doc).raise_for_status()
        d = c.post(f"{BASE}/share", json={"grid": name}).json()
    print(f"サーバー描画: {d['id']}  {d.get('width')}x{d.get('height')}")
    print(f"次: ブラウザで{BASE}/?share={d['id']}を開き「トラックを共有」を押す")


def _load(sid: str) -> Image.Image:
    r = httpx.get(f"{BASE}/shares/{sid}.jpg", timeout=300, follow_redirects=True)
    r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGB")


def diff(srv: str, web: str) -> int:
    ok = _score(_load(srv), _load(web), ROOT / "outputs" / f"compare-{srv}-{web}.jpg")
    return 0 if ok else 1


def _score(a: Image.Image, b: Image.Image, out: pathlib.Path) -> bool:
    """2枚の差を数えて出し、並べた比較画像をoutに書く。正常の範囲ならTrue。"""
    print(f"サーバー描画{a.size} / ブラウザ描画{b.size}")
    if a.size != b.size:
        print("  大きさが違う（端末ごとの上限の差）。合わせてから比べる")
        b = b.resize(a.size, Image.LANCZOS)
    n = a.size[0] * a.size[1]
    raw = ImageChops.difference(a, b).convert("L")
    soft = ImageChops.difference(a.filter(ImageFilter.GaussianBlur(3)), b.filter(ImageFilter.GaussianBlur(3))).convert("L")
    # マスが少ないと文字が大きくなり、3pxのぼかしでは輪郭の差が消えきらない（4x4で1.3% 出る）。
    # 6pxまで掛けても残るならレイアウトのずれ
    soft6 = ImageChops.difference(a.filter(ImageFilter.GaussianBlur(6)), b.filter(ImageFilter.GaussianBlur(6))).convert("L")
    rh, sh, sh6 = raw.histogram(), soft.histogram(), soft6.histogram()
    over = lambda h, t: sum(h[t + 1 :]) / n * 100   # noqa: E731
    print(f"そのまま: 差>8 {over(rh, 8):.2f}%  差>32 {over(rh, 32):.2f}%  差>128 {over(rh, 128):.2f}%")
    print(f"ぼかし後: 差>32 {over(sh, 32):.2f}%（3px） / {over(sh6, 32):.2f}%（6px）")
    print("  ← 3pxが1% 未満、または6pxが0.3% 未満なら正常（文字が大きいと3pxでは輪郭が残る）")
    # **グリッド側と曲名リスト側を分けて出す**。マスが少ないとジャケットの縮小の仕方（PILとCanvas）の
    # 違いが大きく出て、レイアウトのずれと見分けがつかないため。見たいのはリスト側
    cut = int(a.size[0] * 0.52)
    for label, box in (("  グリッド側", (0, 0, cut, a.size[1])), ("  曲名リスト側", (cut, 0, a.size[0], a.size[1]))):
        ca, cb = a.crop(box), b.crop(box)
        cn = max(1, ca.size[0] * ca.size[1])
        d3 = ImageChops.difference(ca.filter(ImageFilter.GaussianBlur(3)), cb.filter(ImageFilter.GaussianBlur(3))).convert("L").histogram()
        d6 = ImageChops.difference(ca.filter(ImageFilter.GaussianBlur(6)), cb.filter(ImageFilter.GaussianBlur(6))).convert("L").histogram()
        print(f"{label}: 差>32 {sum(d3[33:]) / cn * 100:.2f}%（3px） / {sum(d6[33:]) / cn * 100:.2f}%（6px）")
    out.parent.mkdir(exist_ok=True)
    w, h = a.size
    sz = (900, max(1, round(h * 900 / w)))
    canvas = Image.new("RGB", (sz[0], sz[1] * 3 + 20), (255, 255, 255))
    canvas.paste(a.resize(sz, Image.LANCZOS), (0, 0))
    canvas.paste(b.resize(sz, Image.LANCZOS), (0, sz[1] + 10))
    canvas.paste(raw.point(lambda v: min(255, v * 6)).convert("RGB").resize(sz, Image.LANCZOS), (0, sz[1] * 2 + 20))
    canvas.save(out, "JPEG", quality=88)
    print(f"比較画像: {out}（上=サーバー 中=ブラウザ 下=差分を6倍に強調）")
    return over(sh, 32) < 1.0 or over(sh6, 32) < 0.3


# autoで回す並び（横, 縦, 比率, 付け足し）。曲名リストの組み方が一通り出るように選んだ
AUTO_CASES = ("3x3:1:1", "4x4:16:9:fill", "16x16:16:9:fill", "6x6:9:16:fill", "2x5:4:5",
              "3x3:1:1:blur", "3x3:16:9:wide:blur", "5x4:16:9:labels", "4x6:1:1:labels:fill")


def auto(specs: list[str]) -> int:
    """サーバー描画とブラウザ描画を手元で描いて比べる（共有を作らない）。"""
    import os
    import subprocess
    import tempfile
    max_side = os.getenv("COMPARE_MAX_SIDE", "2400")
    os.environ["MAX_SIDE"] = max_side   # **backendを読む前に**立てる（max_side() が見る。compare_layout.pyと同じ）
    sys.path.insert(0, str(ROOT))
    from backend import render as R
    from backend.grids import GridDoc
    try:
        httpx.get(f"{BASE}/robots.txt", timeout=5).raise_for_status()
    except httpx.HTTPError:
        print(f"{BASE} にサーバーがありません（公開モードで立ててから。使い方はファイルの頭）")
        return 2
    keep = "--keep" in specs   # 両方の絵を実寸のPNGでも残す（細部を切り抜いて見るとき）
    global TRACKS_FILE
    TRACKS_FILE = next((v.split("=", 1)[1] for v in specs if v.startswith("--tracks=")), None)
    specs = [v for v in specs if not v.startswith("--")]
    flags = {"fill", "blur", "wide", "labels", "covers"}
    cases = []
    for spec in specs or AUTO_CASES:
        size, *rest = spec.split(":")
        cols, rows = (int(v) for v in size.lower().split("x"))
        ratio = ":".join(v for v in rest if v not in flags)[:5] or "16:9"
        on = {v for v in rest if v in flags}
        doc = _doc(cols, rows, ratio, "fill" in on, "blur" in on, "wide" in on, "labels" in on, "covers" in on)
        key = spec.replace(":", "_")
        cases.append({"key": key, "cols": cols, "rows": rows, "title": doc["title"], "rowLabels": doc["rowLabels"],
                      "options": doc["options"], "cells": doc["cells"], "doc": doc})
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "cases.json").write_text(json.dumps([{k: v for k, v in c.items() if k != "doc"} for c in cases],
                                               ensure_ascii=False), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "promo" / "dump_render.mjs"), str(tmp / "web"), str(tmp / "cases.json"), max_side],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        print(r.stdout, r.stderr)
        return 1
    bad = []
    for c in cases:
        print(f"== {c['key']}")
        a = R.render(GridDoc(**c["doc"])).convert("RGB")
        b = Image.open(tmp / "web" / f"{c['key']}.png").convert("RGB")
        if keep:
            (ROOT / "outputs").mkdir(exist_ok=True)
            a.save(ROOT / "outputs" / f"compare-auto-{c['key']}-server.png")
            b.save(ROOT / "outputs" / f"compare-auto-{c['key']}-browser.png")
        if not _score(a, b, ROOT / "outputs" / f"compare-auto-{c['key']}.jpg"):
            bad.append(c["key"])
    print(f"\nずれ {len(bad)} / {len(cases)}" + (f"（{', '.join(bad)}）" if bad else ""))
    return 1 if bad else 0


def clean(ids: list[str]) -> None:
    """作ったテスト共有をR2から消す。IDを明示するので一括削除にはならない。"""
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
    if cmd == "auto":
        return auto(sys.argv[2:])
    if cmd == "make":
        flags = {"fill", "blur", "wide", "labels"}
        args = [a for a in sys.argv[2:] if a not in flags]
        make(int(args[0]), int(args[1]), args[2] if len(args) > 2 else "16:9", "fill" in sys.argv[2:],
             blur="blur" in sys.argv[2:], wide="wide" in sys.argv[2:], labels="labels" in sys.argv[2:])
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
