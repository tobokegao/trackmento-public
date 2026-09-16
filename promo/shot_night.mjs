import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1280, height: 1000 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
await pg.evaluate(() => {
  const t = (n) => ({ source: ["itunes","bandcamp","youtube","otodb","manual","nicovideo"][n % 6], title: "曲" + n, artist: "だれか", album: null,
                      image: "/no-cover.png", thumb: "/no-cover.png", external_url: null });
  window.__setGrid(3, 3, { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true, margin: 16, gap: 16, bg: "night", bgCustom: null },
                   Array.from({ length: 9 }, (_, i) => t(i + 1)));
  document.querySelector("#palette-btn").click();
  const lanes = [...document.querySelectorAll(".pal-lane")];
  lanes[2].querySelector(".btn").click();          // ナイト
  document.querySelector("#pal-modal-close").click();
});
await pg.waitForTimeout(700);
console.log(JSON.stringify(await pg.evaluate(() => {
  const g = (n) => getComputedStyle(document.documentElement).getPropertyValue("--color-" + n).trim();
  return { ground: document.documentElement.dataset.ground,
           tokens: Object.fromEntries(["paper","paper-2","paper-3","ink","muted","bar","bar-dark","hl","hl-dim","shadow","on-light","on-dark"].map(k => [k, g(k)])) };
})));
await pg.screenshot({ path: process.argv[2] });
console.log("エラー:", errs.length ? errs : "なし");
await b.close();
