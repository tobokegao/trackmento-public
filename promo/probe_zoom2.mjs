import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
// 曲を入れてから拡大し、マスを選んで編集欄が窓の中に出るか、入れ替えが効くかを見る
await pg.evaluate(() => {
  const t = (n) => ({ source: "manual", title: "曲" + n, artist: "だれか", album: null,
                      image: "/no-cover.png", thumb: "/no-cover.png", external_url: null });
  window.__setGrid(16, 16, { title: "テスト", showTitle: true, sidebar: true, numbers: true, margin: 16, gap: 16, bg: "paper", bgCustom: null },
                   [t(1), t(2), t(3)]);
});
await pg.waitForTimeout(300);
await pg.click("#zoom-btn");
await pg.waitForTimeout(500);
await pg.click("#grid .cell:nth-child(1)");
await pg.waitForTimeout(400);
console.log(JSON.stringify(await pg.evaluate(() => {
  const ed = document.querySelector("#editor");
  const gs = document.querySelector("#grid-scroll").getBoundingClientRect();
  const slot = document.querySelector("#zoom-slot");
  return { editorInZoom: !!document.querySelector("#zoom-slot > #editor"), editorHidden: ed.hidden,
           editorTop: Math.round(ed.getBoundingClientRect().top), box: Math.round(gs.width),
           overflow: slot.scrollHeight - slot.clientHeight, title: document.querySelector("#e-title").value };
})));
await pg.screenshot({ path: process.argv[2] });
await pg.keyboard.press("Escape");
await pg.waitForTimeout(300);
console.log(JSON.stringify(await pg.evaluate(() => ({
  editorHome: !!document.querySelector(".pane-search > #editor"),
  gridHome: !!document.querySelector(".pane-grid #grid-scroll"),
}))));
console.log("エラー:", errs.length ? errs : "なし");
await b.close();
