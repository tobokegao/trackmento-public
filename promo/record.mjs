// TRACKMENTO の操作を Playwright で自動実行し、9:16（1080×1920）の webm と操作時刻（events.json）を残す。
// 前提: ローカルの uvicorn が http://localhost:8000 で動いていること。uploads/ に手入力用の 2 枚があること。
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const BASE = process.env.TRACKMENTO_URL || "http://localhost:8000";
// MODE=pc で PC 表示（1280×720 を 1.5 倍で録って 1920×1080）。既定はスマホ表示（540×960 を 2 倍で 1080×1920）
const PC = process.env.MODE === "pc";
const OUT = path.resolve(PC ? "public/recordings-pc" : "public/recordings");
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

// 画面の実ピクセルで録るため DPR を 2 に固定（Playwright の deviceScaleFactor だと 540×960 で録られて余白が灰色になる）
const browser = await chromium.launch({ args: [PC ? "--force-device-scale-factor=1.5" : "--force-device-scale-factor=2", "--hide-scrollbars"] });
const ctx = await browser.newContext(PC ? {
  viewport: { width: 1280, height: 720 }, locale: "ja-JP", bypassCSP: true,
  recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
} : {
  viewport: { width: 540, height: 960 }, isMobile: true, hasTouch: true, locale: "ja-JP", bypassCSP: true,
  recordVideo: { dir: OUT, size: { width: 1080, height: 1920 } },
});
// タップ位置に波紋を出す（動画で操作が分かるように）
await ctx.addInitScript((PC_MODE) => {
  window.__mark = (i) => {
    let d = document.getElementById("__mk");
    if (!d) { d = document.createElement("div"); d.id = "__mk"; d.style.cssText = "position:fixed;right:0;bottom:0;width:16px;height:16px;z-index:99999;pointer-events:none"; document.body.append(d); }
    d.style.background = `rgb(${(i % 6) * 51},${(Math.floor(i / 6) % 6) * 51},${(Math.floor(i / 36) % 6) * 51})`;
  };
  window.__tap = (x, y) => {
    if (PC_MODE) {
      let c = document.getElementById("__cur");
      if (!c) { c = document.createElement("div"); c.id = "__cur"; c.style.cssText = "position:fixed;width:22px;height:30px;z-index:99998;pointer-events:none;transition:left .25s ease-out,top .25s ease-out"; c.innerHTML = '<svg width="22" height="30" viewBox="0 0 22 30"><path d="M2 2 L2 24 L8 18 L12 28 L16 26 L12 17 L20 17 Z" fill="#1b1d24" stroke="#f5f4f0" stroke-width="2"/></svg>'; document.body.append(c); }
      c.style.left = x - 2 + "px"; c.style.top = y - 2 + "px";
    }
    const d = document.createElement("div");
    d.style.cssText = `position:fixed;left:${x}px;top:${y}px;width:56px;height:56px;margin:-28px 0 0 -28px;border:3px solid #1b1d24;border-radius:50%;background:rgba(27,29,36,.18);pointer-events:none;z-index:9999;animation:__tapAnim .45s ease-out forwards`;
    document.body.append(d); setTimeout(() => d.remove(), 500);
  };
  const s = document.createElement("style");
  s.textContent = "@keyframes __tapAnim{from{transform:scale(.4);opacity:1}to{transform:scale(1.6);opacity:0}}";
  document.addEventListener("DOMContentLoaded", () => document.head.append(s));
}, PC);
const page = await ctx.newPage();
const t0 = Date.now();
const events = [];
const mark = async (name, extra = {}) => { const i = events.length; events.push({ t: (Date.now() - t0) / 1000, name, ...extra }); try { await page.evaluate((i) => window.__mark(i), i); } catch {} console.log(`${((Date.now() - t0) / 1000).toFixed(2)}s ${name}`); };
const wait = (ms) => page.waitForTimeout(ms);

