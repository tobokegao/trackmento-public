// スライダーの「掴まないと動かない」を確かめる: 連打・溝タップ・ドラッグ
import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1100, height: 900 }, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
const fold = page.locator(".pane-options .fold").first();
if ((await fold.getAttribute("aria-expanded")) !== "true") { await fold.click(); await page.waitForTimeout(400); }
const el = page.locator("#margin");
await el.scrollIntoViewIfNeeded().catch(() => {});
const box = await el.boundingBox();
const val = async () => await el.inputValue();
const info = await page.evaluate(() => { const e = document.querySelector("#margin"); return { min: e.min, max: e.max, v: e.value }; });
const thumbX = (v) => box.x + 19 / 2 + ((v - info.min) / (info.max - info.min)) * (box.width - 19);
const y = box.y + box.height / 2;

const before = await val();
// 1) つまみの上を 8 回連打
for (let i = 0; i < 8; i++) { await page.mouse.click(thumbX(Number(before)), y); await page.waitForTimeout(30); }
const afterTaps = await val();
// 2) 溝（右端寄り）をタップ
await page.mouse.click(box.x + box.width - 6, y); await page.waitForTimeout(60);
const afterGroove = await val();
// 3) つまみを掴んで右へドラッグ
await page.mouse.move(thumbX(Number(afterGroove)), y);
await page.mouse.down();
await page.mouse.move(thumbX(Number(afterGroove)) + 60, y, { steps: 8 });
await page.mouse.up();
await page.waitForTimeout(80);
const afterDrag = await val();
console.log(JSON.stringify({ before, afterTaps, afterGroove, afterDrag }));
await ctx.close(); await browser.close();
