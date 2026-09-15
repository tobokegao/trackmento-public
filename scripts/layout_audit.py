"""並び（横×縦）と比率のすべての組み合わせで、書き出し画像の割り付けがどうなるかを調べる。

    PYTHONUTF8=1 PUBLIC_MODE=1 .venv/Scripts/python scripts/layout_audit.py          # 数値だけ（速い）
    PYTHONUTF8=1 PUBLIC_MODE=1 .venv/Scripts/python scripts/layout_audit.py --render  # 気になるものを画像にする
    PYTHONUTF8=1 PUBLIC_MODE=1 .venv/Scripts/python scripts/layout_audit.py --render --all   # 全部画像にする（重い）

結果は `outputs/layout-audit/` に置く（`index.html` を開いて見る）。

**画像は 2400px で組んでから縮める**。割り付けの判断は「出力で何 px になるか」で行うので、
小さく組むと別の結果になる。ジャケットは本物を数枚だけ読み込んで使い回す（取得を待たない）。
"""
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from PIL import Image  # noqa: E402

from backend import render as R  # noqa: E402
from backend.config import max_side  # noqa: E402
from backend.grids import GridDoc  # noqa: E402

OUT = ROOT / "outputs" / "layout-audit"
RATIOS = ("1:1", "4:5", "9:16", "16:9", "free")
MAX_CELLS = 256
MAX_SIDE_CELLS = 32
THUMB_W = 360        # 一覧に並べるサムネの幅

# 判定のしきい値。**ここに引っかかったものを「要確認」として一覧の上に出す**
MIN_FONT = 12        # 出力での曲名の大きさ（px）。これ未満は読めない
MIN_CELL = 40        # 出力でのマスの大きさ（px）。これ未満はジャケットが判別できない
MIN_FILL = 0.60      # 描いたものが枠を覆う割合。これ未満は使われない余白が目立つ
MIN_TITLE_RATIO = 1.2   # タイトル ÷ 曲名。これ未満はタイトルが目立たない


def load_tracks() -> list[dict]:
    src = json.loads((ROOT / "grids" / "default.json").read_text(encoding="utf-8"))
    return [c for c in src["cells"] if c]


def stub_covers(tracks: list[dict]) -> None:
    """ジャケットの取得を 1 回だけにして使い回す（2,950 回ぶん取りに行くと終わらない）。"""
    cache: dict[int, Image.Image] = {}
    real = R.load_cover
    first = [GridDoc(**{"app": "trackmento", "version": 1, "name": "t", "cols": 1, "rows": 1,
                        "cells": [t], "stash": []}).cells[0] for t in tracks[:6]]
    base = [im for im in (real(t, R.CELL_PX) for t in first) if im is not None]
    if not base:
        base = [Image.new("RGB", (R.CELL_PX, R.CELL_PX), (200, 200, 200))]

    def fake(t, size: int = R.CELL_PX):
        key = (abs(hash(t.title)) % len(base), size)
        if key not in cache:
            cache[key] = base[key[0]].resize((size, size), Image.LANCZOS)
        return cache[key]

    R.load_cover = fake


def make_doc(tracks: list[dict], cols: int, rows: int, ratio: str) -> GridDoc:
    src = json.loads((ROOT / "grids" / "default.json").read_text(encoding="utf-8"))
    cells = [tracks[i % len(tracks)] for i in range(cols * rows)]
    return GridDoc(**{**src, "name": "audit", "cols": cols, "rows": rows, "cells": cells, "stash": [],
                      "title": "私を構成する曲",
                      "options": {**src.get("options", {}), "ratio": ratio, "showTitle": True,
                                  "sidebar": True, "numbers": True}})


