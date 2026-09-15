// 共有ページの見た目を撮る（曲名リストのリンク表示の確認用）。node promo/shot_share.mjs <id> <出力>
import { chromium } from "playwright";
const [id, out] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 900, height: 1200 }, locale: "ja-JP", deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto(`http://127.0.0.1:8000/s/${id}`, { waitUntil: "networkidle" });
const li = page.locator("li").first();
await li.scrollIntoViewIfNeeded();
const box = await page.locator("ol").boundingBox();
await page.screenshot({ path: out, clip: { x: box.x, y: box.y, width: box.width, height: Math.min(box.height, 300) } });
await ctx.close(); await browser.close();
