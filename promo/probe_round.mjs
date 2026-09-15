import { chromium } from "playwright";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 300, height: 200 }, deviceScaleFactor: 2.625 });
const page = await ctx.newPage();
await page.setContent(`<div id=a style="width:100px;height:20px;background:red"></div>`);
console.log(JSON.stringify(await page.evaluate(() => {
  const e = document.querySelector("#a");
  const out = {};
  e.style.width = "round(down, 100%, 7px)";
  out.pctRound = getComputedStyle(e).width;
  e.style.width = "";
  e.style.clipPath = "polygon(round(down, 100%, 7px) 0, 100% 0, 100% 100%, 0 100%)";
  out.clipRound = getComputedStyle(e).clipPath;
  out.supports = CSS.supports("width", "round(down, 100%, 7px)");
  return out;
})));
await ctx.close(); await browser.close();
