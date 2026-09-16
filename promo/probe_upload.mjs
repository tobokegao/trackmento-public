import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1280, height: 950 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => window.__setGrid);
// 送信中の窓だけを見たいので、関数を直接呼ぶ（本物の共有は R2 を汚すため）
const seen = await pg.evaluate(async () => {
  const out = [];
  const g = (s) => document.querySelector(s);
  window.__openUpload ? window.__openUpload() : null;
  return out;
});
// 直接呼べないので、実際に共有ボタンを押して窓が出るかを見る
await pg.evaluate(() => {
  const t = (n) => ({ source: "manual", title: "曲" + n, artist: "だれか", album: null,
                      image: "/no-cover.png", thumb: "/no-cover.png", external_url: null });
  window.__setGrid(2, 2, { title: "テスト", showTitle: true, sidebar: true, numbers: true, margin: 16, gap: 16, bg: "paper", bgCustom: null },
                   [t(1), t(2), t(3), t(4)]);
});
await pg.waitForTimeout(600);
await pg.evaluate(() => { const b = document.querySelector("#share-btn"); b.disabled = false; b.click(); });
// 窓が出た瞬間を捉える
try {
  await pg.waitForSelector("#up-modal:not([hidden])", { timeout: 20000 });
  const info = await pg.evaluate(() => ({
    title: document.querySelector("#up-modal-title").textContent,
    pct: document.querySelector("#up-pct").textContent,
    note: document.querySelector("#up-note").textContent,
    track: document.querySelector("#up-track").textContent.trim(),
    href: document.querySelector("#up-track a")?.href,
  }));
  console.log(JSON.stringify(info, null, 1));
  await pg.screenshot({ path: process.argv[2] });
} catch (e) {
  console.log("窓が出なかった:", e.message);
}
await pg.waitForTimeout(3000);
console.log("エラー:", errs.length ? errs : "なし");
await b.close();
