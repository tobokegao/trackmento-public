"""割り付けの総点検（layout_audit.py）の結果を、外から見られる 1 枚の HTML にまとめる。

    PYTHONUTF8=1 .venv/Scripts/python scripts/layout_audit_page.py <出力先ディレクトリ>

画像は全部で 1,100 枚あって公開には多すぎるので、**問題の種類ごとにひどい順 30 件**だけ選ぶ。
数値は全 2,950 件ぶんを表に入れる（ページ内で並べ替え・絞り込みできる）。
選んだ画像は出力先の `img/` に複製する（Artifact の supporting files として上げるため）。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "outputs" / "layout-audit"
PER_GROUP = 30

GROUPS = [
    ("title", "タイトルが曲名リストより小さい", "タイトルが目立たない",
     lambda m: m["title_ratio"],
     "曲名リストの大きさは「入る量」から決まるのに、タイトルは今までどおりマスの幅の 4.5%（上限 96）から"
     "決めている。曲が少ないと曲名が大きくなり、タイトルのほうが小さくなる。"
     "回り込みでは先に直したが、流し込みと 1 曲 1 行が残っている。"),
    ("font", "曲名リストが読めない大きさ", "文字が小さい",
     lambda m: m["font"],
     "すべて「比率なし」。横に長い並びだと右の曲名リストに幅が残らず、下限まで落ちる。"
     "回り込みは比率が決まっているときだけなので、ここには効かない。"),
    ("cell", "ジャケットが判別できない大きさ", "マスが小さい",
     lambda m: m["cell"],
     "曲が多いうえに、並びの形と枠の比率が食い違うもの。曲名を読める大きさにすると、そのぶんマスが潰れる。"
     "「選べないようにする」候補はここに出る。"),
    ("fill", "使われない余白が目立つ", "余白が目立つ", lambda m: m["fill"] or 0, ""),
    ("seg", "回り込みの段が狭い", "段が狭い", lambda m: m["seg_chars"] or 0, ""),
]


def thumb(m: dict) -> str:
    return f"{m['cols']}x{m['rows']}-{m['ratio'].replace(':', '-')}.jpg"


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else SRC / "page")
    out.mkdir(parents=True, exist_ok=True)
    (out / "img").mkdir(exist_ok=True)
    ms = json.loads((SRC / "audit.json").read_text(encoding="utf-8"))
    bad = [m for m in ms if m["bad"]]

    picked: dict[str, list[dict]] = {}
    names: set[str] = set()
    for key, _, tag, order, _why in GROUPS:
        g = sorted([m for m in bad if any(b.startswith(tag) for b in m["bad"])], key=order)[:PER_GROUP]
        picked[key] = g
        names |= {thumb(m) for m in g}
    # 比較用に、問題なしのものも少しだけ
    fine = [m for m in ms if not m["bad"] and m["n"] >= 60]
    fine = sorted(fine, key=lambda m: -m["cell"])[:4]
    picked["fine"] = fine
    names |= {thumb(m) for m in fine}

    copied = set()
    for n in sorted(names):
        s = SRC / "img" / n
        if s.exists():
            shutil.copy2(s, out / "img" / n)
            copied.add(n)
    # 問題なしのものは画像を作っていないので、無いものは落とす
    for k, g in picked.items():
        picked[k] = [m for m in g if thumb(m) in copied]

    slim = [[m["cols"], m["rows"], m["ratio"], m["n"], m["mode"], m["font"], m["title_ratio"],
             m["cell"], m["fill"], m["seg_chars"], "、".join(m["bad"])] for m in ms]
    data = {"rows": slim, "groups": {k: [thumb(m) for m in g] for k, g in picked.items()},
            "cards": {k: [{"t": thumb(m), "c": m["cols"], "r": m["rows"], "q": m["ratio"], "n": m["n"],
                           "mode": m["mode"], "font": m["font"], "tr": m["title_ratio"], "cell": m["cell"],
                           "fill": m["fill"], "seg": m["seg_chars"], "bad": m["bad"]} for m in g]
                      for k, g in picked.items()}}

    counts: dict[str, int] = {}
    for m in bad:
        for b in m["bad"]:
            counts[b.split("（")[0]] = counts.get(b.split("（")[0], 0) + 1

    html = PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    html = html.replace("__TOTAL__", str(len(ms))).replace("__BAD__", str(len(bad)))
    html = html.replace("__PCT__", str(round(len(bad) / len(ms) * 100)))
    html = html.replace("__COUNTS__", json.dumps(counts, ensure_ascii=False))
    html = html.replace("__SHOTS__", str(len(copied)))
    (out / "audit.html").write_text(html, encoding="utf-8")
    print(f"{out / 'audit.html'}  画像 {len(copied)} 枚")
    return 0


PAGE = r"""<title>割り付け総点検 2026-09-15</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+JP:wght@400;600;700&family=Silkscreen:wght@400;700&display=swap">
<style>
:root{
  --paper:#f6f5f3; --paper-2:#e8e8e5; --paper-3:#dcdbd7; --ink:#12171b; --ink-2:#25292f;
  --muted:#53595f; --rule:#acb2b9; --mustard:#e6b731; --vermilion:#e5462c; --leaf:#52a555;
  --bg:var(--paper); --fg:var(--ink); --panel:#fff; --panel-2:var(--paper-2); --line:var(--ink);
  --soft:var(--rule); --dim:var(--muted); --shadow:var(--ink);
  --step-0:.9375rem; --step-1:1.0625rem; --step-2:1.375rem; --step-3:1.875rem;
}
@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]){
  --bg:#0e1216; --fg:#eceae6; --panel:#171c21; --panel-2:#1f252b; --line:#3a424a;
  --soft:#3a424a; --dim:#98a1aa; --shadow:#000;
}}
:root[data-theme="dark"]{
  --bg:#0e1216; --fg:#eceae6; --panel:#171c21; --panel-2:#1f252b; --line:#3a424a;
  --soft:#3a424a; --dim:#98a1aa; --shadow:#000;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font-family:"IBM Plex Sans JP",system-ui,sans-serif;font-size:var(--step-0);line-height:1.7;
  -webkit-text-size-adjust:100%}
