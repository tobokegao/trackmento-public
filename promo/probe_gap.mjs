import { chromium } from "playwright";
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625, isMobile: true, hasTouch: true });
const pg = await ctx.newPage();
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
await pg.evaluate(() => {
  document.querySelector("#palette-btn").click();
  [...document.querySelectorAll(".pal-lane")][1].querySelector(".btn").click();
  document.querySelector("#pal-modal-close").click();
  const t = (n) => ({ source: "manual", title: "曲" + n, artist: "だれか", album: null,
                      image: "/no-cover.png", thumb: "/no-cover.png", external_url: null });
  window.__setGrid(3, 3, { title: "", showTitle: true, sidebar: true, numbers: true, margin: 16, gap: 16, bg: "ivory", bgCustom: null },
                   [t(1), t(2), t(3), t(4), t(5), t(6), t(7), t(8), t(9)]);
});
await pg.waitForTimeout(700);
await pg.evaluate(() => document.querySelector("#grid-scroll").scrollIntoView({ block: "center" }));
await pg.waitForTimeout(300);
const info = await pg.evaluate(() => {
  const gs = document.querySelector("#grid-scroll");
  const r = gs.getBoundingClientRect();
  const out = [];
  for (let dy = -3; dy <= 8; dy++) {
    const y = Math.round(r.bottom) + dy;
    const el = document.elementFromPoint(Math.round(r.x + r.width / 2), y);
    out.push({ dy, tag: el ? el.tagName + "." + (el.className || "").toString().slice(0, 24) : null,
               bg: el ? getComputedStyle(el).backgroundColor : null });
  }
  return { rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
           gsStyle: { bg: getComputedStyle(gs).backgroundColor, border: getComputedStyle(gs).borderBottom, h: gs.style.height },
           gridH: document.querySelector("#grid").getBoundingClientRect().height, rows: out };
});
console.log(JSON.stringify(info, null, 1));
const box = await pg.evaluate(() => { const r = document.querySelector("#grid-scroll").getBoundingClientRect();
  return { x: r.x, y: r.bottom - 12, width: r.width, height: 24 }; });
await pg.screenshot({ path: process.argv[2], clip: box });
await b.close();