async function tap(sel, name) {
  const loc = typeof sel === "string" ? page.locator(sel).first() : sel;
  await loc.scrollIntoViewIfNeeded();
  const box = await loc.boundingBox();
  if (!box) throw new Error(`no box: ${sel}`);
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await page.evaluate(([x, y]) => window.__tap(x, y), [x, y]);
  await wait(120);
  await mark(name || `tap ${sel}`);
  await loc.click();
}
async function type(sel, text) {
  const loc = page.locator(sel).first();
  await loc.click();
  await loc.fill("");
  await loc.pressSequentially(text, { delay: 55 });
}
async function openSheet() { if (PC) { await wait(300); return; } await tap("#find-btn", "open-sheet"); await page.waitForSelector("#sheet:not([hidden])"); await wait(500); }
async function pickFirstResult(label, source, match) {   // match: 候補のテキスト（アルバム名など）で絞る
  let sel = source ? `#results .result:has(.badge[data-source="${source}"])` : "#results .result";
  if (match) sel += `:has-text("${match}")`;
  await page.waitForSelector(sel, { timeout: 60000 });
  await wait(700);
  await tap(sel, `add:${label}`);
  await page.waitForSelector("#sheet[hidden]", { state: "attached" });
  await wait(600);
}
async function searchAdd(title, artist, label, source, opts = {}) {   // opts.match: 選ぶ候補のテキスト
  if (opts.viaCell) { await tap(cell(opts.viaCell), "cell-tap"); if (!PC) await page.waitForSelector("#sheet:not([hidden])"); await wait(700); }
  else await openSheet();
  if (opts.tour) {   // 検索ソースの切り替えを見せる（オン→オン→オフ→オフで元に戻す）
    for (const k of ["musicbrainz", "otodb"]) { await tap(page.locator(`#sources input[value="${k}"] + span`), `src:${k}`); await wait(350); }
    for (const k of ["musicbrainz", "otodb"]) { await tap(page.locator(`#sources input[value="${k}"] + span`), `src-off:${k}`); await wait(300); }
    await wait(300);
  }
  if (source) {
    const cb = page.locator(`#sources input[value="${source}"]`);
    if (!(await cb.isChecked())) await tap(page.locator(`#sources input[value="${source}"] + span`), `source:${source}`);
  }
  await type("#q", title);
  if (artist) await type("#artist", artist);
  await tap("#search-btn", `search:${label}`);
  await pickFirstResult(label, source, opts.match);
}
async function urlAdd(url, label, source) {
  await openSheet();
  await expandSub("sub-bandcamp", "url");
  await page.locator("#bc-url").scrollIntoViewIfNeeded();
  await wait(300);
  await type("#bc-url", url);
  await tap("#bc-btn", `url:${label}`);
  await pickFirstResult(label, source);
}
async function manualAdd(image, title, artist, label) {
  await openSheet();
  await expandSub("sub-manual", "manual");
  await page.locator("#m-image").scrollIntoViewIfNeeded();
  await wait(300);
  await type("#m-image", image);
  await type("#m-title", title);
  await type("#m-artist", artist);
  await tap("#m-btn", `manual:${label}`);
  await pickFirstResult(label, "manual");   // 手入力は候補の先頭に入るので、それをタップして配置
}
async function expandSub(id, name) {
  const b = page.locator(`#${id} .sub-title`);
  await b.scrollIntoViewIfNeeded();
  if ((await b.getAttribute("aria-expanded")) !== "true") { await tap(b, `expand:${name}`); await wait(400); }
}
const cell = (n) => `#grid .cell[data-index="${n - 1}"]`;
async function swapCells(a, b) { await tap(cell(a), `select:${a}`); await wait(450); await tap(cell(b), `swap:${a}-${b}`); await wait(600); }

// ---- 本編 ----
await page.goto(`${BASE}/`, { waitUntil: "networkidle" });
await page.addStyleTag({ content: "#wordmark-tag,#bar-status{visibility:hidden}" });
// まっさらから始める
await page.evaluate(() => { localStorage.clear(); });
await page.reload({ waitUntil: "networkidle" });
await page.addStyleTag({ content: "#wordmark-tag,#bar-status{visibility:hidden}" });
if (await page.locator("#grid .cell img").count()) { page.once("dialog", (d) => d.accept()); await page.locator("#clear-btn").click(); await wait(500); }
await wait(1000);
await mark("start");

await tap("#title", "title-focus");
await page.locator("#title").fill("");
await page.locator("#title").pressSequentially("私を構成する9選", { delay: 90 });
await wait(600); await mark("title-done");

// 追加（並びは後で入れ替える）
await searchAdd("近道したい", "須賀響子", "chikamichi", undefined, { viaCell: 1, tour: true });
await searchAdd("天才ヴァガボンド", "COIL", "vagabond", undefined, { match: "天才ヴァガボンド - Single" });
await urlAdd("https://www.youtube.com/watch?v=x2Uj_ILuNw0", "talk", "youtube");
await urlAdd("https://www.nicovideo.jp/watch/sm44887188", "10-10-10", "nicovideo");
await manualAdd("/uploads/ca3a841b8281ff38.jpg", "みつあみ引っ張って", "くま井ゆう子", "mitsuami");
await urlAdd("https://jamiepaige.bandcamp.com/track/birdbrain-with-ok-glass-2", "birdbrain", "bandcamp");
await urlAdd("https://on.soundcloud.com/QSnj7ttO5W4ErGhJ7U", "worldwidesuperstar", "soundcloud");
await manualAdd("/uploads/78b3b5f5be01fa10.jpg", "(tike)2 runaway", "サラダ", "runaway");
await searchAdd("I Love Love You", "Guitar Vader", "ilovelove", "musicbrainz", { match: "Remixes GVR" });
await mark("grid-full");
await wait(800);

