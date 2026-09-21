// 画面側（frontend の layout()）の割り付けを、並び × 比率でまとめて書き出す。
// サーバー側（backend/render.py）と突き合わせて、二重実装のずれを見つける。
//   node promo/dump_layouts.mjs <出力する JSON> <組み合わせの JSON> <曲の JSON> [出力の最大辺]
// **曲の中身を揃えること**。曲名の長さで折り返しの行数が変わり、そこから文字の大きさが決まるので、
// 中身が違うと割り付けも当然変わる（画面側は手元のグリッドを読むので、そのままだと別物になる）
// **出力の最大辺も揃えること**。組み方は出力での文字の大きさで決まるので、サーバー側と違う値で測ると
// 別の組み方になる（`scripts/compare_layout.py` が自分の `MAX_SIDE` を渡してくる。既定 2400）
import { chromium } from "playwright";
import fs from "node:fs";
const [out, combosPath, tracksPath, maxSideArg] = process.argv.slice(2);
const maxSide = Number(maxSideArg) || 2400;
const combos = JSON.parse(fs.readFileSync(combosPath, "utf-8"));
const tracks = JSON.parse(fs.readFileSync(tracksPath, "utf-8"));
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 }, locale: "ja-JP" });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
await page.waitForFunction(() => window.__layoutFor && window.__setGrid);
const res = await page.evaluate(async ({ combos, tracks, maxSide }) => {
  const opt = { title: "私を構成する9選", showTitle: true, sidebar: true, numbers: false,
                margin: 16, gap: 16, bg: "mustard", bgCustom: null };
  // **字幅の控えは Web フォントが効いてから取る**（代替フォントで測った値が残ると折り返しがずれる）
  window.__setGrid(4, 4, opt, tracks);
  await window.__loadShareFonts();
  window.__clearCharW();
  const got = [];
  for (const [c, r, q] of combos) {
    window.__setGrid(c, r, opt, tracks);
    const L = window.__layoutFor(q, maxSide);
    got.push([c, r, q, L.W, L.H, Math.round(L.scale * 1e9), L.fontS, L.lineH, L.ox, L.oy,
              L.titleSize, L.titleH, L.wrap ? 1 : 0, L.wrapPad, L.wrapTop, L.wrapSegs.length,
              L.sbCols, L.side, L.sbFlow ? 1 : 0, L.sbInline ? 1 : 0, L.wrapTx || 0, L.wrapInline ? 1 : 0]);
  }
  return got;
}, { combos, tracks, maxSide });
fs.writeFileSync(out, JSON.stringify(res));
console.log("書き出し", res.length, `（出力の最大辺 ${maxSide}px）`);
await ctx.close(); await browser.close();
