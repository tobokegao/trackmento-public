import { chromium } from "playwright";
const sid = process.argv[2];
const browser = await chromium.launch();
const ctx = await browser.newContext({ locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto(`http://127.0.0.1:8000/?share=${sid}`, { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__layout && window.__loadShareFonts);
await page.waitForTimeout(1500);
console.log(JSON.stringify(await page.evaluate(async () => {
  await window.__loadShareFonts();
  window.__clearCharW && window.__clearCharW();
  const L = window.__layout();
  return { W: L.W, H: L.H, scale: L.scale, fontS: L.fontS, lineH: L.lineH, sbW: L.sbW, sbH: L.sbH,
           sbCols: L.sbCols, side: L.side, sbFlow: L.sbFlow, sbPlan: L.sbPlan, titleSize: L.titleSize,
           titleH: L.titleH, ox: L.ox, oy: L.oy, cols: window.__st ? window.__st().cols : null };
})));
await ctx.close(); await browser.close();
