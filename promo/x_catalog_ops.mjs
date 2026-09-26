// X に載せる短い動画の台本・3 段目「並べる操作」（2026-09-26）。決まりは x_catalog.mjs の頭と同じ。
// 段取りは題材の台帳（https://claude.ai/artifact/GZ3kefBb8ouyGpV5fc2MRo）の「撮影の段取り」。
//
// - グリッドを組むときの手触り。1 操作 1 本、3〜10 秒
// - 応答は k.mock で架空の曲に差し替える（x_catalog_flow.mjs と同じ）。曲名もサムネも架空
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import { ready, nico, GT, OT, openCellsMore } from "./x_catalog.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));
const ST = ".pane-search > .pane-title", RT = ".pane-results > .pane-title";

/** グリッドの窓だけを真ん中に置く（x_catalog.mjs の ARRANGE_GRID と同じ。編集欄を使う場面は右に検索の窓も置く） */
const GRID_ONLY = { ".pane-grid": { x: 360, y: 16, w: 560, only: ["#grid-scroll", "#grid-msg", ".grid-actions"] } };
const GRID_AND_EDITOR = { ".pane-grid": { x: 40, y: 30, w: 560, only: ["#grid-scroll", "#grid-msg"] }, ".pane-search": { x: 640, y: 30, w: 600 } };
const EDITOR_ONLY_CSS = ".pane-search > :not(.pane-title):not(#editor) { display: none !important; } #grid-scroll { height: auto !important; }";
/** 検索・候補・グリッドを横に並べる（x_catalog_flow.mjs の ARRANGE_FLOW と同じ） */
const FLOW = {
  ".pane-search": { x: 24, y: 24, w: 400 },
  ".pane-results": { x: 444, y: 24, w: 360, h: 672 },
  ".pane-grid": { x: 824, y: 24, w: 432, only: ["#grid-scroll", "#grid-msg"] },
};
const onlySubs = (...keep) => ["#sub-bandcamp", "#sub-list", "#sub-manual"].filter((s) => !keep.includes(s))
  .map((s) => `${s} { display: none !important; }`).join(" ");

/** 空きマスを混ぜて並べる（cells は曲か null の配列） */
async function place(k, cols, rows, cells, opts = {}) {
  await k.page.evaluate(({ cols, rows, cells, opts }) => {
    window.__setGridUI(cols, rows, { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true, margin: 16, gap: 16, bg: "mustard", bgCustom: null, ...opts }, cells);
    document.querySelector("#title").value = opts.title ?? "私を構成する9曲";
    window.scrollTo(0, 0);
  }, { cols, rows, cells, opts });
  await k.hold(0.3);
  await k.waitArt();
}
const withHoles = (list, n, holes) => Array.from({ length: n }, (_, i) => (holes.includes(i) ? null : list[i % list.length]));
/** ポップアップメニュー（OS 9 風）で項目を選ぶ。sel は select の id */
async function popPick(k, sel, text) {
  await k.press(`.popup:has(#${sel}) .popup-hit`);
  await k.until(() => k.page.evaluate(() => !document.querySelector("#popmenu").hidden), "メニュー", 5000);
  await k.hold(0.4);
  await k.press(`#popmenu-list li:text-is("${text}")`);
}
/** 撮る前に検索して候補を並べておく（入れる先を決める場面など）。曲名は検索語を含むものしか残らないので、
    list の 2 つ目からは「検索語＋付け足し」の題にする（絵は list のまま） */
async function searchFirst(k, q, list) {
  const tails = ["", " (Live)", " - Remix", " (Acoustic)"];
  const rows = list.map((t, i) => ({ ...t, source: "itunes", title: t.title.includes(q) ? t.title : `${q}${tails[i % tails.length] || " (ver." + i + ")"}` }));
  await k.mock({ itunes: () => rows });
  await k.page.fill("#q", q);
  await k.page.click("#search-btn");
  await k.until(() => k.page.evaluate(() => document.querySelectorAll("#results .result").length >= 3), "候補", 15000);
}

const OUT = "#output > .pane-title";
/** 見本を作って待つ（撮る前は時計だけ進めて待つ） */
async function refreshOut(k, live = true) {
  const done = () => k.page.evaluate(() => /px/.test(document.querySelector("#out-msg").textContent) && !document.querySelector("#out-shot").hidden && document.querySelector("#output-img").complete);
  if (live) { await k.press("#out-refresh"); await k.live(done, { min: 0.3, timeout: 30 }); }
  else { await k.page.$eval("#out-refresh", (el) => el.click()); await k.until(done, "見本", 30000); }
}
const OUT_ONLY_CSS = "#output .out-actions > :not(#out-refresh), #output .listed, #output .msg-under, #share-done { display: none !important; }";

/** **撮影用の擬似ファイルの窓**（2026-09-26、利用者の案）。ヘッドレスのブラウザでは本物の保存・開くの窓が出ないので、
    「名前を付けて保存」「開く」の窓をページの上に描く（サイトの機能ではない。撮影のときだけ差し込む）。
    見た目は OS の標準の窓に寄せた素朴なもの（サイトの OS 9 の部品と混ざらないように、角丸・灰色・細い線） */