.wrap{max-width:1180px;margin:0 auto;padding-block:28px 64px;padding-left:20px;padding-right:20px}
.pix{font-family:"Silkscreen",ui-monospace,monospace;letter-spacing:.06em}
.eyebrow{font-family:"Silkscreen",ui-monospace,monospace;font-size:.7rem;letter-spacing:.14em;
  text-transform:uppercase;color:var(--dim)}
h1{font-size:var(--step-3);line-height:1.25;margin:.2em 0 .1em;text-wrap:balance;font-weight:700}
h2{font-size:var(--step-2);margin:0;font-weight:700;text-wrap:balance}
h3{font-size:var(--step-1);margin:0;font-weight:600}
p{margin:.5em 0;max-width:68ch}
a{color:inherit}
.sub{color:var(--dim);max-width:70ch}
.tally{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:22px 0 8px}
.tile{background:var(--panel);border:2px solid var(--line);box-shadow:3px 3px 0 var(--shadow);padding:10px 12px}
.tile b{display:block;font-family:"Silkscreen",monospace;font-size:1.65rem;line-height:1.2;
  font-variant-numeric:tabular-nums}
.tile span{color:var(--dim);font-size:.8rem}
.tile.warn b{color:var(--vermilion)}
section{margin-top:40px}
.bar{display:flex;align-items:center;gap:10px;background:var(--ink);color:var(--paper);
  border:2px solid var(--line);padding:6px 10px;box-shadow:3px 3px 0 var(--shadow)}
:root[data-theme="dark"] .bar,:root:not([data-theme="light"]) .bar{--x:0}
.bar .stripe{flex:1;height:10px;min-width:24px;
  background:repeating-linear-gradient(180deg,currentColor 0 1px,transparent 1px 3px);opacity:.55}
.bar .n{font-family:"Silkscreen",monospace;font-size:.85rem;font-variant-numeric:tabular-nums}
.why{margin:10px 0 16px}
.specimens{display:grid;grid-template-columns:repeat(auto-fill,minmax(228px,1fr));gap:14px}
.card{background:var(--panel);border:2px solid var(--line);box-shadow:3px 3px 0 var(--shadow);
  padding:8px;display:flex;flex-direction:column;gap:6px;min-width:0;
  border-left-width:6px;border-left-color:var(--vermilion)}
.card.ok{border-left-color:var(--leaf)}
.card figure{margin:0;background:var(--panel-2);border:1px solid var(--soft);
  display:flex;align-items:center;justify-content:center;height:132px;padding:6px;overflow:hidden}
.card img{max-width:100%;max-height:100%;width:auto;height:auto;display:block;object-fit:contain}
.card .name{font-family:"Silkscreen",monospace;font-size:.95rem;font-variant-numeric:tabular-nums}
.card .mode{color:var(--dim);font-size:.78rem}
.kv{display:grid;grid-template-columns:auto 1fr;gap:0 10px;font-size:.8rem;margin:0}
.kv dt{color:var(--dim)}
.kv dd{margin:0;font-variant-numeric:tabular-nums;text-align:right}
.flags{display:flex;flex-wrap:wrap;gap:4px;min-width:0}
.flag{font-size:.7rem;line-height:1.5;padding:1px 6px;border:1px solid var(--vermilion);
  color:var(--vermilion);overflow-wrap:anywhere;max-width:100%}
.tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:14px 0 8px}
.tools input[type=search]{font:inherit;padding:5px 8px;border:2px solid var(--line);background:var(--panel);color:var(--fg);min-width:150px}
.tools label{display:inline-flex;gap:5px;align-items:center;font-size:.85rem}
.scroll{overflow-x:auto;border:2px solid var(--line);background:var(--panel);box-shadow:3px 3px 0 var(--shadow)}
table{border-collapse:collapse;width:100%;font-size:.8rem}
th,td{border-bottom:1px solid var(--soft);padding:4px 8px;text-align:right;white-space:nowrap;
  font-variant-numeric:tabular-nums}
th{background:var(--panel-2);position:sticky;top:0;cursor:pointer;user-select:none;text-align:right;
  font-family:"Silkscreen",monospace;font-size:.72rem;letter-spacing:.04em}
th:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid var(--mustard);outline-offset:2px}
td.l,th.l{text-align:left}
tr.bad td:first-child{box-shadow:inset 4px 0 0 var(--vermilion)}
.count{color:var(--dim);font-size:.8rem}
footer{margin-top:44px;border-top:2px solid var(--line);padding-top:14px;color:var(--dim);font-size:.82rem}
@media (max-width:520px){ .kv{font-size:.75rem} h1{font-size:1.5rem} }
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>

<div class="wrap">
<p class="eyebrow">TRACKMENTO ／ 書き出し画像の割り付け</p>
<h1>並び × 比率 の総点検</h1>
<p class="sub">横×縦（1 辺 32 マス・総数 256 マスまで）と比率 5 種の<b>全 __TOTAL__ 通り</b>を実際に組み、
出力での曲名・タイトル・マスの大きさ、文字の埋まり具合、段の狭さを測った結果。
曲名リストあり・タイトルあり・番号あり、出力の最大辺 2400px。</p>

<div class="tally">
  <div class="tile"><b>__TOTAL__</b><span>組み合わせ</span></div>
  <div class="tile warn"><b>__BAD__</b><span>気になるもの（__PCT__%）</span></div>
  <div class="tile"><b>__SHOTS__</b><span>この頁に載せた実物</span></div>
  <div class="tile"><b id="t-worst">—</b><span>いちばん小さい曲名（px）</span></div>
</div>
<p class="sub">判定のしきい値は、曲名 12px 未満／マス 40px 未満／文字の埋まり 0.60 未満／
タイトルが曲名の 1.2 倍未満／回り込みの段が 14 字未満。
実物は<b>ひどい順に各 30 件</b>まで。残りは下の表で全件見られる。</p>

<div id="sections"></div>

<section>
  <div class="bar"><h2>全 __TOTAL__ 通りの数値</h2><div class="stripe"></div></div>
  <div class="tools">
    <input type="search" id="q" placeholder="12x8 や 9:16 で絞る" aria-label="絞り込み">
    <label><input type="checkbox" id="onlybad"> 気になるものだけ</label>
    <span class="count" id="count"></span>
  </div>
  <div class="scroll"><table id="all"><thead><tr>
    <th class="l" data-k="0">並び</th><th class="l" data-k="2">比率</th><th class="l" data-k="4">組み方</th>
    <th data-k="3">曲数</th><th data-k="5">曲名px</th><th data-k="6">題÷本文</th><th data-k="7">マスpx</th>
    <th data-k="8">埋まり</th><th data-k="9">段の字数</th><th class="l" data-k="10">気になる点</th>
  </tr></thead><tbody></tbody></table></div>
</section>

<footer>2026-09-15 に <code>scripts/layout_audit.py --render</code> で測定。
「柱・帯」（塊を枠の辺にぴったり付ける組み方）と「マスごと」（1 列の並びで曲名をマスの横に並べる）を足し、
下に置く曲名リストも列を割るようにした回。<b>2950 件のうち 505 件でマスが大きくなり、小さくなったのは 1 件</b>。
画像はジャケットを数枚だけ使い回して組んだもので、割り付けを見るためのもの。</footer>
</div>

