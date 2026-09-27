// Instagram・TikTok に載せる短い動画の台本・スマホ版（2026-09-27）。決まりは x_catalog.mjs の頭と同じ。
// 投稿先を X から Instagram と TikTok に変え、**見る人をスマホで使う人に絞った**（利用者の判断）。
// PC の画面で撮った場面を、スマホの画面（390×844、指）で撮り直す。
//
// - id は元の場面の id に「-sp」を付ける（PC 版の素材は /howto の動画に使っているので上書きしない）。
//   縦の動画の見出しは元の id の問いを使う（x_titles.py）
// - 縦 9:16 に書き出すと、スマホの枠ごと画面ぜんぶが映る（利用者の選択。寄らない）。**k.look は使わず k.wide(0) だけ**
// - 押すのは k.tap、送るのは k.swipe（シートの中は第 3 引数に "#sheet-body"）
// - スマホでは検索と候補がシートに入る。「トラックを探す」で開き、候補を押すとシートが閉じてマスに入る
import fs from "node:fs";
import { nico } from "./x_catalog.mjs";
import { variants, empty } from "./x_catalog_flow.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));

/** 要素を画面の上から y の所へ送る（撮る前） */
const scrollTo = (k, sel, y = 60) => k.page.evaluate(({ sel, y }) => window.scrollBy(0, document.querySelector(sel).getBoundingClientRect().top - y), { sel, y });
/** 空のグリッドから始める（グリッドが画面の上のほうに来るように送る） */
async function start(k, size, opts) {
  await empty(k, size, opts);
  await scrollTo(k, "#grid-scroll", 60);
  await k.hold(0.2);
  k.wide(0);
  await k.park(300, 640);
}
const sheetShown = (k) => k.until(() => k.page.evaluate(() => !document.querySelector("#sheet").hidden), "シートが開く", 5000);
const sheetGone = (k) => k.until(() => k.page.evaluate(() => document.querySelector("#sheet").hidden), "シートが閉じる", 5000);
const resultsAtLeast = (k, n) => k.until(() => k.page.evaluate((n) => document.querySelectorAll("#results .result").length >= n, n), "候補", 15000);
/** シートの中を、候補の窓の頭が上から y の所に来るまで送る */
async function toResults(k, y = 150, sec = 0.5) {
  const dy = await k.page.evaluate((y) => document.querySelector(".pane-results").getBoundingClientRect().top - y, y);
  if (dy > 4) await k.swipe(dy, sec, "#sheet-body");
}
/** シートの中の欄を撮る前に打つ位置へ送る（打つ所が画面の下に隠れないように） */
async function sheetTo(k, sel, y = 200, sec = 0.4) {
  const dy = await k.page.evaluate(({ sel, y }) => document.querySelector(sel).getBoundingClientRect().top - y, { sel, y });
  if (Math.abs(dy) > 4) await k.swipe(dy, sec, "#sheet-body");
}

export default [
  {
    id: "f-search-sp",
    phone: true,
    what: "「トラックを探す」でトラック名を入れて探し、候補を押すと空いているマスに入る。候補には出どころの札が付く",
    async setup(k) {
      await k.mock({ itunes: (term) => variants(term, square()) });
      await start(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.4);
      await k.tap("#q");
      await k.type("#q", "夜明けのシグナル", 0.07);
      await k.hold(0.3);
      await k.tap("#search-btn");
      await resultsAtLeast(k, 3);
      await k.hold(0.3);
      await toResults(k);
      await k.hold(0.9);
      await k.tap("#results li:nth-child(1) .result");
      await sheetGone(k);
      await k.waitArt();
      await k.hold(1.0);
      // もう 1 つ（シートを開き直すと、さっきの候補が残っている）
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.3);
      await toResults(k);
      await k.hold(0.5);
      await k.tap("#results li:nth-child(3) .result");
      await sheetGone(k);
      await k.waitArt();
      await k.hold(1.6);
    },
  },
  {
    id: "f-url-sp",
    phone: true,
    what: "YouTube やニコニコ動画などのページの URL を貼るだけで、そのトラックが取れる。ニコニコなら sm… の ID だけでもいい",
    async setup(k) {
      const wide = nico();
      let n = 0;
      await k.mock({ url: () => ({ ...wide[(n++ * 3 + 1) % wide.length], source: "nicovideo", external_url: "https://www.nicovideo.jp/watch/sm45000000" }) });
      await start(k, [3, 3], { cellRatio: "16:9" });
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.3);
      await k.tap("#sub-bandcamp > .sub-title");
      await k.hold(0.3);
      await sheetTo(k, "#sub-bandcamp", 170);
      await k.tap("#bc-url");
      await k.type("#bc-url", "https://www.nicovideo.jp/watch/sm45012345", 0.03);
      await k.tap("#bc-btn");
      await resultsAtLeast(k, 1);
      await k.hold(0.5);
      await k.tap("#bc-url");
      await k.type("#bc-url", "sm45067890", 0.07);
      await k.tap("#bc-btn");
      await resultsAtLeast(k, 2);
      await k.hold(0.3);
      await toResults(k);
      await k.hold(0.8);
      await k.tap("#results li:nth-child(1) .result");
      await sheetGone(k);
      await k.waitArt();
      await k.hold(1.6);
    },
  },
  {
    id: "f-playlist-sp",
    phone: true,
    what: "マイリストや再生リストの URL を 1 本貼るだけで、まとめて取れる（最大 500 トラック）。「マスに入れる」で順に埋まる",
    async setup(k) {
      const wide = nico();
      await k.mock({ playlist: () => [...wide, ...wide.slice(0, 3)].map((t, i) => ({ ...t, source: "nicovideo", external_url: `https://www.nicovideo.jp/watch/sm4500${1000 + i}` })) });
      await start(k, [3, 3], { cellRatio: "16:9", title: "好きな音MAD" });
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.3);
      await k.tap("#sub-bandcamp > .sub-title");
      await k.hold(0.3);
      await sheetTo(k, "#sub-bandcamp", 170);
      await k.tap("#bc-url");
      await k.type("#bc-url", "https://www.nicovideo.jp/mylist/73019452", 0.03);
      await k.tap("#bc-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pl-modal").hidden), "まとめて取れた窓", 15000);
      await k.hold(1.4);
      await k.tap("#pl-to-grid");
      await k.hold(0.8);
      await k.tap("#sheet-close");
      await sheetGone(k);
      await k.waitArt();
      await k.hold(2.2);
    },
  },
];

