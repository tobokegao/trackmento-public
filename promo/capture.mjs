// TRACKMENTO の操作を**1 コマずつ**撮る（2026-09-20、record.mjs の置き換え）。
//
// なぜ: record.mjs は画面を実時間で録画し（Playwright の webm、およそ 25fps・コマ落ちあり）、右下の色マーカーから
// 操作の時刻を後で探し、ずれを 1 本の直線で補正していた。フレームの時計が無いので、動画（30fps）と操作の時刻が
// 少しずつずれ、撮り直すたびに結果も変わる（xxxbaaa さんの指摘「足りないのはフレーム単位の時計」）。
//
// どうするか:
// - **ページの時計を止め**（Playwright の clock）、1/30 秒ずつ進めては 1 枚撮る。CSS のアニメーションも同じ時刻に合わせる。
//   操作の時刻は「何コマ目か」でそのまま記録する（マーカー探し・速度の補正が要らない）
// - 待ち（検索の結果・読み込み）は**撮らずに待つ**（until）。見せたい待ち（読み込みで埋まっていくところ）は live で撮る
// - **場面（take）ごとに撮り分ける**。各場面は前の場面の終わりの状態（localStorage）から始まり、台本と始まりの状態が
//   前回と同じなら撮り直さない（1 か所の直しで全部やり直さない）。最後に場面をつないで、今までと同じ
//   public/recordings*/session.mp4 と events.json（v = コマ ÷ 30 秒）を作る。Remotion 側はそのまま読める
//
// 使い方（サーバーは手元で PUBLIC_MODE=1 PUBLIC_BASE_URL=https://trackmento.com、ポート 8000）:
//   node capture.mjs                       # 本編（main）。MODE=pc で横、LANG_UI=en で英語
//   SCENE=feat node capture.mjs            # 新機能（feat）
//   node capture.mjs --only share,options  # 指定した場面だけ撮り直す（ほかは控えを使う）
//   node capture.mjs --force               # 全部撮り直す
//   node capture.mjs --list                # 場面の一覧と、撮り直しが要るかだけ見る
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync } from "node:child_process";

const CAPTURE_VERSION = 4;   // 撮り方（下の道具）を変えたら上げる。全部の場面が撮り直しになる
const FPS = 30;
const BASE = process.env.TRACKMENTO_URL || "http://localhost:8000";
const PC = process.env.MODE === "pc";
const FEAT = process.env.SCENE === "feat";
const EN = process.env.LANG_UI === "en";
const ARGS = process.argv.slice(2);
const FORCE = ARGS.includes("--force");
const LIST = ARGS.includes("--list");
const ONLY = (() => { const i = ARGS.findIndex((a) => a.startsWith("--only")); if (i < 0) return []; const v = ARGS[i].includes("=") ? ARGS[i].split("=")[1] : ARGS[i + 1]; return (v || "").split(",").filter(Boolean); })();
const VARIANT = `${PC ? "pc" : "tall"}-${FEAT ? "feat" : "main"}-${EN ? "en" : "ja"}`;
const TAKES_DIR = path.resolve(`public/takes/${VARIANT}`);
const OUT = path.resolve(`public/recordings${PC ? "-pc" : ""}${FEAT ? "-feat" : ""}${EN ? "-en" : ""}`);
const FF = path.resolve("node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe");
const START_TIME = new Date("2026-09-19T12:00:00+09:00");   // ページの時計の始まり（日付入りのファイル名がこの日になる）

const MYLIST = "https://www.nicovideo.jp/mylist/79113711";
const REVIVE = "https://www.nicovideo.jp/watch/sm7889666";
const AUTHOR = "https://www.nicovideo.jp/watch/sm17315575";
const MULTI_URLS = [
  "https://www.youtube.com/watch?v=x2Uj_ILuNw0",
  "https://jamiepaige.bandcamp.com/track/birdbrain-with-ok-glass-2",
  "https://on.soundcloud.com/QSnj7ttO5W4ErGhJ7U",
].join(String.fromCharCode(10));

