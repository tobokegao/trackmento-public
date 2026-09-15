// スライダーの「掴まないと動かない」を確かめる
//   1) つまみの上を連打  2) つまみの真横（溝）を連打  3) 真横をドラッグ
//   4) 見出しの文字を長押し  5) つまみを掴んでドラッグ（これだけ動く）
import { chromium, devices } from "playwright";
const touch = process.argv[2] === "touch";
const browser = await chromium.launch();
const ctx = await browser.newContext(touch ? { ...devices["Pixel 7"], locale: "ja-JP" }
                                           : { viewport: { width: 1100, height: 900 }, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2200);
const fold = page.locator(".pane-options .fold").first();
if ((await fold.getAttribute("aria-expanded")) !== "true") { await fold.click(); await page.waitForTimeout(400); }
const el = page.locator("#margin");
await el.scrollIntoViewIfNeeded().catch(() => {});
const box = await el.boundingBox();
const info = await page.evaluate(() => { const e = document.querySelector("#margin"); return { min: +e.min, max: +e.max }; });
const thumbX = (v) => box.x + 19 / 2 + ((v - info.min) / (info.max - info.min)) * (box.width - 19);
const y = box.y + box.height / 2;
const val = async () => await el.inputValue();
const tap = async (x, yy) => touch ? page.touchscreen.tap(x, yy) : page.mouse.click(x, yy);
const out = {};
out.before = await val();
for (let i = 0; i < 8; i++) { await tap(thumbX(+out.before), y); await page.waitForTimeout(30); }
out.つまみ連打 = await val();
for (let i = 0; i < 8; i++) { await tap(thumbX(+out.つまみ連打) + 14, y); await page.waitForTimeout(30); }
out.真横連打 = await val();
// 真横からドラッグ
const sx = thumbX(+out.真横連打) + 14;
if (touch) { /* タッチのドラッグは touchscreen に無いので pointer で */ }
await page.mouse.move(sx, y); await page.mouse.down();
await page.mouse.move(sx + 70, y, { steps: 8 }); await page.mouse.up();
await page.waitForTimeout(80);
out.真横ドラッグ = await val();
// 見出しの長押し
const lab = page.locator('label[for="margin"]');
const lb = await lab.boundingBox();
await page.mouse.move(lb.x + lb.width / 2, lb.y + lb.height / 2);
await page.mouse.down(); await page.waitForTimeout(700); await page.mouse.up();
await page.waitForTimeout(60);
out.見出し長押し = await val();
// つまみを掴んでドラッグ
const tx = thumbX(+out.見出し長押し);
await page.mouse.move(tx, y); await page.mouse.down();
await page.mouse.move(tx + 70, y, { steps: 8 }); await page.mouse.up();
await page.waitForTimeout(80);
out.つまみドラッグ = await val();
// 6) 指で「真横をタップして滑らせる」（touchstart → touchmove）。実機で動いていた操作
if (touch) {
  const v0 = await val();
  const sx2 = thumbX(+v0) + 16;
  await page.evaluate(([x, y]) => {
    const el = document.querySelector("#margin");
    const mk = (type, cx) => { const t = new Touch({ identifier: 1, target: el, clientX: cx, clientY: y });
      return new TouchEvent(type, { touches: type === "touchend" ? [] : [t], targetTouches: type === "touchend" ? [] : [t],
        changedTouches: [t], bubbles: true, cancelable: true }); };
    el.dispatchEvent(mk("touchstart", x));
    for (let i = 1; i <= 8; i++) el.dispatchEvent(mk("touchmove", x + i * 10));
    el.dispatchEvent(mk("touchend", x + 80));
  }, [sx2, y]);
  await page.waitForTimeout(80);
  out["真横タップして滑らせる"] = await val();
}
console.log(JSON.stringify(out, null, 1));
await ctx.close(); await browser.close();
