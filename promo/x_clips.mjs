// X に 1 機能ずつ載せる短い動画の素材を撮る。
//   node promo/x_clips.mjs [id,id,…|all]
// 撮る場面は promo/x_catalog.mjs（1 場面 = 1 本）。素材は promo/public/xclips/<id>/{take.mp4,events.json}。
// 動画にするのは promo/render_x.mjs（Remotion の XClip）。
// 手元のサーバー（PUBLIC_MODE=1、ポート 8000）が要る。
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { openPage, makeKit } from "./clip_kit.mjs";
import CATALOG from "./x_catalog.mjs";

const only = process.argv[2] ?? "all";
const ids = new Set(only.split(","));
const picked = CATALOG.filter((c) => only === "all" || ids.has(c.id));
const unknown = [...ids].filter((i) => i !== "all" && !CATALOG.some((c) => c.id === i));
if (unknown.length) console.warn("台本に無い:", unknown.join(" "));
const OUT = path.resolve("promo/public/xclips");

// 曲は紹介動画の静止画と同じ一覧から（grids/ は手元の並びで、中身が決まっていない）。**[TEST] の付いた曲は除く**
const TRACKS = JSON.parse(fs.readFileSync("promo/stills-tracks.json", "utf-8")).filter((t) => !/\[TEST\]/.test(t.artist));
// **画面は 16:9 で開き、ぜんぶを撮る**（寄るのは Remotion のカメラ）。倍率 2 で撮るので、2 倍まで寄ってもぼやけない
const PC = { viewport: { width: 1280, height: 720 }, deviceScaleFactor: 2 };

const browser = await chromium.launch();
const failed = [];
for (const c of picked) {
  // **場面ごとに新しいページで撮る**。前の場面の状態（開いた窓・スクロール・パレット）を持ち越さないため
  const page = await openPage(browser, PC);
  const k = makeKit(page, TRACKS);
  const dir = path.join(OUT, c.id);
  // **撮影で本番の R2 に上げた画像を記録する**（背景の画像の場面は /upload を通る。手元のサーバーも .env の R2 を使うため）。
  // 消すのは scripts/clean_x_uploads.py（記録した分だけを消す。利用者の画像には触れない）
  const uploaded = [];
  page.on("response", async (r) => { if (r.url().endsWith("/upload") && r.ok()) { try { uploaded.push((await r.json()).url); } catch { /* 読めなければ記録しない */ } } });
  try {
    if (c.setup) await c.setup(k);
    k.start(dir);
    await c.run(k);
    const n = await k.finish(dir, { id: c.id, what: c.what });
    if (uploaded.length) fs.writeFileSync(path.join(dir, "uploads.json"), JSON.stringify(uploaded));
    console.log(c.id, n, "コマ", (n / 30).toFixed(1), "秒");
  } catch (e) {
    failed.push(c.id);
    console.error(c.id, "失敗:", e.message.split("\n")[0]);
  } finally {
    await page.context().close();
  }
}
await browser.close();
if (failed.length) { console.error("失敗した場面:", failed.join(" ")); process.exitCode = 1; }