// ---------------------------------------------------------------- 撮る道具
let browser, ctx, page;
let frames = 0;          // この場面で撮ったコマの数
let frameDir = "";
let events = [];
let vars = {};           // 場面をまたいで渡す値（共有 URL など）

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 1 コマ進めて撮る。ページの時計を 1/30 秒進め、CSS のアニメーションもその時刻に合わせる */
async function frame() {
  const dt = Math.round((frames + 1) * 1000 / FPS) - Math.round(frames * 1000 / FPS);
  await page.clock.runFor(dt);
  await page.evaluate(() => {
    const now = performance.now();
    for (const a of document.getAnimations()) {
      if (a.__t0 === undefined) a.__t0 = now - (Number(a.currentTime) || 0);
      a.pause(); a.currentTime = now - a.__t0;
    }
  }).catch(() => {});
  frames++;
  const buf = await page.screenshot({ type: "jpeg", quality: 92 });
  fs.writeFileSync(path.join(frameDir, `${String(frames).padStart(6, "0")}.jpg`), buf);
}
/** ms ぶんのコマを撮る（旧 record.mjs の wait に当たる） */
async function hold(ms) { const n = Math.round(ms * FPS / 1000); for (let i = 0; i < n; i++) await frame(); }
/** 撮らずに待つ。ページの時計も進める（タイマー待ちの処理が止まらないように） */
async function until(fn, { timeout = 120000, label = "" } = {}) {
  const t0 = Date.now();
  for (;;) {
    if (await fn().catch(() => false)) return true;
    if (Date.now() - t0 > timeout) throw new Error(`待ちきれない: ${label}`);
    await page.clock.runFor(50); await sleep(50);
  }
}
/** 撮りながら待つ（読み込みで埋まっていくところなど、待つ様子そのものを見せたいとき）。実時間とコマをおおよそ合わせる */
async function live(fn, { timeout = 60000, min = 0 } = {}) {
  const t0 = Date.now();
  for (let i = 0; ; i++) {
    const a = Date.now();
    await frame();
    if (i * 1000 / FPS >= min && await fn().catch(() => false)) return true;
    if (Date.now() - t0 > timeout) return false;
    const rest = 1000 / FPS - (Date.now() - a); if (rest > 0) await sleep(rest);
  }
}
const visible = (sel) => () => page.locator(sel).first().isVisible();
const attached = (sel) => async () => (await page.locator(sel).count()) > 0;
const waitSel = (sel, o = {}) => until(o.state === "attached" ? attached(sel) : visible(sel), { label: sel, ...o });
const mark = (name, extra = {}) => { events.push({ f: frames, name, ...extra }); console.log(`  ${(frames / FPS).toFixed(2)}s ${name}`); };

/** 見えるようにする。**画面に収まっているなら動かさない**（v9 で、押すたびに真ん中へ送ってページが下にずれ、
    グリッドの上が見切れていた）。収まっていないときだけ、スマホは真ん中・PC は近いほうの端へ送る */
async function center(loc) {
  await loc.evaluate((el, pc) => {
    const r = el.getBoundingClientRect(), vh = window.innerHeight;
    let p = el.parentElement;   // シートの中なら、その入れ物の見えている範囲で見る
    while (p && p !== document.body && !/(auto|scroll)/.test(getComputedStyle(p).overflowY)) p = p.parentElement;
    const box = p && p !== document.body ? p.getBoundingClientRect() : { top: 0, bottom: vh };
    const top = Math.max(0, box.top), bottom = Math.min(vh, box.bottom);
    if (r.top >= top + 8 && r.bottom <= bottom - 8) return;
    el.scrollIntoView({ block: pc ? "nearest" : "center", inline: "nearest" });
  }, PC);
}
/** 押す。波紋（とカーソル）を出してから押す。押した瞬間が印の時刻 */
async function tap(sel, name) {
  const loc = typeof sel === "string" ? page.locator(sel).first() : sel;
  await until(() => loc.isVisible(), { label: String(name || sel), timeout: 60000 });
  await center(loc);
  if (!PC) await hold(250);
  const box = await loc.boundingBox();
  if (!box) throw new Error(`no box: ${sel}`);
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await page.evaluate(([x, y]) => window.__tap(x, y), [x, y]);
  await hold(120);
  mark(name || `tap ${sel}`);
  await page.mouse.click(x, y);
  await frame();
}
/** 1 字ずつ打つ（ms = 1 字の間隔） */
async function type(sel, text, ms = 55) {
  const loc = page.locator(sel).first();
  await center(loc);
  await loc.click(); await loc.fill("");
  for (const ch of text) { await page.keyboard.insertText(ch); await hold(ms); }
}
/** なめらかに縦へ送る（ホイールの代わり。ブラウザのなめらかスクロールは実時間で動くので自分で動かす） */
async function scrollBy(dy, ms = 500, sel = null) {
  const n = Math.max(1, Math.round(ms * FPS / 1000));
  const y0 = await page.evaluate((s) => (s ? document.querySelector(s).scrollTop : window.scrollY), sel);
  for (let i = 1; i <= n; i++) {
    const k = i / n, e = k < 0.5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
    await page.evaluate(([s, y]) => { if (s) document.querySelector(s).scrollTop = y; else window.scrollTo(0, y); }, [sel, y0 + dy * e]);
    await frame();
  }
}
async function goto(url) {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await until(() => page.evaluate(() => document.readyState === "complete"), { label: url });
  await page.addStyleTag({ content: "#wordmark-tag,#bar-status{visibility:hidden}" }).catch(() => {});
}

