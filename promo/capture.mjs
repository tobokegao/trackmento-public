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

const CAPTURE_VERSION = 6;   // 撮り方（下の道具）を変えたら上げる。全部の場面が撮り直しになる
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
// 転載元の候補（2026-09-21）。YouTube の転載で、otoDB に作品が登録されている（作者「CB」が候補に出る）
const REUPLOAD = "https://www.youtube.com/watch?v=T9Cb_iP5uNI";
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
/** 印に**画面の中の位置**を添える（2026-09-21）。動画の赤枠（Highlight）はこの位置から描く。
    sels の要素をまとめた四角を、見えている範囲で切って 0〜1 の割合にする（スクロールしたあとの位置がそのまま入る） */
async function markRect(name, sels) {
  const rect = await page.evaluate((sels) => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const s of sels) for (const el of document.querySelectorAll(s)) {
      const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
      x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top); x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom);
    }
    const W = innerWidth, H = innerHeight;
    x0 = Math.max(0, x0); y0 = Math.max(0, y0); x1 = Math.min(W, x1); y1 = Math.min(H, y1);
    if (!(x1 > x0 && y1 > y0)) return null;
    const r4 = (v) => Math.round(v * 1e4) / 1e4;
    return { x: r4(x0 / W), y: r4(y0 / H), w: r4((x1 - x0) / W), h: r4((y1 - y0) / H) };
  }, sels);
  if (!rect) throw new Error(`${name}: ${sels.join(", ")} が画面に見えていない`);
  mark(name, { rect });
}

/** 要素の四角（見えている範囲で切った 0〜1 の割合）。横の動画のカメラはこれを順に追って寄る（2026-09-22）。
    **ラジオの組・色見本の中の 1 つを押したときは、組ぜんぶの四角**にする（2026-09-22、利用者の指摘。押した 1 つに寄ると
    「曲名リストは 3 択」のような場面で、選べるものの全体が映らなかった） */
async function rectOf(loc) {
  const group = await loc.evaluateHandle((el) => el.closest(".seg, #swatches") || el).catch(() => null);
  const b = await (group ? group.asElement() : loc).boundingBox().catch(() => null);
  if (!b) return undefined;
  const vp = page.viewportSize(), r4 = (v) => Math.round(v * 1e4) / 1e4;
  const x0 = Math.max(0, b.x), y0 = Math.max(0, b.y), x1 = Math.min(vp.width, b.x + b.width), y1 = Math.min(vp.height, b.y + b.height);
  if (!(x1 > x0 && y1 > y0)) return undefined;
  return { x: r4(x0 / vp.width), y: r4(y0 / vp.height), w: r4((x1 - x0) / vp.width), h: r4((y1 - y0) / vp.height) };
}
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
/** **PC だけ**: 要素（か、そのラジオの組）を、入れ物の縦の真ん中まで**なめらかに**送る（2026-09-22、利用者の指摘）。
    横の動画はカメラが操作した所に寄るが、要素が画面の下の端にあると、カメラは録画の外を映せないので真ん中に持ってこられなかった */
