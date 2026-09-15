import { chromium } from "playwright";
const b = await chromium.launch();
const pg = await b.newPage();
const errs = [];
pg.on("pageerror", e => errs.push(String(e)));
pg.on("console", m => { if (m.type() === "error") errs.push("console: " + m.text()); });
await pg.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
const out = await pg.evaluate(() => {
  const g = (n) => getComputedStyle(document.documentElement).getPropertyValue("--color-" + n).trim();
  const snap = () => ({ paper: g("paper"), ink: g("ink"), paper3: g("paper-3"), rule: g("rule"), muted: g("muted"), mustard: g("mustard") });
  const swatches = () => [...document.querySelectorAll('#swatches input[name="bg"]')].map(i => i.value);
  const riso = { sw: swatches(), ...snap() };
  document.querySelector("#palette-btn").click();
  const lanes = [...document.querySelectorAll(".pal-lane")].map(l => ({
    name: l.querySelector(".pal-name").textContent,
    chips: l.querySelectorAll(".pal-chips > *").length,
    warn: !!l.querySelector(".pal-warn"),
  }));
  const use = [...document.querySelectorAll(".pal-lane")][1].querySelector(".btn");
  use.click();
  const pop = { sw: swatches(), ...snap() };
  return { riso, lanes, pop };
});
console.log(JSON.stringify(out, null, 1));
console.log("エラー:", errs.length ? errs : "なし");
await b.close();