// ---------------------------------------------------------------- 画面の中の小道具（前の record.mjs と同じ）
async function openSheet() {
  if (PC) { await hold(300); return; }
  if (await page.locator("#sheet:not([hidden])").count()) { await hold(300); return; }
  await tap("#find-btn", "open-sheet");
  await waitSel("#sheet:not([hidden])");
  await hold(500);
}
async function closeSheet(name) {
  if (!PC && await page.locator("#sheet:not([hidden])").count()) { await tap("#sheet-close", name); await hold(500); }
}
async function openOptions(name) {
  const fold = page.locator(".pane-options .fold");
  if ((await fold.getAttribute("aria-expanded")) !== "true") { await tap(fold, name); await hold(700); }
}
async function expandSub(id, name) {
  const b = page.locator(`#${id} .sub-title`);
  await center(b);
  if ((await b.getAttribute("aria-expanded")) !== "true") { await tap(b, `expand:${name}`); await hold(400); }
}
async function setUrl(value, ms = 30) {
  await type("#bc-url", value, ms);
  const loc = page.locator("#bc-url");
  if ((await loc.inputValue()) !== value) await loc.fill(value);
}
async function pickFirstResult(label, source, match, timeout = 120000) {
  let sel = source ? `#results .result:has(.badge[data-source="${source}"])` : "#results .result";
  if (match) sel += `:has-text("${match}")`;
  await waitSel(sel, { timeout, label: `${label} の候補` });
  await hold(700);
  await tap(sel, `add:${label}`);
  await waitSel("#sheet[hidden]", { state: "attached" });
  await hold(600);
}
async function pasteUrl(url, name, ms = 30) {
  await openSheet();
  await expandSub("sub-bandcamp", name);
  await center(page.locator("#bc-url"));
  await hold(300);
  await setUrl(url, ms);
  await center(page.locator("#bc-btn"));   // 伸びた欄の下のボタンまで見えるように
}
const cell = (n) => `#grid .cell[data-index="${n - 1}"]`;
async function swapCells(a, b) { await tap(cell(a), `select:${a}`); await hold(450); await tap(cell(b), `swap:${a}-${b}`); await hold(600); }
async function setSize(c, r, name) {
  await openOptions(name);
  await center(page.locator("#cols"));
  await hold(300);
  await type("#cols", String(c)); await type("#rows", String(r));
  await page.locator("#rows").press("Enter");
}
/** マスの画像が出そろうまで撮りながら待つ */
const imagesLoaded = () => page.evaluate(() => [...document.querySelectorAll("#grid .cell img")].every((i) => i.complete));

// ---------------------------------------------------------------- 場面（take）
// 各場面は「前の場面の終わりの状態」から始まる。**場面の頭では何も開いていない状態**（シート・窓は閉じている）にそろえる。
// 頭の 1.5 秒は何もしないで撮る（Remotion のショットは印の数秒前から見せることがあるため）
const PREROLL = 1500;

