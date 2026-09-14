// 字幕と一緒に出す赤枠（timeline.ts の Shot.hl）の座標を実測する。
// 録画と同じ見た目・同じ状態（まっさら・3×3）で開き、要素の位置を「録画に対する割合」で出す。
//
// 使い方: node measure.mjs        （スマホ表示）
//         MODE=pc node measure.mjs（PC 表示）
import { chromium } from "playwright";

const BASE = process.env.TRACKMENTO_URL || "http://localhost:8000";
const PC = process.env.MODE === "pc";
const VIEW = PC ? { width: 1280, height: 720 } : { width: 540, height: 960 };

const browser = await chromium.launch({ args: [PC ? "--force-device-scale-factor=1.5" : "--force-device-scale-factor=2", "--hide-scrollbars"] });
const ctx = await browser.newContext({ viewport: VIEW, isMobile: !PC, hasTouch: !PC, locale: "ja-JP", bypassCSP: true });
const page = await ctx.newPage();
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.evaluate(() => { localStorage.clear(); localStorage.setItem("trackmento.lang", "ja"); });
await page.reload({ waitUntil: "networkidle" });
await page.addStyleTag({ content: "#wordmark-tag,#bar-status{visibility:hidden}" });
await page.waitForTimeout(1200);

// 録画は viewport をそのまま撮るので、viewport に対する割合がそのまま Shot.hl になる
const targets = {
  "上にタイトル": "#title",
  "真ん中に 3×3 のマス": "#grid",
  "下に共有と検索のボタン": ".grid-actions",
  "出力オプション": ".pane-options",
};
const out = {};
for (const [label, sel] of Object.entries(targets)) {
  const loc = page.locator(sel).first();
  const box = await loc.boundingBox().catch(() => null);
  if (!box) { out[label] = "見つからない（画面の外か、畳まれている）"; continue; }
  const r = (v) => Math.round(v * 1000) / 1000;
  out[label] = {
    x: r(box.x / VIEW.width), y: r(box.y / VIEW.height),
    w: r(box.width / VIEW.width), h: r(box.height / VIEW.height),
    見える: box.y >= 0 && box.y + box.height <= VIEW.height,
  };
}
console.log(`${PC ? "PC" : "スマホ"}（${VIEW.width}×${VIEW.height}）での位置`);
for (const [k, v] of Object.entries(out)) {
  if (typeof v === "string") { console.log(`  ${k}: ${v}`); continue; }
  console.log(`  ${k}: { x: ${v.x}, y: ${v.y}, w: ${v.w}, h: ${v.h} }${v.見える ? "" : "  ← 画面の外にはみ出している"}`);
}
await ctx.close();
await browser.close();
