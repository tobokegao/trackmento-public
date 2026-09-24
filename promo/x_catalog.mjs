// X に載せる 1 機能 1 本の動画の台本。撮るのは promo/x_clips.mjs、組むのは scripts/make_x_clips.py。
//
// 1 本 = { id, what, device?, viewport?, follow?, setup?(k), clip?(k), run(k, shot) }
//   what   … 台帳に載せる説明（投稿の本文の下書きにもなる）
//   follow … 撮る範囲を毎コマ測り直す（既定は最初の 1 回だけ。範囲が伸び縮みすると窓が跳ねる）
//   device … "pc"（既定。1280x720）か "phone"
//   clip   … 撮る範囲を返す関数を返す（clip_kit の rect*）。無ければ画面ぜんぶ
//   run    … 撮る手順。k は clip_kit の makeKit の道具
//
// 決まり:
// - **1 本は 3〜8 秒**。最初の 1 秒で「何の画面か」が分かるように、頭に 0.6〜1 秒の「ため」を置く
// - **終わりは始めと同じ状態に戻す**（X では短い動画が繰り返し再生されるので、つなぎ目で跳ねない）
// - 文字は動画に入れない（説明は投稿の本文。2026-09-25 の利用者の判断）
// - **3×3 のマスは小さい扱い**（1280 幅の画面ではマスが 96px 未満で、× と曲名の帯が隠れる）。
//   × を押す場面は 2×2 にする
import fs from "node:fs";
import { rectUnion } from "./clip_kit.mjs";

// 動画サイトのサムネ（16:9）の曲。マスの形・サムネの入れ方の場面で使う
const NICO = JSON.parse(fs.readFileSync("promo/stills-tracks-nico.json", "utf-8"));