const MAIN = [
  ["title", async () => {
    mark("start");
    await tap("#title", "title-focus");
    await page.locator("#title").fill("");
    for (const ch of "私を構成する9選") { await page.keyboard.insertText(ch); await hold(90); }
    await hold(600); mark("title-done");
  }],
  ["add-chikamichi", async () => {
    await tap(cell(1), "cell-tap");
    if (!PC) await waitSel("#sheet:not([hidden])");
    await hold(700);
    // 検索ソースの切り替えを見せる（ほかの 3 つをオン → オフ）
    for (const k of ["musicbrainz", "otodb", "vocadb"]) { await tap(page.locator(`#sources input[value="${k}"] + span`), `src:${k}`); await hold(350); }
    for (const k of ["musicbrainz", "otodb", "vocadb"]) { await tap(page.locator(`#sources input[value="${k}"] + span`), `src-off:${k}`); await hold(300); }
    await hold(300);
    await type("#q", "近道したい"); await type("#artist", "須賀響子");
    await tap("#search-btn", "search:chikamichi");
    await pickFirstResult("chikamichi");
  }],
  ["add-vagabond", async () => {
    await openSheet();
    await type("#q", "天才ヴァガボンド"); await type("#artist", "COIL");
    await tap("#search-btn", "search:vagabond");
    await pickFirstResult("vagabond", undefined, "天才ヴァガボンド - Single");
  }],
  ["add-talk", async () => { await pasteUrl("https://www.youtube.com/watch?v=x2Uj_ILuNw0", "url"); await tap("#bc-btn", "url:talk"); await pickFirstResult("talk", "youtube"); }],
  ["add-10-10-10", async () => { await pasteUrl("https://www.nicovideo.jp/watch/sm44887188", "url"); await tap("#bc-btn", "url:10-10-10"); await pickFirstResult("10-10-10", "nicovideo"); }],
  ["add-mitsuami", async () => { await manualAdd("/uploads/ca3a841b8281ff38.jpg", "みつあみ引っ張って", "くま井ゆう子", "mitsuami"); }],
  ["add-birdbrain", async () => { await pasteUrl("https://jamiepaige.bandcamp.com/track/birdbrain-with-ok-glass-2", "url"); await tap("#bc-btn", "url:birdbrain"); await pickFirstResult("birdbrain", "bandcamp"); }],
  ["add-wws", async () => { await pasteUrl("https://on.soundcloud.com/QSnj7ttO5W4ErGhJ7U", "url"); await tap("#bc-btn", "url:worldwidesuperstar"); await pickFirstResult("worldwidesuperstar", "soundcloud"); }],
  ["add-runaway", async () => { await manualAdd("/uploads/78b3b5f5be01fa10.jpg", "(tike)2 runaway", "サラダ", "runaway"); }],
  ["add-ilovelove", async () => {
    await openSheet();
    const cb = page.locator('#sources input[value="musicbrainz"]');
    if (!(await cb.isChecked())) await tap(page.locator('#sources input[value="musicbrainz"] + span'), "source:musicbrainz");
    await type("#q", "I Love Love You"); await type("#artist", "Guitar Vader");
    await tap("#search-btn", "search:ilovelove");
    // MusicBrainz はブラウザから直接引くので、続けて撮るとレート制限で空が返ることがある。出なければ少し待って引き直す（撮らない）
    for (let i = 0; ; i++) {
      try { await pickFirstResult("ilovelove", "musicbrainz", "Remixes GVR", 45000); break; }
      catch (e) {
        if (i >= 3) { console.log(await page.locator("#results").innerText().catch(() => "")); throw e; }
        console.log(`   ilovelove: 候補が出ないので引き直す（${i + 1} 回目）`);
        await sleep(6000); await page.locator("#search-btn").click();
      }
    }
    await until(imagesLoaded, { label: "ジャケット" });
    mark("grid-full");
    await hold(800);
  }],
  ["reorder", async () => {
    // 今 1 近道 2 天才 3 Talk 4 10-10 5 みつあみ 6 BIRDBRAIN 7 wws 8 runaway 9 ILLY
    // 目標 1 Talk 2 みつあみ 3 10-10 4 BIRDBRAIN 5 wws 6 runaway 7 近道 8 天才 9 ILLY
    for (const [a, b] of [[1, 3], [2, 5], [3, 4], [4, 6], [5, 7], [6, 8], [7, 8]]) await swapCells(a, b);
    mark("reorder-done");
    await hold(800);
  }],
  ["options", async () => {
    if (PC) {   // PC では出力オプションは常に開いている。波紋だけ出して印を付ける
      const b = await page.locator(".pane-options .pane-title").boundingBox();
      await page.evaluate(([x, y]) => window.__tap(x, y), [b.x + 80, b.y + b.height / 2]);
      await hold(120); mark("open-options");
    } else await tap(".pane-options .fold", "open-options");
    await hold(600);
    await center(page.locator("#list-seg")); await hold(300);
    // 3 択をぜんぶ押して見せ、最後は「マスに重ねる」に戻す（以後の共有はこの表示）
    for (const [v, n] of [["side", "list:beside"], ["overlay", "list:overlay"], ["none", "list:none"], ["overlay", "list:overlay2"]]) {
      await tap(`#list-seg input[value="${v}"] + span`, n); await hold(300);
    }
    await hold(600);
    for (const r of (PC ? ["9:16", "16:9", "free", "16:9"] : ["16:9", "9:16", "free", "9:16"])) { await tap(`#ratio-seg input[value="${r}"] + span`, `ratio:${r}`); await hold(380); }
    await hold(400);
    for (const c of ["cerulean", "pink", "mustard"]) { await tap(`#swatches input[value="${c}"]`, `bg:${c}`); await hold(450); }
    await hold(400);
    await tap("#bg-custom-btn", "bg:custom");
    await waitSel("#bg-custom-panel:not([hidden])");
    await hold(500);
    for (const [h, sat, v] of [[262, 64, 100], [16, 65, 90]]) {
      for (const [id, val] of [["hsv-h", h], ["hsv-s", sat], ["hsv-v", v]]) {
        await page.locator(`#${id}`).fill(String(val));
        await page.locator(`#${id}`).dispatchEvent("input");
        await hold(220);
      }
      await hold(600);
    }
    await tap(`#swatches input[value="mustard"]`, "bg:mustard2");
    await hold(400);
  }],
  ["share", async () => {
    await center(page.locator("#share-btn"));
    await hold(400);
    // 送信の進み具合を見せるので上りを細くする（約 80KB/秒）。送っているあいだは撮りながら待つ
    const net = await ctx.newCDPSession(page);
    await net.send("Network.enable");
    await net.send("Network.emulateNetworkConditions", { offline: false, latency: 40, downloadThroughput: -1, uploadThroughput: 80 * 1024 });
    await tap("#share-btn", "share");
    await live(() => page.evaluate(() => { const o = document.querySelector("#output"), i = document.querySelector("#output-img"); return o && !o.hidden && i && i.complete && i.naturalWidth > 0; }), { timeout: 180000 });
    mark("share-ready");
    await net.send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
    await center(page.locator("#output-img"));
    await hold(1800);
    const shareUrl = await page.locator("#share-url").inputValue();
    mark("share-url", { url: shareUrl });
    vars.shareUrl = shareUrl;
    await tap("#open-share", "open-share");
    // 表示の URL は trackmento.com（サーバーを PUBLIC_BASE_URL=https://trackmento.com で立てる）。開くのは手元の同じ ID
    for (const p of ctx.pages()) if (p !== page) await p.close();
    await goto(`${BASE}/s/${shareUrl.split("/s/")[1]}`);
    mark("share-page");
    await hold(1500);
    await scrollBy(600, 700); await hold(1200);
    await scrollBy(600, 700); await hold(1500);
    mark("end");
  }],
];
async function manualAdd(image, title, artist, label) {
  await openSheet();
  await expandSub("sub-manual", "manual");
  await center(page.locator("#m-image")); await hold(300);
  await type("#m-image", image); await type("#m-title", title); await type("#m-artist", artist);
  await tap("#m-btn", `manual:${label}`);
  await pickFirstResult(label, "manual");
}

