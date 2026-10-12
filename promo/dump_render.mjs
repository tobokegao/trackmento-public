// 画面側（frontend の renderShareCanvas）で共有画像を描き、PNG に書き出す。
// scripts/compare_render.py の auto から呼ぶ（サーバー側の render.py と絵で突き合わせる）。
//   node promo/dump_render.mjs <出力するフォルダ> <並びの JSON> [出力の最大辺]
// 並びの JSON は [{ key, cols, rows, title, rowLabels, options, cells }, ...]。
// **共有は作らない**（R2 に書かない）。描いた Canvas をそのまま PNG にして持ち帰る
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
const [outDir, casesPath, maxSideArg] = process.argv.slice(2);
const maxSide = Number(maxSideArg) || 2400;
const cases = JSON.parse(fs.readFileSync(casesPath, "utf-8"));
fs.mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, locale: "ja-JP" });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__renderShare && window.__setGrid);
for (const c of cases) {
  const url = await page.evaluate(async ({ c, maxSide }) => {
    // cells はマスの数ちょうどで渡す（__setGrid は渡した配列を i % 長さで配るので、空きマスの null もそのまま入る）
    window.__setGrid(c.cols, c.rows, { ...c.options, title: c.title, rowLabels: c.rowLabels }, c.cells);
    // **字幅の控えは Web フォントが効いてから取る**（promo/dump_layouts.mjs と同じ）
    await window.__loadShareFonts();
    window.__clearCharW();
    const { canvas } = await window.__renderShare(maxSide);
    return canvas.toDataURL("image/png");
  }, { c, maxSide });
  fs.writeFileSync(path.join(outDir, `${c.key}.png`), Buffer.from(url.split(",")[1], "base64"));
}
if (errors.length) { console.error("画面のエラー:", errors.join("\n")); process.exitCode = 1; }
await ctx.close(); await browser.close();
