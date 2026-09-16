// note には表が無いので、記事の表を画像にして貼れるようにする。
//   node promo/shoot_tables.mjs <記事の HTML> <出力ディレクトリ>
// 記事ページの中の表をそのまま撮るので、見た目は本文と揃う。
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const [src, outDir] = process.argv.slice(2);
const NAMES = ["table-services.png", "table-cost.png"];

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 2,
                                 colorScheme: "light", locale: "ja-JP" });
const p = await ctx.newPage();
await p.goto("file://" + path.resolve(src).split(path.sep).join("/"), { waitUntil: "networkidle" });
const tables = await p.$$(".scroll table");
console.log("表:", tables.length);
fs.mkdirSync(outDir, { recursive: true });
let styled = false;
for (let i = 0; i < tables.length; i++) {
  const name = NAMES[i] || `table-${i + 1}.png`;
  // **表だけを切り取る**（まわりの窓の枠は入れない）。少しだけ余白を足す
  // **その要素を画面の中に入れてから撮る**（下のほうにある表は切り取りが画面の外に出る）
  // **見出しの行はピクセルフォントをやめる**。記事のページでは OS 9 風の味付けだが、
  // 切り出して note に貼ると本文の書体と食い違って浮く（「英語のフォントが違う」と指摘）
  if (!styled) {
    await p.addStyleTag({ content: "thead th{font-family:inherit;letter-spacing:normal;font-size:.94rem;font-weight:700}" });
    styled = true;
  }
  // **サービスの表は最後の行を太字にしない**（合計行を太くする記事の指定が効いてしまうため）
  if (i === 0) await p.addStyleTag({ content: "table tbody tr:last-child td{font-weight:400}" });
  await tables[i].scrollIntoViewIfNeeded();
  await p.waitForTimeout(150);
  await tables[i].screenshot({ path: path.join(outDir, name) });
  const box = await tables[i].boundingBox();
  console.log(name, Math.round(box.width) + "x" + Math.round(box.height));
}
await b.close();
