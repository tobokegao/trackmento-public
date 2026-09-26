// X に載せる、サイトのページを知らせる動画（2026-09-27）。決まりは x_catalog.mjs の頭と同じ。
// 「使い方の動画」（/howto）の告知用。題を押すと、その操作の短い動画が流れるところまでを見せる。

const CLIP = "#sp-share-target";   // 押す問い「YouTube のアプリから直接送れますか？」（利用者の指定）

/** 画面をなめらかに送る（撮りながら。出だしと終わりをゆるめる） */
async function scrollEase(k, y1, sec) {
  const y0 = await k.page.evaluate(() => window.scrollY);
  const n = Math.max(1, Math.round(sec * 30));
  for (let i = 1; i <= n; i++) {
    const t = i / n, e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    await k.page.evaluate((y) => window.scrollTo(0, y), y0 + (y1 - y0) * e);
    await k.frame();
  }
}
/** 要素を画面の縦の位置 top（CSS px）に置くときの scrollY */
const yFor = (k, sel, top) => k.page.evaluate(({ sel, top }) => window.scrollY + document.querySelector(sel).getBoundingClientRect().top - top, { sel, top });
/** 本文の段（main）の幅だけを、16:9 で映す四角 */
async function column(k, pad = 48) {
  const r = await k.page.evaluate(() => { const b = document.querySelector("main").getBoundingClientRect(); return { x: b.left, w: b.width }; });
  const w = r.w + pad * 2, h = w * 9 / 16;
  return { x: r.x - pad, y: (720 - h) / 2, w, h };
}

export default [
  {
    id: "howto-intro",
    what: "「使い方の動画」のページ。知りたいことの題を押すと、その操作の数秒の動画が流れる（題は YouTube のアプリから直接送れますか？）",
    async setup(k) {
      await k.page.goto("http://127.0.0.1:8000/howto", { waitUntil: "domcontentloaded" });
      for (let i = 0; i < 30; i++) { await k.page.clock.runFor(100); await new Promise((r) => setTimeout(r, 50)); }
      await k.page.evaluate(() => document.fonts && document.fonts.ready);
      // **ページの動画はコマ送りで撮る**。止めた時計のままだと <video> だけ実時間で流れ、コマ撮りでは早回しに見える。
      // 操作の帯（controls）は撮るあいだだけ外す（止めた動画に帯が出たままになり、流れて見えないため）
      await k.page.evaluate((sel) => { const v = document.querySelector(sel + " video"); v.removeAttribute("controls"); }, CLIP);
      await k.page.evaluate(() => window.scrollTo(0, 0));
      k.lookRect(await column(k, 120), 0);
      await k.park(1010, 560);
    },
    async run(k) {
      await k.hold(1.6);                                                    // 題「使い方の動画」と頭の説明
      await scrollEase(k, await yFor(k, CLIP, 300), 1.8);                   // 「スマホで使う」の問いまで送る
      k.lookRect(await column(k, 48), 0.6);
      await k.hold(0.6);
      await k.press(CLIP + " summary");
      await k.hideCursor();
      // 開いたら動画を頭から 1 コマずつ送って撮る（止めた時計の外で流れないよう、毎コマ止めてから位置を決める）
      await k.until(() => k.page.evaluate((sel) => { const v = document.querySelector(sel + " video"); return v.readyState >= 2 && v.duration > 0; }, CLIP), "動画", 30000);
      await k.page.evaluate((sel) => { const v = document.querySelector(sel + " video"); v.pause(); v.__t = 0; }, CLIP);
      k.setOnFrame(() => k.page.evaluate((sel) => new Promise((res) => {
        const v = document.querySelector(sel + " video");
        v.pause();
        v.__t = (v.__t + 1 / 30) % v.duration;
        v.addEventListener("seeked", () => res(), { once: true });
        v.currentTime = v.__t;
      }), CLIP));
      await scrollEase(k, await yFor(k, CLIP, 40), 0.9);                   // 題と答えと動画が 1 画面に入るよう送る
      await k.hold(0.8);
      k.lookRect(await k.page.evaluate((sel) => {                            // 答えの文と動画に寄る（文の頭が切れないよう、文から含める）
        const t = document.querySelector(sel + " .clip-body p").getBoundingClientRect();
        const b = document.querySelector(sel + " video").getBoundingClientRect();
        return { x: b.left - 16, y: t.top - 12, w: b.width + 32, h: b.bottom - t.top + 24 };
      }, CLIP), 0.8);
      const dur = await k.page.evaluate((sel) => document.querySelector(sel + " video").duration, CLIP);
      await k.hold(dur - 1.2);
      k.lookRect(await column(k, 48), 0.8);
      await k.hold(1.4);
    },
  },
];
