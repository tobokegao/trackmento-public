import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true, locale: "ja-JP" });
const page = await ctx.newPage();
const errs = [];
page.on("pageerror", e => errs.push(String(e)));
page.on("console", m => { if (m.type() === "error") errs.push(m.text()); });
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2000);
await page.evaluate(() => { for (const p of document.querySelectorAll('.pane[data-collapsed="true"]')) p.dataset.collapsed = "false"; });
// HSV（カスタムカラー）のつまみ
await page.evaluate(() => { const b = [...document.querySelectorAll("button, .swatch")].find(e => /カスタム|自分/.test(e.textContent || "")); if (b) b.click(); });
await page.waitForTimeout(400);
const hsv = await page.evaluate(() => {
  const e = document.querySelector("#hsv-h"); if (!e) return null;
  const panel = document.querySelector("#bg-custom-panel"); if (panel) panel.hidden = false;
  e.scrollIntoView({ block: "center" });
  const b = e.getBoundingClientRect();
  const t = (e.value - e.min) / (e.max - e.min);
  return { cx: b.left + 9.5 + t * (b.width - 19), cy: b.top + b.height / 2, v: e.value,
           wrapped: e.parentElement.className, pad: !!e.parentElement.querySelector(".range-pad") };
});
console.log("hsv-h:", JSON.stringify(hsv));
if (hsv) {
  await page.mouse.move(hsv.cx, hsv.cy); await page.mouse.down();
  await page.mouse.move(hsv.cx + 60, hsv.cy, { steps: 8 }); await page.mouse.up();
  console.log("hsv-h ドラッグ後 =", await page.locator("#hsv-h").inputValue());
}
// レイアウトが崩れていないか（余白スライダーの幅が親と同じか）
console.log(JSON.stringify(await page.evaluate(() => {
  const e = document.querySelector("#margin"), w = e.parentElement, f = w.parentElement;
  return { input: e.getBoundingClientRect().width, wrap: w.getBoundingClientRect().width, field: f.getBoundingClientRect().width };
})));
console.log("errors:", errs.length ? errs : "なし");
await ctx.close(); await browser.close();