async function bring(sel, ms = 450) {
  if (!PC) return;
  const loc = typeof sel === "string" ? page.locator(sel).first() : sel;
  const info = await loc.evaluate((el) => {
    const g = el.closest(".seg, #swatches") || el;
    let p = g.parentElement;
    while (p && p !== document.body && !(/(auto|scroll)/.test(getComputedStyle(p).overflowY) && p.scrollHeight > p.clientHeight)) p = p.parentElement;
    const inBox = p && p !== document.body;
    const box = inBox ? p.getBoundingClientRect() : { top: 0, bottom: innerHeight };
    const r = g.getBoundingClientRect();
    const top = Math.max(0, box.top), bottom = Math.min(innerHeight, box.bottom);
    let dy = Math.round((r.top + r.bottom) / 2 - (top + bottom) / 2);
    // 送れる範囲で止める（端より先は動かない）
    const cur = inBox ? p.scrollTop : scrollY, max = inBox ? p.scrollHeight - p.clientHeight : document.documentElement.scrollHeight - innerHeight;
    dy = Math.max(-cur, Math.min(max - cur, dy));
    if (inBox) p.dataset.capBring = "1";
    return { dy, box: inBox };
  });
  if (Math.abs(info.dy) >= 40) await scrollBy(info.dy, ms, info.box ? "[data-cap-bring]" : null);
  await page.evaluate(() => { for (const el of document.querySelectorAll("[data-cap-bring]")) delete el.dataset.capBring; });
}
/** 引きの印（画面全体）。窓が重なって出たときなど、横の動画のカメラを寄りから引きに戻す（2026-09-22、利用者の指定） */
const markWide = (name) => mark(name, { rect: { x: 0, y: 0, w: 1, h: 1 } });
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
  mark(name || `tap ${sel}`, { rect: await rectOf(loc) });
  await page.mouse.click(x, y);
  await frame();
}
/** 1 字ずつ打つ（ms = 1 字の間隔） */
async function type(sel, text, ms = 55) {
  const loc = page.locator(sel).first();
  await center(loc);
  mark(`type:${sel}`, { rect: await rectOf(loc) });   // 打ち始める欄（カメラが寄る先）
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
  // 読み込みの完了（画像まで）を待つ。**30 秒で見切って進む**（2026-09-21、画像の中継が 1 枚だけ返ってこず、
  // readyState が complete にならないまま 2 分待って止まった。マスの画像の出そろいは imagesLoaded で別に待つ）
  await until(() => page.evaluate(() => document.readyState === "complete"), { label: url, timeout: 30000 })
    .catch(() => console.log(`   （${url} の読み込みが終わりきらないまま進める）`));
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
/** ページの画像を全部読ませてから進む（撮らずに待つ）。loading="lazy" は時計を止めて撮ると読み込みが間に合わない */
async function imgsReady() {
  await page.evaluate(() => { for (const i of document.querySelectorAll("img")) i.loading = "eager"; });
  await until(() => page.evaluate(() => [...document.querySelectorAll("img")].every((i) => i.complete)), { label: "ページの画像", timeout: 30000 })
    .catch(() => console.log("   （画像が出そろわないまま進める）"));
}
/** マスの画像が出そろうまで撮りながら待つ */
const imagesLoaded = () => page.evaluate(() => [...document.querySelectorAll("#grid .cell img")].every((i) => i.complete));

// ---------------------------------------------------------------- 場面（take）
// 各場面は「前の場面の終わりの状態」から始まる。**場面の頭では何も開いていない状態**（シート・窓は閉じている）にそろえる。
// 頭の 1.5 秒は何もしないで撮る（Remotion のショットは印の数秒前から見せることがあるため）
const PREROLL = 1500;

const MAIN = [
  // 画面の説明（2026-09-21）。上にタイトル → 真ん中にマス → 下に共有と検索 → 出力の設定。印ごとに赤枠の位置（rect）を持つ
  ["tour", async () => {
    mark("start");
    await hold(1000);
    await markRect("tour:title", [".grid-head"]); await hold(1300);
    await markRect("tour:grid", ["#grid-scroll"]); await hold(1300);
    await center(page.locator(".grid-actions")); await hold(300);
    await markRect("tour:buttons", [".grid-actions > .btn"]); await hold(1300);
    if (PC) {   // PC では出力オプションは右に常に出ている
      await markRect("tour:options", [".pane-options"]); await hold(1600);
    } else {
      // 出力オプションの窓が見えるところまで送り、開いて中を見せる（見えている部分を枠で囲む）
      const y = await page.locator(".pane-options").evaluate((el) => el.getBoundingClientRect().top + scrollY - 90);
      await scrollBy(y - (await page.evaluate(() => scrollY)), 700); await hold(300);
      await tap(".pane-options .fold", "tour:options-open"); await hold(500);
      // 開くと下に伸びるので、**開いてからもう一度送り**、窓の頭を画面の上寄りに置く（開く前だけだと窓の上の方しか入らなかった）
      const y2 = await page.locator(".pane-options").evaluate((el) => el.getBoundingClientRect().top - 70);
      await scrollBy(y2, 600); await hold(300);
      await markRect("tour:options", [".pane-options"]); await hold(1600);
      await tap(".pane-options .fold", "tour:options-close"); await hold(400);
      await scrollBy(-(await page.evaluate(() => scrollY)), 700);
    }
    await hold(500);
  }],
  ["title", async () => {
    await tap("#title", "title-focus");
    await page.locator("#title").fill("");
    for (const ch of "私を構成する9選") { await page.keyboard.insertText(ch); await hold(90); }
    await hold(600); mark("title-done");
  }],
  // マスの形を横長 16:9 に（2026-09-21）。これより後の本編は全部 16:9 のマス
  ["cellratio", async () => {
    await openOptions("cellratio:open");
    await center(page.locator("#cell-ratio-seg")); await bring("#cell-ratio-seg"); await hold(400);
    await tap('#cell-ratio-seg input[value="16:9"] + span', "cellratio:16:9");
    await hold(1500);
    if (!PC) { await tap(".pane-options .fold", "cellratio:close"); await hold(400); }
    await scrollBy(-(await page.evaluate(() => scrollY)), 600);
    await hold(300);
  }],
  ["add-saishu", async () => {
    await tap(cell(1), "cell-tap");
    if (!PC) await waitSel("#sheet:not([hidden])");
    await hold(700);
    // 検索ソースの切り替えを見せる。**ソースは 1 つだけ選ぶ**（2026-09-22 からラジオボタン）ので、順に選んで最後に otoDB
    for (const k of ["musicbrainz", "vocadb", "otodb"]) { await tap(page.locator(`#sources input[value="${k}"] + span`), `src:${k}`); await hold(450); }
    await hold(300);
    // 2026-09-21: 本編の 9 マスはニコニコ・YouTube・otoDB だけ（利用者の指定）。検索は otoDB の作品を引く
    await type("#q", "最終鬼畜妹"); await page.locator("#artist").fill("");
    await tap("#search-btn", "search:saishu");
    await pickFirstResult("saishu", "otodb", "大丈夫か");
  }],
  ["add-talk", async () => { await pasteUrl("https://www.youtube.com/watch?v=x2Uj_ILuNw0", "url"); await tap("#bc-btn", "url:talk"); await pickFirstResult("talk", "youtube"); }],
  ["add-10-10-10", async () => { await pasteUrl("https://www.nicovideo.jp/watch/sm44887188", "url"); await tap("#bc-btn", "url:10-10-10"); await pickFirstResult("10-10-10", "nicovideo"); }],
  // 動画 ID だけ貼っても入る。古い投稿はサムネが 4:3（「サムネの入れ方」の見せ場）。
  // **ダッシュウパニック（sm9821748、2010 年）**: 左右の端までピンクの柄なので、ぼかすと色がにじんで分かる。
  // 2026-09-22 まで使っていた組曲『ニコニコ動画』（sm500873）は地が黒く、ぼかしても黒い帯と見分けがつかなかった（利用者の指摘）。
  // 場面と印の名前（kumikyoku）は譜割りエディタが指しているのでそのまま
  ["add-kumikyoku", async () => { await pasteUrl("sm9821748", "url"); await tap("#bc-btn", "url:kumikyoku"); await pickFirstResult("kumikyoku", "nicovideo"); }],
  // 2026-09-21: 16:9 のサムネが主役なので、残りの 5 マスはニコニコの動画（作者はみんな別。デモ用マイリストから選んだ）
  ["add-babylinth", async () => { await pasteUrl("https://www.nicovideo.jp/watch/sm46340359", "url"); await tap("#bc-btn", "url:babylinth"); await pickFirstResult("babylinth", "nicovideo"); }],
  ["add-rockclub", async () => { await pasteUrl("https://www.nicovideo.jp/watch/sm46323931", "url"); await tap("#bc-btn", "url:rockclub"); await pickFirstResult("rockclub", "nicovideo"); }],
  ["add-cheerleader", async () => { await pasteUrl("https://www.nicovideo.jp/watch/sm46235071", "url"); await tap("#bc-btn", "url:cheerleader"); await pickFirstResult("cheerleader", "nicovideo"); }],
  ["add-hakusen", async () => { await pasteUrl("https://www.nicovideo.jp/watch/sm46316572", "url"); await tap("#bc-btn", "url:hakusen"); await pickFirstResult("hakusen", "nicovideo"); }],
  ["add-mahiro", async () => {
    await pasteUrl("https://www.nicovideo.jp/watch/sm46313967", "url"); await tap("#bc-btn", "url:mahiro"); await pickFirstResult("mahiro", "nicovideo");
    await until(imagesLoaded, { label: "ジャケット" });
    mark("grid-full");
    await hold(800);
  }],
  // サムネの入れ方（2026-09-21）。全体を「ぼかして埋める」→「切り抜く」に戻し、4:3 のサムネ（組曲）1 マスだけ「ぼかして埋める」
  ["fit", async () => {
    await openOptions("fit:open");
    await center(page.locator("#cell-fit-seg")); await bring("#cell-fit-seg"); await hold(400);
    await tap('#cell-fit-seg input[value="blur"] + span', "fit:blur"); await hold(1600);
    await tap('#cell-fit-seg input[value="crop"] + span', "fit:crop"); await hold(900);
    if (!PC) { await tap(".pane-options .fold", "fit:close"); await hold(400); }
    await scrollBy(-(await page.evaluate(() => scrollY)), 600); await hold(300);
    await tap(cell(4), "fit:cell"); await hold(600);   // 4 番はダッシュウパニック（4:3 のサムネ）
    await center(page.locator("#e-fit-seg")); await hold(400);
    await tap('#e-fit-seg input[value="blur"] + span', "fit:one"); await hold(1200);
    if (!PC) { await scrollBy(-(await page.evaluate(() => scrollY)), 600); await hold(300); }
    await markRect("fit:shown", ["#grid-scroll"]); await hold(1000);
    await tap(cell(4), "fit:deselect"); await hold(600);
  }],
  ["reorder", async () => {
    // 今 1 最終鬼畜妹 2 Talk 3 10-10 4 組曲 5 バビリンス 6 Rock Club 7 CHEERLEADER 8 白線 9 まひろ
    // 目標 1 CHEERLEADER 2 Talk 3 Rock Club 4 まひろ 5 10-10 6 白線 7 バビリンス 8 最終鬼畜妹 9 組曲
    for (const [a, b] of [[1, 7], [3, 6], [4, 9], [5, 6], [6, 8], [7, 8]]) await swapCells(a, b);
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
    await center(page.locator("#list-seg")); await bring("#list-seg"); await hold(300);
    // 3 択をぜんぶ押して見せ、最後は「マスに重ねる」に戻す（以後の共有はこの表示）
    // 最後の選択が書き出しの曲名リストになる。**縦（スマホ）は横に並べる**（できあがりの画を重ねない形に。2026-09-22、利用者の指定）
    for (const [v, n] of [["side", "list:beside"], ["overlay", "list:overlay"], ["none", "list:none"], PC ? ["overlay", "list:overlay2"] : ["side", "list:beside2"]]) {
      await tap(`#list-seg input[value="${v}"] + span`, n); await hold(300);
    }
    await hold(600);
    await bring("#ratio-seg");
    for (const r of (PC ? ["9:16", "16:9", "free", "16:9"] : ["16:9", "9:16", "free", "9:16"])) { await tap(`#ratio-seg input[value="${r}"] + span`, `ratio:${r}`); await hold(380); }
    await hold(400);
    await center(page.locator("#swatches")); await bring("#swatches");
    for (const c of ["cerulean", "pink", "mustard"]) { await tap(`#swatches input[value="${c}"]`, `bg:${c}`); await hold(450); }
    await hold(400);
    await tap("#bg-custom-btn", "bg:custom");
    await waitSel("#bg-custom-panel:not([hidden])");
    // つまみの窓ぜんぶが映るように送り、窓ぜんぶに寄る（2026-09-22、利用者の指摘。押したボタンに寄ったままで窓が見切れていた）
    await center(page.locator("#bg-custom-panel")); await bring("#bg-custom-panel");
    await markRect("bg:panel", ["#bg-custom-panel"]);
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
    markWide("share:wide");   // 送信の窓が重なって出るので、横の動画は引きに戻す（2026-09-22、利用者の指定）
    await live(() => page.evaluate(() => { const o = document.querySelector("#output"), i = document.querySelector("#output-img"); return o && !o.hidden && i && i.complete && i.naturalWidth > 0; }), { timeout: 180000 });
    mark("share-ready");
    await net.send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
    await center(page.locator("#output-img")); await bring("#output");
    await markRect("share:output", ["#output"]);   // 出来上がりの窓ぜんぶ（2026-09-22、利用者の指摘。窓の上の方だけに寄っていた）
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
  // 新機能の録画も 16:9 のマスで撮る（2026-09-21）。印は使わない下ごしらえ
  ["cells169", async () => {
    await openOptions("setup:open");
    await center(page.locator("#cell-ratio-seg")); await hold(200);
    await tap('#cell-ratio-seg input[value="16:9"] + span', "setup:16:9"); await hold(300);
    if (!PC) { await tap(".pane-options .fold", "setup:close"); await hold(300); }
    await page.evaluate(() => window.scrollTo(0, 0)); await hold(300);
  }],
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
  // 転載でも元の作者が分かる（2026-09-21）。YouTube の転載を入れ → マスを選び → 「元の投稿を探す」→ otoDB の候補を押す
  ["origin", async () => {
    // 題の頭の [병만로이드] は曲名の刈り込みで外れるので、題では探さない。**入れたマスの番号は案内文から読む**
    // （「4 番に「…」を入れました。」。マスの描き直しは遅れることがあり、画像や title の有無では判定できなかった）
    await pasteUrl(REUPLOAD, "url-origin");
    await tap("#bc-btn", "origin:paste");
    await pickFirstResult("origin", "youtube");
    const n = Number(((await page.locator("#grid-msg").innerText()).match(/(\d+)/) || [])[1] || 0);
    if (!n) throw new Error("転載の動画を入れたマスの番号が案内文から読めない");
    await closeSheet("origin-close");
    // PC は URL 欄まで送ったままだとグリッドも編集欄も画面の外（2026-09-21 の撮影で候補が映らなかった）。頭まで戻す
    if (PC) await scrollBy(-(await page.evaluate(() => scrollY)), 500);
    await center(page.locator(".pane-grid")); await hold(500);
    await tap(cell(n), "origin:select"); await hold(700);
    await center(page.locator("#e-origin-find")); await hold(400);
    await tap("#e-origin-find", "origin:find");
    await live(() => page.locator("#e-origin-seg .origin-cap").first().isVisible(), { timeout: 30000 });
    await hold(300); mark("origin:cands");
    // 候補の欄が画面の下で切れないように送る（なめらかに）
    const dy = await page.locator("#e-origin-field").evaluate((el) => { const r = el.getBoundingClientRect(); return Math.max(0, r.bottom - innerHeight + 40); });
    if (dy) await scrollBy(dy, 500);
    await hold(200);
    await markRect("origin:cands-rect", ["#e-origin-field"]);
    await hold(1200);
    await tap("#e-origin-seg .btn", "origin:pick"); await hold(1500);
    await tap(cell(n), "origin:deselect"); await hold(500);
    await page.evaluate(() => window.scrollTo(0, 0)); await hold(300);
  }],
  ["listed", async () => {
    await center(page.locator("#opt-listed")); await hold(400);
    await tap("#opt-listed", "listed:check");
    await hold(900);
    await tap("#share-btn", "listed:share");
    markWide("listed:wide");   // 送信の窓が出たら引き（share と同じ）
    await live(() => page.evaluate(() => { const i = document.querySelector("#output-img"); return !document.querySelector("#output").hidden && i && i.complete && i.naturalWidth > 0; }), { timeout: 120000 });
    await hold(1200); mark("listed:shared", { url: await page.locator("#share-url").inputValue().catch(() => "") });
    await hold(800);
    await goto(`${BASE}/find?q=${encodeURIComponent("グルメレース")}`);
    await imgsReady();
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
    await imgsReady();   // 共有ページのサムネが灰色のまま映っていた（2026-09-22）
    await hold(300); mark("find:share");
    await hold(1500);
    // 「TRACKMENTO で開く（この並びを読み込む）」を押したあとの画面まで見せる（2026-09-22、利用者の指定）。
    // リンクの先は PUBLIC_BASE_URL（本番）なので、押した印だけ付けて手元の同じ ID を開く。
    // 開くと並びが置き換わるので、見せたあと**元の並びに戻してから**次の場面へ（io 以降の頭の状態を変えない）
    const open = page.locator('a.btn[href*="?share="]').first();
    await center(open); await hold(300);
    const sid = new URL(await open.getAttribute("href")).searchParams.get("share");
    const ob = await open.boundingBox();
    await page.evaluate(([x, y]) => window.__tap(x, y), [ob.x + ob.width / 2, ob.y + ob.height / 2]);
    await hold(150); mark("find:app-tap");
    const keep = await page.evaluate(() => JSON.stringify(Object.fromEntries(Object.keys(localStorage).map((k) => [k, localStorage.getItem(k)]))));
    await goto(`${BASE}/?share=${sid}`);
    await until(imagesLoaded, { label: "読み込んだ並び", timeout: 30000 }).catch(() => {});
    await hold(200); mark("find:app");
    await hold(2200);
    await page.goto(`${BASE}/health`, { waitUntil: "domcontentloaded" });
    await page.evaluate((ls) => { localStorage.clear(); for (const [k, v] of Object.entries(JSON.parse(ls))) localStorage.setItem(k, v); }, keep);
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
    // ソースは 1 つだけ選ぶので、iTunes を選んで戻す（あとの場面の検索が VocaDB のままにならないように）
    await tap(page.locator('#sources input[value="itunes"] + span'), "source-off:vocadb");
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
    // 候補のサムネは loading="lazy"。時計を止めて撮るので、送っても読み込みが間に合わず空の四角が並んだ（2026-09-22）。
    // 先に全部読ませてから撮る（待つあいだは撮らない）
    await page.evaluate(() => { for (const i of document.querySelectorAll("#results img")) i.loading = "eager"; });
    await until(() => page.evaluate(() => [...document.querySelectorAll("#results img")].every((i) => i.complete)), { label: "候補のサムネ", timeout: 60000 })   // 消えた動画の画像は読めずに終わるので、成否は問わない
      .catch(() => console.log("   （候補のサムネが出そろわないまま進める）"));
    mark("pl:rest");
    // 候補の窓の**中**を送る（2026-09-22、横でページ全体が動いていた）。#results の送れる入れ物を探して印を付ける
    await page.evaluate(() => { let p = document.querySelector("#results"); while (p && p !== document.body && !(/(auto|scroll)/.test(getComputedStyle(p).overflowY) && p.scrollHeight > p.clientHeight)) p = p.parentElement; if (p && p !== document.body) p.dataset.capScroll = "1"; });
    const box = (await page.locator("[data-cap-scroll]").count()) ? "[data-cap-scroll]" : (PC ? null : ".sheet-body");
    await scrollBy(900, 700, box); await scrollBy(900, 900, box);
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
    if (PC) {
      // Ctrl＋ホイールで拡大（アプリの「大きく見る」はこれで拡大する）。少しずつ回して 1 コマずつ撮る。そのあと中を送る
      const g = await page.locator("#grid-scroll").boundingBox();
      await page.mouse.move(g.x + g.width / 2, g.y + g.height * 0.3);
      await page.evaluate(([x, y]) => window.__tap(x, y), [g.x + g.width / 2, g.y + g.height * 0.3]);
      mark("zoom32:wheel", { rect: await rectOf(page.locator("#grid-scroll")) });
      // **8 列がちょうど窓の幅に収まる大きさまで**拡大する（2026-09-22、利用者の指摘。16 回 × 60 で 11 倍になり、2 列しか見えなかった）。
      // 見積もって回すと外れた（窓・グリッドの幅の取り方で 1.5 倍ずれた）ので、**1 回ずつ回して、グリッドの右端が窓に届いたら止める**
      const fits = () => page.evaluate(() => { const sc = document.querySelector("#grid-scroll"); return sc.scrollWidth <= sc.clientWidth + 1; });
      await page.keyboard.down("Control");
      for (let i = 0; i < 40; i++) {
        await page.mouse.wheel(0, -25); await frame();
        if (!(await fits())) { await page.mouse.wheel(0, 25); await frame(); break; }   // はみ出したら 1 回ぶん戻す
      }
      await page.evaluate(() => { document.querySelector("#grid-scroll").scrollLeft = 0; });
      await page.keyboard.up("Control");
      await hold(400);
      await scrollBy(700, 900, "#grid-scroll");
    }
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
const names = all.map((e) => e.name), dup = names.filter((n, i) => names.indexOf(n) !== i && !n.startsWith("take:") && !n.startsWith("type:") && n !== "start" && n !== "end");
if (dup.length) console.log(`!! 同じ名前の印が 2 つ以上ある（Remotion は最初のものを使う）: ${[...new Set(dup)].join(", ")}`);
console.log(`done ${VARIANT}: ${off} コマ（${(off / FPS).toFixed(1)} 秒）→ ${OUT}`);
