// 記事に貼る静止画を撮る（動きが要らないもの）。
//   node promo/shots.mjs <出力ディレクトリ> [対象]
// 対象: listed（共有のチェック欄）／find（みんなのグリッドを探す画面）／all
// find は「載せてもいい」と印の付いた共有が要るので、**別に立てたサーバー**（既定 8001）を見る。
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const [outRoot, only = "all"] = process.argv.slice(2);
const APP = process.env.APP_URL || "http://127.0.0.1:8000";
const FIND = process.env.FIND_URL || "http://127.0.0.1:8001";
const want = (n) => only === "all" || only === n;
fs.mkdirSync(outRoot, { recursive: true });

const browser = await chromium.launch();

/** 切り取って 1 枚だけ保存する */
async function shot(page, name, clip) {
  const file = path.join(outRoot, `shot-${name}.png`);
  await page.screenshot({ path: file, clip });
  console.log(name, "→", file);
}

// ---- 1. 共有のところにあるチェック欄 ----
if (want("listed")) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2, locale: "ja-JP" });
  const p = await ctx.newPage();
  await p.goto(APP + "/", { waitUntil: "networkidle" });
  await p.waitForFunction(() => window.__setGridUI);
  await p.evaluate(() => document.querySelector(".listed").scrollIntoView({ block: "center" }));
  await p.waitForTimeout(400);
  const clip = await p.evaluate(() => {
    const a = document.querySelector(".grid-actions").getBoundingClientRect();
    const b = document.querySelectorAll(".msg-under")[0].getBoundingClientRect();
    const x = Math.max(0, a.x - 10), y = Math.max(0, a.y - 10);
    return { x, y, width: a.width + 20, height: b.bottom - y + 10 };
  });
  await shot(p, "listed", clip);
  await ctx.close();
}

// ---- 2. 「みんなのグリッドを探す」画面 ----
if (want("find")) {
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 2, locale: "ja-JP" });
  const p = await ctx.newPage();
  await p.goto(FIND + "/find?q=" + encodeURIComponent("感電"), { waitUntil: "networkidle" });
  await p.waitForTimeout(500);
  const clip = await p.evaluate(() => {
    const m = document.querySelector("main").getBoundingClientRect();
    return { x: 0, y: 0, width: Math.min(1000, m.right + 24), height: Math.min(900, m.bottom + 24) };
  });
  await shot(p, "find", clip);
  await ctx.close();
}

await browser.close();
