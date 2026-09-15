import { chromium } from "playwright";
const [url, out, w, h] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: +(w || 1200), height: +(h || 1400) }, deviceScaleFactor: 1, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
await page.screenshot({ path: out, fullPage: false });
await ctx.close(); await browser.close();
