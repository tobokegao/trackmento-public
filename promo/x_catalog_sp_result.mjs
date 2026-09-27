// Instagram・TikTok 向けの短い動画・スマホ版の台本（続き）。決まりは x_catalog_sp.mjs の頭と同じ。
// 元は x_catalog_result.mjs（出力オプションを変える → 「更新」→ できあがりの見本が変わる）。2026-09-27
//
// - スマホでは出力オプションの窓がグリッドの窓（「できあがり」を含む）より下にあり、欄と見本が 1 画面に収まらない。
//   **「見本の構図」（できあがりの窓の頭を画面の上端）と「欄の構図」（変える欄の下端を画面の下の端）を指で行き来する**。
//   こうすると送る量が 200〜900px で済む（欄を画面の真ん中に置くと 1000px を超え、何が動いたか追えない）
// - 送る量は毎回 DOM を測って決める（見本の形が変わると下の欄の位置がずれるため）
// - 送り方は k.swipe の等速ではなく、ゆっくり動き出して止まる前に減速する（指ではじいたときに近い。glideTo）
import fs from "node:fs";
import { ready } from "./x_catalog.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));
const pickRadio = (seg, v) => `#${seg} label:has(input[value="${v}"])`;

/** 要素の上端（edge="bottom" なら下端）の画面上の位置 */
const edgeOf = (k, sel, edge = "top") => k.page.evaluate(({ sel, edge }) => document.querySelector(sel).getBoundingClientRect()[edge], { sel, edge });
/** 撮る前に置く（要素の edge を画面の y に） */
async function place(k, sel, y, edge = "top") {
  const dy = (await edgeOf(k, sel, edge)) - y;
  await k.page.evaluate((dy) => window.scrollBy(0, dy), dy);
}
/** 撮りながら送る（要素の edge が画面の y に来るまで）。動き出しと止まり際をゆっくりに */
async function glideTo(k, sel, y, sec = 0.6, edge = "top", box = null) {
  const dy = (await edgeOf(k, sel, edge)) - y;
  if (Math.abs(dy) < 4) return;
  const n = Math.max(1, Math.round(sec * 30));
  let done = 0;
  for (let i = 1; i <= n; i++) {
    const t = i / n, e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    const to = Math.round(dy * e);
    await k.page.evaluate(({ d, box }) => (box ? document.querySelector(box) : window).scrollBy(0, d), { d: to - done, box });
    done = to;
    await k.frame();
  }
}
/** 見本の構図（できあがりの窓の頭を画面の上端に。見本と「更新」が上半分に入る） */
const toOutput = (k, sec = 0.6) => glideTo(k, "#output", 8, sec);
/** 欄の構図（sel の下端を画面の下の端に） */
const toField = (k, sel, sec = 0.6, y = 800) => glideTo(k, sel, y, sec, "bottom");

/** 出力オプションの窓を開いておく（スマホでは畳んで始まる。撮る前に） */
async function openOptions(k) {
  if (await k.page.evaluate(() => document.querySelector(".pane-options").dataset.collapsed === "true")) await k.page.click(".pane-options > .pane-title .fold");
}
const outDone = (k) => k.page.evaluate(() => /px/.test(document.querySelector("#out-msg").textContent)
  && !document.querySelector("#out-shot").hidden && document.querySelector("#output-img").complete);
/** 撮る前に見本を 1 回作っておく（最初の絵から見本が出ているように） */
async function primeOutput(k) {
  await k.page.$eval("#out-refresh", (el) => el.click());
  await k.until(() => outDone(k), "見本", 30000);
}
/** 「更新」を押して、見本ができるまで撮る */
async function update(k) {
  await k.tap("#out-refresh");
  await k.live(() => outDone(k), { min: 0.3, timeout: 30 });
}
/** 背景の絵（グラデーション・画像）ができあがるまで待つ */
const bgSettled = (k) => k.until(() => k.page.evaluate(() => !/調べています|作っています|送っています/.test(document.querySelector("#bg-msg")?.textContent || "")), "背景", 30000).catch(() => {});
const tiled = (k) => k.until(() => k.page.evaluate(() => /模様を敷きました/.test(document.querySelector("#bg-msg").textContent)), "既定の模様", 15000).catch(() => {});

