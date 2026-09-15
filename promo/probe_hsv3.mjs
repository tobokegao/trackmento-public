// つまみの位置を変えながら、外枠と面取りの間にすきまが出るか調べる
import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.evaluate(() => {
  for (const p of document.querySelectorAll('.pane[data-collapsed="true"]')) p.dataset.collapsed = "false";
  document.querySelector("#bg-custom-panel").hidden = false;
  document.querySelector("#hsv-h").scrollIntoView({ block: "center" });
});
await page.waitForTimeout(400);
const out = [];
for (const v of [0, 17, 33, 50, 67, 90, 123, 180, 240, 300, 360]) {
  const b = await page.evaluate((v) => {
    const e = document.querySelector("#hsv-h"); e.value = String(v);
    const r = e.getBoundingClientRect(), t = (e.value - e.min) / (e.max - e.min);
    return { y: r.y, h: r.height, cx: r.left + 9.5 + t * (r.width - 19) };
  }, v);
  const f = `C:/Users/amisi/AppData/Local/Temp/claude/hv_${v}.png`;
  await page.screenshot({ path: f, clip: { x: b.cx - 14, y: b.y, width: 28, height: b.h } });
  out.push(v);
}
console.log(JSON.stringify(out));
await ctx.close(); await browser.close();
