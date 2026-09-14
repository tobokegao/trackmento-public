// 動画 ⑤ の「見くらべ」に使う v1（Mac OS 9 風スクロールバーを入れる前）の画面を撮る。
//
// 作業ツリーの frontend/index.html は触らない。Playwright で「/」の応答だけを
// v1 の HTML に差し替えて開く（route の横取り）。API も R2 も同じオリジンのまま使える。
//
// 前提:
//   - ローカルの uvicorn が 8000 番で動いていること（本編の録画と同じ立て方）
//   - V1_HTML に、git show 7e38bc5~1:frontend/index.html で取り出した HTML のパスを渡すこと
//
// 使い方: V1_HTML=/path/to/v1-index.html node record_v1look.mjs
//         V1_HTML=... MODE=pc node record_v1look.mjs
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.TRACKMENTO_URL || "http://localhost:8000";
const PC = process.env.MODE === "pc";
const V1_HTML = process.env.V1_HTML;
if (!V1_HTML) throw new Error("V1_HTML に v1 の HTML のパスを渡してください");
const OUT = path.resolve(PC ? "public/v1-look-pc.png" : "public/v1-look.png");
const VIEW = PC ? { width: 1280, height: 720 } : { width: 540, height: 960 };

// サーバーが差し込むものを自分で埋める（フォントの <link> と、説明文の保存日数）
const live = await fetch(`${BASE}/`).then((r) => r.text());
const fontLink = (live.match(/<link[^>]+fonts-css[^>]*>/) || [""])[0];
let html = fs.readFileSync(V1_HTML, "utf8")
  .replace("<!--__FONT_LINK__-->", fontLink)
  .replaceAll("__RETENTION__", "7");

// --hide-scrollbars は付けない。⑤ で見せたいのがスクロールバーそのものなので
const browser = await chromium.launch({ args: [PC ? "--force-device-scale-factor=1.5" : "--force-device-scale-factor=2"] });
// 動画の枠と同じ実ピクセルで撮る。deviceScaleFactor を書かないと CSS px のままになる
// （録画のときはフラグで拡大しているが、screenshot はこちらを見る）
const ctx = await browser.newContext({ viewport: VIEW, deviceScaleFactor: PC ? 1.5 : 2, isMobile: !PC, hasTouch: !PC, locale: "ja-JP", bypassCSP: true });
const page = await ctx.newPage();
// 「/」だけ v1 の中身に差し替える。ほかの要求（API・画像・フォント）はそのまま通す
await page.route((url) => url.origin === new URL(BASE).origin && (url.pathname === "/" || url.pathname === ""),
  (route) => route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: html }));

await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.evaluate(() => { localStorage.clear(); });
await page.reload({ waitUntil: "networkidle" });
await page.addStyleTag({ content: "#wordmark-tag,#bar-status{visibility:hidden}" });
await page.waitForTimeout(800);

// スクロールバーを出すため、候補がたくさん並ぶ検索をする
if (!PC) {
  await page.locator("#find-btn").click();
  await page.waitForSelector("#sheet:not([hidden])");
  await page.waitForTimeout(400);
}
// 候補を増やすため otoDB と MusicBrainz も足す（iTunes だけだと数件で終わる）
for (const src of ["musicbrainz", "otodb"]) {
  const cb = page.locator(`#sources input[value="${src}"]`);
  if (await cb.count() && !(await cb.isChecked())) await page.locator(`#sources input[value="${src}"] + span`).click();
}
await page.waitForTimeout(300);
await page.locator("#q").fill("グルメレース");
await page.locator("#search-btn").click();
await page.waitForSelector("#results .result", { timeout: 90000 });
await page.waitForTimeout(2500);   // ジャケットが出そろうまで待つ
// 候補の途中までスクロールして、つまみが真ん中あたりに来るようにする
// スマホではシート全体（.sheet-body）が、PC では候補ペインがスクロールする
await page.evaluate(() => {
  const el = document.querySelector(".sheet-body:not([hidden])") || document.querySelector("#results");
  if (el) el.scrollTop = el.scrollHeight * 0.35;
});
await page.waitForTimeout(600);

// scale: "device" を付けないと CSS px で撮られる（1280×720 になって、動画の枠に入れると拡大でぼける）
await page.screenshot({ path: OUT, scale: "device" });
console.log(`撮った: ${OUT}（候補 ${await page.locator("#results .result").count()} 件）`);
await ctx.close();
await browser.close();
