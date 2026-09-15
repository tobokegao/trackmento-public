import { chromium } from "playwright";
const b = await chromium.launch();
const ctx = await b.newContext();
await ctx.addInitScript(() => {
  // 6 色で保存された古い組（移行の確認）と、地と文字が近すぎる組（番人の確認）
  localStorage.setItem("trackmento.palettes", JSON.stringify([
    { id: "uold", name: "むかしの組", hexes: ["#111111", "#222222", "#333333", "#444444", "#555555", "#666666"] },
    { id: "udark", name: "読めない組", hexes: ["#555555", "#666666", "#111111", "#222222", "#333333", "#444444", "#777777", "#888888"] },
  ]));
  localStorage.setItem("trackmento.palette", "udark");
});
const pg = await ctx.newPage();
const errs = [];
pg.on("pageerror", e => errs.push(String(e)));
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
const out = await pg.evaluate(() => {
  const g = (n) => getComputedStyle(document.documentElement).getPropertyValue("--color-" + n).trim();
  document.querySelector("#palette-btn").click();
  const lanes = [...document.querySelectorAll(".pal-lane")].map(l => ({
    name: l.querySelector(".pal-name").textContent,
    chips: l.querySelectorAll(".pal-chips > *").length,
    warn: l.querySelector(".pal-warn") ? l.querySelector(".pal-warn").textContent : null,
  }));
  return { lanes, paper: g("paper"), ink: g("ink"), mustard: g("mustard"),
           swatches: [...document.querySelectorAll('#swatches input[name="bg"]')].map(i => i.value) };
});
console.log(JSON.stringify(out, null, 1));
console.log("エラー:", errs.length ? errs : "なし");
await b.close();
