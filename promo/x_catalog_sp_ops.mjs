// Instagram・TikTok 向けの短い動画・スマホ版の台本（続き）。決まりは x_catalog_sp.mjs の頭と同じ。
// 元は 3 段目「並べる操作」（x_catalog_ops.mjs）。PC の画面で撮った場面を、スマホの画面（390×844、指）で撮り直す（2026-09-27）。
//
// - id は元の id に「-sp」。縦 9:16 に書き出すとスマホの枠ごと画面ぜんぶが映るので、k.look は使わず k.wide(0) だけ
// - 押すのは k.tap / k.tapAt、送るのは k.swipe（シートの中は "#sheet-body"）
// - スマホに同じ操作が無いもの（o-drag … マスを掴んで運ぶ、o-window … 窓を題名バーで動かす、o-keys … キーボード）は撮らない。
//   o-drag はスマホでは「2 つ押して入れ替え」になり o-swap-sp と同じ。窓の「—」で畳むのは o-tri-sp で見せる
// - 応答はすべて差し替え（元の台本と同じ）。曲名もサムネも架空
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import { nico } from "./x_catalog.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));

/** 並べる（空きマスは null） */
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
/** 要素を画面の上から y の所へ送る（撮る前） */
const scrollTo = (k, sel, y = 60) => k.page.evaluate(({ sel, y }) => window.scrollBy(0, document.querySelector(sel).getBoundingClientRect().top - y), { sel, y });
/** 撮り始めの構図（画面ぜんぶ）と指の置き場 */
async function frameIt(k, x = 300, y = 640) {
  await k.hold(0.2);
  k.wide(0);
  await k.park(x, y);
}
/** 要素が画面の上から y の所に来るまで指で送る（撮りながら） */
async function swipeTo(k, sel, y = 200, sec = 0.5, box = null) {
  const dy = await k.page.evaluate(({ sel, y }) => document.querySelector(sel).getBoundingClientRect().top - y, { sel, y });
  if (Math.abs(dy) > 4) await k.swipe(dy, sec, box);
}
const shown = (k, sel, label) => k.until(() => k.page.evaluate((sel) => !document.querySelector(sel).hidden, sel), label, 8000);
const gone = (k, sel, label) => k.until(() => k.page.evaluate((sel) => document.querySelector(sel).hidden, sel), label, 8000);
const sheetShown = (k) => shown(k, "#sheet", "シートが開く");
const sheetGone = (k) => gone(k, "#sheet", "シートが閉じる");
const resultsAtLeast = (k, n) => k.until(() => k.page.evaluate((n) => document.querySelectorAll("#results .result").length >= n, n), "候補", 15000);
/** シートの中を、sel の頭が上から y の所に来るまで送る */
const sheetTo = (k, sel, y = 170, sec = 0.4) => swipeTo(k, sel, y, sec, "#sheet-body");
/** シートの中で補助の欄（URL から・トラック名の一覧から・手入力）を開く（開いていれば何もしない） */
async function tapSub(k, sel) {
  if (await k.page.getAttribute(`${sel} > .sub-title`, "aria-expanded") !== "true") await k.tap(`${sel} > .sub-title`);
  await k.hold(0.3);
}
/** ポップアップメニュー（スマホでは画面いっぱいの一覧）で項目を選ぶ。sel は select の id */
async function popPick(k, sel, text) {
  await k.tap(`.popup:has(#${sel}) .popup-hit`);
  await shown(k, "#popmenu", "メニュー");
  await k.hold(0.6);
  // k.tap は画面の中の querySelectorAll で位置を測るので、Playwright だけの :text-is は使えない。何番目かを数えて押す
  const n = await k.page.evaluate((t) => [...document.querySelectorAll("#popmenu-list > li")].findIndex((li) => li.textContent.trim() === t) + 1, text);
  if (!n) throw new Error(`メニューに無い: ${text}`);
  await k.tap(`#popmenu-list > li:nth-child(${n})`);
}
/** 撮る前に検索して候補を並べておく（シートは閉じたまま）。題は検索語＋付け足し（元の searchFirst と同じ） */
async function searchFirst(k, q, list) {
  const tails = ["", " (Live)", " - Remix", " (Acoustic)"];
  const rows = list.map((t, i) => ({ ...t, source: "itunes", title: t.title.includes(q) ? t.title : `${q}${tails[i % tails.length] || " (ver." + i + ")"}` }));
  await k.mock({ itunes: () => rows });
  await k.page.evaluate((q) => { document.querySelector("#q").value = q; document.querySelector("#search-btn").click(); }, q);
  await resultsAtLeast(k, 3);
}

