// ローカルのサーバーでブラウザ描画の共有を 1 件作る（scripts/compare_render.py の「2)」を自動でやる）。
// 拡張機能を使わずに確かめたいとき用。
//   使い方: node promo/browser_share.mjs <共有ID>
import { chromium } from "playwright";

const id = process.argv[2];
if (!id) throw new Error("共有 ID を渡してください");
const BASE = "http://127.0.0.1:8000";
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ja-JP" });
const page = await ctx.newPage();
page.on("console", (m) => { if (m.type() === "warning" || m.type() === "error") console.log("  [console]", m.text().slice(0, 200)); });
await page.goto(`${BASE}/?share=${id}`, { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.locator("#share-btn").click();
await page.waitForFunction(() => document.querySelector("#share-url")?.value?.includes("/s/"), null, { timeout: 300000 });
const url = await page.locator("#share-url").inputValue();
console.log("ブラウザ描画:", url.split("/s/")[1]);
await ctx.close();
await browser.close();
