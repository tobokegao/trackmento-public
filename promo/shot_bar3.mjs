// 実機に近い画素密度でタイトルバーの下端を調べる
import { chromium } from "playwright";
const out = process.argv[2], dpr = Number(process.argv[3] || 2.625);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: dpr,
  isMobile: true, hasTouch: true, locale: "ja-JP",
  userAgent: "Mozilla/5.0 (Linux; Android 16; motorola edge 60s pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
const bars = page.locator(".pane-title");
let b = null;
for (let i = 0; i < await bars.count(); i++) { const r = await bars.nth(i).boundingBox(); if (r && r.height > 10) { b = r; break; } }
await page.screenshot({ path: out, clip: { x: b.x, y: b.y, width: Math.min(200, b.width), height: b.height } });
console.log(JSON.stringify({ h: b.h ?? b.height, dpr }));
await ctx.close(); await browser.close();
