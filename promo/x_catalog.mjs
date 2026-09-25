// X に載せる 1 機能 1 本の動画の台本。撮るのは promo/x_clips.mjs、動画にするのは promo/render_x.mjs（src/XClip.tsx）。
//
// 1 本 = { id, what, setup?(k), run(k) }
//   what  … 台帳に載せる説明（投稿の本文の下書きにもなる）
//   setup … 撮る前の準備（曲を入れる・送る・**最初の構図 k.look と最初のカーソル k.park**）
//   run   … 撮る手順。k は clip_kit の makeKit の道具。カメラは k.look([…]) で行き先を変える
//
// 決まり:
// - **1 本は 3〜8 秒**。最初の 1 秒で「何の画面か」が分かるように、頭に 0.6〜1 秒の「ため」を置く
// - **終わりは始めと同じ構図に戻す**（X では短い動画が繰り返し再生される。絵の違いは XClip が終わりで溶かしてつなぐ）
// - 文字は動画に入れない（説明は投稿の本文。2026-09-25 の利用者の判断）
// - **1280 幅では 3×3 のマスが「小さい扱い」**（96px 未満）で × と曲名の帯が出ない。× を押す場面は 2×2 にする
// - 画面を送るのは撮る前だけ（k.scrollTo）。撮りながら送るとカメラと二重に動く
import fs from "node:fs";

// 動画サイトのサムネ風（16:9）の架空の曲。マスの形・サムネの入れ方の場面で使う
// **使うときに読む**（x_clips.mjs は台本を読み込んでから一覧を作るので、読み込んだ瞬間に読むと一覧がまだ無いことがある）
const nico = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks-wide.json", "utf-8"));
// 白黒の架空のジャケット（明るさを段階的に）。色で並べ替えの場面で使う
const mono = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks-mono.json", "utf-8"));   // 架空の 16:9 のサムネ（promo/fake_covers.py）

/** 背景色の場面の窓の置き方（k.arrange）。左にグリッドの窓（グリッドとメッセージと「できあがりを見る」）、右に出力オプション（背景色の欄だけ）、
    その下に「できあがり」の窓（見本と状態の一行）。1280x720 の画面にぜんぶ入る */
const ARRANGE_BG = {
  ".pane-grid": { x: 40, y: 40, w: 330, only: ["#grid-scroll", "#grid-msg", ".grid-actions"] },
  ".pane-options": { x: 400, y: 40, w: 330, only: [".gbox:has(#bg-mode-seg)"] },   // 2026-09-25 から欄はグループボックスの中（中の余白の欄は ARRANGE_BG_CSS で隠す）
  "#output": { x: 760, y: 40, w: 480 },
};
const ARRANGE_BG_CSS = ".gbox:has(#bg-mode-seg) > :not(.gbox-title):not(fieldset:has(#bg-mode-seg)), .grid-actions > :not(#preview-btn), #output .pane-body > :not(#out-shot):not(#out-msg) { display: none !important; } .grid-actions > #preview-btn { grid-column: 1 / -1; }";

/** 曲を n 個入れて、ジャケットがそろうまで待つ */
async function ready(k, n, size, opts = {}, list) {
  await k.seed(n, size, opts, list);
  await k.waitArt();
  await k.hold(0.5);   // 撮影前なので時計だけ進む
}

/** 出力オプションの「枠とサムネ」の三角を開く（既定で畳んである。2026-09-25 から。撮る前だけ） */
async function openCellsMore(k) {
  if (await k.page.getAttribute("#cells-more-btn", "aria-expanded") !== "true") await k.page.click("#cells-more-btn");
}

