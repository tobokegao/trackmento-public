import { chromium } from "playwright";
import fs from "node:fs";
const b = await chromium.launch();
for (const dpr of [1, 2, 2.625, 3]) {
  const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: dpr });
  const pg = await ctx.newPage();
  await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
  await pg.waitForFunction(() => window.__setGrid);
  const info = await pg.evaluate(() => {
    const el = document.querySelector("#margin");
    el.scrollIntoView({ block: "center" });
    const b = el.getBoundingClientRect();
    return { box: [b.x, b.y, b.width, b.height],
             dot: getComputedStyle(document.documentElement).getPropertyValue("--dot").trim() };
  });
  await pg.waitForTimeout(200);
  const [x, y, w, h] = info.box;
  const png = await pg.screenshot({ clip: { x, y: y - 2, width: w, height: h + 4 } });
  fs.writeFileSync(`${process.argv[2]}/thumb-dpr${dpr}.png`, png);
  console.log("dpr", dpr, "dot", info.dot, "box", info.box.map(Math.round).join(","));
  await ctx.close();
}
await b.close();
