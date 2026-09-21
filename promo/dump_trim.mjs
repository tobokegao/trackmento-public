// 画面側（frontend の trimName）の刈り込みをまとめて書き出す。
// サーバー側（backend/names.py）と突き合わせて、二重実装のずれを見つける。
//   node promo/dump_trim.mjs <出力する JSON> <題と作者名の JSON>
// **ブラウザで動かす**のが肝心。lookbehind や \p{L} の扱いは Chromium のものを見たいので、
// Node の正規表現エンジンで代用しない（scripts/compare_trim.py から呼ばれる）
import { chromium } from "playwright";
import fs from "node:fs";

const [out, inPath] = process.argv.slice(2);
const pairs = JSON.parse(fs.readFileSync(inPath, "utf-8"));
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__trimName);
const res = await page.evaluate((pairs) => pairs.map(([t, a]) => window.__trimName(t, a)), pairs);
fs.writeFileSync(out, JSON.stringify(res, null, 1));
await browser.close();
console.log(`${res.length} 件書き出しました`);
