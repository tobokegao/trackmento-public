import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 1280, height: 900 } });
const errs = []; pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await pg.waitForFunction(() => document.querySelector('#sources input[value="vocadb"]'));
await pg.evaluate(() => {
  document.querySelectorAll('#sources input').forEach(i => { i.checked = i.value === "vocadb"; i.dispatchEvent(new Event("change", { bubbles: true })); });
  document.querySelector("#q").value = "ロストワンの号哭";
});
await pg.click("#search-btn");
await pg.waitForSelector(".result", { timeout: 30000 });
await pg.waitForTimeout(1200);
console.log(JSON.stringify(await pg.evaluate(() => {
  const rs = [...document.querySelectorAll(".result")].slice(0, 3);
  return rs.map(r => ({ t: r.querySelector(".t")?.textContent, a: r.querySelector(".a")?.textContent,
                        badge: r.querySelector(".badge")?.textContent,
                        img: r.querySelector("img")?.naturalWidth }));
}), null, 1));
await pg.screenshot({ path: process.argv[2], clip: { x: 300, y: 60, width: 320, height: 700 } });
console.log("エラー:", errs.length ? errs : "なし");
await b.close();
