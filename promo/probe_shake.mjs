import { chromium } from "playwright";
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true });
const pg = await ctx.newPage();
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
const cols = Number(process.argv[2] || 3), rows = Number(process.argv[3] || 3);
await pg.evaluate(({ cols, rows }) => {
  const set = (id, v) => { const el = document.querySelector(id); el.value = v; el.dispatchEvent(new Event("change", { bubbles: true })); };
  set("#cols", cols); set("#rows", rows);
}, { cols, rows });
await pg.waitForTimeout(900);
const trace = await pg.evaluate(() => new Promise((res) => {
  const gs = document.querySelector("#grid-scroll");
  const out = []; let n = 0;
  const tick = () => {
    out.push([Math.round(gs.getBoundingClientRect().height), gs.scrollHeight - gs.clientHeight, gs.classList.contains("tsb-on") ? 1 : 0]);
    if (++n < 90) requestAnimationFrame(tick); else res(out);
  };
  requestAnimationFrame(tick);
}));
const info = await pg.evaluate(() => ({ cols: getComputedStyle(document.querySelector("#grid")).getPropertyValue("--cols"),
  gridH: Math.round(document.querySelector("#grid").getBoundingClientRect().height),
  cells: document.querySelectorAll("#grid .cell").length }));
let flips = 0;
for (let i = 1; i < trace.length; i++) if (trace[i].join() !== trace[i - 1].join()) flips++;
console.log(`${cols}x${rows}: cells=${info.cells} gridH=${info.gridH} 切り替わり ${flips} 回 / 状態`, [...new Set(trace.map(t => t.join("/")))].slice(0, 6));
await b.close();
