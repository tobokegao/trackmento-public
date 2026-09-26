// X に載せる短い動画の台本・3 段目「並べる操作」（2026-09-26）。決まりは x_catalog.mjs の頭と同じ。
// 段取りは題材の台帳（https://claude.ai/artifact/GZ3kefBb8ouyGpV5fc2MRo）の「撮影の段取り」。
//
// - グリッドを組むときの手触り。1 操作 1 本、3〜10 秒
// - 応答は k.mock で架空の曲に差し替える（x_catalog_flow.mjs と同じ）。曲名もサムネも架空
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
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

export default [
  {
    id: "o-same",
    what: "同じトラックをもう一度入れると「N 番にも同じトラックがあります」と知らせる（入れるのは止めない）",
    async setup(k) {
      const sq = square();
      await place(k, 3, 3, withHoles(sq, 9, [5, 6, 7, 8]));
      await k.arrange(FLOW); await k.stage(onlySubs());
      await searchFirst(k, "夜明けのシグナル", [sq[9], sq[0], sq[12]]);
      await k.look([RT, GT, "#results", "#grid", "#grid-msg"]);
      await k.park(640, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#results li:nth-child(2) .result");   // 1 番と同じ曲
      await k.hold(0.3);
      await k.look([GT, "#grid", "#grid-msg"], 0.5);
      await k.hold(2.0);
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
    what: "「トラック名を短くする」… 【東方Vocal】や「- Topic」のような部分をトラック名から外す。何件か確かめてから直し、あとで戻せる",
    async setup(k) {
      const sq = square().slice(0, 6);
      const junk = ["【東方Vocal】", " (Official Music Video)", "【MV】", " - Topic", " [Full ver.]", "〈オリジナル〉"];
      const cells = sq.map((t, i) => (i === 3 ? { ...t, artist: `${t.artist} - Topic` } : { ...t, title: i % 2 ? `${t.title}${junk[i]}` : `${junk[i]}${t.title}` }));
      await place(k, 3, 2, cells, { trimNames: false });
      await k.arrange({ ".pane-grid": { x: 340, y: 16, w: 600, only: ["#grid-scroll", "#grid-msg", ".grid-actions"] } });
      await k.stage(".grid-actions > :not(.grid-foot) { display: none !important; } #grid-scroll { height: auto !important; }");
      await k.look([GT, "#grid", "#grid-msg", "#trim-all-btn"]);
      await k.park(640, 650);
    },
    async run(k) {
      await k.hold(1.0);
      await k.press("#trim-all-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#confirm-modal").hidden), "確認の窓", 5000);
      await k.look(["#confirm-modal .modal-panel"], 0.5);
      await k.hold(1.2);
      await k.press("#confirm-yes");
      await k.look([GT, "#grid", "#grid-msg", "#trim-all-btn"], 0.5);
      await k.hold(2.0);
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
    what: "「並び」は 10 個まで持てる。「新しい並び」で空の並びを作り、メニューで切り替える",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9), { title: "私を構成する9曲" });
      await k.arrange({ ".pane-grid": { x: 330, y: 16, w: 620, only: [".layouts", "#grid-scroll", "#grid-msg"] } });
      await k.look([GT, ".layouts", "#grid"]);
      await k.park(900, 300);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#layout-new");
      await k.hold(0.8);
      await k.glide("#title", 0.3).catch(() => {});
      await k.page.evaluate(() => { const t = document.querySelector("#title"); t.value = "雨の日に聴く曲"; t.dispatchEvent(new Event("input", { bubbles: true })); });
      await k.hold(0.8);
      await popPick(k, "layout-sel", "私を構成する9曲");
      await k.waitArt();
      await k.hold(1.2);
      await popPick(k, "layout-sel", "雨の日に聴く曲");
      await k.hold(0.8);
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
    what: "「大きく見る」でグリッドを画面いっぱいに。細長い並びは横に送って見られ、窓の中でマスを選んで直せる",
    async setup(k) {
      await place(k, 12, 1, square().slice(0, 12), { title: "今月かなり聴いた曲" });
      k.wide(0);
      await k.park(900, 400);
    },
    async run(k) {
      await k.hold(0.6);
      await k.press("#zoom-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#zoom-modal").hidden), "大きく見る", 5000);
      await k.hold(0.8);
      for (let i = 0; i < 6; i++) { await k.page.evaluate(() => document.querySelector("#zoom-slot .grid-scroll, #zoom-slot").scrollBy({ left: 120 })); await k.hold(0.12); }
      await k.hold(0.5);
      await k.press("#zoom-slot .cell:nth-child(7)");
      await k.hold(1.4);
      await k.press("#zoom-modal-close");
      await k.hold(0.8);
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
      await k.arrange({ ".pane-options": { x: 440, y: 16, w: 400 } });
      await k.look([OT, ".pane-options .gbox:nth-of-type(1)"]);
      await k.park(900, 400);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#cells-more-btn");
      await k.hold(1.4);
      await k.press("#cells-more-btn");
      await k.hold(0.6);
      await k.look([OT, ".pane-options .opts"], 0.6);
      await k.hold(1.2);
      await k.look([OT, ".pane-options .gbox:nth-of-type(1)"], 0.6);
      await k.hold(0.6);
    },
  },
  {
    id: "o-json",
    what: "「並びを保存」でファイルに書き出し、「並びを読み込み…」で同じ並びに戻せる（共有は 30 日で消えるので、長く残したいとき）",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange(GRID_ONLY);
      await k.stage(".grid-actions > :not(.minor) { display: none !important; } #color-sort { display: none !important; }");
      await k.look([GT, "#grid", "#grid-msg", ".grid-actions"]);
      await k.park(640, 650);
    },
    async run(k) {
      await k.hold(0.8);
      const dl = k.page.waitForEvent("download");
      await k.press("#json-export");
      const file = path.join(os.tmpdir(), `x-json-${Date.now()}.json`);
      await (await dl).saveAs(file);
      await k.hold(0.8);
      // 並びを崩す（全部外す。確認の窓は撮らない）
      await k.page.evaluate(() => { window.__setGridUI(3, 3, {}, Array(9).fill(null)); });
      await k.hold(1.0);
      const fc = k.page.waitForEvent("filechooser");
      await k.press("#json-import");
      await (await fc).setFiles(file);
      await k.waitArt();
      await k.hold(1.6);
      fs.rmSync(file, { force: true });
    },
  },
  {
    id: "o-keys",
    what: "キーボードでも操作できる … Tab でグリッドへ、矢印でマスを移り、Return で選ぶ、Esc でやめる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
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
    what: "英語表示で探すと、iTunes の米国の表記でトラック名とアーティスト名が出る",
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
      await k.arrange(FLOW); await k.stage(onlySubs());
      await k.look([ST, "#search-form", RT, "#results"]);
      await k.park(640, 400);
    },
    async run(k) {
      await k.hold(0.6);
      await k.page.$eval("#lang-switch", (el) => el.click());   // 英語に（ボタンは並べ直した窓の外なので、押した所は映さない）
      await k.hold(0.8);
      await k.glide("#q", 0.3);
      await k.type("#q", "夜明け", 0.08);
      await k.press("#search-btn");
      await k.until(() => k.page.evaluate(() => /Dawn Signal/.test(document.querySelector("#results").textContent)), "英語の候補", 15000);
      await k.hold(2.0);
    },
  },
  {
    id: "o-sub",
    what: "検索の窓の補助の欄（URL から・一覧から・手入力）は 1 つ開くとほかが閉じる。ソースの「?」で説明が出る",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange({ ".pane-search": { x: 400, y: 16, w: 480 } });
      await k.look([ST, ".pane-search"]);
      await k.park(900, 400);
    },
    async run(k) {
      await k.hold(0.8);
      for (const sel of ["#sub-list", "#sub-manual", "#sub-bandcamp"]) { await k.press(`${sel} > .sub-title`); await k.hold(0.9); }
      await k.press("#src-hint-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#src-modal").hidden), "ソースについて", 5000);
      await k.hold(1.6);
      await k.press("#src-modal-close");
      await k.hold(0.8);
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
    what: "共有 URL から開くと、その並びが新しい並びとして入る（今の並びはそのまま残り、「並び」のメニューで戻れる）",
    async setup(k) {
      const sq = square();
      const doc = { title: "雨の日に聴く曲", cols: 3, rows: 2, cells: sq.slice(10, 16), stash: [],
        options: { ratio: "16:9", bg: "cerulean", showTitle: true, sidebar: true, numbers: true, gap: 16, margin: 16 } };
      await k.page.route(/\/shares\/fa4e0ab1c2d3\.json/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(doc) }));
      await place(k, 3, 3, sq.slice(0, 9));
      await k.hold(0.5);
      await k.page.evaluate(() => { try { localStorage.setItem("trackmento:x-dummy", "1"); } catch {} });
    },
    async run(k) {
      // 共有 URL を開く（手元のサーバーで。共有の中身は差し替え）
      await k.page.goto("http://127.0.0.1:8000/?share=fa4e0ab1c2d3", { waitUntil: "domcontentloaded" });
      for (let i = 0; i < 200 && !(await k.page.evaluate(() => !!window.__setGridUI)); i++) { await k.page.clock.runFor(50); await new Promise((r) => setTimeout(r, 50)); }
      await k.page.addStyleTag({ content: '#sources label:has(input[value="discogs"]) { display: none !important; }' });
      await k.arrange({ ".pane-grid": { x: 330, y: 16, w: 620, only: [".layouts", "#grid-scroll", "#grid-msg"] } });
      await k.stage("#grid-scroll { height: auto !important; }");
      await k.until(() => k.page.evaluate(() => /新しい並び/.test(document.querySelector("#grid-msg").textContent)), "共有の読み込み", 15000);
      await k.waitArt();
      await k.look([GT, ".layouts", "#grid", "#grid-msg"], 0);
      await k.park(900, 300);
      await k.hold(1.6);
      await popPick(k, "layout-sel", "私を構成する9曲");
      await k.waitArt();
      await k.hold(1.4);
    },
  },
];
