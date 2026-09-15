import { chromium } from "playwright";
const [id] = process.argv.slice(2);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto(`http://127.0.0.1:8000/?share=${id}`, { waitUntil: "networkidle" });
await page.waitForTimeout(3000);
const r = await page.evaluate(() => {
  const out = {};
  for (const q of ["1:1", "4:5", "16:9", "9:16", "free"]) {
    const t0 = performance.now();
    const L = window.__layoutFor ? window.__layoutFor(q, 2400) : null;
    out[q] = { ms: Math.round(performance.now() - t0), cell: L ? Math.round(600 * L.scale) : null };
  }
  return out;
});
console.log(JSON.stringify(r));
await ctx.close(); await browser.close();
