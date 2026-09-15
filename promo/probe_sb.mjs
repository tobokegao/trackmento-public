import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625,
  isMobile: true, hasTouch: true, locale: "ja-JP",
  userAgent: "Mozilla/5.0 (Linux; Android 16; motorola edge 60s pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.evaluate(() => { const h = document.querySelector(".tsb-host") || document.querySelectorAll(".pane-body")[0]; const d = document.createElement("div"); d.style.height="3000px"; h.append(d); });
await page.waitForTimeout(1600);
console.log(JSON.stringify(await page.evaluate(() => {
  const bar = [...document.querySelectorAll(".tsb")].find(b => !b.hidden);
  const host = bar.parentElement.querySelector(".tsb-host");
  const chain = [];
  let e = host;
  while (e && e !== document.body) {
    const cs = getComputedStyle(e), r = e.getBoundingClientRect();
    chain.push({ cls: e.className || e.tagName, right: r.right, bw: cs.borderRightWidth, bc: cs.borderRightColor, pr: cs.paddingRight, bg: cs.backgroundColor });
    e = e.parentElement;
  }
  return { bar: bar.getBoundingClientRect().right, chain };
}), null, 1));
await ctx.close(); await browser.close();