/** **撮影用の擬似の保存・ファイル選択**（スマホ版。ヘッドレスでは本物が出ないので、撮影のときだけページの上に描く）。
    Android の Chrome の「ダウンロードしました」の帯と、ファイルを選ぶ画面に寄せた素朴なもの（サイトの OS 9 の部品と混ざらないよう角丸・灰色） */
const FAKE_PHONE_CSS = `
.x-fk, .x-fk * { box-sizing: border-box; font: 14px/1.4 "Roboto", "Noto Sans JP", "Yu Gothic UI", sans-serif; color: #1f1f1f; }
.x-bar { position: fixed; left: 10px; right: 10px; bottom: 16px; z-index: 2147483000; display: flex; align-items: center; gap: 12px; padding: 14px 16px;
  background: #fff; border-radius: 14px; box-shadow: 0 4px 18px rgba(0,0,0,.28); }
.x-bar .ic { width: 28px; height: 28px; border-radius: 50%; background: #1a73e8; flex: none; position: relative; }
.x-bar .ic::after { content: ""; position: absolute; left: 9px; top: 7px; width: 8px; height: 11px; border: solid #fff; border-width: 0 3px 3px 0; transform: rotate(45deg); }
.x-bar .tx { flex: 1; min-width: 0; } .x-bar .tx b { display: block; font-weight: 500; } .x-bar .tx i { font-style: normal; color: #666; font-size: 12px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.x-bar .op { color: #1a73e8; font-weight: 500; }
.x-pick { position: fixed; inset: 0; z-index: 2147483000; background: #f6f7fb; display: flex; flex-direction: column; }
.x-pick .hd { display: flex; align-items: center; gap: 18px; padding: 18px 18px 10px; font-size: 20px; }
.x-pick .hd s { text-decoration: none; font-size: 22px; color: #444; }
.x-pick .sub { padding: 0 18px 12px; color: #555; font-size: 13px; }
.x-pick .chips { display: flex; gap: 8px; padding: 0 18px 14px; }
.x-pick .chips span { padding: 6px 12px; border: 1px solid #c4c7c5; border-radius: 8px; font-size: 13px; }
.x-pick .chips .on { background: #d3e3fd; border-color: #d3e3fd; }
.x-pick .ls { background: #fff; margin: 0 12px; border-radius: 16px; overflow: hidden; }
.x-pick .f { display: flex; align-items: center; gap: 14px; padding: 12px 16px; border-bottom: 1px solid #eee; }
.x-pick .f::before { content: ""; width: 34px; height: 34px; border-radius: 8px; flex: none; background: #e8eaed url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M7 3h7l4 4v14H7z' fill='%23fff' stroke='%235f6368' stroke-width='1.5' stroke-linejoin='round'/%3E%3Cpath d='M14 3v4h4' fill='none' stroke='%235f6368' stroke-width='1.5'/%3E%3C/svg%3E") center/22px no-repeat; }
.x-pick .f.folder::before { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M3 6h6l2 2h10v11H3z' fill='%23a8c7fa'/%3E%3C/svg%3E"); }
.x-pick .f div { min-width: 0; } .x-pick .f b { display: block; font-weight: 400; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .x-pick .f i { font-style: normal; color: #777; font-size: 12px; }
.x-pick .f.sel { background: #d3e3fd; }
`;
/** 「ダウンロードしました」の帯を出す */
const fakeSaved = (k, name) => k.page.evaluate((name) => {
  const d = document.createElement("div"); d.className = "x-fk x-bar"; d.id = "x-fk";
  d.innerHTML = `<span class="ic"></span><span class="tx"><b>ダウンロードしました</b><i>${name}</i></span><span class="op">開く</span>`;
  document.body.append(d);
}, name);
/** ファイルを選ぶ画面を出す。files は [名前, 添え書き]（名前が / で終わるとフォルダ） */
const fakePicker = (k, files) => k.page.evaluate((files) => {
  const d = document.createElement("div"); d.className = "x-fk x-pick"; d.id = "x-fk";
  d.innerHTML = `<div class="hd"><s>☰</s>ダウンロード</div><div class="sub">ファイルを選択</div>
    <div class="chips"><span class="on">すべて</span><span>画像</span><span>動画</span><span>ドキュメント</span></div>
    <div class="ls">${files.map(([f, sub]) => `<div class="f ${f.endsWith("/") ? "folder" : ""}" data-name="${f}"><div><b>${f.replace(/\/$/, "")}</b><i>${sub}</i></div></div>`).join("")}</div>`;
  document.body.append(d);
}, files);
const closeFake = (k) => k.page.evaluate(() => document.querySelector("#x-fk")?.remove());