/** 並びをかき混ぜる（色で並べ替えの前に。seed は一覧の順に入れるので、そのままだと色がそろって見えない） */
function shuffled(list, seed = 7) {
  const a = [...list];
  let s = seed;
  for (let i = a.length - 1; i > 0; i--) {
    s = (s * 9301 + 49297) % 233280;
    const j = Math.floor(s / 233280 * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export default [
  {
    id: "color-sort",
    what: "「色で並べ替え」… サムネイルの主な色で、赤から紫の順に並べ直す。白黒のサムネイルは明るい順",
    async setup(k) {
      // **白黒のジャケットで見せる**（明るい順にそろうのがひと目で分かる。カラフルな絵だと色相の順は伝わりにくい、と利用者）
      await ready(k, 16, [4, 4], {}, shuffled(mono()));
      await k.scrollTo("#grid", 60);
      await k.look(["#grid"]);
      await k.park(1180, 660);
    },
    async run(k) {
      await k.hold(1.0);
      await k.look(["#grid", "#color-sort"], 0.7);
      await k.press("#color-sort", { sec: 0.7 });
      await k.look(["#grid"], 0.8);
      // 色を調べ終わるまで撮り続ける（「（n/N）」と数えている間も見せる）
      await k.live(() => k.page.evaluate(() => !/\d+\/\d+/.test(document.querySelector("#color-sort").textContent)), { min: 0.5, timeout: 15 });
      await k.hold(2.0);
    },
  },
  {
    id: "cell-ratio",
    what: "「マス枠」を横長 16:9 に … 動画サイトのサムネイルが左右で切れずに並ぶ",
    async setup(k) {
      await ready(k, 9, [3, 3], { title: "好きな音MAD" }, nico());
      await openCellsMore(k);
      await k.scrollTo("#cell-ratio-seg", 200);
      await k.look(["#grid", "fieldset:has(#cell-ratio-seg)"]);
      await k.park(1100, 600);
    },
    async run(k) {
      await k.hold(1.0);
      await k.press('#cell-ratio-seg label:has(input[value="16:9"])');
      await k.waitArt();
      await k.hold(2.0);
      await k.press('#cell-ratio-seg label:has(input[value="1:1"])');
      await k.hold(1.2);
    },
  },
  {
    id: "cell-fit",
    what: "「サムネ余白」… 「ぼかし背景」にすると、形の違うサムネも切らずに入る",
    async setup(k) {
      await ready(k, 9, [3, 3], { title: "好きな音MAD" }, nico());
      await openCellsMore(k);
      await k.scrollTo("#cell-fit-seg", 260);
      await k.look(["#grid", "fieldset:has(#cell-fit-seg) legend", "#cell-fit-seg"]);
      await k.park(1100, 600);
    },
    async run(k) {
      await k.hold(1.0);
      await k.press('#cell-fit-seg label:has(input[value="blur"])');
      await k.hold(2.0);
      await k.press('#cell-fit-seg label:has(input[value="crop"])');
      await k.hold(1.2);
    },
  },
  {
    id: "stash",
    what: "マスを減らしても曲は消えない … いったん外して取っておき、サイズを戻すと帰ってくる",
    async setup(k) {
      await ready(k, 9, [3, 3]);
      await k.scrollTo("#cols", 60);
      await k.look(["#grid", "#grid-msg", "#cols", "#rows"]);
      await k.park(1100, 500);
    },
    async run(k) {
      // **減らすのは縦**。横を減らすとマスが大きくなり、グリッドの枠の中でスクロールして下の段が隠れる
      const down = "#rows ~ .stepper button[data-step='-1']", up = "#rows ~ .stepper button[data-step='1']";
      await k.hold(1.0);
      await k.press(down);
      await k.hold(2.0);
      await k.press(up);
      await k.hold(1.6);
    },
  },
  {
    id: "lang",
    what: "右上の「EN」で、画面がまるごと英語に。もう一度押すと日本語に戻る",
    async setup(k) {
      await ready(k, 9, [3, 3]);
      k.wide();
      await k.park(900, 300);
    },
    async run(k) {
      await k.hold(1.0);
      await k.press("#lang-switch");
      await k.hold(2.2);
      await k.press("#lang-switch");
      await k.hold(1.2);
    },
  },
  {
    id: "undo-keys",
    what: "外したトラックは Ctrl+Z（Mac は ⌘+Z）で 1 手ずつ戻せる。30 手まで",
    async setup(k) {
      await ready(k, 4, [2, 2]);
      await k.scrollTo("#grid", 90);
      await k.look(["#grid", "#grid-msg"]);
      await k.park(900, 150);
    },
    async run(k) {
      await k.hold(0.8);
      for (const n of [4, 1]) {
        await k.glide(`#grid .cell:nth-child(${n})`, 0.3);   // × はマスに乗せたときに出る
        await k.press(`#grid .cell:nth-child(${n}) .rm`, { sec: 0.2 });
        await k.hold(0.5);
      }
      await k.hideCursor();
      await k.hold(0.6);
      for (let i = 0; i < 2; i++) { await k.key("Control+z"); await k.hold(0.7); }
      await k.hold(0.8);
    },
  },
  {
    id: "alt-arrows",
    what: "キーボードだけで並べ替え … 矢印でマスを移り、Alt（Option）＋矢印でトラックを持ったまま運ぶ",
    async setup(k) {
      await ready(k, 9, [3, 3]);
      await k.scrollTo("#grid", 90);
      await k.look(["#grid", "#grid-msg"]);
      await k.hideCursor();   // キーボードの場面なので矢印は出さない
      await k.page.focus("#grid .cell");
    },
    async run(k) {
      await k.hold(1.0);
      for (const key of ["Alt+ArrowRight", "Alt+ArrowRight", "Alt+ArrowDown", "Alt+ArrowDown"]) { await k.key(key); await k.hold(0.6); }
      await k.hold(0.6);
      // 元の場所へ運び戻す（繰り返し再生のつなぎ目で跳ねないように）
      for (const key of ["Alt+ArrowUp", "Alt+ArrowUp", "Alt+ArrowLeft", "Alt+ArrowLeft"]) { await k.key(key); await k.hold(0.4); }
      await k.hold(0.8);
    },
  },
  {
    id: "zoom-wheel",
    what: "「大きく見る」の中で、2 本指（Ctrl＋ホイール）でマスを拡大・縮小。並びの形ごとに大きさを覚える",
    async setup(k) {
      await ready(k, 64, [8, 8]);
      k.wide();
      await k.park(900, 300);
    },
    async run(k) {
      await k.hold(0.6);
      await k.press("#zoom-btn");
      await k.hold(0.8);
      await k.glide("#zoom-slot", 0.4);
      const [x, y] = [640, 380];
      for (let i = 0; i < 10; i++) { await k.ctrlWheel(x, y, -50); await k.hold(0.1); }
      await k.hold(1.0);
      for (let i = 0; i < 10; i++) { await k.ctrlWheel(x, y, 50); await k.hold(0.1); }
      await k.hold(0.6);
      await k.press("#zoom-modal-close");
      await k.hold(0.6);
    },
  },
  {
    id: "undo-buttons",
    what: "グリッドの下の「元に戻す」「やり直す」… スマホでも 30 回まで戻せて、戻したものをやり直せる",
    async setup(k) {
      await ready(k, 4, [2, 2]);
      await k.scrollTo("#grid", 70);
      await k.look(["#grid", "#grid-msg", ".grid-actions > .history"]);
      await k.park(900, 150);
    },
    async run(k) {
      await k.hold(0.8);
      for (const n of [4, 1]) {
        await k.glide(`#grid .cell:nth-child(${n})`, 0.3);   // × はマスに乗せたときに出る
        await k.press(`#grid .cell:nth-child(${n}) .rm`, { sec: 0.2 });
        await k.hold(0.4);
      }
      await k.press("#undo-btn");
      await k.hold(0.6);
      await k.press("#undo-btn", { sec: 0.2 });
      await k.hold(0.6);
      await k.press("#redo-btn");
      await k.hold(0.6);
      await k.press("#undo-btn");   // 始めと同じ 4 曲に戻して終わる（繰り返し再生のつなぎ目）
      await k.hold(1.0);
    },
  },
  {
    id: "bg-modes",
    what: "「背景」の決め方 … 「サムネの近似色」「サムネの補色」を選ぶと、並んだサムネイルから色を取る",
    async setup(k) {
      // 背景の色が見えるように、マスの間隔と余白を広めにする
      await ready(k, 9, [3, 3], { gap: 48, margin: 48, bg: "paper" });
      // **撮るあいだだけ、窓を並べ直す**（k.arrange）。背景色の欄は出力オプションのずっと下にあり、
      // そのままだとグリッド（色が変わるところ）と同じ画面に入らない
      await k.arrange(ARRANGE_BG); await k.stage(ARRANGE_BG_CSS);
      await k.look(["#grid", "fieldset:has(#bg-mode-seg) legend", "#bg-mode-seg", "#bg-cands", "#bg-msg"]);
      await k.park(1150, 650);
    },
    async run(k) {
      const pick = (v) => `#bg-mode-seg label:has(input[value="${v}"])`;
      await k.hold(1.0);
      await k.press(pick("near"));
      await k.until(() => k.page.evaluate(() => /選びました/.test(document.querySelector("#bg-msg").textContent)), "サムネイルの色", 20000);
      await k.hold(1.6);
      await k.press(pick("far"));
      await k.hold(1.6);
      await k.press(pick("pick"));   // 元の色に戻して終わる
      await k.hold(1.0);
    },
  },
  {
    id: "bg-image",
    what: "「背景」の「画像」… 選ぶとまず TRACKMENTO の模様、「画像を選ぶ」で端末の好きな画像に。曲名が読めるように、にぎやかな画像ほど薄く",
    async setup(k) {
      await ready(k, 9, [3, 3], { gap: 48, margin: 48, bg: "paper" });
      // **撮るあいだだけ、窓を並べ直す**（k.arrange）。背景色の欄は出力オプションのずっと下にあり、
      // そのままだとグリッド（色が変わるところ）と同じ画面に入らない
      await k.arrange(ARRANGE_BG); await k.stage(ARRANGE_BG_CSS);
      await k.look(["#grid", "fieldset:has(#bg-mode-seg) legend", "#bg-mode-seg", "#bg-image-box", "#bg-msg"]);
      await k.park(1150, 650);
    },
    async run(k) {
      await k.hold(1.0);
      // 「画像」を選ぶと、まず既定の TRACKMENTO の模様が敷かれる（2026-09-25 から。選ぶ窓は開かない）
      await k.press('#bg-mode-seg label:has(input[value="image"])');
      await k.until(() => k.page.evaluate(() => /模様を敷きました/.test(document.querySelector("#bg-msg").textContent)), "既定の模様", 10000);
      await k.hold(1.2);
      // 「画像を選ぶ…」で端末の画像に替える。選ぶ窓は写らないので、選んだあとの見本の変わり方を見せる
      const fc = k.page.waitForEvent("filechooser");
      await k.press("#bg-image-btn");
      await (await fc).setFiles("promo/public/x-bg-logo.png");   // Tobokegao のロゴ（利用者の絵。文字の部分だけを切り出し、16:9 の白地の真ん中に置いたもの）
      await k.until(() => k.page.evaluate(() => /画像を背景に/.test(document.querySelector("#bg-msg").textContent)), "背景の画像", 30000);
      await k.until(() => k.page.evaluate(() => /url\(/.test(document.querySelector("#grid").style.background)), "見本の画像", 10000);
      await k.hold(1.2);
      // **書き出しの画像（曲名リスト込み）まで見せる**。見本はマスの隙間にしか画像が見えないので（利用者の指摘）、
      // 「できあがりを見る」を押して、できあがりの窓の見本に寄る（端末の中で描くだけで、共有は作らない）
      // ボタンはグリッドの下なので、押す前にそこまで引いて映す（枠の外で押すと、何を押したか分からない。利用者の指摘）
      await k.look(["#grid", "#preview-btn", "fieldset:has(#bg-mode-seg) legend", "#bg-mode-seg"], 0.6);
      await k.press("#preview-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#out-shot").hidden && document.querySelector("#output-img").complete), "できあがりの見本", 60000);
      await k.hold(0.3);   // 窓まで送り終わるのを待つ（送るのはページの時計で動く）
      await k.look(["#output"], 0.8);
      await k.hold(3.0);
    },
  },
];
