// いろいろな画素密度・拡大率でタイトルバーの縞を数える（6 本目が出ないことの確認）
import { chromium } from "playwright";
const browser = await chromium.launch();
for (const dpr of [1, 2, 2.625, 3, 3.5, 4, 5.25, 12]) {
  const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: dpr,
    isMobile: true, hasTouch: true, locale: "ja-JP" });
  const page = await ctx.newPage();
  await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
  await page.waitForTimeout(1800);
  const b = await page.evaluate(() => {
    const t = [...document.querySelectorAll(".pane-title")].find(e => e.getBoundingClientRect().height > 10);
    const r = t.getBoundingClientRect(), h2 = t.querySelector("h2").getBoundingClientRect();
    return { x: r.x, y: r.y, w: r.width, h: r.height, h2r: h2.right };
  });
  const f = `C:/Users/amisi/AppData/Local/Temp/claude/bar_${dpr}.png`;
  await page.screenshot({ path: f, clip: { x: b.x, y: b.y, width: b.w, height: b.h } });
  console.log(JSON.stringify({ dpr, bar: b, file: f }));
  await ctx.close();
}
await browser.close();