const FAKE_DLG_CSS = `
.x-fake, .x-fake * { visibility: visible !important; box-sizing: border-box; }
.x-fake { position: fixed; inset: 0; z-index: 90; display: grid; place-items: center; background: rgba(0,0,0,.18); font: 13px/1.4 "Segoe UI", "Yu Gothic UI", "Meiryo", sans-serif; color: #1b1b1b; }
.x-fake .w { width: 620px; background: #fff; border: 1px solid #8a8a8a; border-radius: 8px; box-shadow: 0 8px 28px rgba(0,0,0,.28); overflow: hidden; }
.x-fake .t { display: flex; align-items: center; justify-content: space-between; padding: 8px 12px; background: #f3f3f3; border-bottom: 1px solid #ddd; font-size: 12px; }
.x-fake .t b { font-weight: 600; }
.x-fake .t i { font-style: normal; color: #666; }
.x-fake .path { margin: 10px 12px 0; padding: 6px 10px; border: 1px solid #ccc; border-radius: 4px; color: #333; }
.x-fake .body { display: grid; grid-template-columns: 150px 1fr; min-height: 220px; margin: 10px 12px; border: 1px solid #ddd; border-radius: 4px; }
.x-fake .nav { background: #fafafa; border-right: 1px solid #e5e5e5; padding: 8px 0; }
.x-fake .nav div { padding: 5px 14px; }
.x-fake .nav .on { background: #cce4f7; }
.x-fake .files { padding: 6px; }
.x-fake .files div { display: flex; gap: 8px; align-items: center; padding: 5px 8px; border-radius: 3px; }
.x-fake .files div::before { content: ""; width: 14px; height: 16px; border: 1px solid #888; border-radius: 1px; background: linear-gradient(135deg, #fff 70%, #ddd 70%); }
.x-fake .files .folder::before { width: 18px; height: 13px; border-color: #c9a227; background: #f4d470; }
.x-fake .files .sel { background: #cce4f7; }
.x-fake .row { display: flex; gap: 8px; align-items: center; margin: 0 12px 12px; }
.x-fake .row label { width: 90px; color: #444; }
.x-fake .row .in { flex: 1; padding: 5px 8px; border: 1px solid #7a7a7a; border-radius: 3px; min-height: 28px; }
.x-fake .btns { display: flex; justify-content: flex-end; gap: 8px; margin: 0 12px 12px; }
.x-fake .btns span { min-width: 88px; padding: 5px 14px; text-align: center; border: 1px solid #adadad; border-radius: 4px; background: #fdfdfd; }
.x-fake .btns .ok { background: #0067c0; border-color: #0067c0; color: #fff; }
`;
/** 窓を出す。kind は "save" / "open"。files はフォルダの中身（名前の配列）。name は保存する名前 */
async function fakeDialog(k, kind, files, name = "") {
  await k.page.evaluate(({ kind, files, name }) => {
    const d = document.createElement("div"); d.className = "x-fake"; d.id = "x-fake";
    const title = kind === "save" ? "名前を付けて保存" : "開く";
    d.innerHTML = `<div class="w"><div class="t"><b>${title}</b><i>✕</i></div>
      <div class="path">PC ＞ ダウンロード</div>
      <div class="body"><div class="nav"><div>デスクトップ</div><div>ドキュメント</div><div class="on">ダウンロード</div><div>ピクチャ</div><div>ミュージック</div></div>
      <div class="files">${files.map((f) => `<div class="${f.endsWith("/") ? "folder" : "file"}" data-name="${f}">${f.replace(/\/$/, "")}</div>`).join("")}</div></div>
      <div class="row"><label>ファイル名:</label><div class="in" id="x-fake-name">${name}</div></div>
      <div class="btns"><span class="ok" id="x-fake-ok">${kind === "save" ? "保存" : "開く"}</span><span>キャンセル</span></div></div>`;
    document.body.append(d);
  }, { kind, files, name });
}
const closeFake = (k) => k.page.evaluate(() => document.querySelector("#x-fake")?.remove());

