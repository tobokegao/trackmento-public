import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625,
  isMobile: true, hasTouch: true, locale: "ja-JP",
  userAgent: "Mozilla/5.0 (Linux; Android 16; motorola edge 60s pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
const b = await page.evaluate(() => {
  const t = [...document.querySelectorAll(".pane-title")].find(e => e.getBoundingClientRect().height > 10);
  const r = t.getBoundingClientRect();
  const h2 = t.querySelector("h2").getBoundingClientRect();
  return { x: r.x, y: r.y, w: r.width, h: r.height, h2r: h2.right };
});
console.log(JSON.stringify(b));
await page.screenshot({ path: "C:/Users/amisi/AppData/Local/Temp/claude/bar.png", clip: { x: b.x, y: b.y, width: b.w, height: b.h } });
await ctx.close(); await browser.close();
