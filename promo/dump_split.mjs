// 画面側の splitTitle の結果を書き出す（サーバー側と突き合わせる）
//   node promo/dump_split.mjs <入力 JSON: {px, maxW, titles:[...]}>
import { chromium } from "playwright";
import fs from "node:fs";
const inp = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
const browser = await chromium.launch();
const ctx = await browser.newContext({ locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__splitTitle && window.__loadShareFonts);
await page.evaluate(() => window.__loadShareFonts());
const out = await page.evaluate((i) => i.titles.map((t) => window.__splitTitle(t, i.px, i.maxW)), inp);
console.log(JSON.stringify(out, null, 1));
await ctx.close(); await browser.close();
