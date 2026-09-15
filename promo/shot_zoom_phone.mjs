import { chromium, devices } from "playwright";
const b = await chromium.launch();
const ctx = await b.newContext({ ...devices["Pixel 5"] });
const pg = await ctx.newPage();
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
await pg.evaluate(() => { const set=(i,v)=>{const e=document.querySelector(i);e.value=v;e.dispatchEvent(new Event("change",{bubbles:true}));}; set("#cols",16); set("#rows",16); });
await pg.waitForTimeout(400);
await pg.screenshot({ path: process.argv[2] });
await pg.click("#zoom-btn");
await pg.waitForTimeout(500);
console.log(JSON.stringify(await pg.evaluate(() => {
  const c = document.querySelector("#grid .cell").getBoundingClientRect();
  const slot = document.querySelector("#zoom-slot");
  return { cell: Math.round(c.width), overflow: slot.scrollHeight - slot.clientHeight };
})));
await pg.screenshot({ path: process.argv[3] });
await b.close();