// 並べ替え: 今 1 近道 2 天才 3 Talk 4 10-10 5 みつあみ 6 BIRDBRAIN 7 wws 8 runaway 9 ILLY
// 目標:        1 Talk 2 みつあみ 3 10-10 4 BIRDBRAIN 5 wws 6 runaway 7 近道 8 天才 9 ILLY
await swapCells(1, 3);   // Talk 近道 → 1 Talk, 3 近道
await swapCells(2, 5);   // 1 Talk 2 みつあみ 3 近道 4 10-10 5 天才
await swapCells(3, 4);   // 3 10-10 4 近道
await swapCells(4, 6);   // 4 BIRDBRAIN 6 近道
await swapCells(5, 7);   // 5 wws 7 天才
await swapCells(6, 8);   // 6 runaway 8 近道
await swapCells(7, 8);   // 7 近道 8 天才
await mark("reorder-done");
await wait(800);

// 出力オプション: 比率と背景色
if (PC) {   // PC では出力オプションは常に開いている。見出しをクリックすると畳まれるので、波紋だけ出して印を付ける
  const b = await page.locator(".pane-options .pane-title").boundingBox();
  await page.evaluate(([x, y]) => window.__tap(x, y), [b.x + 80, b.y + b.height / 2]);
  await wait(120); await mark("open-options");
} else await tap(".pane-options .fold", "open-options");
await wait(600);
// 比率を 4 種類順にタップ。最後の比率はスマホ版 9:16、PC 版 16:9
for (const r of (PC ? ["9:16", "16:9", "free", "16:9"] : ["16:9", "9:16", "free", "9:16"])) { await tap(`#ratio-seg input[value="${r}"] + span`, `ratio:${r}`); await wait(380); }
await wait(400);
for (const c of ["cerulean", "pink", "mustard"]) { await tap(`#swatches input[value="${c}"]`, `bg:${c}`); await wait(450); }
await wait(400);
await page.locator("#bg-custom").scrollIntoViewIfNeeded();
{ const box = await page.locator("#bg-custom").boundingBox(); await page.evaluate(([x, y]) => window.__tap(x, y), [box.x + box.width / 2, box.y + box.height / 2]); }
await wait(120); await mark("bg:custom");
await page.locator("#bg-custom").fill("#7c5cff");
await wait(700);
await page.locator("#bg-custom").fill("#ff7a59");
await wait(700);
await tap(`#swatches input[value="mustard"]`, "bg:mustard2");
await wait(400);

// 共有
await page.locator("#share-btn").scrollIntoViewIfNeeded();
await wait(400);
await tap("#share-btn", "share");
await page.waitForSelector("#output:not([hidden])", { timeout: 120000 });
await page.waitForFunction(() => document.querySelector("#output-img")?.complete && document.querySelector("#output-img")?.naturalWidth > 0, null, { timeout: 120000 });
await mark("share-ready");
await page.locator("#output-img").scrollIntoViewIfNeeded();
await wait(1800);
const shareUrl = await page.locator("#share-url").inputValue();
await mark("share-url", { url: shareUrl });
await tap("#open-share", "open-share");
await page.goto(shareUrl, { waitUntil: "networkidle" });
await mark("share-page");
await wait(1500);
await page.mouse.wheel(0, 600); await wait(1200);
await page.mouse.wheel(0, 600); await wait(1500);
await mark("end");

await ctx.close(); await browser.close();
// 「共有ページを開く」で別タブが開くと短い webm がもう 1 本できるので、いちばん大きいもの（本編）を選ぶ
const webm = fs.readdirSync(OUT).filter((f) => f.endsWith(".webm")).sort((a, b) => fs.statSync(path.join(OUT, b)).size - fs.statSync(path.join(OUT, a)).size)[0];
fs.renameSync(path.join(OUT, webm), path.join(OUT, "session.webm"));
fs.writeFileSync(path.join(OUT, "events.json"), JSON.stringify(events, null, 1));
console.log("done", shareUrl);
