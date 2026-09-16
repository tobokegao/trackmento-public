// 記事に添える「窓ごとの数秒 GIF」のコマを撮る。
//   node promo/gif_windows.mjs <出力ディレクトリ> [search|results|grid|options|all]
// PNG のコマを <出力ディレクトリ>/<場面>/ に並べる。GIF への変換は scripts/make_gifs.py が行う。
// **操作はゆっくり**にする（見る人が目で追えるように、1 手ごとに数コマ入れる）。
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const [outRoot, only = "all"] = process.argv.slice(2);
const FPS = 10;
const TRACKS = JSON.parse(fs.readFileSync("grids/default.json", "utf-8")).cells.filter(Boolean);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__setGrid);

/** 指定の秒数ぶん、その場のコマを撮る（何も起きていない間の「ため」にも使う） */
async function hold(shot, sec) {
  const n = Math.max(1, Math.round(sec * FPS));
  for (let i = 0; i < n; i++) { await shot(); await page.waitForTimeout(1000 / FPS); }
}

/** 場面を 1 つ撮る。clip は撮る範囲を返す関数（画面が動いても追従できるように） */
async function scene(name, clipOf, steps) {
  const dir = path.join(outRoot, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  let i = 0;
  const shot = async () => {
    const clip = await page.evaluate(clipOf);
    await page.screenshot({ path: path.join(dir, `f${String(i++).padStart(3, "0")}.png`), clip });
  };
  await steps(shot);
  console.log(name, i, "コマ");
}

const rectOf = (sel) => new Function("", `
  const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();
  return { x: Math.max(0, r.x - 8), y: Math.max(0, r.y - 8), width: r.width + 16, height: r.height + 16 };`);

const rectPair = (a, b) => new Function("", `
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  const q = document.querySelector(${JSON.stringify(b)}).getBoundingClientRect();
  const x = Math.min(p.x, q.x) - 8, y = Math.min(p.y, q.y) - 8;
  return { x: Math.max(0, x), y: Math.max(0, y),
           width: Math.max(p.right, q.right) - x + 8, height: Math.max(p.bottom, q.bottom) - y + 8 };`);

const seed = (n) => page.evaluate(({ tracks, n }) => {
  window.__setGrid(3, 3, { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true,
                           margin: 16, gap: 16, bg: "mustard", bgCustom: null }, tracks.slice(0, n));
  document.querySelector("#title").value = "私を構成する9曲";   // 入力欄にも出す（見た目のため）
}, { tracks: TRACKS, n });

/** a の上端から b の下端までを撮る（窓まるごとだと縦に長くなりすぎる） */
const rectSpan = (a, b) => new Function("", `
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  const q = document.querySelector(${JSON.stringify(b)}).getBoundingClientRect();
  const x = Math.max(0, p.x - 8), y = Math.max(0, p.y - 8);
  return { x, y, width: p.width + 16, height: q.bottom - y + 8 };`);

// ---- 1. 検索の窓 ----
if (only === "all" || only === "search") {
  await seed(0);
  await page.waitForTimeout(400);
  await scene("search", rectPair(".pane-search", ".pane-results"), async (shot) => {
    await hold(shot, 0.6);
    await page.click("#q");
    await page.type("#q", "感電", { delay: 160 });
    await hold(shot, 0.5);
    await page.click("#search-btn");
    for (let i = 0; i < 25; i++) { await shot(); await page.waitForTimeout(100); }
    await hold(shot, 1.2);
  });
}

// ---- 2. 候補の窓 ----
if (only === "all" || only === "results") {
  // 候補が要るので、先に検索だけ済ませておく（撮らない）
  if (!(await page.$(".result"))) {
    await seed(0);
    await page.fill("#q", "感電");
    await page.click("#search-btn");
    await page.waitForSelector(".result", { timeout: 20000 });
    await page.waitForTimeout(800);
  }
  await scene("results", rectPair(".pane-results", ".pane-grid"), async (shot) => {
    await hold(shot, 0.6);
    const items = await page.$$(".result");
    for (const it of items.slice(0, 3)) {
      await it.click();
      await hold(shot, 0.8);
    }
    await hold(shot, 0.8);
  });
}

// ---- 3. グリッドの窓 ----
if (only === "all" || only === "grid") {
  await seed(9);
  // ジャケットが出そろうまで待つ（読み込み中の市松が写り込まないように）
  await page.waitForFunction(() => {
    const imgs = [...document.querySelectorAll("#grid img")];
    return imgs.length > 0 && imgs.every(i => i.complete && i.naturalWidth > 0);
  }, null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(500);
  await scene("grid", rectSpan(".pane-grid", "#grid-msg"), async (shot) => {
    await hold(shot, 0.6);
    await page.click("#grid .cell:nth-child(1)");        // 1 つ目を選ぶ
    await hold(shot, 0.9);
    await page.click("#grid .cell:nth-child(5)");        // 5 つ目と入れ替え
    await hold(shot, 1.2);
    await page.click("#zoom-btn");                       // 大きく見る
    await hold(shot, 1.0);
    await page.click("#zoom-modal-close");
    await hold(shot, 0.8);
  });
}

// ---- 4. 出力オプションの窓 ----
if (only === "all" || only === "options") {
  await scene("options", rectSpan(".pane-options", "#custom-color, .swatches, #swatches"), async (shot) => {
    await hold(shot, 0.6);
    for (const sel of ['input[name="ratio"][value="1:1"]', 'input[name="ratio"][value="9:16"]',
                       'input[name="ratio"][value="16:9"]']) {
      await page.click(`label:has(${sel})`);
      await hold(shot, 0.7);
    }
    const sw = await page.$$('#swatches label');
    for (const s of [sw[3], sw[5], sw[1]]) { await s.click(); await hold(shot, 0.6); }
    await hold(shot, 0.8);
  });
}

await browser.close();
