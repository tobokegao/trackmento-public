import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625,
  isMobile: true, hasTouch: true, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.evaluate(() => {
  for (const p of document.querySelectorAll('.pane[data-collapsed="true"]')) p.dataset.collapsed = "false";
  document.querySelector("#margin").scrollIntoView({ block: "center" });
});
await page.waitForTimeout(600);
const el = page.locator("#margin");
const box = await el.boundingBox();
const val = () => el.inputValue();
const ta = await page.evaluate(() => getComputedStyle(document.querySelector("#margin")).touchAction);
console.log("touch-action =", ta, "start =", await val());
// 1) 溝を連打
for (let i = 0; i < 5; i++) await page.touchscreen.tap(box.x + box.width * 0.8, box.y + box.height / 2);
console.log("溝を連打 →", await val());
// 2) つまみの真横をタップして滑らす
const r = await page.evaluate(() => { const e = document.querySelector("#margin"); const b = e.getBoundingClientRect();
  const t = (e.value - e.min) / (e.max - e.min); return b.left + 9.5 + t * (b.width - 19); });
await page.mouse.move(r + 30, box.y + box.height / 2);
await page.mouse.down(); await page.mouse.move(r + 120, box.y + box.height / 2, { steps: 8 }); await page.mouse.up();
console.log("真横から滑らす →", await val());
// 3) ラベルを長押し
const lb = await page.locator('label[for="margin"]').boundingBox();
await page.touchscreen.tap(lb.x + 10, lb.y + lb.height / 2);
console.log("ラベルをタップ →", await val());
// 4) つまみを掴んで動かす（効かなければならない）
await page.mouse.move(r, box.y + box.height / 2);
await page.mouse.down(); await page.mouse.move(r + 100, box.y + box.height / 2, { steps: 10 }); await page.mouse.up();
console.log("つまみを掴む →", await val());
await ctx.close(); await browser.close();
