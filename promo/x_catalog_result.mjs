// X に載せる短い動画の台本・2 段目「できあがりと見た目の切り替え」（2026-09-26）。決まりは x_catalog.mjs の頭と同じ。
// 段取りは題材の台帳（https://claude.ai/artifact/GZ3kefBb8ouyGpV5fc2MRo）の「撮影の段取り」。
//
// - **書き出しの絵が主役**。設定を替えたら「更新」を押し、「できあがり」の見本が変わるところを見せる
//   （見本は自動では作り直さない。数秒かかるので、スマホで重くなるため。frontend の refreshOutput）
// - 窓は k.arrange で、左に出力オプションの欄（その場面の欄だけ）、右に「できあがり」を大きく置く
// - 曲名もサムネも架空（promo/fake_covers.py）
import fs from "node:fs";
import { ready, nico, GT, OT, openCellsMore } from "./x_catalog.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));
const OUT = "#output > .pane-title";
/** 見本の絵を画面の高さに収める（縦長 9:16 でも窓が 720px を超えない）。横は窓の幅まで */
const OUT_FIT = "#output .out-shot img { width: auto !important; max-width: 100% !important; max-height: 540px !important; margin: 0 auto; }";

/** 左に出力オプション（sel を含むグループボックスだけ）、右に「できあがり」 */
const arrangeOut = (w = 820) => ({
  ".pane-options": { x: 32, y: 40, w: 360, only: [".x-keep"] },   // 目印はグループボックス自身に付く（keepField）
  "#output": { x: 1280 - 32 - w, y: 24, w },
});
/** 欄を 1 つだけ残す CSS（sel を含む欄に目印を付け、同じグループボックスのほかの欄と説明を隠す）。
    k.arrange より先に呼ぶ（arrangeOut の only が目印を見る）。
    できあがりの窓は「更新」だけ残す（トラック名のコピー・共有・載せるの説明は隠す） */
async function keepField(k, sel) {
  await k.page.evaluate((sel) => {
    const f = document.querySelector(sel).closest(".field"), g = f.closest(".gbox");
    f.classList.add("x-keep-field"); g.classList.add("x-keep");
  }, sel);
  await k.stage(".x-keep .field:not(.x-keep-field), .x-keep .disclose-head, .x-keep > p { display: none !important; } "
    + "#output .out-actions > :not(#out-refresh), #output .listed, #output .msg-under, #share-done { display: none !important; } "
    + OUT_FIT);
}
/** 「更新」を押して、見本ができるまで撮る */
async function refresh(k) {
  await k.press("#out-refresh");
  await k.live(() => k.page.evaluate(() => /px/.test(document.querySelector("#out-msg").textContent)
    && !document.querySelector("#out-shot").hidden && document.querySelector("#output-img").complete), { min: 0.3, timeout: 30 });
}
/** 撮る前に見本を 1 回作っておく（最初の絵から見本が出ているように） */
async function primeOutput(k) {
  await k.page.$eval("#out-refresh", (el) => el.click());   // 撮る前なので直接押す（隠してある場面もある）
  await k.until(() => k.page.evaluate(() => /px/.test(document.querySelector("#out-msg").textContent)
    && document.querySelector("#output-img").complete && !document.querySelector("#out-shot").hidden), "見本", 30000);
}
const pickRadio = (seg, v) => `#${seg} label:has(input[value="${v}"])`;

/** 背景の決め方の欄とできあがりを並べる（見本集の場面）。欄は背景のまとまりだけ */
async function bgOut(k) {
  await keepField(k, "#bg-mode-seg"); await k.arrange(arrangeOut());
}
/** 背景の絵（グラデーション・画像）ができあがるまで待つ */
const bgSettled = (k) => k.until(() => k.page.evaluate(() => !/調べています|作っています|送っています/.test(document.querySelector("#bg-msg")?.textContent || "")), "背景", 30000).catch(() => {});

