import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.evaluate(() => { for (const p of document.querySelectorAll('.pane[data-collapsed="true"]')) p.dataset.collapsed = "false"; });
const bs = await page.evaluate(() => [...document.querySelectorAll(".btn")].filter(b => b.getBoundingClientRect().width > 10).slice(0, 3).map(b => {
  const r = b.getBoundingClientRect();
  return { w: +r.width.toFixed(3), h: +r.height.toFixed(3), x: r.x, y: r.y, sh: getComputedStyle(b).getPropertyValue("--sh").trim(), t: (b.textContent||"").trim().slice(0,6) };
}));
for (const [i, b] of bs.entries()) {
  await page.screenshot({ path: `C:/Users/amisi/AppData/Local/Temp/claude/z_top_${i}.png`, clip: { x: b.x + b.w - 8, y: b.y - 4, width: 14, height: 16 } });
  await page.screenshot({ path: `C:/Users/amisi/AppData/Local/Temp/claude/z_bot_${i}.png`, clip: { x: b.x - 4, y: b.y + b.h - 8, width: 16, height: 14 } });
}
console.log(JSON.stringify(bs));
await ctx.close(); await browser.close();