/** 9 曲の 3×3 を並べ、出力オプションを開いて見本を作っておく */
async function base(k, opts = {}, list = square().slice(0, 9)) {
  await ready(k, 9, [3, 3], opts, list);
  await openOptions(k);
  await primeOutput(k);
}
/** 撮り始めの構図を決める */
async function frameStart(k, x = 355, y = 560) {
  await k.hold(0.2);
  k.wide(0);
  await k.park(x, y);
}
/** 欄を押す → 見本へ送る → 「更新」→ 欄へ戻る、を繰り返す。steps は [押すもの（セレクタ・関数）, 欄]。最後は見本の構図で終わる */
async function cycle(k, steps, { hold = 1.1, sec = 0.6, y = 800 } = {}) {
  for (let i = 0; i < steps.length; i++) {
    const [act, field] = steps[i];
    await toField(k, field, sec, y);
    if (typeof act === "function") await act(); else await k.tap(act);
    await k.hold(0.3);
    await toOutput(k, sec);
    await update(k);
    await k.hold(hold);
  }
}
const BG = "fieldset:has(#bg-mode-seg)";

export default [
  {
    id: "r-layouts-sp",
    phone: true,
    what: "曲名リストの組み方は、横 × 縦と曲の数で自動で変わる（マスの横・帯の下・表・流し込み）。「更新」を押すたびに組み直す",
    async setup(k) {
      await base(k);
      await place(k, "#output", 8);   // 見本の下に出力オプションの「横 × 縦」が見える
      await frameStart(k);
    },
    async run(k) {
      await k.hold(1.0);
      // 並びは画面の外で替える（横 × 縦の数字は画面の下で替わる）。「更新」を押すと見本の組み方が変わる
      for (const [c, r] of [[1, 6], [6, 1], [4, 4], [6, 4], [3, 3]]) {
        await k.page.evaluate(({ c, r, t }) => window.__setGridUI(c, r, {}, t.slice(0, c * r)), { c, r, t: square() });
        await place(k, "#output", 8);   // 上のグリッドの高さが変わっても、見本の位置は動かさない
        await k.hold(0.4);
        await update(k);
        await k.hold(1.3);
      }
    },
  },
  {
    id: "r-tracklist-sp",
    phone: true,
    what: "「トラックリスト」は 3 通り … 横並び・サムネイルに重ねる・出さない。選んで「更新」を押すと見本が変わる",
    async setup(k) {
      await base(k);
      await place(k, "fieldset:has(#list-seg)", 800, "bottom");
      await frameStart(k);
    },
    async run(k) {
      await k.hold(0.8);
      const F = "fieldset:has(#list-seg)";
      await cycle(k, [[pickRadio("list-seg", "overlay"), F], [pickRadio("list-seg", "none"), F], [pickRadio("list-seg", "side"), F]], { hold: 1.0 });
    },
  },
  {
    id: "r-output-sp",
    phone: true,
    what: "「できあがり」の窓 … 「更新」で書き出す画像の見本ができる（共有はしない）。見本を押すと「できあがりの見本」の窓で大きく見られる",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await place(k, "#output", 420);   // 上にグリッドの下のほう、下にできあがりの窓
      await frameStart(k, 355, 300);
    },
    async run(k) {
      await k.hold(1.0);
      await update(k);
      await k.hold(1.2);
      await k.tap("#out-shot");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#preview-modal").hidden && document.querySelector("#preview-img").complete), "大きく見る", 10000);
      await k.hold(2.2);
      await k.tap("#preview-modal-close");
      await k.hold(1.0);
    },
  },
  {
    id: "r-empty-sp",
    phone: true,
    what: "空いたマスは塗らずに書き出し、番号は曲の入ったマスだけで 01 から詰めて振る。1 曲外して「更新」すると番号が詰め直される",
    async setup(k) {
      const sq = square();
      const cells = Array(9).fill(null);
      [0, 2, 4, 6, 8].forEach((i, n) => { cells[i] = sq[n]; });
      await k.page.evaluate((cells) => { window.__setGridUI(3, 3, { title: "私を構成する5曲", numbers: true }, cells); document.querySelector("#title").value = "私を構成する5曲"; }, cells);
      await k.waitArt();
      await primeOutput(k);
      await place(k, "#grid-scroll", 8);   // グリッドと見本が 1 画面に入る（「更新」は少し下）
      await frameStart(k, 355, 300);
    },
    async run(k) {
      await k.hold(1.4);
      await k.tap("#grid .cell:nth-child(3) .rm");   // 1 曲外すと、番号が詰め直される
      await k.hold(0.6);
      await glideTo(k, "#out-refresh", 720, 0.5);
      await update(k);
      await k.hold(1.8);
    },
  },
  {
    id: "s-ratio-sp",
    phone: true,
    what: "「全体枠」で書き出しの形を選べる … 正方形 1:1・インスタ 4:5・横長 16:9・縦長 9:16。選んで「更新」を押すと見本の形が変わる",
    async setup(k) {
      await base(k);
      if (await k.page.getAttribute("#cells-more-btn", "aria-expanded") !== "true") await k.page.click("#cells-more-btn");   // 「枠とサムネ」の三角を開く
      await place(k, "fieldset:has(#ratio-seg)", 800, "bottom");
      await frameStart(k);
    },
    async run(k) {
      await k.hold(0.8);
      const F = "fieldset:has(#ratio-seg)";
      await cycle(k, [[pickRadio("ratio-seg", "1:1"), F], [pickRadio("ratio-seg", "9:16"), F], [pickRadio("ratio-seg", "4:5"), F], [pickRadio("ratio-seg", "16:9"), F]], { hold: 0.9, sec: 0.5 });
    },
  },
  {
    id: "s-fit-one-sp",
    phone: true,
    what: "マスを押して選ぶと、グリッドの下の編集の欄で、そのマスだけサムネイルの入れ方を変えられる（横長のマスに正方形のサムネイルを、切らずにぼかして入れる）",
    async setup(k) {
      // 横長 16:9 のマスに正方形のサムネイル。「トリミング」だと上下が切れ、「ぼかし背景」だと左右にぼかしが入る
      await ready(k, 9, [3, 3], { cellRatio: "16:9", cellFit: "crop" }, square().slice(0, 9));
      await place(k, "#grid-scroll", 16);   // 編集の欄が出ると、マスとサムネ余白の欄が 1 画面に入る
      await frameStart(k, 300, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#grid .cell:nth-child(1)");   // 絵のはっきりしたマス
      await k.until(() => k.page.evaluate(() => !document.querySelector("#editor").hidden), "編集欄", 5000);
      await k.hold(0.8);
      await k.tap(pickRadio("e-fit-seg", "blur"));
      await k.hold(1.8);
      await k.tap(pickRadio("e-fit-seg", ""));   // 「全体と同じ」に戻す
      await k.hold(0.8);
      await k.tap("#grid .cell:nth-child(1)");   // もう一度押すと選ぶのをやめる（編集の欄が閉じる）
      await k.hold(0.8);
    },
  },
  {
    id: "s-labels-sp",
    phone: true,
    what: "「表示」でタイトル・番号バッジ・トラック名の省略表示を切り替えられる。切り替えて「更新」を押すと見本に出る",
    async setup(k) {
      const sq = square().slice(0, 9).map((t, i) => (i === 2 ? { ...t, title: `${t.title}【Official Music Video】` } : t));
      await base(k, { numbers: false }, sq);
      await place(k, "fieldset:has(#opt-numbers)", 800, "bottom");
      await frameStart(k);
    },
    async run(k) {
      await k.hold(0.8);
      const F = "fieldset:has(#opt-numbers)";
      await cycle(k, [["#opt-numbers", F], ["#opt-title", F], ["#opt-trim", F]], { hold: 1.2, sec: 0.5 });
    },
  },
  {
    id: "s-pad-gap-sp",
    phone: true,
    what: "「余白」（ふつう・ひろめ・たっぷり）と「マスの間隔」で、書き出しの詰まり具合を変えられる",
    async setup(k) {
      await base(k, { gap: 16 });
      await place(k, "#gap", 720, "bottom");
      await frameStart(k);
    },
    async run(k) {
      await k.hold(0.8);
      await cycle(k, [
        [pickRadio("pad-seg", "xwide"), "#gap"],
        [() => k.dragThumb("#gap", 245, 0.9), "#gap"],   // いちばん広くまで（96px。つまみを画面の右の端より外へ運ぶと途中で止まる）
      ], { hold: 1.4, sec: 0.7, y: 720 });
    },
  },
  {
    id: "s-palette-sp",
    phone: true,
    what: "「配色パレット」で画面ごと色が替わる。ナイトは暗い地で、OS 9 風の部品まで暗い版に",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await openOptions(k);
      await place(k, "#palette-btn", 560);
      await frameStart(k);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#palette-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pal-modal").hidden), "パレット", 5000);
      await k.hold(0.6);
      for (const n of [2, 3]) {
        await k.tap(`#pal-lanes .pal-lane:nth-child(${n}) .pal-btns .btn:first-child`);
        await k.hold(1.4);
      }
      await k.tap("#pal-modal-close");   // 閉じると、後ろの画面ぜんぶがナイトの色に
      await k.hold(0.6);
      await glideTo(k, "#grid-scroll", 60, 0.8);   // グリッドの窓もナイトの色
      await k.hold(1.4);
    },
  },
  {
    id: "s-pal-make-sp",
    phone: true,
    what: "「いまの色から作る」で自分の配色を作れる。色を押してつまみで直す。カラーコードを貼っても作れる",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await openOptions(k);
      await place(k, "#palette-btn", 560);
      await k.page.click("#palette-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pal-modal").hidden), "パレット", 5000);
      await frameStart(k);
    },
    async run(k) {
      const box = await k.page.evaluate(() => {   // 窓の中で送れる箱（高さが足りないとき中身が送れる）
        const panel = document.querySelector("#pal-modal .modal-panel");
        const el = [panel, ...panel.querySelectorAll("*")].find((e) => /auto|scroll/.test(getComputedStyle(e).overflowY) && e.scrollHeight > e.clientHeight + 2);
        if (!el) return null;
        el.setAttribute("data-x-scroll", "1");
        return "[data-x-scroll]";
      });
      await k.hold(0.8);
      await k.tap("#pal-new");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#pal-lanes .pal-lane").length >= 4), "自作の組", 5000);
      await k.hold(0.3);
      const lane = "#pal-lanes .pal-lane:nth-child(4)";
      if (box) await glideTo(k, lane, 560, 0.5, "bottom", box);
      await k.hold(0.4);
      await k.tap(`${lane} .pal-chips button:nth-child(3)`);
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pal-hsv").hidden), "つまみ", 5000);
      await k.hold(0.3);
      if (box) await glideTo(k, "#pal-hsv", 720, 0.5, "bottom", box);
      await k.dragThumb("#pal-hsv-h", 120, 0.8);
      await k.hold(0.6);
      if (box) await glideTo(k, "#pal-import", 700, 0.5, "bottom", box);
      await k.tap("#pal-import");
      await k.page.fill("#pal-import", "#f2418f, #4878da, #ffd23f, #3bceac, #ee6c4d, #6a4c93, #1b1b1e, #fdfcdc");   // 貼り付けたように一度に入れる
      await k.hold(0.6);
      await k.tap("#pal-import-btn");
      await k.hold(0.3);
      if (box) await glideTo(k, "#pal-lanes .pal-lane:last-child", 700, 0.5, "bottom", box);
      await k.hold(1.4);
    },
  },
  {
    id: "s-swatch-sp",
    phone: true,
    what: "背景は見本の 8 色から選べる。「カスタムカラー」で色相・彩度・明度を好きに",
    async setup(k) {
      await ready(k, 9, [3, 3], { gap: 40, margin: 40 }, square().slice(0, 9));
      await openOptions(k);
      await place(k, "#grid-scroll", 60);
      await frameStart(k);
    },
    async run(k) {
      // 色を選ぶ所とグリッドは 1 画面に入らないので、選ぶ → グリッドへ送って見せる、を 2 回
      await k.hold(0.8);
      await toField(k, "#palette-btn", 0.8);
      await k.tap("#swatches > :nth-child(4)");
      await k.hold(0.4);
      await glideTo(k, "#grid-scroll", 60, 0.8);
      await k.hold(1.0);
      await toField(k, ".custom-color", 0.8, 520);
      await k.tap("#bg-custom-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#bg-custom-panel").hidden), "カスタムカラー", 5000);
      await k.hold(0.3);
      await k.dragThumb("#hsv-s", 150, 0.6);   // 開いたときは彩度がほぼ 0（白っぽい）なので、先に鮮やかにする
      await k.dragThumb("#hsv-h", 90, 0.8);
      await k.hold(0.4);
      await glideTo(k, "#grid-scroll", 60, 0.8);
      await k.hold(1.4);
    },
  },
  {
    id: "s-grad-sp",
    phone: true,
    what: "背景を「グラデーション」に … サムネイルの色から作る。「ほかの模様」で揺らぎの形だけ変わる。色を自分で選んでもいい",
    async setup(k) {
      await base(k, { gap: 32 });
      await place(k, BG, 800, "bottom");
      await frameStart(k);
    },
    async run(k) {
      // 欄の見本（小さい四角）で模様の変わり方を見せ、最後にできあがりへ送って大きく見せる
      await k.hold(0.8);
      await k.tap(pickRadio("bg-mode-seg", "gradient"));
      await bgSettled(k);
      await k.hold(0.3);
      await toField(k, BG, 0.5);   // 模様の見本が下に出る
      await k.hold(0.8);
      for (let i = 0; i < 2; i++) { await k.tap("#bg-grad-shuffle"); await bgSettled(k); await k.hold(0.8); }
      await toOutput(k, 0.7);
      await update(k);
      await k.hold(1.8);
    },
  },
  {
    id: "s-img-tile-sp",
    phone: true,
    what: "背景の「画像」は全体表示かタイル（小・中・大）で敷ける。好きな画像を選んでもいい",
    async setup(k) {
      await base(k, { gap: 32 });
      await k.page.route(/\/upload$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ url: "/uploads/fa4e010000000017.jpg" }) }));
      await place(k, BG, 800, "bottom");
      await frameStart(k);
    },
    async run(k) {
      await k.hold(0.8);
      await cycle(k, [
        [async () => { await k.tap(pickRadio("bg-mode-seg", "image")); await tiled(k); }, BG],
        [async () => { await k.tap(pickRadio("bg-fit-seg", "tile")); await k.hold(0.3); await k.tap(pickRadio("bg-tile-seg", "s")); await bgSettled(k); }, BG],
        [async () => {
          const fc = k.page.waitForEvent("filechooser");
          await k.tap("#bg-image-btn");
          await (await fc).setFiles("promo/public/x-bg-logo.png");
          await k.until(() => k.page.evaluate(() => !document.querySelector("#bg-image-reset").hidden), "画像", 20000);
          await bgSettled(k);
        }, BG],
      ], { hold: 1.2 });
    },
  },
  {
    id: "s-none-sp",
    phone: true,
    what: "背景を「透過」にすると、背景が透明な PNG で保存できる。字の色は黒と白から選ぶ",
    async setup(k) {
      await base(k, { gap: 24 });
      await place(k, BG, 800, "bottom");
      await frameStart(k);
    },
    async run(k) {
      await k.hold(0.8);
      await cycle(k, [[pickRadio("bg-mode-seg", "none"), BG], [pickRadio("bg-ink-seg", "light"), BG]], { hold: 1.3 });
    },
  },
  {
    id: "s-bg-preview-sp",
    phone: true,
    what: "背景の決め方の見本集 … 色の選択・サムネの近似色・グラデーション・画像・透過。選んで「更新」を押すと見本が変わる",
    async setup(k) {
      await base(k, { gap: 32 });
      await place(k, "#bg-mode-seg", 800, "bottom");
      await frameStart(k);
    },
    async run(k) {
      await k.hold(0.8);
      const F = "#bg-mode-seg";   // 決め方の欄だけを見る（下の細かい欄は決め方ごとに替わる）
      const pick = (v) => [async () => { await k.tap(pickRadio("bg-mode-seg", v)); if (v === "image") await tiled(k); await bgSettled(k); }, F];
      await cycle(k, [pick("near"), pick("gradient"), pick("image"), pick("none")], { hold: 0.9, sec: 0.5 });
    },
  },
];