export default [
  {
    id: "r-layouts",
    what: "曲名リストの組み方は、横 × 縦と曲の数で自動で変わる（マスの横・帯の下・表・流し込み）。書き出すたびに組み直す",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await k.arrange({ "#output": { x: 190, y: 12, w: 900 } });
      await k.stage("#output .out-actions, #output .listed, #output .msg-under, #share-done, #out-msg { display: none !important; }");
      await primeOutput(k);
      await k.look(["#out-shot"]);
      await k.hideCursor();
    },
    async run(k) {
      await k.hold(1.4);
      // 並びを替えるたびに見本を作り直す（画面の操作は映さない。見本の組み方の変わり方だけを見せる）
      for (const [c, r] of [[1, 6], [6, 1], [4, 4], [6, 4], [3, 3]]) {
        await k.page.evaluate(({ c, r, t }) => window.__setGridUI(c, r, {}, t.slice(0, c * r)), { c, r, t: square() });
        await k.page.$eval("#out-refresh", (el) => el.click());   // ボタンは隠してあるので直接押す
        await k.live(() => k.page.evaluate(() => /px/.test(document.querySelector("#out-msg").textContent)
          && document.querySelector("#output-img").complete), { min: 0.2, timeout: 30 });
        await k.hold(1.5);
      }
    },
  },
  {
    id: "r-tracklist",
    what: "「トラックリスト」は 3 通り … 横並び・サムネイルに重ねる・出さない",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await keepField(k, "#list-seg"); await k.arrange(arrangeOut());
      await primeOutput(k);
      await k.look([OT, "#list-seg", OUT, "#out-shot"]);
      await k.park(900, 650);
    },
    async run(k) {
      await k.hold(1.0);
      for (const v of ["overlay", "none", "side"]) {
        await k.press(pickRadio("list-seg", v));
        await refresh(k);
        await k.hold(1.3);
      }
    },
  },
  {
    id: "r-output",
    what: "「できあがり」の窓 … 「更新」で書き出す画像の見本ができる（共有はしない）。見本を押すと「できあがりの見本」の窓で大きく見られる",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await k.arrange({ ".pane-grid": { x: 60, y: 30, w: 440, only: ["#grid-scroll", "#grid-msg"] }, "#output": { x: 540, y: 30, w: 680 } });
      await k.stage("#output .out-actions > :not(#out-refresh), #output .listed, #output .msg-under, #share-done { display: none !important; }");
      await k.look([GT, "#grid", OUT, "#output"]);
      await k.park(1000, 600);
    },
    async run(k) {
      // カメラは動かしすぎない（無駄なスクロールが多い、と利用者）。構図は 2 つだけ: グリッドとできあがり → 開いた窓
      await k.hold(0.8);
      await refresh(k);
      await k.hold(1.0);
      await k.press("#out-shot");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#preview-modal").hidden && document.querySelector("#preview-img").complete), "大きく見る", 10000);
      await k.look(["#preview-modal .modal-panel"], 0.6);   // 窓の題名「できあがりの見本」も入る
      await k.hold(2.2);
      await k.press("#preview-modal-close");
      await k.look([GT, "#grid", OUT, "#output"], 0.6);
      await k.hold(1.0);
    },
  },
  {
    id: "r-empty",
    what: "空いたマスは塗らずに書き出し、番号は曲の入ったマスだけで 01 から詰めて振る",
    async setup(k) {
      const sq = square();
      const cells = Array(9).fill(null);
      [0, 2, 4, 6, 8].forEach((i, n) => { cells[i] = sq[n]; });
      await k.page.evaluate((cells) => { window.__setGridUI(3, 3, { title: "私を構成する5曲", numbers: true }, cells); document.querySelector("#title").value = "私を構成する5曲"; }, cells);
      await k.waitArt();
      await k.arrange({ ".pane-grid": { x: 60, y: 30, w: 440, only: ["#grid-scroll", "#grid-msg"] }, "#output": { x: 540, y: 30, w: 680 } });
      await k.stage("#output .out-actions > :not(#out-refresh), #output .listed, #output .msg-under, #share-done { display: none !important; }");
      await primeOutput(k);
      await k.look([GT, "#grid", OUT, "#output"]);
      await k.park(1000, 600);
    },
    async run(k) {
      await k.hold(1.2);
      await k.look([OUT, "#out-shot"], 0.6);
      await k.hold(1.4);
      await k.look([GT, "#grid", OUT, "#output"], 0.6);
      await k.glide("#grid .cell:nth-child(3)", 0.3);
      await k.press("#grid .cell:nth-child(3) .rm", { sec: 0.2 });   // 1 曲外すと、番号が詰め直される
      await k.hold(0.4);
      await refresh(k);
      await k.look([OUT, "#out-shot"], 0.6);
      await k.hold(1.6);
    },
  },
  {
    id: "s-ratio",
    what: "「全体枠」で書き出しの形を選べる … 正方形 1:1・インスタ 4:5・横長 16:9・縦長 9:16",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await openCellsMore(k);
      await keepField(k, "#ratio-seg"); await k.arrange(arrangeOut());
      await primeOutput(k);
      await k.look([OT, "#ratio-seg", OUT, "#output"]);
      await k.park(900, 650);
    },
    async run(k) {
      await k.hold(1.0);
      for (const v of ["1:1", "4:5", "9:16", "free", "16:9"]) {   // 「自由」も押す（利用者の指摘）
        await k.press(pickRadio("ratio-seg", v));
        await refresh(k);
        await k.look([OT, "#ratio-seg", OUT, "#output"], 0.3);
        await k.hold(1.1);
      }
    },
  },
  {
    id: "s-fit-one",
    what: "マスを選ぶと、そのマスだけサムネイルの入れ方を変えられる（横長のマスに正方形のサムネイルを、切らずにぼかして入れる）",
    async setup(k) {
      // **横長 16:9 のマスに正方形のサムネイル**（利用者の案）。「トリミング」だと上下が切れ、「ぼかし背景」だと左右にぼかしが入る
      await ready(k, 9, [3, 3], { cellRatio: "16:9", cellFit: "crop" }, square().slice(0, 9));
      await k.arrange({ ".pane-grid": { x: 40, y: 30, w: 600, only: ["#grid-scroll", "#grid-msg"] }, ".pane-search": { x: 680, y: 30, w: 560 } });
      await k.stage(".pane-search > :not(.pane-title):not(#editor) { display: none !important; } #grid-scroll { height: auto !important; }");
      await k.look([GT, "#grid"]);
      await k.park(900, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#grid .cell:nth-child(1)");   // 絵のはっきりしたマス（淡い絵だとぼかしが見えない）
      await k.until(() => k.page.evaluate(() => !document.querySelector("#editor").hidden), "編集欄", 5000);
      await k.look([GT, "#grid", ".pane-search > .pane-title", "#editor"], 0.6);
      await k.hold(0.5);
      await k.press(pickRadio("e-fit-seg", "blur"));
      await k.look(["#grid .cell:nth-child(1)", "#grid .cell:nth-child(2)"], 0.6);   // 選んだマスに寄って、左右のぼかしを見せる
      await k.hold(1.6);
      await k.look([GT, "#grid", ".pane-search > .pane-title", "#editor"], 0.6);
      await k.press(pickRadio("e-fit-seg", ""));   // 「全体と同じ」に戻す
      await k.hold(0.6);
      await k.press("#e-close");
      await k.look([GT, "#grid"], 0.5);
      await k.hold(0.8);
    },
  },
  {
    id: "s-labels",
    what: "「表示」でタイトル・番号バッジ・トラック名の省略表示を切り替えられる",
    async setup(k) {
      const sq = square().slice(0, 9).map((t, i) => (i === 2 ? { ...t, title: `${t.title}【Official Music Video】` } : t));
      await ready(k, 9, [3, 3], { numbers: false }, sq);
      await keepField(k, "#opt-numbers"); await k.arrange(arrangeOut());
      await primeOutput(k);
      await k.look([OT, "#opt-numbers", OUT, "#output"]);
      await k.park(900, 650);
    },
    async run(k) {
      await k.hold(1.0);
      // それぞれ替えたあと、見本の中の変わった所に寄る（番号バッジは小さいので、マスの左上へ。利用者の指摘）
      const steps = [["#opt-numbers", [0.02, 0.02, 0.36, 0.42]], ["#opt-title", [0.5, 0.0, 0.5, 0.42]], ["#opt-trim", [0.5, 0.05, 0.5, 0.5]]];
      for (const [sel, part] of steps) {
        await k.look([OT, "#opt-numbers", OUT, "#output"], 0.4);
        await k.press(sel);
        await refresh(k);
        await k.lookPart("#out-shot", ...part, 0.6);
        await k.hold(1.3);
      }
      await k.look([OT, "#opt-numbers", OUT, "#output"], 0.5);
      await k.hold(0.5);
    },
  },
  {
    id: "s-pad-gap",
    what: "「余白」（ふつう・ひろめ・たっぷり）と「マスの間隔」で、書き出しの詰まり具合を変えられる",
    async setup(k) {
      await ready(k, 9, [3, 3], { gap: 16 }, square().slice(0, 9));
      await keepField(k, "#pad-seg"); await k.arrange(arrangeOut());
      await k.stage(".x-keep .field:has(#gap) { display: block !important; }");
      await primeOutput(k);
      await k.look([OT, "#pad-seg", "#gap", OUT, "#output"]);
      await k.park(900, 650);
    },
    async run(k) {
      await k.hold(1.0);
      await k.press(pickRadio("pad-seg", "xwide"));
      await refresh(k);
      await k.hold(1.2);
      await k.dragThumb("#gap", 400, 0.9);   // いちばん広くまで（96px。変わり方を大げさに、と利用者）
      await k.hold(0.3);
      await refresh(k);
      await k.hold(1.6);
      await k.press(pickRadio("pad-seg", "normal"));
      await k.dragThumb("#gap", -400, 0.6);   // 間隔 0 まで詰める
      await refresh(k);
      await k.hold(0.8);
    },
  },
  {
    id: "s-palette",
    what: "「配色パレット」で画面ごと色が替わる。ナイトは暗い地で、OS 9 風の部品まで暗い版に",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      // グリッドと背景の欄を並べ、パレットの窓はその上に開く（窓は .modal なので並べ直しの影響を受けない）
      await k.arrange({ ".pane-grid": { x: 40, y: 30, w: 470, only: ["#grid-scroll", "#grid-msg"] },
                        ".pane-options": { x: 540, y: 30, w: 360, only: [".gbox:has(#bg-mode-seg)"] } });
      await k.stage(".gbox:has(#bg-mode-seg) > :not(.gbox-title):not(fieldset:has(#bg-mode-seg)) { display: none !important; } "
        + "#pal-modal { align-items: start; justify-items: end; padding: 24px; } #pal-modal .modal-panel { width: 520px; } "
        + "#pal-modal .sheet-backdrop { background: transparent; } #pal-modal .pal-io, #pal-modal .pal-actions, #pal-modal .modal-body > p { display: none !important; }");
      k.wide(0);
      await k.park(700, 400);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#palette-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pal-modal").hidden), "パレット", 5000);
      await k.hold(0.5);
      for (const n of [2, 3]) {
        await k.press(`#pal-lanes .pal-lane:nth-child(${n}) .pal-btns .btn:first-child`);
        await k.hold(1.5);
      }
      // 始めのリソに戻して終わる（繰り返しのつなぎ目）
      await k.press("#pal-lanes .pal-lane:nth-child(1) .pal-btns .btn:first-child");
      await k.hold(0.6);
      await k.press("#pal-modal-close");
      await k.hold(0.8);
    },
  },
  {
    id: "s-pal-make",
    what: "「いまの色から作る」で自分の配色を作れる。色を押してつまみで直す。カラーコードを貼っても作れる",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await k.page.evaluate(() => document.querySelector("#palette-btn").scrollIntoView({ block: "center" }));
      await k.page.click("#palette-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pal-modal").hidden), "パレット", 5000);
      await k.look(["#pal-modal .modal-panel"]);
      await k.park(900, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#pal-new");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#pal-lanes .pal-lane").length >= 4), "自作の組", 5000);
      await k.hold(0.6);
      await k.press("#pal-lanes .pal-lane:nth-child(4) .pal-chips button:nth-child(3)");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pal-hsv").hidden), "つまみ", 5000);
      await k.hold(0.3);
      await k.dragThumb("#pal-hsv-h", 120, 0.8);
      await k.hold(0.6);
      await k.glide("#pal-import", 0.4);
      await k.page.click("#pal-import");
      await k.key("Control+v");   // 貼り付けたように見せる（キーの絵が出る）。中身は下で入れる
      await k.page.fill("#pal-import", "#f2418f, #4878da, #ffd23f, #3bceac, #ee6c4d, #6a4c93, #1b1b1e, #fdfcdc");
      await k.hold(0.6);
      await k.press("#pal-import-btn");
      await k.hold(1.6);
    },
  },
  {
    id: "s-swatch",
    what: "背景は見本の 8 色から選べる。「カスタムカラー」で色相・彩度・明度を好きに",
    async setup(k) {
      await ready(k, 9, [3, 3], { gap: 40, margin: 40 }, square().slice(0, 9));
      await k.arrange({ ".pane-grid": { x: 60, y: 30, w: 520, only: ["#grid-scroll", "#grid-msg"] },
                        ".pane-options": { x: 640, y: 30, w: 380, only: [".gbox:has(#bg-mode-seg)"] } });
      await k.stage(".gbox:has(#bg-mode-seg) > :not(.gbox-title):not(fieldset:has(#bg-mode-seg)) { display: none !important; }");
      await k.look([GT, "#grid", OT, "#swatches", "#bg-custom-btn"]);
      await k.park(900, 600);
    },
    async run(k) {
      await k.hold(0.8);
      for (const n of [4, 6, 2]) { await k.press(`#swatches > :nth-child(${n})`); await k.hold(0.7); }
      await k.press("#bg-custom-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#bg-custom-panel").hidden), "カスタムカラー", 5000);
      await k.look([GT, "#grid", OT, "#bg-custom-panel"], 0.5);
      await k.dragThumb("#hsv-s", 60, 0.6);
      await k.dragThumb("#hsv-h", 90, 0.8);
      await k.hold(0.8);
      await k.press("#bg-custom-btn");
      await k.press("#swatches > :nth-child(3)");   // 始めのマスタードに戻す
      await k.look([GT, "#grid", OT, "#swatches", "#bg-custom-btn"], 0.5);
      await k.hold(0.8);
    },
  },
  {
    id: "s-grad",
    what: "背景を「グラデーション」に … サムネイルの色から作る。「ほかの模様」で揺らぎの形だけ変わる。色を自分で選んでもいい",
    async setup(k) {
      await ready(k, 9, [3, 3], { gap: 32 }, square().slice(0, 9));
      await bgOut(k);
      await primeOutput(k);
      await k.look([OT, "#bg-mode-seg", OUT, "#output"]);
      await k.park(900, 650);
    },
    async run(k) {
      // **できあがりの見本集**にする（グリッドの見本より、書き出しの絵のほうが分かりやすい、と利用者）
      await k.hold(0.8);
      await k.press(pickRadio("bg-mode-seg", "gradient"));
      await bgSettled(k);
      await refresh(k);
      await k.hold(1.3);
      for (let i = 0; i < 2; i++) { await k.press("#bg-grad-shuffle"); await bgSettled(k); await refresh(k); await k.hold(1.1); }
      await k.press(pickRadio("bg-grad-src", "custom"));
      await bgSettled(k);
      await refresh(k);
      await k.hold(1.3);
      await k.press(pickRadio("bg-mode-seg", "pick"));   // 始めに戻す
      await refresh(k);
      await k.hold(0.6);
    },
  },
  {
    id: "s-img-tile",
    what: "背景の「画像」は全体表示かタイル（小・中・大）で敷ける。好きな画像を選んでもいい",
    async setup(k) {
      await ready(k, 9, [3, 3], { gap: 32 }, square().slice(0, 9));
      await k.page.route(/\/upload$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ url: "/uploads/fa4e010000000017.jpg" }) }));
      await bgOut(k);
      await primeOutput(k);
      await k.look([OT, "#bg-mode-seg", OUT, "#output"]);
      await k.park(900, 650);
    },
    async run(k) {
      // できあがりの見本集（利用者の案）
      await k.hold(0.8);
      await k.press(pickRadio("bg-mode-seg", "image"));
      await k.until(() => k.page.evaluate(() => /模様を敷きました/.test(document.querySelector("#bg-msg").textContent)), "既定の模様", 15000);
      await refresh(k);
      await k.hold(1.2);
      await k.press(pickRadio("bg-fit-seg", "tile"));
      for (const v of ["s", "l"]) { await k.press(pickRadio("bg-tile-seg", v)); await bgSettled(k); await refresh(k); await k.hold(1.0); }
      const fc = k.page.waitForEvent("filechooser");
      await k.press("#bg-image-btn");
      await (await fc).setFiles("promo/public/x-bg-logo.png");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#bg-image-reset").hidden), "画像", 20000);
      await bgSettled(k);
      await refresh(k);
      await k.hold(1.4);
      // 始めに戻す（撮影の片付け）
      for (const sel of ["#bg-image-reset", pickRadio("bg-tile-seg", "m"), pickRadio("bg-fit-seg", "cover"), pickRadio("bg-mode-seg", "pick")]) await k.page.click(sel).catch(() => {});
    },
  },
  {
    id: "s-none",
    what: "背景を「透過」にすると、背景が透明な PNG で保存できる。字の色は黒と白から選ぶ",
    async setup(k) {
      await ready(k, 9, [3, 3], { gap: 24 }, square().slice(0, 9));
      await keepField(k, "#bg-mode-seg"); await k.arrange(arrangeOut());
      await primeOutput(k);
      await k.look([OT, "#bg-mode-seg", OUT, "#output"]);
      await k.park(900, 650);
    },
    async run(k) {
      await k.hold(1.0);
      await k.press(pickRadio("bg-mode-seg", "none"));
      await k.hold(0.3);
      await refresh(k);
      await k.hold(1.3);
      await k.press(pickRadio("bg-ink-seg", "light"));
      await refresh(k);
      await k.hold(1.3);
      await k.press(pickRadio("bg-ink-seg", "dark"));
      await k.press(pickRadio("bg-mode-seg", "pick"));
      await refresh(k);
      await k.hold(0.8);
    },
  },
  {
    id: "s-bg-preview",
    what: "背景の決め方の見本集 … 色の選択・サムネの近似色・サムネの補色・グラデーション・画像・透過",
    async setup(k) {
      await ready(k, 9, [3, 3], { gap: 32 }, square().slice(0, 9));
      await bgOut(k);
      await k.stage("#bg-mode-seg ~ * { display: none !important; }");   // 細かい欄は隠す（決め方の違いだけを見せる）
      await primeOutput(k);
      await k.look([OT, "#bg-mode-seg", OUT, "#output"]);
      await k.park(900, 650);
    },
    async run(k) {
      // できあがりの見本集（グリッドの見本より書き出しの絵のほうが分かりやすい、と利用者）
      await k.hold(0.8);
      for (const v of ["near", "far", "gradient", "image", "none", "pick"]) {
        await k.press(pickRadio("bg-mode-seg", v));
        await bgSettled(k);
        if (v === "image") await k.until(() => k.page.evaluate(() => /模様を敷きました/.test(document.querySelector("#bg-msg").textContent)), "既定の模様", 15000).catch(() => {});
        await refresh(k);
        await k.hold(1.0);
      }
    },
  },
];
