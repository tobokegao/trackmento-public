import { chromium } from "playwright";
import fs from "fs";
const sd = process.argv[2], id = process.argv[3];
const pil = JSON.parse(fs.readFileSync(`${sd}/pilw.json`, "utf-8"));
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto(`http://127.0.0.1:8000/?share=${id}`, { waitUntil: "networkidle" });
await page.waitForTimeout(3000);
const res = await page.evaluate((pil) => {
  const c = document.createElement("canvas").getContext("2d");
  const out = {};
  for (const kind of ["title", "artist"]) {
    c.font = `${kind === "title" ? 700 : 400} 142px "IBM Plex Sans JP", sans-serif`;
    out[kind] = {};
    for (const ch of Object.keys(pil[kind])) out[kind][ch] = [Math.round(Math.round(c.measureText(ch).width*64)/64), Math.round(c.measureText(ch).width * 1000) / 1000];
  }
  return out;
}, pil);
let bad = 0, tot = 0, worst = [];
for (const kind of ["title", "artist"]) for (const ch of Object.keys(pil[kind])) {
  tot++;
  const d = res[kind][ch][0] - pil[kind][ch][0];
  if (d !== 0) { bad++; worst.push(`${kind} ${JSON.stringify(ch)} pil=${pil[kind][ch][1]} cv=${res[kind][ch][1]} 丸め差=${d}`); }
}
console.log(`ちがう字: ${bad}/${tot}`);
console.log(worst.slice(0, 20).join("\n"));
await ctx.close(); await browser.close();
