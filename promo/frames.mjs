import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
const [mp4, outDir, nStr] = process.argv.slice(2);
const n = Number(nStr || 8);
fs.mkdirSync(outDir, { recursive: true });
const b = await chromium.launch();
const pg = await b.newPage({ viewport: { width: 500, height: 1000 } });
await pg.setContent("<body style=\"margin:0;background:#000\"><video id=v style=\"width:100%\" muted></video>");
await pg.evaluate((src) => { document.querySelector("#v").src = src; }, pathToFileURL(mp4).href);
await pg.waitForFunction(() => { const v = document.querySelector("#v"); return v.readyState >= 2 && v.duration > 0; }, null, { timeout: 30000 });
const dur = await pg.evaluate(() => document.querySelector("#v").duration);
console.log("長さ", dur.toFixed(2), "秒");
for (let i = 0; i < n; i++) {
  const t = dur * (i + 0.5) / n;
  await pg.evaluate((t) => new Promise((res) => {
    const v = document.querySelector("#v");
    v.onseeked = () => res();
    v.currentTime = t;
  }), t);
  await pg.waitForTimeout(120);
  await pg.locator("#v").screenshot({ path: path.join(outDir, `f${String(i).padStart(2, "0")}.png`) });
}
console.log("書き出し", n, "枚");
await b.close();
