import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1440, height: 900 } });
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
await pg.evaluate(() => {
  const set = (id, v) => { const el = document.querySelector(id); el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
  set("#cols", 16); set("#rows", 16);
});
await pg.waitForTimeout(600);
const info = await pg.evaluate(() => {
  const g = document.querySelector("#grid"), sc = document.querySelector("#grid-scroll");
  const cell = g.querySelector(".cell");
  const r = cell ? cell.getBoundingClientRect() : null;
  return { grid: g.getBoundingClientRect().width, scrollH: sc.getBoundingClientRect().height,
           scrollTop: sc.scrollHeight, cells: g.querySelectorAll(".cell").length,
           cell: r ? [Math.round(r.width), Math.round(r.height)] : null };
});
console.log(JSON.stringify(info));
await pg.screenshot({ path: process.argv[2] });
await b.close();
