// 実際の描画と同じ値で maxW と折り位置を出す
import { chromium } from "playwright";
const sid = process.argv[2];
const browser = await chromium.launch();
const ctx = await browser.newContext({ locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto(`http://127.0.0.1:8000/?share=${sid}`, { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__layout && window.__loadShareFonts);
await page.waitForTimeout(1500);
console.log(JSON.stringify(await page.evaluate(async () => {
  await window.__loadShareFonts();
  window.__clearCharW && window.__clearCharW();
  const L = window.__layout();
  const S = L.scale, sc = (v) => Math.round(v * S);
  const colW = Math.floor((L.sbW - 80 * (L.sbCols - 1)) / L.sbCols);
  const c = document.createElement("canvas").getContext("2d");
  const fs = Math.max(8, sc(L.fontS));
  c.font = `700 ${fs}px "IBM Plex Sans JP", sans-serif`;
  const fT = c.font;
  c.font = `400 ${Math.max(8, sc(L.fontS * 0.8))}px Silkscreen, monospace`;
  const nw = c.measureText("00").width + sc(L.fontS * 0.8);
  const maxW = colW * S - nw;
  const t = window.__oneLine ? window.__oneLine(document.title) : null;
  const titles = window.__titles ? window.__titles() : [];
  return { fontS: L.fontS, scale: S, fs, sbW: L.sbW, sbCols: L.sbCols, colW, nw, maxW,
           splits: titles.map((x) => window.__splitTitle(x, fs, maxW)) };
}), null, 1));
await ctx.close(); await browser.close();
