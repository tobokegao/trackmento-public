import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.evaluate(() => {
  for (const p of document.querySelectorAll('.pane[data-collapsed="true"]')) p.dataset.collapsed = "false";
  const panel = document.querySelector("#bg-custom-panel"); if (panel) panel.hidden = false;
  document.querySelector("#hsv-h").scrollIntoView({ block: "center" });
});
await page.waitForTimeout(500);
const b = await page.evaluate(() => {
  const e = document.querySelector("#hsv-h"), r = e.getBoundingClientRect();
  const t = (e.value - e.min) / (e.max - e.min);
  return { x: r.x, y: r.y, w: r.width, h: r.height, cx: r.left + 9.5 + t * (r.width - 19) };
});
// つまみを掴んで離す（受け皿で focus() が走る）
await page.mouse.move(b.cx, b.y + b.h / 2);
await page.mouse.down(); await page.mouse.move(b.cx + 1, b.y + b.h / 2); await page.mouse.up();
await page.waitForTimeout(300);
console.log("matches :focus-visible =", await page.evaluate(() => document.querySelector("#hsv-h").matches(":focus-visible")));
const b2 = await page.evaluate(() => {
  const e = document.querySelector("#hsv-h"), r = e.getBoundingClientRect();
  const t = (e.value - e.min) / (e.max - e.min);
  return { y: r.y, h: r.height, cx: r.left + 9.5 + t * (r.width - 19) };
});
await page.screenshot({ path: "C:/Users/amisi/AppData/Local/Temp/claude/hsv2.png", clip: { x: b2.cx - 18, y: b2.y - 6, width: 36, height: b2.h + 12 } });
await ctx.close(); await browser.close();
