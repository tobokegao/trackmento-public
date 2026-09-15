import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1440, height: 900 } });
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
await pg.evaluate(() => { const set=(i,v)=>{const e=document.querySelector(i);e.value=v;e.dispatchEvent(new Event("change",{bubbles:true}));}; set("#cols",16); set("#rows",16); });
await pg.waitForTimeout(300);
await pg.click("#zoom-btn");
await pg.waitForTimeout(600);
console.log(JSON.stringify(await pg.evaluate(() => {
  const r = (el) => { const x = el.getBoundingClientRect(); return [Math.round(x.top), Math.round(x.bottom), Math.round(x.width), Math.round(x.height)]; };
  const panel = document.querySelector("#zoom-modal .modal-panel");
  const slot = document.querySelector("#zoom-slot");
  const gs = document.querySelector("#grid-scroll");
  return { panel: r(panel), slot: r(slot), gs: r(gs), slotClient: [slot.clientWidth, slot.clientHeight],
           slotScroll: [slot.scrollWidth, slot.scrollHeight], vh: innerHeight };
}), null, 1));
await b.close();
