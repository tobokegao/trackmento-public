// Instagram・TikTok 向けの短い動画・スマホ版の台本（続き）。決まりは x_catalog_sp.mjs の頭と同じ。
// 元は x_catalog.mjs の 11 本と x_catalog_parts.mjs の 5 本。PC だけの操作（Ctrl+Z・Alt＋矢印）の 2 本は撮らない
// （undo-keys はスマホでは undo-buttons-sp と同じになる。alt-arrows はスマホに同じ操作が無い）。
// p-logo も撮らない（寄れないスマホの画面ではロゴは頭の小さな字のままで、縦の動画の上にも同じロゴと帯が出るため）。
//
// - スマホでは出力オプション（横 × 縦・枠とサムネ・背景）がグリッドよりずっと下にあり、同じ画面に入らない。
//   欄を押したら k.swipe でグリッドまで送って変わった所を見せ、また送って戻る（swipeTo）
import fs from "node:fs";
import { ready, nico, mono, shuffled } from "./x_catalog.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));

/** 並べる（空きマスは null）。x_catalog_phone.mjs の place と同じ */
async function place(k, cols, rows, cells, opts = {}) {
  await k.page.evaluate(({ cols, rows, cells, opts }) => {
    window.__setGridUI(cols, rows, { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true, margin: 16, gap: 16, bg: "mustard", bgCustom: null, ...opts }, cells);
    document.querySelector("#title").value = opts.title ?? "私を構成する9曲";
  }, { cols, rows, cells, opts });
  await k.hold(0.3);
  await k.waitArt();
}
/** 要素を画面の上から y の所へ送る（撮る前） */
const scrollTo = (k, sel, y = 60) => k.page.evaluate(({ sel, y }) => window.scrollBy(0, document.querySelector(sel).getBoundingClientRect().top - y), { sel, y });
/** 撮りながら、要素が画面の上から y の所に来るまで指で送る。**送る前に指の丸を消す**（押した所に残ったまま、送った先の別の部品に重なるため） */
async function swipeTo(k, sel, y = 60, sec = 0.7) {
  await k.hideCursor();
  const dy = await k.page.evaluate(({ sel, y }) => document.querySelector(sel).getBoundingClientRect().top - y, { sel, y });
  if (Math.abs(dy) > 4) await k.swipe(dy, sec);
}
/** 出力オプションの窓を開いておく（スマホでは既定で畳んである。撮る前だけ） */
async function openOptions(k) {
  if (await k.page.evaluate(() => document.querySelector(".pane-options").dataset.collapsed === "true")) await k.page.click(".pane-options > .pane-title .fold");
  await k.hold(0.2);
}
/** 「枠とサムネ」の三角も開く */
async function openCells(k) {
  await openOptions(k);
  if (await k.page.getAttribute("#cells-more-btn", "aria-expanded") !== "true") await k.page.click("#cells-more-btn");
  await k.hold(0.2);
}
/** 撮りながら、ページの頭まで指で送る */
async function swipeTop(k, sec = 0.8) {
  await k.hideCursor();
  const dy = await k.page.evaluate(() => -window.scrollY);
  if (Math.abs(dy) > 4) await k.swipe(dy, sec);
}
const sheetShown = (k) => k.until(() => k.page.evaluate(() => !document.querySelector("#sheet").hidden), "シートが開く", 5000);
const sheetGone = (k) => k.until(() => k.page.evaluate(() => document.querySelector("#sheet").hidden), "シートが閉じる", 5000);