const FEATS = [
  ["multi", async () => {
    mark("start");
    await pasteUrl(MULTI_URLS, "url-multi", 12);
    await tap("#bc-btn", "multi:paste");
    await waitSel("#results .result", { timeout: 120000 });
    await hold(1000); mark("multi:got");
    await hold(700);
    await tap("#results .result", "add:multi");
    await waitSel("#sheet[hidden]", { state: "attached" }).catch(() => {});
    await hold(1200);
    await closeSheet("multi-close");
  }],
  ["revive", async () => {
    await pasteUrl(REVIVE, "url-revive");
    await tap("#bc-btn", "revive:paste");
    await pickFirstResult("revive", "otodb");
    await until(imagesLoaded, { label: "復活したジャケット", timeout: 30000 }).catch(() => console.log("   （ジャケットが出そろわなかった）"));
    await hold(1200);
    await closeSheet("revive-close");
    await center(page.locator(".pane-grid"));
    await hold(1800); mark("revive:done");
    await hold(1500);
  }],
  ["author", async () => {
    await pasteUrl(AUTHOR, "url-author");
    await tap("#bc-btn", "author:paste");
    await waitSel('#results .result:has-text("kz")', { timeout: 60000 }).catch(() => console.log("   （作者名の入った候補が出なかった）"));
    await hold(1800); mark("author:got");
    await hold(600);
    await tap("#results .result", "add:author");
    await waitSel("#sheet[hidden]", { state: "attached" }).catch(() => {});
    await hold(1200);
    await closeSheet("author-close");
  }],
  ["listed", async () => {
    await center(page.locator("#opt-listed")); await hold(400);
    await tap("#opt-listed", "listed:check");
    await hold(900);
    await tap("#share-btn", "listed:share");
    await live(() => page.evaluate(() => { const i = document.querySelector("#output-img"); return !document.querySelector("#output").hidden && i && i.complete && i.naturalWidth > 0; }), { timeout: 120000 });
    await hold(1200); mark("listed:shared", { url: await page.locator("#share-url").inputValue().catch(() => "") });
    await hold(800);
    await goto(`${BASE}/find?q=${encodeURIComponent("グルメレース")}`);
    mark("find:page");
    await hold(2200);
    await scrollBy(300, 400); await hold(900);
    mark("find:results");
    await hold(800);
    const link = page.locator('a[href*="/s/"]').first();
    await center(link); await hold(300);
    const href = await link.getAttribute("href");
    const b = await link.boundingBox();
    if (b) await page.evaluate(([x, y]) => window.__tap(x, y), [b.x + b.width / 2, b.y + b.height / 2]);
    await hold(150); mark("find:open");
    await goto(new URL(href, BASE).href);
    await hold(300); mark("find:share");
    await hold(1800); await scrollBy(500, 500); await hold(1200);
    await goto(`${BASE}/`);
  }],
  ["io", async () => {
    const tmp = path.join(TAKES_DIR, "_grid.json");
    await center(page.locator("#json-export")); await hold(500);
    const dlP = page.waitForEvent("download", { timeout: 15000 });
    await tap("#json-export", "io:save");
    await (await dlP).saveAs(tmp);
    await hold(1300);
    await tap("#clear-btn", "io:clear");
    await waitSel("#confirm-modal:not([hidden])"); await hold(700);
    await tap("#confirm-yes", "io:yes");
    await hold(1000); mark("io:empty");
    await center(page.locator("#json-import")); await hold(300);
    const fcP = page.waitForEvent("filechooser", { timeout: 15000 });
    await tap("#json-import", "io:load");
    await (await fcP).setFiles(tmp);
    await hold(1600); mark("io:back");
    await hold(900);
    fs.rmSync(tmp, { force: true });
  }],
  ["palette", async () => {
    await openOptions("open-options-pal");
    await center(page.locator("#palette-btn")); await hold(400);
    await tap("#palette-btn", "pal:open");
    await waitSel("#pal-modal:not([hidden])");
    await hold(900);
    const laneUse = (n) => page.locator(`#pal-lanes .pal-lane:nth-child(${n}) .pal-btns .btn`).nth(0);
    const laneCopy = (n) => page.locator(`#pal-lanes .pal-lane:nth-child(${n}) .pal-btns .btn`).nth(1);
    await tap(laneUse(2), "pal:pop"); await hold(1100);
    await tap(laneUse(3), "pal:night"); await hold(1400);
    await tap(laneCopy(3), "pal:copy");
    await hold(700);
    const codes = await page.evaluate(() => {
      const toHex = (c) => { const m = c.match(/\d+/g) || []; return "#" + m.slice(0, 3).map((v) => (+v).toString(16).padStart(2, "0")).join(""); };
      return [...document.querySelectorAll("#pal-lanes .pal-lane:nth-child(3) .pal-chips > *")].map((el) => toHex(getComputedStyle(el).backgroundColor)).join(", ");
    });
    await type("#pal-import", codes, 18);
    await hold(400); mark("pal:paste");
    await tap("#pal-import-btn", "pal:import");
    await hold(1400);
    await center(page.locator("#pal-lanes"));
    await hold(600); mark("pal:made");
    const lanes = await page.locator("#pal-lanes .pal-lane").count();
    const save = page.locator(`#pal-lanes .pal-lane:nth-child(${lanes}) .pal-btns .btn`).nth(2);
    const dlP = page.waitForEvent("download", { timeout: 15000 });
    await tap(save, "pal:save");
    const d = await dlP; mark("pal:saved", { file: d.suggestedFilename() });
    await d.saveAs(path.join(TAKES_DIR, "_palette.json")); fs.rmSync(path.join(TAKES_DIR, "_palette.json"), { force: true });
    await hold(1400);
    await tap(laneUse(1), "pal:riso"); await hold(700);
    await tap("#pal-modal-close", "pal:close");
    await hold(500);
  }],
  ["vocadb", async () => {
    await openSheet();
    await type("#q", "恐怖ガーデン");
    await page.locator("#artist").fill("");
    await tap("#search-btn", "vocadb:itunes");
    await hold(4000); mark("vocadb:none");
    await tap(page.locator('#sources input[value="vocadb"] + span'), "source:vocadb");
    await hold(500);
    await tap("#search-btn", "vocadb:search");
    await waitSel('#results .result:has(.badge[data-source="vocadb"])', { timeout: 60000 }).catch(() => console.log("   （VocaDB の候補が出なかった）"));
    await hold(1800); mark("vocadb:got");
    await hold(600);
    await tap(page.locator('#sources input[value="vocadb"] + span'), "source-off:vocadb");
    await hold(300);
    await tap('#results .result:has(.badge[data-source="vocadb"])', "add:vocadb");
    await waitSel("#sheet[hidden]", { state: "attached" }).catch(() => {});
    await hold(1500); mark("vocadb:added");
    await closeSheet("vocadb-close");
  }],
  ["playlist", async () => {
    await setSize(16, 9, "open-options");
    await hold(1100); mark("cells:wide");
    await type("#cols", "16"); await type("#rows", "16");
    await page.locator("#rows").press("Enter");
    await hold(900); mark("cells:16");
    await hold(600);
    await pasteUrl(MYLIST, "url");
    await tap("#bc-btn", "pl:paste");
    await waitSel("#pl-modal:not([hidden])", { timeout: 300000 });
    await hold(1400); mark("pl:overlay");
    await tap("#pl-to-grid", "pl:fill");
    await waitSel("#pl-modal[hidden]", { state: "attached" });
    await hold(2000);
    await closeSheet("pl-close");
    await center(page.locator(".pane-grid"));
    // ジャケットが読み込まれて埋まっていくところを撮る（最長 20 秒）
    await live(imagesLoaded, { timeout: 20000, min: 1600 }); mark("pl:filled");
    await hold(1000);
    await openSheet();
    await center(page.locator("#results")); await hold(300);
    mark("pl:rest");
    await scrollBy(900, 700, PC ? null : ".sheet-body"); await scrollBy(900, 900, PC ? null : ".sheet-body");
    await closeSheet("pl-rest-close");
    await hold(500);
  }],
  ["zoom", async () => {
    await center(page.locator("#zoom-btn")); await hold(400);
    await tap("#zoom-btn", "zoom:open");
    await waitSel("#zoom-modal:not([hidden])");
    await hold(1200);
    await tap(cell(1), "zoom:select"); await hold(600);
    await tap(cell(20), "zoom:swap"); await hold(1000);
    mark("zoom:done");
    await hold(600);
    await tap("#zoom-modal-close", "zoom:close");
    await hold(500);
  }],
  ["zoom32", async () => {
    await setSize(8, 32, "open-options-32");
    await hold(900);
    await center(page.locator("#zoom-btn")); await hold(400);
    await tap("#zoom-btn", "zoom32:open");
    await waitSel("#zoom-modal:not([hidden])");
    await hold(900);
    const slot = await page.locator(".zoom-slot .grid-scroll, #zoom-slot").first().boundingBox();
    const sx = slot.x + slot.width / 2, sy0 = slot.y + slot.height * 0.8;
    mark("zoom32:swipe");
    if (PC) await scrollBy(1080, 900, ".zoom-slot .grid-scroll");
    else {
      // 指で 2 回送る。離す前に止めて、はじいた勢い（実時間で動く）を残さない
      const cdp = await ctx.newCDPSession(page);
      const T = (type, pts) => cdp.send("Input.dispatchTouchEvent", { type, touchPoints: pts.map(([x, y]) => ({ x, y })) });
      for (let r = 0; r < 2; r++) {
        await page.evaluate(([x, y]) => window.__tap(x, y), [sx, sy0]);
        await T("touchStart", [[sx, sy0]]);
        for (let i = 1; i <= 14; i++) { await T("touchMove", [[sx, sy0 - i * 26]]); await frame(); }
        await hold(100);
        await T("touchEnd", []);
        await hold(500);
      }
    }
    await hold(900); mark("zoom32:done");
    await tap("#zoom-modal-close", "zoom32:close");
    await hold(500);
    await setSize(16, 16, "open-options-16");
    await hold(900);
  }],
  ["pages", async () => {
    await goto(`${BASE}/updates`);
    await hold(300); mark("updates:page");
    await hold(1600); await scrollBy(500, 500); await hold(1400);
    await goto(`${BASE}/guide`);
    await hold(300); mark("guide:page");
    await hold(1600); await scrollBy(500, 500); await hold(1400);
    mark("end");
  }],
];

