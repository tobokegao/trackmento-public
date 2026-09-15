// バー本体の縞と、題名・右端の列の縞が同じ行に来るか
import { chromium } from "playwright";
const browser = await chromium.launch();
for (const dpr of [2.625, 3, 4, 12]) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: dpr, isMobile: true, hasTouch: true, locale: "ja-JP" });
  const page = await ctx.newPage();
  await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
  await page.waitForTimeout(1600);
  const b = await page.evaluate(() => {
    const t = [...document.querySelectorAll(".pane-title")].find(e => e.getBoundingClientRect().height > 10);
    const r = t.getBoundingClientRect();
    const tail = t.querySelector(".tail").getBoundingClientRect();
    const h2 = t.querySelector("h2").getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height, tailL: tail.left, h2r: h2.right, h2l: h2.left };
  });
  const f = `C:/Users/amisi/AppData/Local/Temp/claude/al_${dpr}.png`;
  await page.screenshot({ path: f, clip: { x: b.x, y: b.y, width: b.w, height: b.h } });
  console.log(JSON.stringify({ dpr, ...b, f }));
  await ctx.close();
}
await browser.close();