export default [
  {
    id: "o-same-sp",
    phone: true,
    what: "同じトラックをもう一度入れると「N 番にも同じトラックがあります」と知らせる（入れるのは止めない）",
    async setup(k) {
      const sq = square();
      await place(k, 3, 3, withHoles(sq, 9, [5, 6, 7, 8]));
      await searchFirst(k, "夜明けのシグナル", [sq[0], sq[9], sq[12]]);   // 先頭は 1 番と同じ曲
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.3);
      await sheetTo(k, ".pane-results", 150);
      await k.hold(0.8);
      await k.tap("#results li:nth-child(1) .result");
      await sheetGone(k);
      await k.until(() => k.page.evaluate(() => /同じトラック/.test(document.querySelector("#grid-msg").textContent)), "同じトラックの知らせ", 5000);
      await k.waitArt();
      await k.hold(3.0);
    },
  },
  {
    id: "o-swap-sp",
    phone: true,
    what: "マスを押して選び、別のマスを押すと入れ替わる。空きマスを押せばそこへ移る。もう一度押すと選ぶのをやめる",
    async setup(k) {
      await place(k, 3, 3, withHoles(square(), 9, [8]));
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#grid .cell:nth-child(1)"); await k.hold(0.7);
      await k.tap("#grid .cell:nth-child(5)"); await k.hold(1.1);   // 入れ替え
      await k.tap("#grid .cell:nth-child(3)"); await k.hold(0.7);
      await k.tap("#grid .cell:nth-child(9)"); await k.hold(1.1);   // 空きマスへ移す
      await k.tap("#grid .cell:nth-child(2)"); await k.hold(0.7);
      await k.tap("#grid .cell:nth-child(2)"); await k.hold(1.0);   // もう一度押して解除
    },
  },
  {
    id: "o-target-sp",
    phone: true,
    what: "空きマスを押すと、そのマスに入れるトラックを探すシートが開く。押した候補がそのマスに入る",
    async setup(k) {
      const sq = square();
      await place(k, 3, 3, withHoles(sq, 9, [4, 7]));
      await searchFirst(k, "ソーダ水の惑星", [sq[15], sq[16], sq[17]]);
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#grid .cell:nth-child(5)");
      await sheetShown(k);
      await k.hold(0.5);
      await sheetTo(k, ".pane-results", 150);
      await k.hold(0.6);
      await k.tap("#results li:nth-child(2) .result");
      await sheetGone(k);
      await k.waitArt();
      await k.hold(1.2);
      await k.tap("#grid .cell:nth-child(8)");
      await sheetShown(k);
      await k.hold(0.4);
      await sheetTo(k, ".pane-results", 150);
      await k.hold(0.5);
      await k.tap("#results li:nth-child(1) .result");
      await sheetGone(k);
      await k.waitArt();
      await k.hold(1.4);
    },
  },
  {
    id: "o-remove-sp",
    phone: true,
    what: "マスの × で外せる。外したあとのメッセージの「元に戻す」で戻る",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(1.0);
      await k.tap("#grid .cell:nth-child(5) .rm");
      await k.hold(1.6);
      await k.tap("#grid-msg .undo");
      await k.waitArt();
      await k.hold(1.8);
    },
  },
  {
    id: "o-clear-sp",
    phone: true,
    what: "「トラックを全て外す」は確認の窓を出す（既定は「やめる」）。外したあとも「元に戻す」で戻せる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      // 「できあがり」の窓を畳んでおく（グリッドとボタンを 1 画面に入れる）
      await k.page.click("#output > .pane-title .fold");
      await k.hold(0.3);
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#clear-btn");
      await shown(k, "#confirm-modal", "確認の窓");
      await k.hold(1.3);
      await k.tap("#confirm-yes");
      await k.hold(1.0);
      await k.tap("#grid-msg .undo");
      await k.waitArt();
      await k.hold(1.4);
    },
  },
  {
    id: "o-trim-sp",
    phone: true,
    what: "「トラック名を短くする」… 【東方Vocal】や「- Topic」のような部分をトラック名から外す（マスの下の名前も、書き出しの曲名リストもすっきりする）",
    async setup(k) {
      // 2×2 にする（3 列だとマスの下の名前が数文字で切れ、外す前と後の違いが見えない）。
      // 書き出しの見本（できあがり）はスマホの幅では曲名リストの字が読めないので映さない
      const sq = square().slice(0, 4);
      const cells = [{ ...sq[0], title: `【東方Vocal】${sq[0].title}` }, { ...sq[1], title: `${sq[1].title} (Official Music Video)` },
                     { ...sq[2], artist: `${sq[2].artist} - Topic` }, { ...sq[3], title: `【MV】${sq[3].title}` }];
      await place(k, 2, 2, cells, { trimNames: false });
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(1.6);
      await k.tap("#trim-all-btn");
      await shown(k, "#confirm-modal", "確認の窓");
      await k.hold(1.2);
      await k.tap("#confirm-yes");
      await k.hold(2.6);
    },
  },
  {
    id: "o-editor-sp",
    phone: true,
    what: "マスを押すと、グリッドのすぐ下の欄でトラック名・アーティスト名を直せる。メモは共有ページのトラックリストに出る",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#grid .cell:nth-child(5)");
      await shown(k, "#editor", "編集欄");
      await k.hold(0.6);
      await k.tap("#e-title");
      await k.page.fill("#e-title", "");
      await k.type("#e-title", "迷子の自販機 (2026 Remix)", 0.05);
      await k.hold(0.4);
      await k.tap("#e-note");
      await k.type("#e-note", "駅前の自販機の前でずっと聴いてた", 0.05);
      await k.hold(1.0);
      await swipeTo(k, "#e-close", 700, 0.5);
      await k.tap("#e-close");
      await k.hold(0.3);
      await swipeTo(k, "#grid-scroll", 60, 0.5);
      await k.hold(1.0);
    },
  },
  {
    id: "o-origin-sp",
    phone: true,
    what: "動画サイトの曲は、アーティスト名がチャンネル名のことがある。マスを押して「元の投稿を探す」で、otoDB やニコニコ動画の古い投稿から作者を探して選べる",
    async setup(k) {
      const wide = nico();
      const cells = wide.slice(0, 9).map((t, i) => ({ ...t, source: i === 0 ? "youtube" : "nicovideo", artist: i === 0 ? "音MAD まとめチャンネル" : t.artist, external_url: `https://www.youtube.com/watch?v=Ab${i}` }));
      await place(k, 3, 3, cells, { cellRatio: "16:9" });
      await k.page.route(/\/artist-candidates\?/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        otodb: { artist: "こはく", work: "#1234", posts: [{ id: "sm12345678", at: "2014-05-03" }] },
        candidates: [{ artist: "こはく", id: "sm12345678", at: "2014-05-03T21:00:00" }, { artist: "ユウグレ", id: "sm20123456", at: "2016-11-20T12:00:00" }] }) }));
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#grid .cell:nth-child(1)");
      await shown(k, "#editor", "編集欄");
      await k.hold(0.5);
      await swipeTo(k, "#editor", 120, 0.6);
      await k.hold(0.4);
      await k.tap("#e-origin-find");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#e-origin-seg button").length >= 2), "候補", 10000);
      await k.hold(1.2);
      await k.tap("#e-origin-seg button:first-of-type");
      await k.hold(1.4);
      await swipeTo(k, "#e-close", 700, 0.5);
      await k.tap("#e-close");
      await k.hold(0.3);
      await swipeTo(k, "#grid-scroll", 60, 0.5);
      await k.hold(1.0);
    },
  },
  {
    id: "o-theme-sp",
    phone: true,
    what: "「お題」から選ぶとタイトルが入る。「私を構成する9曲」なら横 × 縦も 3 × 3 に",
    async setup(k) {
      await place(k, 4, 4, withHoles(square(), 16, [9, 10, 11, 12, 13, 14, 15]), { title: "" });
      await frameIt(k, 300, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await popPick(k, "theme-sel", "好きな音MAD");
      await k.hold(1.2);
      await popPick(k, "theme-sel", "私を構成する9曲");
      await k.waitArt();
      await k.hold(1.8);
    },
  },
  {
    id: "o-layouts-sp",
    phone: true,
    what: "「並び」は 10 個まで持てる。「新しい並び」で別の並びを作り、メニューで切り替える",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9), { title: "私を構成する9曲" });
      await frameIt(k, 300, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#layout-new");
      await k.hold(0.6);
      // 2 つ目の並びにも曲を入れる（入れる操作はほかの動画で見せているので一度に入れる。元の台本と同じ）
      const sq = square();
      await k.page.evaluate((cells) => { window.__setGridUI(3, 3, { title: "雨の日に聴く曲", bg: "cerulean" }, cells); document.querySelector("#title").value = "雨の日に聴く曲"; document.querySelector("#title").dispatchEvent(new Event("input", { bubbles: true })); window.scrollTo(0, 0); }, sq.slice(9, 18));
      await k.waitArt();
      await k.hold(1.2);
      await popPick(k, "layout-sel", "私を構成する9曲");
      await k.waitArt();
      await k.hold(1.2);
      await popPick(k, "layout-sel", "雨の日に聴く曲");
      await k.waitArt();
      await k.hold(1.2);
      await k.tap("#layout-del");
      await shown(k, "#confirm-modal", "確認の窓");
      await k.hold(0.8);
      await k.tap("#confirm-yes");
      await k.waitArt();
      await k.hold(1.2);
    },
  },
  {
    id: "o-zoom-sp",
    phone: true,
    what: "「大きく見る」でグリッドを画面いっぱいに。2 本指で広げるとマスが大きくなり、指で送って見られる。中でもマスを 2 つ押せば入れ替わる",
    async setup(k) {
      await place(k, 8, 8, Array.from({ length: 64 }, (_, i) => square()[i % 24]), { title: "今月かなり聴いた曲" });
      await frameIt(k, 300, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#zoom-btn");
      await shown(k, "#zoom-modal", "大きく見る");
      await k.hold(0.8);
      // 中でも 2 つ押して入れ替えられる
      await k.tap("#grid .cell:nth-child(1)"); await k.hold(0.5);
      await k.tap("#grid .cell:nth-child(19)"); await k.hold(1.0);
      // 2 本指で広げる（マスが大きくなる）
      const r = await k.page.evaluate(() => { const b = document.querySelector("#grid-scroll").getBoundingClientRect(); return { x: b.x + b.width / 2, y: b.y + b.height / 2 }; });
      await k.pinch(r.x, r.y, 80, 260, 0.9, [1, 1]);
      await k.hold(0.6);
      await k.swipe(360, 1.0, "#grid-scroll");   // 指で送って見る
      await k.hold(0.6);
      await k.pinch(r.x, r.y, 260, 80, 0.8, [1, 1]);
      await k.hold(0.8);
      await k.tap("#zoom-modal-close");
      await k.hold(0.8);
    },
  },
  {
    id: "o-grid-size-sp",
    phone: true,
    what: "横 × 縦は出力オプションの「グリッド」の上下の小さな矢印で増やせる。マスは全部で 256 まで",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      if (await k.page.evaluate(() => document.querySelector(".pane-options").dataset.collapsed === "true")) await k.page.click(".pane-options > .pane-title .fold");
      await k.hold(0.3);
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(0.8);
      await swipeTo(k, ".pane-options", 300, 1.0);
      await k.hold(0.4);
      const up = (id) => `#${id} ~ .stepper button[data-step='1']`;
      for (let i = 0; i < 3; i++) { await k.tap(up("cols"), { sec: i ? 0.15 : 0.4 }); await k.hold(0.3); }
      for (let i = 0; i < 2; i++) { await k.tap(up("rows"), { sec: i ? 0.15 : 0.4 }); await k.hold(0.3); }
      await k.hold(0.5);
      await swipeTo(k, "#grid-scroll", 60, 1.0);   // 上に戻ってグリッドを見る
      await k.waitArt();
      await k.hold(2.0);
    },
  },
  {
    id: "o-tri-sp",
    phone: true,
    what: "スマホでは出力オプションの窓が畳まれている。右上の「—」で開くと「マス」「文字」「背景と余白」のまとまりに分かれていて、枠の形は「枠とサムネ」の三角で開け閉めできる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await scrollTo(k, ".pane-options", 300);
      await frameIt(k, 300, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap(".pane-options > .pane-title .fold");
      await k.hold(0.3);
      await swipeTo(k, ".pane-options", 60, 0.6);
      await k.hold(1.0);
      await k.tap("#cells-more-btn");
      await k.hold(1.4);
      await k.tap("#cells-more-btn");
      await k.hold(0.6);
      await k.swipe(420, 1.0);   // 下の「文字」「背景と余白」へ
      await k.hold(1.2);
    },
  },
  {
    id: "o-json-sp",
    phone: true,
    what: "「並びを保存」でファイルに書き出し、「並びを読み込み…」で同じ並びに戻せる（共有は 30 日で消えるので、長く残したいとき）",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.stage(FAKE_PHONE_CSS);
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      const name = "trackmento-私を構成する9曲.json";
      await k.hold(0.8);
      // 保存: 本物の保存は裏で済ませ、画面には擬似の「ダウンロードしました」を出す
      const dl = k.page.waitForEvent("download");
      await k.tap("#json-export");
      const file = path.join(os.tmpdir(), `x-json-sp-${Date.now()}.json`);
      await (await dl).saveAs(file);
      await fakeSaved(k, name);
      await k.hold(1.6);
      await closeFake(k);
      // 並びを崩す（トラックを全部外す。確認の窓は撮らない）
      await k.page.evaluate(() => { window.__setGridUI(3, 3, {}, Array(9).fill(null)); });
      await k.hold(1.0);
      // 読み込み: 擬似のファイルを選ぶ画面でさっきのファイルを選ぶ
      const fc = k.page.waitForEvent("filechooser");
      await k.tap("#json-import");
      const chooser = await fc;
      await fakePicker(k, [[name, "4.2 kB · 今"], ["trackmento-雨の日に聴く曲.json", "3.9 kB · 9月20日"], ["trackmento-好きな音MAD.json", "5.1 kB · 9月12日"], ["Music/", "フォルダ"]]);
      await k.hold(0.8);
      await k.tap(`#x-fk [data-name="${name}"]`);
      await k.page.evaluate((n) => document.querySelector(`#x-fk [data-name="${n}"]`).classList.add("sel"), name);
      await k.hold(0.3);
      await closeFake(k);
      await chooser.setFiles(file);
      await k.waitArt();
      await k.hold(1.8);
      fs.rmSync(file, { force: true });
    },
  },
  {
    id: "o-lang-us-sp",
    phone: true,
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
      await frameIt(k, 300, 300);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#lang-switch");
      await k.hold(1.4);
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.4);
      await k.tap("#q");
      await k.type("#q", "夜明け", 0.08);
      await k.tap("#search-btn");
      await k.until(() => k.page.evaluate(() => /Dawn Signal/.test(document.querySelector("#results").textContent)), "英語の候補", 15000);
      await k.hold(0.3);
      await sheetTo(k, ".pane-results", 150);
      await k.hold(1.8);
      await k.tap("#sheet-close");
      await sheetGone(k);
      await k.hold(0.3);
      await k.tap("#lang-switch");   // 日本語に戻して終わる
      await k.hold(1.0);
    },
  },
  {
    id: "o-sub-sp",
    phone: true,
    what: "「トラックを探す」のシートには、検索のほかに 3 つの入れ方がある … 「URL から」「トラック名の一覧から」「手入力」。見出しを押すと切り替わる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      // それぞれ開いて、何を入れる欄かが分かるように少し打つ（元の台本と同じ）
      await k.hold(0.6);
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.3);
      await tapSub(k, "#sub-bandcamp");
      await sheetTo(k, "#sub-bandcamp", 170);
      await k.tap("#bc-url"); await k.type("#bc-url", "https://www.nicovideo.jp/watch/sm45012345", 0.025);
      await k.hold(0.8);
      await tapSub(k, "#sub-list");
      await sheetTo(k, "#sub-list", 170);
      const a = '#list-rows input[data-row="0"][data-key="artist"]', t = '#list-rows input[data-row="0"][data-key="title"]';
      await k.tap(a); await k.type(a, "ミナトリ", 0.06);
      await k.tap(t); await k.type(t, "夜明けのシグナル", 0.06);
      await k.hold(0.8);
      await tapSub(k, "#sub-manual");
      await sheetTo(k, "#sub-manual", 170);
      await k.tap("#m-title"); await k.type("#m-title", "文化祭で弾いた曲", 0.06);
      await k.hold(1.0);
      await k.tap("#sheet-close");
      await sheetGone(k);
      await k.hold(0.8);
    },
  },
  {
    id: "o-spotify-sp",
    phone: true,
    what: "Spotify の URL はアーティスト名が取れないので、iTunes で同じトラック名から補う。何人かいるときは選べる",
    async setup(k) {
      const sq = square();
      await k.mock({
        url: () => ({ source: "spotify", title: "Paper Rocket", artist: "", album: null, image: sq[8].image, thumb: sq[8].thumb, external_url: "https://open.spotify.com/track/abc" }),
        itunes: () => [{ ...sq[8], source: "itunes" }, { ...sq[8], artist: "Tsubame & Kuro", source: "itunes" }, { ...sq[8], artist: "Paper Planes", source: "itunes" }],
      });
      await place(k, 3, 3, Array(9).fill(null));
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.3);
      await tapSub(k, "#sub-bandcamp");
      await sheetTo(k, "#sub-bandcamp", 170);
      await k.tap("#bc-url");
      await k.type("#bc-url", "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC", 0.03);
      await k.tap("#bc-btn");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#bc-msg .pick").length >= 2), "アーティスト名の候補", 20000);
      await k.hold(1.4);
      await k.tap("#bc-msg .pick:first-of-type");
      await k.hold(1.2);
      await sheetTo(k, ".pane-results", 150);
      await k.hold(0.8);
      await k.tap("#results li:nth-child(1) .result");
      await sheetGone(k);
      await k.waitArt();
      await k.hold(1.4);
    },
  },
  {
    id: "o-revive-sp",
    phone: true,
    what: "削除されたニコニコ動画でも、otoDB に登録があれば題とサムネイルを取れる（マイリストの中の消えた動画も補う）",
    async setup(k) {
      const wide = nico();
      await k.mock({ url: () => ({ ...wide[5], source: "otodb", title: "【音MAD】ねむりの電波塔", artist: "ねむり工房", external_url: "https://www.nicovideo.jp/watch/sm9876543" }) });
      await place(k, 3, 3, Array(9).fill(null), { cellRatio: "16:9" });
      await scrollTo(k, "#grid-scroll", 60);
      await frameIt(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.3);
      await tapSub(k, "#sub-bandcamp");
      await sheetTo(k, "#sub-bandcamp", 170);
      await k.tap("#bc-url");
      await k.type("#bc-url", "sm9876543", 0.08);
      await k.tap("#bc-btn");
      await resultsAtLeast(k, 1);
      await k.hold(0.4);
      await sheetTo(k, ".pane-results", 150);
      await k.hold(1.0);
      await k.tap("#results li:nth-child(1) .result");
      await sheetGone(k);
      await k.waitArt();
      await k.hold(1.6);
    },
  },
  {
    id: "o-share-open-sp",
    phone: true,
    what: "共有ページの「TRACKMENTO で開く」を押すと、その並びが新しい並びとして入る（今の並びはそのまま残り、「並び」のメニューで戻れる）",
    async setup(k) {
      const sq = square();
      const doc = { id: "fa4e0ab1c2d3", title: "雨の日に聴く曲", cols: 3, rows: 2, cells: sq.slice(10, 16), stash: [], createdAt: "2026-09-26T10:00:00Z",
        options: { ratio: "16:9", bg: "cerulean", showTitle: true, sidebar: true, numbers: true, gap: 16, margin: 16 } };
      // 架空の共有ページと共有画像（promo/fake_share_page.py。本番の R2 には何も置かない）
      const dir = path.join(os.tmpdir(), "x-share-open-sp"), docFile = path.join(dir, "doc.json");
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
      // スマホでは画面ぜんぶが映るので、下の「この URL: …」の文に手元のサーバーの宛先が見える。文字だけ本番の宛先に替える（リンクはそのまま）
      await k.page.evaluate(() => {
        const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let n; (n = w.nextNode());) if (n.nodeValue.includes("127.0.0.1:8000")) n.nodeValue = n.nodeValue.replaceAll("http://127.0.0.1:8000", "https://trackmento.com");
      });
      await frameIt(k, 300, 600);
    },
    async run(k) {
      await k.hold(1.8);
      await k.tap('.btns a[href*="?share="]');
      await k.page.waitForURL(/127\.0\.0\.1:8000\/(\?|$)/, { timeout: 20000 });
      for (let i = 0; i < 200 && !(await k.page.evaluate(() => !!window.__setGridUI)); i++) { await k.page.clock.runFor(50); await new Promise((r) => setTimeout(r, 50)); }
      await k.page.addStyleTag({ content: '#sources label:has(input[value="discogs"]) { display: none !important; }' });
      await k.until(() => k.page.evaluate(() => /新しい並び/.test(document.querySelector("#grid-msg").textContent)), "共有の読み込み", 15000);
      await k.waitArt();
      await k.page.evaluate(() => window.scrollTo(0, 0));
      await k.hold(2.0);
      await popPick(k, "layout-sel", "私を構成する9曲");
      await k.waitArt();
      await k.hold(1.6);
    },
  },
];
