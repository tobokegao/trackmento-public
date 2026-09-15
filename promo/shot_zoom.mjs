import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errs = [];
pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
await pg.evaluate(() => {
  const set = (id, v) => { const el = document.querySelector(id); el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
  set("#cols", 16); set("#rows", 16);
});
await pg.waitForTimeout(400);
await pg.click("#zoom-btn");
await pg.waitForTimeout(500);
const info = await pg.evaluate(() => {
  const c = document.querySelector("#grid .cell").getBoundingClientRect();
  const s = document.querySelector("#grid-scroll").getBoundingClientRect();
  return { cell: [Math.round(c.width), Math.round(c.height)], box: [Math.round(s.width), Math.round(s.height)],
           inZoom: !!document.querySelector("#zoom-slot #grid-scroll") };
});
console.log("拡大:", JSON.stringify(info));
await pg.screenshot({ path: process.argv[2] });
await pg.keyboard.press("Escape");
await pg.waitForTimeout(400);
const back = await pg.evaluate(() => {
  const c = document.querySelector("#grid .cell").getBoundingClientRect();
  return { cell: [Math.round(c.width), Math.round(c.height)],
           home: !!document.querySelector(".pane-grid #grid-scroll"), modalHidden: document.querySelector("#zoom-modal").hidden };
});
console.log("戻り:", JSON.stringify(back));
console.log("エラー:", errs.length ? errs : "なし");
await b.close();