// ---------------------------------------------------------------- 場面を撮る・控えを使う
const TAKES = FEAT ? FEATS : MAIN;
const sha = (s) => crypto.createHash("sha1").update(s).digest("hex").slice(0, 16);
/** 状態の指紋。時刻やブラウザの ID のように、中身と関係なく毎回変わるものは外す */
function stateKey(st) {
  if (!st) return "clean";
  const strip = (v) => {
    if (Array.isArray(v)) return v.map(strip);
    if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).filter(([k]) => !/(At|Time|time|ts|_at)$/.test(k)).map(([k, x]) => [k, strip(x)]));
    return v;
  };
  const ls = Object.fromEntries(Object.entries(st.ls).filter(([k]) => k !== "trackmento:gridId").sort().map(([k, v]) => { try { return [k, strip(JSON.parse(v))]; } catch { return [k, v]; } }));
  return sha(JSON.stringify({ ls, vars: st.vars }));
}

async function newPage() {
  browser = await chromium.launch({ args: [PC ? "--force-device-scale-factor=1.5" : "--force-device-scale-factor=2", ...(FEAT ? [] : ["--hide-scrollbars"])] });
  ctx = await browser.newContext(PC
    ? { viewport: { width: 1280, height: 720 }, locale: EN ? "en-US" : "ja-JP", bypassCSP: true, acceptDownloads: true }
    : { viewport: { width: 540, height: 960 }, isMobile: true, hasTouch: true, locale: EN ? "en-US" : "ja-JP", bypassCSP: true, acceptDownloads: true });
  await ctx.addInitScript((PC_MODE) => {
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
  page = await ctx.newPage();
  await page.clock.install({ time: START_TIME });
}

/** 場面の頭の状態を作る（撮らない）。前の場面の localStorage を入れ、ブラウザの ID だけ新しくする
    （同じ ID だとサーバーの控えのほうが新しいと見なされ、あとの場面の状態が読み込まれることがある） */
async function restore(st) {
  // **アプリの動いていないページで入れる**。画面（/）で入れると、読み込み直す前にページが自分の状態を保存し直して上書きする
  await page.goto(`${BASE}/health`, { waitUntil: "domcontentloaded" });
  await page.evaluate(([ls, lang]) => {
    localStorage.clear();
    for (const [k, v] of Object.entries(ls || {})) if (k !== "trackmento:gridId") localStorage.setItem(k, v);
    localStorage.setItem("trackmento.lang", lang);
  }, [st ? st.ls : null, EN ? "en" : "ja"]);
  await goto(`${BASE}/`);
  if (!st && await page.locator("#grid .cell img").count()) {
    await page.locator("#clear-btn").click(); await page.locator("#confirm-yes").click();
  }
  // 入れた並びがそのまま読まれたかを確かめる（ずれていたら撮っても無駄なので止める）
  if (st && st.ls["trackmento:grid:default"]) {
    const want = JSON.parse(st.ls["trackmento:grid:default"]).cells.map((c) => (c ? c.title : null));
    await page.clock.runFor(500);
    const got = await page.evaluate(() => JSON.parse(localStorage.getItem("trackmento:grid:default") || "{}").cells?.map((c) => (c ? c.title : null)));
    if (JSON.stringify(want) !== JSON.stringify(got)) throw new Error(`頭の状態が入っていない: ${JSON.stringify(got)}`);
  }
  await until(imagesLoaded, { label: "頭のジャケット", timeout: 60000 }).catch(() => {});
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.clock.runFor(1000);
}

async function shoot(name, fn, st, key) {
  const dir = path.join(TAKES_DIR, name);
  fs.rmSync(dir, { recursive: true, force: true });
  frameDir = path.join(dir, "frames"); fs.mkdirSync(frameDir, { recursive: true });
  frames = 0; events = []; vars = { ...(st ? st.vars : {}) };
  await newPage();
  try {
    await restore(st);
    mark(`take:${name}`);
    await hold(PREROLL);
    await fn();
    await hold(500);
    const ls = await page.evaluate(() => Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)])));
    const end = { ls, vars };
    execFileSync(FF, ["-y", "-v", "error", "-framerate", String(FPS), "-i", path.join(frameDir, "%06d.jpg"),
      "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", "-g", "15", "-movflags", "+faststart", path.join(dir, "take.mp4")]);
    fs.rmSync(frameDir, { recursive: true, force: true });
    fs.writeFileSync(path.join(dir, "events.json"), JSON.stringify(events, null, 1));
    fs.writeFileSync(path.join(dir, "end.json"), JSON.stringify(end));
    fs.writeFileSync(path.join(dir, "meta.json"), JSON.stringify({ key, frames, shotAt: new Date().toISOString() }, null, 1));
    console.log(`  → ${name}: ${frames} コマ（${(frames / FPS).toFixed(1)} 秒）`);
    return end;
  } finally {
    await browser.close();
  }
}

