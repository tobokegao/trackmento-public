// 幅の違うボタンを並べて、影の市松の位相がそろうか見る
import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 6, isMobile: true, hasTouch: true, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(1800);
const out = await page.evaluate(() => {
  const host = document.createElement("div");
  host.style.cssText = "position:fixed;left:10px;top:10px;z-index:9999;background:#f2efe6;padding:10px;display:flex;gap:14px;align-items:flex-start";
  for (const w of [40, 41, 42, 43, 60.5]) {
    const b = document.createElement("button");
    b.className = "btn"; b.textContent = "x";
    b.style.cssText = `min-height:0;padding:0;width:${w}px;height:30px`;
    host.append(b);
  }
  document.body.append(host);
  return [...host.children].map(b => { const r = b.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; });
});
await page.waitForTimeout(200);
for (const [i, b] of out.entries())
  await page.screenshot({ path: `C:/Users/amisi/AppData/Local/Temp/claude/bw_${i}.png`, clip: { x: b.x - 2, y: b.y - 2, width: b.w + 10, height: b.h + 10 } });
console.log(JSON.stringify(out));
await ctx.close(); await browser.close();