export default [
  {
    id: "o-same",
    what: "同じトラックをもう一度入れると「N 番にも同じトラックがあります」と知らせる（入れるのは止めない）",
    async setup(k) {
      const sq = square();
      await place(k, 3, 3, withHoles(sq, 9, [5, 6, 7, 8]));
      await k.arrange(FLOW); await k.stage(onlySubs() + " #grid-msg { font-size: 15px !important; }");
      await searchFirst(k, "夜明けのシグナル", [sq[9], sq[0], sq[12]]);
      await k.look([RT, GT, "#results", "#grid", "#grid-msg"]);
      await k.park(640, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#results li:nth-child(1) .result");   // 1 番と同じ曲（候補の先頭。題がぴったり合うものが先に並ぶ）
      await k.until(() => k.page.evaluate(() => /同じトラック/.test(document.querySelector("#grid-msg").textContent)), "同じトラックの知らせ", 5000);
      await k.hold(0.3);
      // **知らせの文に寄る**（小さくて読めなかった、と利用者）。1 番と 6 番のマスも入れる
      await k.look(["#grid .cell:nth-child(1)", "#grid .cell:nth-child(6)", "#grid-msg"], 0.6);
      await k.hold(2.4);
      await k.look([RT, GT, "#results", "#grid", "#grid-msg"], 0.5);
      await k.hold(0.6);
    },
  },
  {
    id: "o-swap",
    what: "マスを押して選び、別のマスを押すと入れ替わる。空きマスを押せばそこへ移る。もう一度押すと選ぶのをやめる",
    async setup(k) {
      await place(k, 3, 3, withHoles(square(), 9, [8]));
      await k.arrange(GRID_ONLY);
      await k.look([GT, "#grid", "#grid-msg"]);
      await k.park(640, 650);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#grid .cell:nth-child(1)"); await k.hold(0.5);
      await k.press("#grid .cell:nth-child(5)"); await k.hold(1.0);   // 入れ替え
      await k.press("#grid .cell:nth-child(3)"); await k.hold(0.5);
      await k.press("#grid .cell:nth-child(9)"); await k.hold(1.0);   // 空きマスへ移す
      await k.press("#grid .cell:nth-child(2)"); await k.hold(0.5);
      await k.press("#grid .cell:nth-child(2)"); await k.hold(0.8);   // もう一度押して解除
    },
  },
  {
    id: "o-drag",
    what: "PC ではマスを掴んで運ぶと入れ替わる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange(GRID_ONLY);
      await k.look([GT, "#grid", "#grid-msg"]);
      await k.park(640, 650);
    },
    async run(k) {
      await k.hold(0.8);
      await k.drag("#grid .cell:nth-child(1)", "#grid .cell:nth-child(9)", 1.0);
      await k.hold(1.0);
      await k.drag("#grid .cell:nth-child(9)", "#grid .cell:nth-child(1)", 0.8);   // 元に戻して終わる
      await k.hold(0.8);
    },
  },
  {
    id: "o-target",
    what: "空きマスを押すと「入れる先」になる。次に押した候補がそのマスに入る",
    async setup(k) {
      const sq = square();
      await place(k, 3, 3, withHoles(sq, 9, [4, 7]));
      await k.arrange(FLOW); await k.stage(onlySubs());
      await searchFirst(k, "ソーダ水の惑星", [sq[15], sq[16], sq[17]]);
      await k.look([RT, GT, "#results", "#grid"]);
      await k.park(900, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#grid .cell:nth-child(5)");
      await k.hold(0.8);
      await k.press("#results li:nth-child(2) .result");
      await k.waitArt();
      await k.hold(1.2);
      await k.press("#grid .cell:nth-child(8)");
      await k.hold(0.6);
      await k.press("#results li:nth-child(1) .result");
      await k.waitArt();
      await k.hold(1.2);
    },
  },
  {
    id: "o-remove",
    what: "マスの × で外せる。外したあとのメッセージの「元に戻す」で戻る",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange(GRID_ONLY);
      await k.look([GT, "#grid", "#grid-msg"]);
      await k.park(640, 650);
    },
    async run(k) {
      await k.hold(0.8);
      await k.glide("#grid .cell:nth-child(5)", 0.3);
      await k.press("#grid .cell:nth-child(5) .rm", { sec: 0.2 });
      await k.hold(1.0);
      await k.press("#grid-msg .undo");
      await k.hold(1.4);
    },
  },
  {
    id: "o-clear",
    what: "「トラックを全て外す」は確認の窓を出す（既定は「やめる」）。外したあとも「元に戻す」で戻せる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange({ ".pane-grid": { x: 390, y: 16, w: 500, only: ["#grid-scroll", "#grid-msg", ".clear-row"] } });
      await k.stage("#grid-scroll { height: auto !important; }");
      await k.look([GT, "#grid", "#grid-msg", "#clear-btn"]);
      await k.park(640, 650);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#clear-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#confirm-modal").hidden), "確認の窓", 5000);
      await k.look(["#confirm-modal .modal-panel"], 0.5);
      await k.hold(1.2);
      await k.press("#confirm-yes");
      await k.look([GT, "#grid", "#grid-msg", "#clear-btn"], 0.5);
      await k.hold(1.0);
      await k.press("#grid-msg .undo");
      await k.waitArt();
      await k.hold(1.2);
    },
  },
  {
    id: "o-trim",
    what: "「トラック名を短くする」… 【東方Vocal】や「- Topic」のような部分をトラック名から外す。書き出しの曲名リストもすっきりする",
    async setup(k) {
      const sq = square().slice(0, 6);
      const junk = ["【東方Vocal】", " (Official Music Video)", "【MV】", " - Topic", " [Full ver.]", "【歌ってみた】"];
      const cells = sq.map((t, i) => (i === 3 ? { ...t, artist: `${t.artist} - Topic` } : { ...t, title: i % 2 ? `${t.title}${junk[i]}` : `${junk[i]}${t.title}` }));
      await place(k, 3, 2, cells, { trimNames: false });
      // 左にグリッドと「短くする」、右にできあがりの見本（書き出しの曲名リストで確かめる、と利用者）
      await k.arrange({ ".pane-grid": { x: 24, y: 24, w: 440, only: ["#grid-scroll", "#grid-msg", ".grid-actions"] }, "#output": { x: 490, y: 24, w: 766 } });
      await k.stage(".grid-actions > :not(.grid-foot) { display: none !important; } #grid-scroll { height: auto !important; } " + OUT_ONLY_CSS);
      await refreshOut(k, false);
      await k.look([GT, "#grid", "#trim-all-btn", OUT, "#output"]);
      await k.park(640, 650);
    },
    async run(k) {
      await k.hold(1.0);
      await k.look([OUT, "#out-shot"], 0.5);
      await k.hold(1.2);
      await k.look([GT, "#grid", "#trim-all-btn", OUT, "#output"], 0.5);
      await k.press("#trim-all-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#confirm-modal").hidden), "確認の窓", 5000);
      await k.hold(1.0);
      await k.press("#confirm-yes");
      await k.hold(0.4);
      await refreshOut(k);
      await k.look([OUT, "#out-shot"], 0.5);
      await k.hold(1.8);
    },
  },
  {
    id: "o-editor",
    what: "マスを選ぶと、トラック名・アーティスト名を直せる。メモは共有ページのトラックリストに出る",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange(GRID_AND_EDITOR); await k.stage(EDITOR_ONLY_CSS);
      await k.look([GT, "#grid"]);
      await k.park(640, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#grid .cell:nth-child(5)");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#editor").hidden), "編集欄", 5000);
      await k.look([GT, "#grid", ".pane-search > .pane-title", "#editor"], 0.5);
      await k.glide("#e-title", 0.3);
      await k.page.click("#e-title", { clickCount: 3 });
      await k.type("#e-title", "迷子の自販機 (2026 Remix)", 0.05);
      await k.hold(0.5);
      await k.glide("#e-note", 0.3);
      await k.type("#e-note", "駅前の自販機の前でずっと聴いてた", 0.05);
      await k.hold(1.2);
      await k.press("#e-close");
      await k.look([GT, "#grid"], 0.5);
      await k.hold(0.8);
    },
  },
  {
    id: "o-origin",
    what: "動画サイトの曲は、アーティスト名がチャンネル名のことがある。「元の投稿を探す」で otoDB やニコニコ動画の古い投稿から作者を探して選べる",
    async setup(k) {
      const wide = nico();
      const cells = wide.slice(0, 9).map((t, i) => ({ ...t, source: i === 0 ? "youtube" : "nicovideo", artist: i === 0 ? "音MAD まとめチャンネル" : t.artist, external_url: `https://www.youtube.com/watch?v=Ab${i}` }));
      await place(k, 3, 3, cells, { cellRatio: "16:9" });
      await k.page.route(/\/artist-candidates\?/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        otodb: { artist: "こはく", work: "#1234", posts: [{ id: "sm12345678", at: "2014-05-03" }] },
        candidates: [{ artist: "こはく", id: "sm12345678", at: "2014-05-03T21:00:00" }, { artist: "ユウグレ", id: "sm20123456", at: "2016-11-20T12:00:00" }] }) }));
      await k.arrange(GRID_AND_EDITOR); await k.stage(EDITOR_ONLY_CSS);
      await k.look([GT, "#grid"]);
      await k.park(640, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#grid .cell:nth-child(1)");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#editor").hidden), "編集欄", 5000);
      await k.look([".pane-search > .pane-title", "#editor"], 0.5);
      await k.hold(0.4);
      await k.press("#e-origin-find");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#e-origin-seg button").length >= 2), "候補", 10000);
      await k.hold(1.2);
      await k.press("#e-origin-seg button:first-of-type");
      await k.hold(1.4);
      await k.press("#e-close");
      await k.look([GT, "#grid"], 0.5);
      await k.hold(0.6);
    },
  },
  {
    id: "o-theme",
    what: "「お題」から選ぶとタイトルが入る。「私を構成する9曲」なら横 × 縦も 3 × 3 に",
    async setup(k) {
      await place(k, 4, 4, withHoles(square(), 16, [9, 10, 11, 12, 13, 14, 15]), { title: "" });
      await k.arrange({ ".pane-grid": { x: 330, y: 16, w: 620, only: [".grid-head", ".themes", "#grid-scroll", "#grid-msg"] } });
      await k.stage("#zoom-btn { visibility: hidden !important; }");
      await k.look([GT, "#title", "#theme-sel", "#grid"]);
      await k.park(900, 300);
    },
    async run(k) {
      await k.hold(0.8);
      await popPick(k, "theme-sel", "好きな音MAD");
      await k.hold(1.2);
      await popPick(k, "theme-sel", "私を構成する9曲");
      await k.hold(1.8);
    },
  },
  {
    id: "o-layouts",
    what: "「並び」は 10 個まで持てる。「新しい並び」で別の並びを作り、メニューで切り替える",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9), { title: "私を構成する9曲" });
      await k.arrange({ ".pane-grid": { x: 330, y: 16, w: 620, only: [".layouts", "#grid-scroll", "#grid-msg"] } });
      await k.stage("#grid-scroll { height: auto !important; }");
      await k.look([GT, ".layouts", "#grid"]);
      await k.park(900, 300);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#layout-new");
      await k.hold(0.6);
      // 2 つ目の並びにも曲を入れる（空のままだと比べにくい、と利用者）。入れる操作はほかの動画で見せているので一度に入れる
      const sq = square();
      await k.page.evaluate((cells) => { window.__setGridUI(3, 3, { title: "雨の日に聴く曲", bg: "cerulean" }, cells); document.querySelector("#title").value = "雨の日に聴く曲"; document.querySelector("#title").dispatchEvent(new Event("input", { bubbles: true })); }, sq.slice(9, 18));
      await k.waitArt();
      await k.hold(1.2);
      await popPick(k, "layout-sel", "私を構成する9曲");
      await k.waitArt();
      await k.hold(1.2);
      await popPick(k, "layout-sel", "雨の日に聴く曲");
      await k.waitArt();
      await k.hold(1.2);
      await k.press("#layout-del");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#confirm-modal").hidden), "確認の窓", 5000);
      await k.hold(0.6);
      await k.press("#confirm-yes");
      await k.waitArt();
      await k.hold(1.0);
    },
  },
  {
    id: "o-zoom",
    what: "「大きく見る」でグリッドを画面いっぱいに。窓の中で送って見て、2 本指（Ctrl＋ホイール）でマスの大きさも変えられる",
    async setup(k) {
      await place(k, 8, 8, Array.from({ length: 64 }, (_, i) => square()[i % 24]), { title: "今月かなり聴いた曲" });
      k.wide(0);
      await k.park(900, 400);
    },
    async run(k) {
      await k.hold(0.6);
      await k.press("#zoom-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#zoom-modal").hidden), "大きく見る", 5000);
      await k.hold(0.6);
      await k.glide("#zoom-slot", 0.4);
      const [x, y] = [640, 400];
      for (let i = 0; i < 10; i++) { await k.ctrlWheel(x, y, -60); await k.hold(0.08); }   // 拡大
      await k.hold(0.6);
      const sc = () => k.page.evaluate(() => { const el = [...document.querySelectorAll("#zoom-modal *")].find((e) => e.scrollHeight > e.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(e).overflowY)); if (el) el.scrollBy({ top: 70 }); });
      for (let i = 0; i < 8; i++) { await sc(); await k.hold(0.1); }   // 送って見る
      await k.hold(0.6);
      for (let i = 0; i < 10; i++) { await k.ctrlWheel(x, y, 60); await k.hold(0.08); }   // 縮小
      await k.hold(0.8);
      await k.press("#zoom-modal-close");
      await k.hold(0.6);
    },
  },
  {
    id: "o-grid-size",
    what: "横 × 縦は上下の小さな矢印で増やせる。マスは全部で 256 まで",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange({ ".pane-grid": { x: 40, y: 30, w: 620, only: ["#grid-scroll", "#grid-msg"] },
                        ".pane-options": { x: 700, y: 30, w: 330, only: [".gbox:has(#cols)"] } });
      await k.stage(".gbox:has(#cols) > :not(.gbox-title):not(fieldset:has(#cols)) { display: none !important; } #grid-scroll { height: auto !important; max-height: 560px !important; }");
      await k.look([GT, "#grid", OT, "#cols", "#rows"]);
      await k.park(900, 400);
    },
    async run(k) {
      await k.hold(0.8);
      const up = (id) => `#${id} ~ .stepper button[data-step='1']`, down = (id) => `#${id} ~ .stepper button[data-step='-1']`;
      for (let i = 0; i < 3; i++) { await k.press(up("cols"), { sec: i ? 0.15 : 0.4 }); await k.hold(0.25); }
      for (let i = 0; i < 2; i++) { await k.press(up("rows"), { sec: i ? 0.15 : 0.4 }); await k.hold(0.25); }
      await k.waitArt();
      await k.hold(1.0);
      for (let i = 0; i < 2; i++) { await k.press(down("rows"), { sec: i ? 0.15 : 0.4 }); await k.hold(0.2); }
      for (let i = 0; i < 3; i++) { await k.press(down("cols"), { sec: i ? 0.15 : 0.4 }); await k.hold(0.2); }
      await k.hold(0.8);
    },
  },
  {
    id: "o-window",
    what: "PC では窓を題名バーで動かせる。右上の「—」で畳める。「窓を元に戻す」で元の位置へ",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      k.wide(0);
      await k.park(900, 400);
    },
    async run(k) {
      await k.hold(0.8);
      await k.drag(".pane-results > .pane-title", { dx: 120, dy: 260 }, 1.0, [0.35, 0.5]);
      await k.hold(0.8);
      await k.press(".pane-search > .pane-title .fold");
      await k.hold(0.8);
      await k.press(".pane-search > .pane-title .fold");
      await k.hold(0.6);
      await k.press("#win-reset");
      await k.hold(1.0);
    },
  },
  {
    id: "o-tri",
    what: "出力オプションは「マス」「文字」「背景と余白」のまとまりに分かれ、枠の形は「枠とサムネ」の三角で開け閉めできる",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      k.wide(0);   // 最初は引きの絵（画面ぜんぶ）から（利用者の指摘）
      await k.park(1100, 300);
    },
    async run(k) {
      await k.hold(0.4);   // 引きの絵は短く（長すぎる、と利用者）
      await k.look([OT, ".pane-options .opts"], 0.6);   // 出力オプションの窓へ寄る
      await k.hold(0.7);
      await k.look([OT, ".pane-options .gbox:nth-of-type(1)"], 0.6);
      await k.press("#cells-more-btn");
      await k.hold(1.4);
      await k.press("#cells-more-btn");
      await k.hold(0.6);
      k.wide(0.8);
      await k.hold(0.6);
    },
  },
  {
    id: "o-json",
    what: "「並びを保存」でファイルに書き出し、「並びを読み込み…」で同じ並びに戻せる（共有は 30 日で消えるので、長く残したいとき）",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange({ ".pane-grid": { x: 400, y: 16, w: 480, only: ["#grid-scroll", "#grid-msg", ".grid-actions"] } });
      await k.stage(".grid-actions > :not(.minor) { display: none !important; } #color-sort { display: none !important; } #grid-scroll { height: auto !important; } " + FAKE_DLG_CSS);
      await k.look([GT, "#grid", "#grid-msg", ".grid-actions"]);
      await k.park(640, 650);
    },
    async run(k) {
      const name = "trackmento-私を構成する9曲.json";
      const others = ["音楽/", "trackmento-雨の日に聴く曲.json", "trackmento-好きな音MAD.json"];
      await k.hold(0.8);
      // 保存: 本物の保存は裏で済ませ、画面には擬似の「名前を付けて保存」の窓を出す
      const dl = k.page.waitForEvent("download");
      await k.press("#json-export");
      const file = path.join(os.tmpdir(), `x-json-${Date.now()}.json`);
      await (await dl).saveAs(file);
      await fakeDialog(k, "save", others, name);
      k.wide(0.5);
      await k.hold(1.2);
      await k.press("#x-fake-ok");
      await closeFake(k);
      await k.look([GT, "#grid", "#grid-msg", ".grid-actions"], 0.5);
      await k.hold(0.8);
      // 並びを崩す（トラックを全部外す。確認の窓は撮らない）
      await k.page.evaluate(() => { window.__setGridUI(3, 3, {}, Array(9).fill(null)); });
      await k.hold(0.9);
      // 読み込み: 擬似の「開く」の窓でさっきのファイルを選ぶ
      const fc = k.page.waitForEvent("filechooser");
      await k.press("#json-import");
      const chooser = await fc;
      await fakeDialog(k, "open", [...others, name]);
      k.wide(0.5);
      await k.hold(0.6);
      await k.press(`#x-fake .files [data-name="${name}"]`);
      await k.page.evaluate((n) => { document.querySelector(`#x-fake .files [data-name="${n}"]`).classList.add("sel"); document.querySelector("#x-fake-name").textContent = n; }, name);
      await k.hold(0.6);
      await k.press("#x-fake-ok");
      await closeFake(k);
      await chooser.setFiles(file);
      await k.look([GT, "#grid", "#grid-msg", ".grid-actions"], 0.5);
      await k.waitArt();
      await k.hold(1.6);
      fs.rmSync(file, { force: true });
    },
  },
  {
    id: "o-keys",
    what: "キーボードでも操作できる … Tab でグリッドへ、矢印でマスを移り、Return で選ぶ、Esc でやめる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9), { bg: "paper" });   // 背景は選んだ枠（マスタード）と違う色に（同化して見づらい、と利用者）
      await k.arrange(GRID_ONLY);
      await k.look([GT, "#grid", "#grid-msg"]);
      await k.hideCursor();
      await k.page.focus("#title");
    },
    async run(k) {
      await k.hold(0.8);
      await k.key("Tab");
      await k.page.focus("#grid .cell");   // Tab の行き先はほかの部品を挟むので、撮影ではマスに直接置く
      await k.hold(0.5);
      for (const key of ["ArrowRight", "ArrowRight", "ArrowDown"]) { await k.key(key); await k.hold(0.45); }
      await k.key("Enter"); await k.hold(0.8);
      await k.key("Escape"); await k.hold(0.6);
      for (const key of ["ArrowUp", "ArrowLeft", "ArrowLeft"]) { await k.key(key); await k.hold(0.35); }
      await k.hold(0.6);
    },
  },
  {
    id: "o-lang-us",
    what: "右上の「EN」で英語表示に。英語表示で探すと、iTunes の米国の表記でトラック名とアーティスト名が出る",
    async setup(k) {
      const sq = square();
      const jp = [sq[0], sq[2], sq[6]].map((t, i) => ({ ...t, source: "itunes", external_url: `https://music.apple.com/jp/album/x?i=90000${i}` }));
      const en = { "900000": ["Dawn Signal", "Minatori"], "900001": ["March Radio Tower", "Nemuri Kobo"], "900002": ["White Slope", "Yukimi"] };
      await k.mock({ itunes: () => jp });
      await k.page.route(/^https:\/\/itunes\.apple\.com\/lookup/, (route) => {
        const ids = (new URL(route.request().url()).searchParams.get("id") || "").split(",");
        route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ results: ids.filter((i) => en[i]).map((i) => ({ wrapperType: "track", trackId: +i, trackName: en[i][0], artistName: en[i][1], collectionName: null })) }) });
      });
      await place(k, 3, 3, Array(9).fill(null));
      k.wide(0);   // 画面ぜんぶ（「EN」を押して、画面ごと英語に替わるところを見せる。利用者の指摘）
      await k.park(900, 300);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#lang-switch");
      await k.hold(1.4);
      await k.look([".pane-search > .pane-title", "#search-form", ".pane-results > .pane-title", "#results"], 0.7);
      await k.glide("#q", 0.3);
      await k.type("#q", "夜明け", 0.08);
      await k.press("#search-btn");
      await k.until(() => k.page.evaluate(() => /Dawn Signal/.test(document.querySelector("#results").textContent)), "英語の候補", 15000);
      await k.hold(1.8);
      k.wide(0.6);
      await k.press("#lang-switch");   // 日本語に戻して終わる
      await k.hold(0.8);
    },
  },
  {
    id: "o-sub",
    what: "検索のほかに 3 つの入れ方がある … 「URL から」「トラック名の一覧から」「手入力」。見出しを押すと切り替わる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange({ ".pane-search": { x: 400, y: 16, w: 480 } });
      await k.stage("#search-form { display: none !important; }");   // 検索の欄は隠す（3 つの入れ方に絞る）
      await k.look([ST, ".pane-search"]);
      await k.park(900, 400);
    },
    async run(k) {
      // それぞれ開いて、何を入れる欄かが分かるように少し打つ（何をしているか分からない、と利用者）
      await k.hold(0.6);
      await k.look([ST, "#sub-bandcamp"], 0.5);
      await k.glide("#bc-url", 0.3); await k.type("#bc-url", "https://www.nicovideo.jp/watch/sm45012345", 0.025);
      await k.hold(0.8);
      await k.press("#sub-list > .sub-title");
      await k.look([ST, "#sub-list"], 0.5);
      await k.glide('#list-rows input[data-row="0"][data-key="artist"]', 0.3);
      await k.type('#list-rows input[data-row="0"][data-key="artist"]', "ミナトリ", 0.06);
      await k.page.focus('#list-rows input[data-row="0"][data-key="title"]');
      await k.type('#list-rows input[data-row="0"][data-key="title"]', "夜明けのシグナル", 0.06);
      await k.hold(0.8);
      await k.press("#sub-manual > .sub-title");
      await k.look([ST, "#sub-manual"], 0.5);
      await k.glide("#m-title", 0.3); await k.type("#m-title", "文化祭で弾いた曲", 0.06);
      await k.hold(1.0);
      await k.press("#sub-bandcamp > .sub-title");
      await k.look([ST, ".pane-search"], 0.5);
      await k.hold(0.6);
    },
  },
  {
    id: "o-spotify",
    what: "Spotify の URL はアーティスト名が取れないので、iTunes で同じトラック名から補う。何人かいるときは選べる",
    async setup(k) {
      const sq = square();
      await k.mock({
        url: () => ({ source: "spotify", title: "Paper Rocket", artist: "", album: null, image: sq[8].image, thumb: sq[8].thumb, external_url: "https://open.spotify.com/track/abc" }),
        itunes: () => [{ ...sq[8], source: "itunes" }, { ...sq[8], artist: "Tsubame & Kuro", source: "itunes" }, { ...sq[8], artist: "Paper Planes", source: "itunes" }],
      });
      await place(k, 3, 3, Array(9).fill(null));
      await k.arrange(FLOW); await k.stage(onlySubs("#sub-bandcamp") + " #search-form { display: none !important; }");
      if (await k.page.getAttribute("#sub-bandcamp > .sub-title", "aria-expanded") !== "true") await k.page.click("#sub-bandcamp > .sub-title");
      await k.look([ST, "#sub-bandcamp"]);
      await k.park(640, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.glide("#bc-url", 0.3);
      await k.type("#bc-url", "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC", 0.03);
      await k.press("#bc-btn");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#bc-msg .pick").length >= 2), "アーティスト名の候補", 20000);
      await k.look([ST, "#sub-bandcamp", RT, "#results"], 0.5);
      await k.hold(1.2);
      await k.press("#bc-msg .pick:first-of-type");
      await k.hold(1.6);
    },
  },
  {
    id: "o-revive",
    what: "削除されたニコニコ動画でも、otoDB に登録があれば題とサムネイルを取れる（マイリストの中の消えた動画も補う）",
    async setup(k) {
      const wide = nico();
      await k.mock({ url: () => ({ ...wide[5], source: "otodb", title: "【音MAD】ねむりの電波塔", artist: "ねむり工房", external_url: "https://www.nicovideo.jp/watch/sm9876543" }) });
      await place(k, 3, 3, Array(9).fill(null), { cellRatio: "16:9" });
      await k.arrange(FLOW); await k.stage(onlySubs("#sub-bandcamp") + " #search-form { display: none !important; }");
      if (await k.page.getAttribute("#sub-bandcamp > .sub-title", "aria-expanded") !== "true") await k.page.click("#sub-bandcamp > .sub-title");
      await k.look([ST, "#sub-bandcamp"]);
      await k.park(640, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.glide("#bc-url", 0.3);
      await k.type("#bc-url", "sm9876543", 0.08);
      await k.press("#bc-btn");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#results .result").length >= 1), "候補", 15000);
      await k.look([ST, RT, GT, "#sub-bandcamp", "#results", "#grid"], 0.5);
      await k.hold(0.8);
      await k.press("#results li:nth-child(1) .result");
      await k.waitArt();
      await k.hold(1.4);
    },
  },
  {
    id: "o-share-open",
    what: "共有ページの「TRACKMENTO で開く」を押すと、その並びが新しい並びとして入る（今の並びはそのまま残り、「並び」のメニューで戻れる）",
    async setup(k) {
      const sq = square();
      const doc = { id: "fa4e0ab1c2d3", title: "雨の日に聴く曲", cols: 3, rows: 2, cells: sq.slice(10, 16), stash: [], createdAt: "2026-09-26T10:00:00Z",
        options: { ratio: "16:9", bg: "cerulean", showTitle: true, sidebar: true, numbers: true, gap: 16, margin: 16 } };
      // 架空の共有ページと共有画像（promo/fake_share_page.py。本番の R2 には何も置かない）
      const dir = path.join(os.tmpdir(), "x-share-open"), docFile = path.join(dir, "doc.json");
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(docFile, JSON.stringify(doc));
      const imgUrl = execFileSync(".venv/Scripts/python", ["promo/fake_share_page.py", docFile, dir], { env: { ...process.env, PYTHONUTF8: "1", PUBLIC_MODE: "1" }, encoding: "utf-8" }).trim();
      await k.page.route((u) => u.href === imgUrl, (route) => route.fulfill({ status: 200, contentType: "image/jpeg", body: fs.readFileSync(path.join(dir, "image.jpg")) }));
      await k.page.route(/\/s\/fa4e0ab1c2d3$/, (route) => route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: fs.readFileSync(path.join(dir, "page.html"), "utf-8") }));
      await k.page.route(/\/shares\/fa4e0ab1c2d3\.json/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(doc) }));
      await place(k, 3, 3, sq.slice(0, 9));
      // 共有ページを開いておく（撮り始めはここから）
      await k.page.goto("http://127.0.0.1:8000/s/fa4e0ab1c2d3", { waitUntil: "domcontentloaded" });
      await k.until(() => k.page.evaluate(() => [...document.images].every((i) => i.complete && i.naturalWidth)), "共有ページ", 15000);
      await k.look(["header", "main h1, main img"], 0);
      await k.park(900, 600);
    },
    async run(k) {
      await k.hold(1.6);
      await k.look(["main img", ".btns"], 0.6);
      await k.hold(0.6);
      await k.press('.btns a[href*="?share="]');
      await k.page.waitForURL(/127\.0\.0\.1:8000\/(\?|$)/, { timeout: 20000 });
      for (let i = 0; i < 200 && !(await k.page.evaluate(() => !!window.__setGridUI)); i++) { await k.page.clock.runFor(50); await new Promise((r) => setTimeout(r, 50)); }
      await k.page.addStyleTag({ content: '#sources label:has(input[value="discogs"]) { display: none !important; }' });
      await k.arrange({ ".pane-grid": { x: 330, y: 16, w: 620, only: [".layouts", "#grid-scroll", "#grid-msg"] } });
      await k.stage("#grid-scroll { height: auto !important; }");
      await k.until(() => k.page.evaluate(() => /新しい並び/.test(document.querySelector("#grid-msg").textContent)), "共有の読み込み", 15000);
      await k.waitArt();
      await k.look([GT, ".layouts", "#grid", "#grid-msg"], 0);
      await k.park(900, 300);
      await k.hold(1.8);
      await popPick(k, "layout-sel", "私を構成する9曲");
      await k.waitArt();
      await k.hold(1.4);
    },
  },
];