<script>
const DATA = __DATA__, COUNTS = __COUNTS__;
const GROUPS = [
  ["title","タイトルが曲名リストより小さい","曲名リストの大きさは「入る量」から決まるのに、タイトルはマスの幅から決めている。曲が少ないと曲名が大きくなり、タイトルのほうが小さくなる。回り込みでは先に直したが、流し込みと 1 曲 1 行が残っている。"],
  ["font","曲名リストが読めない大きさ","すべて「比率なし」。横に長い並びだと右の曲名リストに幅が残らず、文字が下限まで落ちる。回り込みは比率が決まっているときだけなので、ここには効かない。"],
  ["cell","ジャケットが判別できない大きさ","曲が多いうえに、並びの形と枠の比率が食い違うもの。曲名を読める大きさにすると、そのぶんマスが潰れる。「選べないようにする」候補はここ。"],
  ["fill","使われない余白が目立つ",""],
  ["seg","回り込みの段が狭い",""],
  ["fine","比べるための「気にならない」例","同じ測り方で問題が出なかったもの。"]
];
const TAG = {title:"タイトルが目立たない",font:"文字が小さい",cell:"マスが小さい",fill:"余白が目立つ",seg:"段が狭い"};
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

document.getElementById("t-worst").textContent = Math.min(...DATA.rows.map((r) => r[5])).toFixed(1);

const card = (m, ok) => `<div class="card${ok ? " ok" : ""}">
  <figure><img src="img/${esc(m.t)}" alt="${esc(m.c)}×${esc(m.r)} ${esc(m.q)} の書き出し例" loading="lazy"></figure>
  <div><div class="name">${m.c}×${m.r} ${esc(m.q)}</div><div class="mode">${esc(m.mode)}・${m.n} 曲</div></div>
  <dl class="kv">
    <dt>曲名</dt><dd>${m.font} px</dd>
    <dt>タイトル</dt><dd>本文の ${m.tr} 倍</dd>
    <dt>マス</dt><dd>${m.cell} px</dd>
    ${m.fill === null ? "" : `<dt>埋まり</dt><dd>${m.fill}</dd>`}
    ${m.seg === null ? "" : `<dt>最小の段</dt><dd>${m.seg} 字</dd>`}
  </dl>
  ${m.bad.length ? `<div class="flags">${m.bad.map((b) => `<span class="flag">${esc(b)}</span>`).join("")}</div>` : ""}
</div>`;

document.getElementById("sections").innerHTML = GROUPS.map(([key, title, why]) => {
  const cards = DATA.cards[key] || [];
  if (!cards.length) return "";
  const total = key === "fine" ? cards.length : (COUNTS[TAG[key]] || cards.length);
  const more = (key !== "fine" && total > cards.length)
    ? `<p class="count">ひどい順に ${cards.length} 件。ほか ${total - cards.length} 件は下の表に。</p>` : "";
  return `<section>
    <div class="bar"><h2>${esc(title)}</h2><div class="stripe"></div><span class="n">${total}</span></div>
    ${why ? `<p class="why sub">${esc(why)}</p>` : ""}
    <div class="specimens">${cards.map((m) => card(m, key === "fine")).join("")}</div>${more}
  </section>`;
}).join("");

const tb = document.querySelector("#all tbody"), q = document.getElementById("q"),
      onlybad = document.getElementById("onlybad"), count = document.getElementById("count");
let view = DATA.rows.slice(), sortK = null, sortDir = 1;
function draw() {
  const term = q.value.trim().toLowerCase(), bad = onlybad.checked;
  const rows = view.filter((r) => (!bad || r[10]) &&
    (!term || (`${r[0]}x${r[1]} ${r[2]} ${r[4]} ${r[10]}`).toLowerCase().includes(term)));
  count.textContent = `${rows.length} 件`;
  tb.innerHTML = rows.map((r) => `<tr class="${r[10] ? "bad" : ""}">
    <td class="l">${r[0]}×${r[1]}</td><td class="l">${esc(r[2])}</td><td class="l">${esc(r[4])}</td>
    <td>${r[3]}</td><td>${r[5]}</td><td>${r[6]}</td><td>${r[7]}</td>
    <td>${r[8] === null ? "" : r[8]}</td><td>${r[9] === null ? "" : r[9]}</td>
    <td class="l">${esc(r[10])}</td></tr>`).join("");
}
document.querySelectorAll("#all th").forEach((th) => {
  th.tabIndex = 0;
  const go = () => {
    const k = +th.dataset.k;
    sortDir = sortK === k ? -sortDir : 1; sortK = k;
    view.sort((a, b) => {
      const x = k === 0 ? a[0] * 1000 + a[1] : a[k], y = k === 0 ? b[0] * 1000 + b[1] : b[k];
      if (typeof x === "number" && typeof y === "number") return (x - y) * sortDir;
      return String(x).localeCompare(String(y), "ja") * sortDir;
    });
    draw();
  };
  th.addEventListener("click", go);
  th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
});
q.addEventListener("input", draw);
onlybad.addEventListener("change", draw);
draw();
</script>
"""

if __name__ == "__main__":
    sys.exit(main())
