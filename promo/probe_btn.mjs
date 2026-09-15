// ボタンの影（市松）の位相がボタンごとに同じか
import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 6, isMobile: true, hasTouch: true, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.evaluate(() => { for (const p of document.querySelectorAll('.pane[data-collapsed="true"]')) p.dataset.collapsed = "false"; });
const bs = await page.evaluate(() => [...document.querySelectorAll(".btn")].map((b, i) => {
  const r = b.getBoundingClientRect();
  return { i, w: +r.width.toFixed(2), h: +r.height.toFixed(2), x: r.x, y: r.y, sh: getComputedStyle(b).getPropertyValue("--sh").trim(), txt: (b.textContent || "").trim() };
}).filter(b => b.w > 10).slice(0, 8));
for (const b of bs) {
  await page.screenshot({ path: `C:/Users/amisi/AppData/Local/Temp/claude/btn_${b.i}.png`, clip: { x: b.x - 4, y: b.y - 4, width: b.w + 14, height: b.h + 14 } });
}
console.log(JSON.stringify(bs));
await ctx.close(); await browser.close();