export default [
  {
    id: "color-sort-sp",
    phone: true,
    what: "グリッドの下の「色で並べ替え」… サムネイルの主な色で、赤から紫の順に並べ直す。白黒のサムネイルは明るい順",
    async setup(k) {
      await ready(k, 16, [4, 4], {}, shuffled(mono()));
      await scrollTo(k, "#grid-scroll", 60);
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      await k.hold(1.0);
      await k.tap("#color-sort");
      // 色を調べ終わるまで撮り続ける（「（n/N）」と数えている間も見せる）
      await k.live(() => k.page.evaluate(() => !/\d+\/\d+/.test(document.querySelector("#color-sort").textContent)), { min: 0.5, timeout: 15 });
      await k.hold(3.2);
    },
  },
  {
    id: "lang-sp",
    phone: true,
    what: "右上の「EN」で、画面がまるごと英語に。もう一度押すと日本語に戻る",
    async setup(k) {
      await ready(k, 9, [3, 3]);
      k.wide(0);
      await k.park(250, 400);
    },
    async run(k) {
      await k.hold(1.0);
      await k.tap("#lang-switch");
      await k.hold(2.4);
      await k.tap("#lang-switch");
      await k.hold(1.2);
    },
  },
  {
    id: "undo-buttons-sp",
    phone: true,
    what: "グリッドの下の「元に戻す」「やり直す」… 30 回まで戻せて、戻したものをやり直せる",
    async setup(k) {
      await ready(k, 9, [3, 3]);
      await scrollTo(k, "#grid-scroll", 60);
      k.wide(0);
      await k.park(300, 640);
    },
    async run(k) {
      await k.hold(0.8);
      for (const n of [9, 5]) {
        await k.tap(`#grid .cell:nth-child(${n}) .rm`);
        await k.hold(0.5);
      }
      await k.tap("#undo-btn");
      await k.hold(0.6);
      await k.tap("#undo-btn", { sec: 0.2 });
      await k.hold(0.6);
      await k.tap("#redo-btn");
      await k.hold(0.6);
      await k.tap("#undo-btn");   // 始めと同じ 9 曲に戻して終わる
      await k.hold(1.0);
    },
  },
  {
    id: "cell-ratio-sp",
    phone: true,
    what: "出力オプションの「マス枠」を横長 16:9 に … 動画サイトのサムネイルが左右で切れずに並ぶ（「枠とサムネ」の三角の中）",
    async setup(k) {
      await ready(k, 9, [3, 3], { title: "好きな音MAD" }, nico());
      await openCells(k);
      await scrollTo(k, "#grid-scroll", 60);
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      const pick = (v) => `#cell-ratio-seg label:has(input[value="${v}"])`;
      await k.hold(1.0);
      await swipeTo(k, "fieldset:has(#cell-ratio-seg)", 420, 0.8);
      await k.hold(0.3);
      await k.tap(pick("16:9"));
      await k.waitArt();
      await k.hold(0.4);
      await swipeTo(k, "#grid-scroll", 60, 0.8);
      await k.hold(2.0);
      await swipeTo(k, "fieldset:has(#cell-ratio-seg)", 420, 0.8);
      await k.hold(0.2);
      await k.tap(pick("1:1"));
      await k.waitArt();
      await k.hold(0.4);
      await swipeTo(k, "#grid-scroll", 60, 0.8);
      await k.hold(1.4);
    },
  },
  {
    id: "cell-fit-sp",
    phone: true,
    what: "出力オプションの「サムネ余白」… 「ぼかし背景」にすると、形の違うサムネも切らずに入る（「枠とサムネ」の三角の中）",
    async setup(k) {
      await ready(k, 9, [3, 3], { title: "好きな音MAD" }, nico());
      await openCells(k);
      await scrollTo(k, "#grid-scroll", 60);
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      const pick = (v) => `#cell-fit-seg label:has(input[value="${v}"])`;
      await k.hold(1.0);
      await swipeTo(k, "fieldset:has(#cell-fit-seg)", 420, 0.8);
      await k.hold(0.3);
      await k.tap(pick("blur"));
      await k.hold(0.4);
      await swipeTo(k, "#grid-scroll", 60, 0.8);
      await k.hold(2.0);
      await swipeTo(k, "fieldset:has(#cell-fit-seg)", 420, 0.8);
      await k.hold(0.2);
      await k.tap(pick("crop"));
      await k.hold(0.4);
      await swipeTo(k, "#grid-scroll", 60, 0.8);
      await k.hold(1.4);
    },
  },
  {
    id: "stash-sp",
    phone: true,
    what: "マスを減らしてもトラックは消えない … 出力オプションの横 × 縦で減らすと、いったん外して取っておき、サイズを戻すと帰ってくる",
    async setup(k) {
      await ready(k, 9, [3, 3]);
      await openOptions(k);
      await scrollTo(k, "#grid-scroll", 60);
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      // **減らすのは縦**（x_catalog.mjs の stash と同じ）
      const down = "#rows ~ .stepper button[data-step='-1']", up = "#rows ~ .stepper button[data-step='1']";
      await k.hold(1.0);
      await swipeTo(k, ".gbox:has(#cols)", 380, 0.8);
      await k.hold(0.3);
      await k.tap(down);
      await k.hold(0.5);
      await swipeTo(k, "#grid-scroll", 60, 0.8);
      await k.hold(2.0);
      await swipeTo(k, ".gbox:has(#cols)", 380, 0.8);
      await k.hold(0.2);
      await k.tap(up);
      await k.hold(0.5);
      await swipeTo(k, "#grid-scroll", 60, 0.8);
      await k.hold(1.8);
    },
  },
  {
    id: "p-care-sp",
    phone: true,
    what: "マスは合計 256 まで。横 × 縦を大きくしすぎると、自動で縮めて知らせる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await openOptions(k);
      await scrollTo(k, ".gbox:has(#cols)", 300);
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#cols");
      await k.page.fill("#cols", "");
      await k.type("#cols", "20", 0.15);
      await k.tap("#rows");   // 横の欄から離れると決まる
      await k.page.fill("#rows", "");
      await k.type("#rows", "20", 0.15);
      await k.hold(0.3);
      await k.page.evaluate(() => document.activeElement.blur());   // キーボードを閉じる（「完了」）と決まる
      await k.until(() => k.page.evaluate(() => /合計 256/.test(document.querySelector("#grid-msg").textContent)), "256 の知らせ", 10000);
      await k.hold(1.4);   // 横が 20 から 12 に縮むところ
      await swipeTo(k, "#grid-msg", 560, 0.9);
      await k.hold(2.6);
    },
  },
  {
    id: "p-small-sp",
    phone: true,
    what: "マスが小さくなると、× と番号とトラック名の帯を隠してサムネイルを見せる。押せばグリッドの下の編集の欄で確かめて直せる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await scrollTo(k, ".pane-grid > .pane-title", 12);
      k.wide(0);
      await k.hideCursor();   // 最初のタップまで指を出さない（置いた所がボタンの上で、押しているように見えた）
    },
    async run(k) {
      await k.hold(1.0);
      for (const [c, r] of [[5, 5], [7, 7]]) {   // スマホの 3×3 は × も番号も帯も出る。5×5（マスは 60px ほど）で全部隠れる
        await k.page.evaluate(({ c, r, t }) => window.__setGridUI(c, r, {}, Array.from({ length: c * r }, (_, i) => t[i % t.length])), { c, r, t: square() });
        await k.waitArt();
        await k.hold(1.5);
      }
      await k.tap("#grid .cell:nth-child(17)");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#editor").hidden), "編集欄", 5000);
      await k.hold(2.0);
      await k.tap("#grid .cell:nth-child(17)");   // もう一度押すと選ぶのをやめる（「選択解除」は画面の下に隠れていて、押すとページが送られる）
      await k.hold(0.4);
      await k.page.evaluate(({ t }) => window.__setGridUI(3, 3, {}, t.slice(0, 9)), { t: square() });
      await k.waitArt();
      await k.hold(1.2);
    },
  },
  {
    id: "bg-modes-sp",
    phone: true,
    what: "出力オプションの「背景」… 「サムネの近似色」「サムネの補色」を選ぶと、並んだサムネイルから色を取る",
    async setup(k) {
      // 背景の色が見えるように、マスの間隔と余白を広めにする
      await ready(k, 9, [3, 3], { gap: 48, margin: 48, bg: "paper" });
      await openOptions(k);
      await scrollTo(k, "#grid-scroll", 60);
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      const pick = (v) => `#bg-mode-seg label:has(input[value="${v}"])`;
      await k.hold(1.0);
      await swipeTo(k, "fieldset:has(#bg-mode-seg)", 360, 0.9);
      await k.hold(0.3);
      await k.tap(pick("near"));
      await k.until(() => k.page.evaluate(() => /選びました/.test(document.querySelector("#bg-msg").textContent)), "サムネイルの色", 20000);
      await k.hold(0.8);
      await swipeTo(k, "#grid-scroll", 60, 0.9);
      await k.hold(1.8);
      await swipeTo(k, "fieldset:has(#bg-mode-seg)", 360, 0.9);
      await k.hold(0.2);
      await k.tap(pick("far"));
      await k.hold(0.8);
      await swipeTo(k, "#grid-scroll", 60, 0.9);
      await k.hold(1.8);
    },
  },
  {
    id: "bg-image-sp",
    phone: true,
    what: "出力オプションの「背景」の「画像」… 選ぶとまず TRACKMENTO の模様、「画像を選ぶ」で端末の好きな画像に。曲名が読めるように、にぎやかな画像ほど薄く",
    async setup(k) {
      await ready(k, 9, [3, 3], { gap: 48, margin: 48, bg: "paper" });
      await openOptions(k);
      await scrollTo(k, "fieldset:has(#bg-mode-seg)", 300);
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      await k.hold(1.0);
      // 「画像」を選ぶと、まず既定の TRACKMENTO の模様が敷かれる（選ぶ窓は開かない）
      await k.tap('#bg-mode-seg label:has(input[value="image"])');
      await k.until(() => k.page.evaluate(() => /模様を敷きました/.test(document.querySelector("#bg-msg").textContent)), "既定の模様", 10000);
      // スマホの見本はマスの隙間が細く、模様はほとんど見えない。欄の中の小さな見本（模様の絵）を見せて、そのまま画像を選ぶ
      await k.hold(1.2);
      // 「画像を選ぶ…」で端末の画像に替える。選ぶ窓は写らないので、選んだあとの見本の変わり方を見せる
      const fc = k.page.waitForEvent("filechooser");
      await k.tap("#bg-image-btn");
      await (await fc).setFiles("promo/public/x-bg-logo.png");   // Tobokegao のロゴ（x_catalog.mjs の bg-image と同じ）
      await k.until(() => k.page.evaluate(() => /画像を背景に/.test(document.querySelector("#bg-msg").textContent)), "背景の画像", 30000);
      await k.until(() => k.page.evaluate(() => /url\(/.test(document.querySelector("#grid").style.background)), "見本の画像", 10000);
      await k.hold(0.6);
      await swipeTo(k, "#grid-scroll", 60, 0.9);
      await k.hold(1.0);
      // 書き出しの画像（曲名リスト込み）まで見せる。「できあがりを見る」を押すと、スマホではできあがりの窓まで送られる
      await k.tap("#preview-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#out-shot").hidden && document.querySelector("#output-img").complete), "できあがりの見本", 60000);
      await k.hold(0.3);
      await swipeTo(k, "#output", 12, 0.5);
      await k.hold(3.0);
    },
  },
  {
    id: "p-os9-sp",
    phone: true,
    what: "見た目は Mac OS 9 風 … 縞の題名バー、ポップアップメニュー、注意の絵の確認窓、グループボックス、ドット絵のラジオボタン",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await openOptions(k);
      await k.page.evaluate(() => window.scrollTo(0, 0));
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      await k.hold(1.4);                                                                  // 縞の題名バー
      await k.tap(".popup:has(#theme-sel) .popup-hit");                                   // ポップアップメニュー
      await k.until(() => k.page.evaluate(() => !document.querySelector("#popmenu").hidden), "メニュー", 5000);
      await k.hold(1.8);
      // メニューの外（暗い所）を押して閉じる
      const r = await k.page.locator(".popmenu-panel").boundingBox();
      await k.tapAt(280, r.y > 60 ? 24 : Math.min(820, r.y + r.height + 30));   // 上の暗い所（ロゴと「?」の間の何も無い所）
      await k.hold(0.5);
      await swipeTo(k, "#clear-btn", 560, 0.8);
      await k.hold(0.2);
      await k.tap("#clear-btn");                                                          // 注意の絵の確認窓
      await k.until(() => k.page.evaluate(() => !document.querySelector("#confirm-modal").hidden), "確認の窓", 5000);
      await k.hold(1.8);
      await k.tap("#confirm-no");
      await k.hold(0.4);
      await swipeTo(k, ".pane-options", 16, 0.8);                                         // グループボックスとラジオボタン
      await k.hold(2.2);
      await swipeTop(k, 0.9);
      await k.hold(0.8);
    },
  },
  {
    id: "p-counts-sp",
    phone: true,
    what: "小さな数の表示 … 候補の数、出どころの札、グリッドの「n/9」、出力サイズとマスの大きさ",
    async setup(k) {
      const sq = square();
      await k.mock({ itunes: () => [sq[3], sq[8], sq[14]].map((t, i) => ({ ...t, source: "itunes", title: `ソーダ水の惑星${["", " (Live)", " - Remix"][i]}` })) });
      await place(k, 3, 3, Array.from({ length: 9 }, (_, i) => (i < 5 ? sq[i] : null)));
      await openOptions(k);
      await scrollTo(k, ".pane-grid > .pane-title", 12);
      k.wide(0);
      await k.park(300, 740);
    },
    async run(k) {
      await k.hold(1.0);                                                                  // グリッドの 5/9
      await k.tap("#find-btn");
      await sheetShown(k);
      await k.hold(0.3);
      await k.tap("#q");
      await k.type("#q", "ソーダ水の惑星", 0.06);
      await k.tap("#search-btn");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#results .result").length >= 3), "候補", 15000);
      await k.hold(0.2);
      const dy = await k.page.evaluate(() => document.querySelector(".pane-results").getBoundingClientRect().top - 150);
      if (dy > 4) await k.swipe(dy, 0.5, "#sheet-body");
      await k.hold(1.6);                                                                  // 候補の数と出どころの札
      await k.tap("#results li:nth-child(2) .result");   // 1 番目はグリッドの 4 番と同じ絵なので 2 番目
      await sheetGone(k);
      await k.waitArt();
      await k.hold(1.4);                                                                  // 6/9 に
      await swipeTo(k, ".pane-options .spec", 700, 0.9);   // 画面のいちばん下に（下のサーバー代のお願いの枠を映さない）
      await k.hold(2.0);                                                                  // 出力サイズとマスの大きさ
      await swipeTo(k, ".pane-grid > .pane-title", 12, 0.9);
      await k.hold(0.8);
    },
  },
  {
    id: "zoom-wheel-sp",
    phone: true,
    what: "「大きく見る」の中で、2 本指で広げる・すぼめるとマスを拡大・縮小できる。並びの形ごとに大きさを覚える",
    async setup(k) {
      await ready(k, 64, [8, 8]);
      k.wide(0);
      await k.park(300, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#zoom-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#zoom-modal").hidden), "大きく見る", 5000);
      await k.hold(0.8);
      const b = await k.page.locator("#grid-scroll").boundingBox();
      const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
      await k.hideCursor();
      await k.pinch(cx, cy, 80, 200, 1.0);
      await k.hold(1.2);
      await k.pinch(cx, cy, 200, 80, 1.0);
      await k.hold(0.8);
      await k.tap("#zoom-modal-close");
      await k.hold(0.8);
    },
  },
];
