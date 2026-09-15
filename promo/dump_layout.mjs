import { chromium } from "playwright";
const id = process.argv[2];
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto(`http://127.0.0.1:8000/?share=${id}`, { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
const out = await page.evaluate(() => {
  const L = window.__layout ? window.__layout(2400) : null;
  return L ? { W: L.W, H: L.H, scale: L.scale, fontS: L.fontS, lineH: L.lineH, ox: L.ox, oy: L.oy, pad: L.wrapPad, segs: L.wrapSegs.length, wrap: L.wrap, titleSize: L.titleSize } : "no hook";
});
console.log(JSON.stringify(out));
await ctx.close(); await browser.close();
