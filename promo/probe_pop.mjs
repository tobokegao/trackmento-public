import { chromium } from "playwright";
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true });
const pg = await ctx.newPage();
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
if (process.argv[3] === "pop") {
  await pg.evaluate(() => {
    document.querySelector("#palette-btn").click();
    [...document.querySelectorAll(".pal-lane")][1].querySelector(".btn").click();
    document.querySelector("#pal-modal-close").click();
  });
}
await pg.waitForTimeout(500);
// 出力オプションのつまみまでスクロール
await pg.evaluate(() => document.querySelector("#margin").scrollIntoView({ block: "center" }));
await pg.waitForTimeout(300);
await pg.screenshot({ path: process.argv[2] });
// グリッド枠の下も
await pg.evaluate(() => document.querySelector("#grid-scroll").scrollIntoView({ block: "center" }));
await pg.waitForTimeout(300);
const box2 = await pg.evaluate(() => {
  const r = document.querySelector("#grid-scroll").getBoundingClientRect();
  return { x: Math.max(0, r.x - 6), y: r.bottom - 26, width: Math.min(400, r.width + 12), height: 52 };
});
await pg.screenshot({ path: process.argv[2].replace(".png", "-grid.png"), clip: box2 });
await b.close();
