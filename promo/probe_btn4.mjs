import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.evaluate(() => { for (const p of document.querySelectorAll('.pane[data-collapsed="true"]')) p.dataset.collapsed = "false"; });
const bs = await page.evaluate(() => [...document.querySelectorAll(".btn")].filter(b => b.getBoundingClientRect().width > 10 && !b.disabled).slice(0, 2).map(b => {
  const r = b.getBoundingClientRect();
  return { w: +r.width.toFixed(3), h: +r.height.toFixed(3), x: r.x, y: r.y, sh: getComputedStyle(b).getPropertyValue("--sh").trim(), op: getComputedStyle(b).opacity, t: (b.textContent||"").trim().slice(0,6) };
}));
for (const [i, b] of bs.entries()) {
  await page.screenshot({ path: `C:/Users/amisi/AppData/Local/Temp/claude/e_tr_${i}.png`, clip: { x: b.x + b.w - 12, y: b.y - 3, width: 20, height: 20 } });   // 右上
  await page.screenshot({ path: `C:/Users/amisi/AppData/Local/Temp/claude/e_bl_${i}.png`, clip: { x: b.x - 3, y: b.y + b.h - 12, width: 20, height: 20 } });   // 左下
}
console.log(JSON.stringify(bs));
await ctx.close(); await browser.close();
