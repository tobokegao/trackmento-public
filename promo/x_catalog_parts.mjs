// X に載せる短い動画の台本・5 段目「見た目の細部と小さな気配り」（2026-09-26）。決まりは x_catalog.mjs の頭と同じ。
// 1 つずつでは伝わりにくい細部を、数個ずつまとめて 1 本にする（台帳の「まとめる粒」）
import fs from "node:fs";
import { ready, GT, OT } from "./x_catalog.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));
const ST = ".pane-search > .pane-title", RT = ".pane-results > .pane-title";

async function place(k, cols, rows, cells, opts = {}) {
  await k.page.evaluate(({ cols, rows, cells, opts }) => {
    window.__setGridUI(cols, rows, { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true, margin: 16, gap: 16, bg: "mustard", bgCustom: null, ...opts }, cells);
    document.querySelector("#title").value = opts.title ?? "私を構成する9曲";
    window.scrollTo(0, 0);
  }, { cols, rows, cells, opts });
  await k.hold(0.3);
  await k.waitArt();
}

export default [
  {
    id: "p-os9",
    what: "見た目は Mac OS 9 風 … 縞の題名バー、ドット絵のラジオボタン、グループボックス、ポップアップメニュー、注意の絵の確認窓",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      k.wide(0);
      await k.park(1100, 300);
    },
    async run(k) {
      await k.hold(0.5);
      await k.look([".pane-grid > .pane-title"], 0.7); await k.hold(0.9);           // 縞の題名バー
      await k.look(["#bg-mode-seg"], 0.7); await k.hold(0.9);                        // ラジオボタン
      await k.look([OT, ".pane-options .gbox:nth-of-type(1)"], 0.7); await k.hold(0.8);   // グループボックス
      await k.look([".themes", "#grid-scroll"], 0.6);
      await k.press(".popup:has(#theme-sel) .popup-hit");                             // ポップアップメニュー
      await k.until(() => k.page.evaluate(() => !document.querySelector("#popmenu").hidden), "メニュー", 5000);
      await k.look([".popmenu-panel"], 0.5); await k.hold(1.0);
      await k.key("Escape");
      await k.page.evaluate(() => document.querySelector("#clear-btn").scrollIntoView({ block: "center" }));
      await k.press("#clear-btn");                                                     // 注意の絵の確認窓
      await k.until(() => k.page.evaluate(() => !document.querySelector("#confirm-modal").hidden), "確認の窓", 5000);
      await k.look(["#confirm-modal .modal-panel"], 0.5); await k.hold(1.2);
      await k.press("#confirm-no");
      await k.page.evaluate(() => window.scrollTo(0, 0));
      k.wide(0.6);
      await k.hold(0.6);
    },
  },
  {
    id: "p-counts",
    what: "小さな数の表示 … 候補の数、出どころの札、グリッドの「n/9」、出力サイズとマスの大きさ",
    async setup(k) {
      const sq = square();
      await k.mock({ itunes: () => [sq[3], sq[8], sq[14]].map((t, i) => ({ ...t, source: "itunes", title: `ソーダ水の惑星${["", " (Live)", " - Remix"][i]}` })) });
      await place(k, 3, 3, Array.from({ length: 9 }, (_, i) => (i < 5 ? sq[i] : null)));
      await k.page.fill("#q", "ソーダ水の惑星");
      await k.page.click("#search-btn");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#results .result").length >= 3), "候補", 15000);
      await k.arrange({ ".pane-results": { x: 40, y: 40, w: 380 }, ".pane-grid": { x: 450, y: 40, w: 400, only: ["#grid-scroll"] },
                        ".pane-options": { x: 880, y: 40, w: 360, only: [".spec"] } });
      await k.stage("#grid-scroll { height: auto !important; }");
      await k.look([RT, "#results", GT, "#grid", OT, ".pane-options .spec"]);
      await k.park(640, 600);
    },
    async run(k) {
      await k.hold(0.6);
      await k.look([RT], 0.5); await k.hold(0.8);                                      // 候補の数
      await k.look(["#results li:nth-child(1) .badge", "#results li:nth-child(2) .badge"], 0.5); await k.hold(0.8);   // 出どころの札
      await k.look([GT], 0.5); await k.hold(0.5);                                      // グリッドの n/9
      await k.press("#results li:nth-child(1) .result");
      await k.hold(0.9);
      await k.look([OT, ".pane-options .spec"], 0.5); await k.hold(1.2);               // 出力サイズ・マスの大きさ
      await k.look([RT, "#results", GT, "#grid", OT, ".pane-options .spec"], 0.6);
      await k.hold(0.6);
    },
  },
  {
    id: "p-small",
    what: "マスが小さくなると、× と番号とトラック名の帯を隠してサムネイルを見せる（押せば編集の欄で直せる）",
    async setup(k) {
      await place(k, 3, 3, Array.from({ length: 9 }, (_, i) => square()[i]));
      await k.arrange({ ".pane-grid": { x: 60, y: 30, w: 560, only: ["#grid-scroll"] }, ".pane-options": { x: 660, y: 30, w: 330, only: [".gbox:has(#cols)"] } });
      await k.stage(".gbox:has(#cols) > :not(.gbox-title):not(fieldset:has(#cols)) { display: none !important; } #grid-scroll { height: auto !important; max-height: 600px !important; }");
      await k.look([GT, "#grid", OT, "#cols"]);
      await k.park(900, 400);
    },
    async run(k) {
      await k.hold(0.8);
      for (const [c, r] of [[5, 5], [10, 10]]) {   // 10×10 で × と番号も隠れる（幅 64px 未満）
        await k.page.evaluate(({ c, r, t }) => window.__setGridUI(c, r, {}, Array.from({ length: c * r }, (_, i) => t[i % t.length])), { c, r, t: square() });
        await k.waitArt();
        await k.look([GT, "#grid", OT, "#cols"], 0.4);
        await k.hold(1.3);
      }
      await k.page.evaluate(({ t }) => window.__setGridUI(3, 3, {}, t.slice(0, 9)), { t: square() });
      await k.waitArt();
      await k.hold(1.0);
    },
  },
  {
    id: "p-logo",
    what: "ロゴの TRACKMENTO はピクセルの字で、下にリソ印刷の 6 色の帯",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      k.wide(0);
      await k.hideCursor();
    },
    async run(k) {
      await k.hold(0.6);
      await k.look([".wordmark"], 1.4);
      await k.hold(2.0);
      k.wide(1.0);
      await k.hold(0.6);
    },
  },
  {
    id: "p-care",
    what: "マスは合計 256 まで。横 × 縦を大きくしすぎると、自動で縮めて知らせる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.arrange({ ".pane-grid": { x: 60, y: 30, w: 560, only: ["#grid-scroll", "#grid-msg"] }, ".pane-options": { x: 660, y: 30, w: 330, only: [".gbox:has(#cols)"] } });
      await k.stage(".gbox:has(#cols) > :not(.gbox-title):not(fieldset:has(#cols)) { display: none !important; } #grid-scroll { height: auto !important; max-height: 560px !important; } #grid-msg { font-size: 14px !important; }");
      await k.look([GT, "#grid", "#grid-msg", OT, "#cols", "#rows"]);
      await k.park(900, 400);
    },
    async run(k) {
      await k.hold(0.6);
      await k.press("#cols");
      await k.page.fill("#cols", "");
      await k.type("#cols", "20", 0.15);
      await k.key("Tab");
      await k.hold(0.5);
      await k.page.fill("#rows", "");
      await k.type("#rows", "20", 0.15);
      await k.key("Tab");
      await k.until(() => k.page.evaluate(() => /合計 256/.test(document.querySelector("#grid-msg").textContent)), "256 の知らせ", 10000);
      await k.look(["#grid-msg", OT, "#cols", "#rows"], 0.5);
      await k.hold(2.0);
      await k.page.evaluate(({ t }) => window.__setGridUI(3, 3, {}, t.slice(0, 9)), { t: square() });
      await k.look([GT, "#grid", "#grid-msg", OT, "#cols", "#rows"], 0.5);
      await k.hold(0.8);
    },
  },
];
