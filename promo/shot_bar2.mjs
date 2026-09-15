import { chromium, devices } from "playwright";
const out = process.argv[2];
const browser = await chromium.launch();
const ctx = await browser.newContext({ ...devices["Pixel 7"], locale: "ja-JP", deviceScaleFactor: 4 });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
const bars = page.locator(".pane-title");
const n = await bars.count();
let target = null, info = null;
for (let i = 0; i < n; i++) {
  const b = await bars.nth(i).boundingBox();
  if (b && b.height > 10) { target = b; info = await bars.nth(i).evaluate(e => ({ h: e.getBoundingClientRect().height })); break; }
}
console.log(JSON.stringify(info));
await page.screenshot({ path: out, clip: { x: target.x, y: target.y - 2, width: Math.min(240, target.width), height: target.height + 5 } });
await ctx.close(); await browser.close();
