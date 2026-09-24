// X に 1 機能ずつ載せる、数秒の動画のコマを撮る。
//   node promo/x_clips.mjs <出力ディレクトリ> [id,id,…|all|pc|phone]
// 撮る場面は promo/x_catalog.mjs（1 場面 = 1 本）。コマは <出力>/<id>/f000.png…。
// 16:9 に組んで MP4 と GIF にするのは scripts/make_x_clips.py。
// 手元のサーバー（PUBLIC_MODE=1、ポート 8000）が要る。
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { openPage, makeKit, record } from "./clip_kit.mjs";
import CATALOG from "./x_catalog.mjs";

const [outRoot, only = "all"] = process.argv.slice(2);
if (!outRoot) { console.error("使い方: node promo/x_clips.mjs <出力ディレクトリ> [id,id,…|all|pc|phone]"); process.exit(1); }
const ids = new Set(only.split(","));
const picked = CATALOG.filter((c) => only === "all" || ids.has(c.id) || ids.has(c.device ?? "pc"));
const unknown = [...ids].filter((i) => !["all", "pc", "phone"].includes(i) && !CATALOG.some((c) => c.id === i));
if (unknown.length) console.warn("台本に無い:", unknown.join(" "));

// 曲は紹介動画の静止画と同じ一覧から（grids/ は手元の並びで、中身が決まっていない）。**[TEST] の付いた曲は除く**
const TRACKS = JSON.parse(fs.readFileSync("promo/stills-tracks.json", "utf-8")).filter((t) => !/\[TEST\]/.test(t.artist));
// **画面は 16:9 で開く**（画面ぜんぶを撮る場面がそのまま 16:9 になるように）。
// 縦に長い窓を切り取る場面だけ、台本の viewport で高さを足す
const DEVICES = {
  pc: { viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2 },
  phone: { viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, hasTouch: true, isMobile: true },
};

const browser = await chromium.launch();
const failed = [];
for (const c of picked) {
  const dev = c.device ?? "pc";
  const opts = { ...DEVICES[dev], ...(c.viewport ? { viewport: c.viewport } : {}) };
  // **場面ごとに新しいページで撮る**。前の場面の状態（開いた窓・スクロール・パレット）を持ち越さないため
  const page = await openPage(browser, opts);
  const k = makeKit(page, TRACKS);
  try {
    if (c.setup) await c.setup(k);
    const n = await record(page, path.join(outRoot, c.id), c.clip ? c.clip(k) : null,
                           (shot) => c.run(k, shot), { id: c.id, device: dev, what: c.what }, c.follow);
    console.log(c.id, n, "コマ");
  } catch (e) {
    failed.push(c.id);
    console.error(c.id, "失敗:", e.message.split("\n")[0]);
  } finally {
    await page.context().close();
  }
}
await browser.close();
if (failed.length) { console.error("失敗した場面:", failed.join(" ")); process.exitCode = 1; }