/** 曲を n 個入れて、ジャケットがそろうまで待つ */
async function ready(k, n, size, opts = {}, list) {
  await k.seed(n, size, opts, list);
  await k.waitArt();
  await k.page.waitForTimeout(500);
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
    what: "「色で並べ替え」… ジャケットの主な色で、赤から紫の順に並べ直す。白黒のジャケットは最後に明るい順",
    async setup(k) {
      await ready(k, 16, [4, 4], {}, shuffled(k.tracks).slice(0, 16));
      // グリッドの下のボタンは「色で並べ替え」だけにする（並んだボタンまで入れると縦に長くなり、動画の中で小さくなる）
      await k.stage(".grid-actions > :not(#color-sort), .pane-grid .note { display: none !important; }");
      await k.scrollTo("#grid", 70);
      await k.park(1000, 400);
    },
    clip: () => rectUnion("#grid", "#grid-msg", "#color-sort"),
    async run(k, shot) {
      await k.hold(shot, 1.0);
      await k.press("#color-sort", shot);
      // 色を調べ終わるまで撮り続ける（「（n/N）」と数えている間も見せる）
      for (let i = 0; i < 60; i++) {
        await shot(); await k.tick();
        if (!(await k.page.evaluate(() => /\d+\/\d+/.test(document.querySelector("#color-sort").textContent))) && i > 8) break;
      }
      await k.hold(shot, 1.8);
    },
  },
  {
    id: "cell-ratio",
    what: "「マスの形」を横長 16:9 に … 動画サイトのサムネが左右で切れずに並ぶ",
    async setup(k) {
      await ready(k, 9, [3, 3], { title: "好きな音MAD" }, NICO);
      await k.scrollTo("#cell-ratio-seg", 200);
      await k.park(1100, 600);
    },
    clip: () => rectUnion("#grid", "fieldset:has(#cell-ratio-seg) legend", "#cell-ratio-seg"),
    async run(k, shot) {
      await k.hold(shot, 1.0);
      await k.press('#cell-ratio-seg label:has(input[value="16:9"])', shot);
      await k.page.waitForTimeout(300);
      await k.waitArt();
      await k.hold(shot, 2.0);
      await k.press('#cell-ratio-seg label:has(input[value="1:1"])', shot);
      await k.page.waitForTimeout(300);
      await k.hold(shot, 1.2);
    },
  },
  {
    id: "cell-fit",
    what: "「サムネの入れ方」… 「ぼかして埋める」にすると、形の違うサムネも切らずに入る",
    async setup(k) {
      await ready(k, 9, [3, 3], { title: "好きな音MAD" }, NICO);
      await k.scrollTo("#cell-fit-seg", 260);
      await k.park(1100, 600);
    },
    clip: () => rectUnion("#grid", "fieldset:has(#cell-fit-seg) legend", "#cell-fit-seg"),
    async run(k, shot) {
      await k.hold(shot, 1.0);
      await k.press('#cell-fit-seg label:has(input[value="blur"])', shot);
      await k.page.waitForTimeout(400);
      await k.hold(shot, 2.0);
      await k.press('#cell-fit-seg label:has(input[value="crop"])', shot);
      await k.page.waitForTimeout(300);
      await k.hold(shot, 1.2);
    },
  },
  {
    id: "stash",
    what: "マスを減らしても曲は消えない … いったん外して取っておき、サイズを戻すと帰ってくる",
    async setup(k) {
      await ready(k, 9, [3, 3]);
      await k.scrollTo("#cols", 60);
      await k.park(1100, 500);
    },
    clip: () => rectUnion("#grid", "#grid-msg", "#cols", "#rows"),
    async run(k, shot) {
      // **減らすのは縦**。横を減らすとマスが大きくなり、グリッドの枠の中でスクロールして下の段が隠れる
      const down = "#rows ~ .stepper button[data-step='-1']", up = "#rows ~ .stepper button[data-step='1']";
      await k.hold(shot, 1.0);
      await k.press(down, shot);
      await k.page.waitForTimeout(300);
      await k.hold(shot, 2.0);
      await k.press(up, shot);
      await k.page.waitForTimeout(300);
      await k.hold(shot, 1.6);
    },
  },
  {
    id: "lang",
    what: "右上の「EN」で、画面がまるごと英語に。もう一度押すと日本語に戻る",
    async setup(k) {
      await ready(k, 9, [3, 3]);
      await k.park(900, 300);
    },
    async run(k, shot) {
      await k.hold(shot, 1.0);
      await k.press("#lang-switch", shot);
      await k.page.waitForTimeout(300);
      await k.hold(shot, 2.2);
      await k.press("#lang-switch", shot);
      await k.page.waitForTimeout(300);
      await k.hold(shot, 1.2);
    },
  },
  {
    id: "undo-keys",
    what: "外したトラックは Ctrl+Z（Mac は ⌘+Z）で 1 手ずつ戻せる。30 手まで",
    async setup(k) {
      await ready(k, 4, [2, 2]);
      await k.scrollTo("#grid", 90);
      await k.park(760, 90);
    },
    clip: () => rectUnion("#grid", "#grid-msg"),
    async run(k, shot) {
      await k.hold(shot, 0.8);
      for (const n of [4, 1]) {
        await k.page.hover(`#grid .cell:nth-child(${n})`);   // × はマスに乗せたときに出る
        await k.press(`#grid .cell:nth-child(${n}) .rm`, shot);
        await k.hold(shot, 0.5);
      }
      await k.park(760, 90);
      await k.hold(shot, 0.6);
      for (let i = 0; i < 2; i++) {
        await k.page.keyboard.press("Control+z");
        await k.hold(shot, 0.7);
      }
      await k.hold(shot, 0.8);
    },
  },
  {
    id: "alt-arrows",
    what: "キーボードだけで並べ替え … 矢印でマスを移り、Alt（Option）＋矢印でトラックを持ったまま運ぶ",
    async setup(k) {
      await ready(k, 9, [3, 3]);
      await k.scrollTo("#grid", 90);
      await k.park(-50, -50);   // キーボードの場面なので矢印は出さない
    },
    clip: () => rectUnion("#grid", "#grid-msg"),
    async run(k, shot) {
      await k.page.focus("#grid .cell");
      await k.hold(shot, 1.0);
      for (const key of ["Alt+ArrowRight", "Alt+ArrowRight", "Alt+ArrowDown", "Alt+ArrowDown"]) {
        await k.page.keyboard.press(key);
        await k.hold(shot, 0.6);
      }
      await k.hold(shot, 0.6);
      // 元の場所へ運び戻す（繰り返し再生のつなぎ目で跳ねないように）
      for (const key of ["Alt+ArrowUp", "Alt+ArrowUp", "Alt+ArrowLeft", "Alt+ArrowLeft"]) {
        await k.page.keyboard.press(key);
        await k.hold(shot, 0.4);
      }
      await k.hold(shot, 0.8);
    },
  },
  {
    id: "zoom-wheel",
    what: "「大きく見る」の中で、2 本指（Ctrl＋ホイール）でマスを拡大・縮小。並びの形ごとに大きさを覚える",
    async setup(k) {
      await ready(k, 64, [8, 8]);
      await k.park(900, 300);
    },
    async run(k, shot) {
      await k.hold(shot, 0.6);
      await k.press("#zoom-btn", shot);
      await k.page.waitForTimeout(400);
      await k.hold(shot, 0.8);
      await k.park(640, 380);
      for (let i = 0; i < 10; i++) { await k.ctrlWheel(640, 380, -50); await shot(); await k.tick(); }
      await k.hold(shot, 1.0);
      for (let i = 0; i < 10; i++) { await k.ctrlWheel(640, 380, 50); await shot(); await k.tick(); }
      await k.hold(shot, 0.6);
      await k.press("#zoom-modal-close", shot);
      await k.page.waitForTimeout(300);
      await k.hold(shot, 0.6);
    },
  },
];