// サーバーが本番と同じ見た目で立っているか（Discogs は本番に鍵を置いていないので出さない）
{
  const r = await fetch(`${BASE}/search?q=a&source=discogs`).then((x) => x.text()).catch(() => "");
  if (!r.includes("未知のソース")) { console.log("!! サーバーを DISCOGS_TOKEN= を付けて立て直す（本番は検索ソースに Discogs が出ない）"); process.exit(1); }
}
fs.mkdirSync(TAKES_DIR, { recursive: true });
let st = null;
const plan = [];
for (const [name, fn] of TAKES) {
  const key = sha(`${CAPTURE_VERSION}|${VARIANT}|${fn.toString()}|${stateKey(st)}`);
  const dir = path.join(TAKES_DIR, name);
  let meta = null; try { meta = JSON.parse(fs.readFileSync(path.join(dir, "meta.json"), "utf8")); } catch {}
  const fresh = meta && meta.key === key && fs.existsSync(path.join(dir, "take.mp4"));
  const want = FORCE || (ONLY.length ? ONLY.includes(name) : !fresh);
  plan.push({ name, fresh, want });
  if (LIST) { console.log(`${want ? "撮る  " : "控え  "} ${name}${fresh ? "" : "（台本か頭の状態が変わった）"}`); if (!fresh) st = { ls: {}, vars: {} }; else st = JSON.parse(fs.readFileSync(path.join(dir, "end.json"), "utf8")); continue; }
  if (want) { console.log(`== ${VARIANT} / ${name} を撮る`); st = await shoot(name, fn, st, key); }
  else if (!fs.existsSync(path.join(dir, "end.json"))) { console.log(`!! ${name} はまだ撮っていない（--only に足すか、--only を外して撮る）`); process.exit(1); }
  else { console.log(`== ${VARIANT} / ${name} は控えを使う${fresh ? "" : "（!! 台本か頭の状態が変わっているが、指定が無いので撮り直さない）"}`); st = JSON.parse(fs.readFileSync(path.join(dir, "end.json"), "utf8")); }
}
if (LIST) process.exit(0);