def measure(doc: GridDoc) -> dict:
    """1 つの組み合わせの割り付けを数値にする。"""
    L = R.layout(doc)
    S = L.scale
    out = {
        "cols": doc.cols, "rows": doc.rows, "ratio": doc.options.ratio,
        "n": sum(1 for c in doc.cells if c),
        "W": round(L.W * S), "H": round(L.H * S),
        "cell": round(R.CELL_PX * S),
        "font": round(L.font_s * S, 1),
        "title": round(L.title_size * S, 1),
        "mode": "回り込み" if L.wrap else ("流し込み" if L.sb_flow else "1 曲 1 行"),
        "side": L.side,
    }
    out["title_ratio"] = round(out["title"] / out["font"], 2) if out["font"] else 0
    if L.wrap:
        rows_used = R._flow_rows(doc, L.font_s, 0.0, [float(sg[2]) for sg in L.wrap_segs])
        # **埋まり＝描いたものが枠をどれだけ覆うか**（マスの塊 ＋ 実際に置いた文字の面積）。
        # 「行数 ÷ 段の数」では測れない（余った段は割り付けの時点で捨てているので必ず 1.0 になる）
        area = (L.W - L.wrap_pad * 2) * (L.H - L.wrap_top - L.wrap_pad)
        ink = L.gw * L.gh + sum(fr.width * L.line_h for fr in rows_used)
        out["fill"] = round(ink / area, 2) if area else 0
        widths = sorted({sg[2] for sg in L.wrap_segs})
        out["seg_min"] = round(widths[0] * S)
        out["seg_chars"] = round(widths[0] / L.font_s)
        full = round((L.W - L.wrap_pad * 2) * S)
        out["kotoji"] = abs(L.ox - L.wrap_pad) < 2 and any(round(sg[2] * S) < full - 2 for sg in L.wrap_segs)
    else:
        out["fill"] = None
        out["seg_min"] = None
        out["seg_chars"] = None
        out["kotoji"] = False
    # 判定
    bad = []
    if out["font"] < MIN_FONT:
        bad.append(f"文字が小さい（{out['font']}px）")
    if out["cell"] < MIN_CELL:
        bad.append(f"マスが小さい（{out['cell']}px）")
    if out["fill"] is not None and out["fill"] < MIN_FILL:
        bad.append(f"余白が目立つ（埋まり {int(out['fill'] * 100)}%）")
    if out["title_ratio"] < MIN_TITLE_RATIO:
        bad.append(f"タイトルが目立たない（本文の {out['title_ratio']} 倍）")
    if out["seg_chars"] is not None and out["seg_chars"] < 14:
        bad.append(f"段が狭い（{out['seg_chars']} 字）")
    out["bad"] = bad
    return out


def combos() -> list[tuple[int, int]]:
    return [(c, r) for c in range(1, MAX_SIDE_CELLS + 1) for r in range(1, MAX_SIDE_CELLS + 1)
            if c * r <= MAX_CELLS]


def thumb_name(m: dict) -> str:
    return f"{m['cols']}x{m['rows']}-{m['ratio'].replace(':', '-')}.jpg"


def render_one(doc: GridDoc, path: Path) -> None:
    im = R.render(doc)
    w = THUMB_W
    im.resize((w, max(1, round(w * im.size[1] / im.size[0]))), Image.LANCZOS).save(path, quality=82)


CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 16px; font: 14px/1.6 system-ui, sans-serif; background: #f6f5f3; color: #12171b; }
h1 { font-size: 1.2rem; margin: 0 0 4px; }
h2 { font-size: 1rem; margin: 24px 0 8px; }
p.lead { margin: 0 0 12px; color: #53595f; }
.bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 12px 0; }
.bar label { display: inline-flex; gap: 4px; align-items: center; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.card { background: #fff; border: 2px solid #12171b; box-shadow: 2px 2px 0 #12171b; padding: 8px; }
.card.ok { border-color: #9aa0a6; box-shadow: none; }
.card img { width: 100%; height: auto; display: block; border: 1px solid #d5d2cc; background: #eee; }
.card h3 { font-size: .95rem; margin: 6px 0 2px; }
.card dl { display: grid; grid-template-columns: auto 1fr; gap: 0 8px; margin: 4px 0 0; font-size: .82rem; }
.card dt { color: #53595f; }
.card dd { margin: 0; }
.tags { margin: 6px 0 0; display: flex; flex-wrap: wrap; gap: 4px; }
.tag { font-size: .75rem; padding: 1px 6px; border: 1px solid #c0392b; color: #c0392b; }
table { border-collapse: collapse; width: 100%; font-size: .82rem; background: #fff; }
th, td { border: 1px solid #d5d2cc; padding: 3px 6px; text-align: right; white-space: nowrap; }
th { background: #eceae6; position: sticky; top: 0; cursor: pointer; }
td:first-child, th:first-child, td.l { text-align: left; }
tr.bad td { background: #fdf0ee; }
.note { background: #fff; border: 2px solid #12171b; padding: 12px 16px; margin: 12px 0; }
"""

JS = """
const rows = [...document.querySelectorAll('#all tbody tr')];
document.querySelectorAll('#all th').forEach((th, i) => th.addEventListener('click', () => {
  const dir = th.dataset.dir === 'asc' ? -1 : 1;
  document.querySelectorAll('#all th').forEach(o => delete o.dataset.dir);
  th.dataset.dir = dir === 1 ? 'asc' : 'desc';
  const body = document.querySelector('#all tbody');
  rows.sort((a, b) => {
    const x = a.cells[i].dataset.v ?? a.cells[i].textContent, y = b.cells[i].dataset.v ?? b.cells[i].textContent;
    const nx = parseFloat(x), ny = parseFloat(y);
    return (isNaN(nx) || isNaN(ny) ? String(x).localeCompare(String(y)) : nx - ny) * dir;
  });
  rows.forEach(r => body.appendChild(r));
}));
document.querySelector('#onlybad').addEventListener('change', (e) => {
  rows.forEach(r => { r.hidden = e.target.checked && !r.classList.contains('bad'); });
});
"""


def write_html(ms: list[dict], rendered: set[str], args) -> None:
    bad = [m for m in ms if m["bad"]]
    by_reason: dict[str, int] = {}
    for m in bad:
        for b in m["bad"]:
            by_reason[b.split("（")[0]] = by_reason.get(b.split("（")[0], 0) + 1

    def card(m: dict) -> str:
        name = thumb_name(m)
        img = f'<img src="img/{html.escape(name)}" alt="" loading="lazy">' if name in rendered else '<div style="padding:24px;text-align:center;color:#888">画像なし</div>'
        tags = "".join(f'<span class="tag">{html.escape(b)}</span>' for b in m["bad"])
        return f"""<div class="card{'' if m['bad'] else ' ok'}">
{img}
<h3>{m['cols']}×{m['rows']}　{html.escape(m['ratio'])}</h3>
<dl><dt>組み方</dt><dd>{html.escape(m['mode'])}{'・コの字' if m['kotoji'] else ''}</dd>
<dt>出力</dt><dd>{m['W']}×{m['H']}</dd>
<dt>曲名</dt><dd>{m['font']}px</dd>
<dt>タイトル</dt><dd>{m['title']}px（本文の {m['title_ratio']} 倍）</dd>
<dt>マス</dt><dd>{m['cell']}px</dd>
<dt>埋まり</dt><dd>{'—' if m['fill'] is None else m['fill']}</dd>
<dt>最小の段</dt><dd>{'—' if m['seg_min'] is None else f"{m['seg_min']}px（{m['seg_chars']} 字）"}</dd></dl>
<div class="tags">{tags}</div></div>"""

    def row(m: dict) -> str:
        cls = ' class="bad"' if m["bad"] else ""
        return (f'<tr{cls}><td class="l" data-v="{m["cols"]*1000+m["rows"]}">{m["cols"]}×{m["rows"]}</td>'
                f'<td class="l">{html.escape(m["ratio"])}</td><td class="l">{html.escape(m["mode"])}</td>'
                f'<td>{m["n"]}</td><td>{m["font"]}</td><td>{m["title_ratio"]}</td><td>{m["cell"]}</td>'
                f'<td>{"" if m["fill"] is None else m["fill"]}</td>'
                f'<td>{"" if m["seg_chars"] is None else m["seg_chars"]}</td>'
                f'<td class="l">{html.escape("、".join(m["bad"]))}</td></tr>')

    reasons = "".join(f"<li>{html.escape(k)}: {v} 件</li>" for k, v in sorted(by_reason.items(), key=lambda kv: -kv[1]))

    # **理由ごとにまとめ、ひどい順に並べる**。1,000 件を一度に並べても読めない
    GROUPS = [
        ("タイトルが目立たない", "タイトルが曲名リストより小さい／近い",
         lambda m: m["title_ratio"],
         "曲名リストの大きさは入る量から決まるのに、タイトルは今までどおりマスの幅から決めている。"
         "曲が少ないと曲名が大きくなり、タイトルのほうが小さくなる。"),
        ("文字が小さい", "曲名リストが読めない大きさ",
         lambda m: m["font"],
         "比率なし（設定なし）で横に長い並びにすると、右の曲名リストに幅が残らず下限まで落ちる。"
         "回り込みは比率が決まっているときだけなので、ここには効かない。"),
        ("マスが小さい", "ジャケットが判別できない大きさ",
         lambda m: m["cell"],
         "曲が多いうえに比率と並びの形が食い違うもの。曲名を読める大きさにすると、"
         "そのぶんマスが小さくなる。**どうにもならない組み合わせはここに出る**。"),
        ("下が空く", "文字が下まで届かない", lambda m: m["fill"] or 0, ""),
        ("段が狭い", "回り込みの段が狭い", lambda m: m["seg_chars"] or 0, ""),
    ]
    LIMIT = 24
    groups_html = []
    for key, heading, order, why in GROUPS:
        g = sorted([m for m in bad if any(b.startswith(key) for b in m["bad"])], key=order)
        if not g:
            continue
        more = f"<p class=lead>ほか {len(g) - LIMIT} 件（下の表で「{html.escape(key)}」を探す）</p>" if len(g) > LIMIT else ""
        groups_html.append(f"<h2>{html.escape(heading)}（{len(g)} 件）</h2>"
                           + (f"<p class=lead>{why}</p>" if why else "")
                           + f'<div class="cards">{"".join(card(m) for m in g[:LIMIT])}</div>{more}')
    doc = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>割り付けの総点検 — TRACKMENTO</title>
<style>{CSS}</style></head><body>
<h1>割り付けの総点検</h1>
<p class="lead">並び（横×縦、総数 {MAX_CELLS} マスまで・1 辺 {MAX_SIDE_CELLS} まで）と比率のすべての組み合わせ
{len(ms)} 件。曲名リストあり・タイトルあり・番号ありで、出力の最大辺 {max_side()} px。</p>
<div class="note">
<b>要確認 {len(bad)} 件</b>（全体の {round(len(bad)/len(ms)*100)}%）。内訳:
<ul>{reasons}</ul>
判定のしきい値: 曲名 &lt; {MIN_FONT}px ／ マス &lt; {MIN_CELL}px ／ 埋まり &lt; {MIN_FILL} ／
タイトルが本文の {MIN_TITLE_RATIO} 倍未満 ／ 段が 14 字未満。
</div>

{"".join(groups_html)}

<h2>全組み合わせ</h2>
<div class="bar"><label><input type="checkbox" id="onlybad"> 要確認だけ表示</label>
<span>見出しを押すと並べ替え</span></div>
<table id="all"><thead><tr><th>並び</th><th>比率</th><th>組み方</th><th>曲数</th><th>曲名px</th>
<th>タイトル倍率</th><th>マスpx</th><th>埋まり</th><th>段の字数</th><th>気になる点</th></tr></thead>
<tbody>{"".join(row(m) for m in ms)}</tbody></table>
<script>{JS}</script></body></html>"""
    (OUT / "index.html").write_text(doc, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true", help="画像も書き出す（要確認のものだけ）")
    ap.add_argument("--all", action="store_true", help="--render と併せて、全部の画像を書き出す（重い）")
    ap.add_argument("--only", help="比率を絞る（例 1:1,9:16）")
    ap.add_argument("--from-json", action="store_true", help="前回の audit.json から HTML だけ作り直す")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if a.from_json:
        ms = json.loads((OUT / "audit.json").read_text(encoding="utf-8"))
        write_html(ms, {p.name for p in (OUT / "img").glob("*.jpg")}, a)
        print(f"{len(ms)} 件 → {OUT / 'index.html'}")
        return 0
    (OUT / "img").mkdir(exist_ok=True)
    tracks = load_tracks()
    if a.render:
        stub_covers(tracks)

    ratios = a.only.split(",") if a.only else RATIOS
    pairs = combos()
    total = len(pairs) * len(ratios)
    ms: list[dict] = []
    done = 0
    for cols, rows in pairs:
        for ratio in ratios:
            doc = make_doc(tracks, cols, rows, ratio)
            ms.append(measure(doc))
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{total} …", flush=True)
    (OUT / "audit.json").write_text(json.dumps(ms, ensure_ascii=False, indent=1), encoding="utf-8")

    rendered: set[str] = set()
    if a.render:
        want = ms if a.all else [m for m in ms if m["bad"]]
        print(f"画像を書き出す: {len(want)} 件")
        for i, m in enumerate(want, 1):
            doc = make_doc(tracks, m["cols"], m["rows"], m["ratio"])
            name = thumb_name(m)
            render_one(doc, OUT / "img" / name)
            rendered.add(name)
            if i % 20 == 0:
                print(f"  {i}/{len(want)} …", flush=True)
    else:
        rendered = {p.name for p in (OUT / "img").glob("*.jpg")}

    write_html(ms, rendered, a)
    bad = sum(1 for m in ms if m["bad"])
    print(f"{len(ms)} 件中 要確認 {bad} 件 → {OUT / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
