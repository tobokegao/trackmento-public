// 実機に近い画素密度でタッチ用スクロールバーの右辺を調べる
import { chromium } from "playwright";
const dpr = Number(process.argv[2] || 2.625);
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: dpr,
  isMobile: true, hasTouch: true, locale: "ja-JP",
  userAgent: "Mozilla/5.0 (Linux; Android 16; motorola edge 60s pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.evaluate(() => {
  const host = document.querySelector(".tsb-host") || document.querySelectorAll(".pane-body")[0];
  const d = document.createElement("div"); d.style.height = "3000px"; d.id = "spacer";
  host.append(d);
});
await page.waitForTimeout(1600);
const info = await page.evaluate(() => {
  const out = [];
  for (const el of document.querySelectorAll(".tsb")) {
    if (el.hidden) continue;
    const r = el.getBoundingClientRect();
    const th = el.querySelector(".tsb-thumb"), tr = th.getBoundingClientRect();
    const host = el.parentElement.querySelector(".tsb-host"), hr = host.getBoundingClientRect();
    out.push({ bar: [r.x, r.y, r.width, r.height], thumb: [tr.x, tr.y, tr.width, tr.height], host: [hr.x, hr.right] });
  }
  return out;
});
console.log(JSON.stringify(info));
if (info[0]) {
  const t = info[0];
  await page.screenshot({ path: "C:/Users/amisi/AppData/Local/Temp/claude/sb.png",
    clip: { x: t.bar[0] - 6, y: t.thumb[1] - 3, width: t.bar[2] + 12, height: 30 } });
  console.log("shot ok");
}
await ctx.close(); await browser.close();