// ---------------------------------------------------------------- つなぐ
// 場面の動画をつないで session.mp4 に、印は通しのコマ番号に直して events.json に（v = t = コマ ÷ 30）
fs.mkdirSync(OUT, { recursive: true });
const list = path.join(TAKES_DIR, "_concat.txt");
let off = 0; const all = [];
fs.writeFileSync(list, TAKES.map(([name]) => `file '${path.join(TAKES_DIR, name, "take.mp4").replace(/\\/g, "/")}'`).join("\n"));
for (const [name] of TAKES) {
  const meta = JSON.parse(fs.readFileSync(path.join(TAKES_DIR, name, "meta.json"), "utf8"));
  for (const e of JSON.parse(fs.readFileSync(path.join(TAKES_DIR, name, "events.json"), "utf8"))) {
    const v = +((off + e.f) / FPS).toFixed(4);
    const { f, ...rest } = e;
    all.push({ ...rest, t: v, v, take: name, takeKey: meta.key, frame: off + f });
  }
  off += meta.frames;
}
execFileSync(FF, ["-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy", "-movflags", "+faststart", path.join(OUT, "session.mp4")]);
fs.rmSync(list, { force: true });
for (const f of fs.readdirSync(OUT)) if (f.endsWith(".webm")) fs.rmSync(path.join(OUT, f));
fs.writeFileSync(path.join(OUT, "events.json"), JSON.stringify(all, null, 1));
const names = all.map((e) => e.name), dup = names.filter((n, i) => names.indexOf(n) !== i && !n.startsWith("take:") && n !== "start" && n !== "end");
if (dup.length) console.log(`!! 同じ名前の印が 2 つ以上ある（Remotion は最初のものを使う）: ${[...new Set(dup)].join(", ")}`);
console.log(`done ${VARIANT}: ${off} コマ（${(off / FPS).toFixed(1)} 秒）→ ${OUT}`);
