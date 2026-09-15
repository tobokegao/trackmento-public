// 指での連打（タッチ）でも動かないか
import { chromium, devices } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ ...devices["Pixel 7"], locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2200);
const fold = page.locator(".pane-options .fold").first();
if ((await fold.getAttribute("aria-expanded")) !== "true") { await fold.click(); await page.waitForTimeout(400); }
const el = page.locator("#margin");
await el.scrollIntoViewIfNeeded().catch(() => {});
const box = await el.boundingBox();
const info = await page.evaluate(() => { const e = document.querySelector("#margin"); return { min: +e.min, max: +e.max, v: +e.value }; });
const thumbX = (v) => box.x + 19 / 2 + ((v - info.min) / (info.max - info.min)) * (box.width - 19);
const y = box.y + box.height / 2;
const val = async () => await el.inputValue();
const before = await val();
for (let i = 0; i < 8; i++) { await page.touchscreen.tap(thumbX(+before), y); await page.waitForTimeout(40); }
const afterTaps = await val();
await page.touchscreen.tap(box.x + box.width - 6, y); await page.waitForTimeout(80);
const afterGroove = await val();
console.log(JSON.stringify({ before, afterTaps, afterGroove }));
await ctx.close(); await browser.close();
