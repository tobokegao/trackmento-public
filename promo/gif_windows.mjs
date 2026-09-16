// 記事に添える「窓ごとの数秒 GIF」のコマを撮る。
//   node promo/gif_windows.mjs <出力ディレクトリ> [場面名|all]
// 場面: search results url manual grid zoom drag io options palette custom sheet touchbar
// PNG のコマを <出力ディレクトリ>/<場面>/ に並べる。GIF への変換は scripts/make_gifs.py が行う。
// **操作はゆっくり**にする（見る人が目で追えるように、1 手ごとに数コマ入れる）。
// 最後の 2 つ（sheet / touchbar）だけは**スマホの画面**で撮る（指で触る画面にしか無い作りのため）。
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const [outRoot, only = "all"] = process.argv.slice(2);
const want = (name) => only === "all" || only === name;
const FPS = 10;
const TRACKS = JSON.parse(fs.readFileSync("grids/default.json", "utf-8")).cells.filter(Boolean);

const browser = await chromium.launch();

/** 画面を 1 つ開く。**公開版に無いソースは撮らない**（手元の .env に DISCOGS_TOKEN があると
    候補に出るが、本番では未設定なので画面に出ない。記事の図と本番の画面を合わせる） */
async function openPage(opts) {
  const c = await browser.newContext({ locale: "ja-JP", ...opts });
  // **カーソルは自前で描く**（システムのカーソルはスクリーンショットに写らない）。promo/cursor.js
  await c.addInitScript({ path: "promo/cursor.js" });
  const p = await c.newPage();
  await p.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
  await p.waitForFunction(() => window.__setGridUI);
  await p.evaluate(() => {
    document.querySelector('#sources input[value="discogs"]')?.closest("label")?.remove();
  });
  return p;
}

let page = await openPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });

/** 指定の秒数ぶん、その場のコマを撮る（何も起きていない間の「ため」にも使う） */
async function hold(shot, sec) {
  const n = Math.max(1, Math.round(sec * FPS));
  for (let i = 0; i < n; i++) { await shot(); await page.waitForTimeout(1000 / FPS); }
}

/** 場面を 1 つ撮る。clip は撮る範囲を返す関数（画面が動いても追従できるように。null なら画面ぜんぶ） */
async function scene(name, clipOf, steps) {
  const dir = path.join(outRoot, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  let i = 0;
  const vp = page.viewportSize();
  const shot = async () => {
    let clip = clipOf ? await page.evaluate(clipOf) : undefined;
    // **切り取りは画面の中に収める**。窓が長いと下端が画面からはみ出し、
    // Playwright がその範囲を撮れずに固まる（手入力の窓で実際に起きた）
    if (clip) {
      clip = { x: Math.max(0, clip.x), y: Math.max(0, clip.y),
               width: Math.min(clip.width, vp.width - Math.max(0, clip.x)),
               height: Math.min(clip.height, vp.height - Math.max(0, clip.y)) };
    }
    await page.screenshot({ path: path.join(dir, `f${String(i++).padStart(3, "0")}.png`), clip });
  };
  await steps(shot);
  console.log(name, i, "コマ");
}

const rectOf = (sel) => new Function("", `
  const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();
  return { x: Math.max(0, r.x - 8), y: Math.max(0, r.y - 8), width: r.width + 16, height: r.height + 16 };`);

const rectPair = (a, b) => new Function("", `
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  const q = document.querySelector(${JSON.stringify(b)}).getBoundingClientRect();
  const x = Math.min(p.x, q.x) - 8, y = Math.min(p.y, q.y) - 8;
  return { x: Math.max(0, x), y: Math.max(0, y),
           width: Math.max(p.right, q.right) - x + 8, height: Math.max(p.bottom, q.bottom) - y + 8 };`);

/** a の上端から b の下端までを撮る（窓まるごとだと縦に長くなりすぎる） */
const rectSpan = (a, b) => new Function("", `
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  const q = document.querySelector(${JSON.stringify(b)}).getBoundingClientRect();
  const x = Math.max(0, p.x - 8), y = Math.max(0, p.y - 8);
  return { x, y, width: p.width + 16, height: q.bottom - y + 8 };`);

/** 横幅は w の窓、縦は a の上端から b の下端まで（窓の一部だけを切り出す） */
const rectRange = (w, a, b) => new Function("", `
  const o = document.querySelector(${JSON.stringify(w)}).getBoundingClientRect();
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  const q = document.querySelector(${JSON.stringify(b)}).getBoundingClientRect();
  const x = Math.max(0, o.x - 8), y = Math.max(0, p.y - 8);
  return { x, y, width: o.width + 16, height: q.bottom - y + 8 };`);

/** n マスぶん曲を入れる。手元の並びは 9 曲しか無いので、足りなければ**繰り返して埋める**
    （マスが多いときの見た目を見せるための場面で、空きだらけだと何も伝わらない） */
/** 横幅は w の窓、縦は a の上端から決め打ちの高さぶん。**途中で開く部分を入れるときはこちら**
    （閉じている間は高さが 0 なので、下端を要素から取るとコマごとに切り取りの大きさが変わる） */
const rectFixed = (w, a, h) => new Function("", `
  const o = document.querySelector(${JSON.stringify(w)}).getBoundingClientRect();
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  const x = Math.max(0, o.x - 8), y = Math.max(0, p.y - 8);
  return { x, y, width: o.width + 16, height: ${h} };`);

const seed = (n, size = [3, 3], opts = {}) => page.evaluate(({ tracks, n, size, opts }) => {
  window.__setGridUI(size[0], size[1], { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true,
                                       margin: 16, gap: 16, bg: "mustard", bgCustom: null, ...opts },
                   Array.from({ length: n }, (_, i) => tracks[i % tracks.length]));
  document.querySelector("#title").value = "私を構成する9曲";   // 入力欄にも出す（見た目のため）
  window.scrollTo(0, 0);   // 前の場面で下へ送っていることがある（切り取りが画面の外に出る）
}, { tracks: TRACKS, n, size, opts });

/** マスを空にする（`seed(0)` では空にならない。0 曲を渡すと「今ある曲で埋め直す」になるため） */
const clearGrid = async () => {
  await seed(9);
  await page.click("#clear-btn");
  await page.waitForTimeout(200);
};

/** ジャケットが出そろうまで待つ（読み込み中の市松が写り込まないように） */
const waitArt = () => page.waitForFunction(() => {
  const imgs = [...document.querySelectorAll("#grid img")];
  return imgs.length > 0 && imgs.every(i => i.complete && i.naturalWidth > 0);
}, null, { timeout: 30000 }).catch(() => {});

/** 折りたたまれている補助フォームを開き、画面の中へ入れる（初期値で閉じているものがある） */
async function bring(sel) {
  await page.evaluate((sel) => {
    const box = document.querySelector(sel);
    if (box && box.dataset.collapsed === "true") box.querySelector(".sub-title")?.click();
    box?.scrollIntoView({ block: "center" });
  }, sel);
  await page.waitForTimeout(300);
}

/** つまみをマウスで掴んで動かす。**矢印キーで動かすと青い焦点の枠が付き、勝手に動いて見える**
    （利用者から指摘）。つまみの位置は画面側の thumbOnly と同じ式で出す（つまみの幅 19px）。
    dx は動かす量（px）。コマを撮りながら少しずつ運ぶ */
async function dragThumb(sel, dx, shot) {
  const c = await page.evaluate((sel) => {
    const el = document.querySelector(sel), r = el.getBoundingClientRect(), T = 19;
    const min = +el.min || 0, max = +el.max || 100, t = max > min ? (+el.value - min) / (max - min) : 0;
    return { x: r.left + T / 2 + t * (r.width - T), y: r.top + r.height / 2 };
  }, sel);
  await page.mouse.move(c.x, c.y);
  await page.mouse.down();
  const steps = 8;
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(c.x + dx * i / steps, c.y);
    await shot(); await page.waitForTimeout(1000 / FPS);
  }
  await page.mouse.up();
}

// ---- 1. 検索の窓 ----
if (want("search")) {
  await clearGrid();
  await page.waitForTimeout(400);
  await scene("search", rectPair(".pane-search", ".pane-results"), async (shot) => {
    await hold(shot, 0.6);
    await page.click("#q");
    await page.type("#q", "感電", { delay: 160 });
    await hold(shot, 0.5);
    await page.click("#search-btn");
    for (let i = 0; i < 25; i++) { await shot(); await page.waitForTimeout(100); }
    await hold(shot, 1.2);
  });
}

// ---- 2. 候補の窓 ----
if (want("results")) {
  // 候補が要るので、先に検索だけ済ませておく（撮らない）
  if (!(await page.$(".result"))) {
    await clearGrid();
    await page.fill("#q", "感電");
    await page.click("#search-btn");
    await page.waitForSelector(".result", { timeout: 20000 });
    await page.waitForTimeout(800);
  }
  await scene("results", rectPair(".pane-results", ".pane-grid"), async (shot) => {
    await hold(shot, 0.6);
    const items = await page.$$(".result");
    for (const it of items.slice(0, 3)) {
      await it.click();
      await hold(shot, 0.8);
    }
    await hold(shot, 0.8);
  });
}

// ---- 3. URL から（アルバムを丸ごと） ----
if (want("url")) {
  await clearGrid();
  await bring("#sub-bandcamp");
  await scene("url", rectRange(".pane-search", "#sub-bandcamp", "#bc-msg"), async (shot) => {
    await hold(shot, 0.6);
    await page.click("#bc-url");
    await page.type("#bc-url", "https://tbkgao.bandcamp.com/album/okane-ga-tarinai-toki-no-uta", { delay: 24 });
    await hold(shot, 0.6);
    await page.click("#bc-btn");
    for (let i = 0; i < 45; i++) {
      await shot(); await page.waitForTimeout(100);
      if (await page.$("#pl-modal:not([hidden])")) break;
    }
    await hold(shot, 0.6);
  });
  // 「まとめて取れました」の窓は別の場面にする。**切り取らない**（窓だけを切り取ると、
  // 押した瞬間に窓が消えて、以降のコマが真っ白になる。利用者から報告）。
  // **選べる道が 2 つある**ので、2 本撮る（マスに入れる／候補に置いて選ぶ）
  if (await page.$("#pl-modal:not([hidden])")) {
    await scene("url-pl", null, async (shot) => {
      await hold(shot, 1.6);
      await page.click("#pl-to-grid");
      await page.waitForTimeout(500);
      await hold(shot, 1.8);
    });
  }
  // もう一度取り込んで、こんどは「候補に置いて選ぶ」
  await clearGrid();
  await bring("#sub-bandcamp");
  // **欄は取り込みに成功すると空になる**ので、入れ直してから押す
  await page.fill("#bc-url", "https://tbkgao.bandcamp.com/album/okane-ga-tarinai-toki-no-uta");
  await page.click("#bc-btn");
  await page.waitForSelector("#pl-modal:not([hidden])", { timeout: 60000 }).catch(() => {});
  if (await page.$("#pl-modal:not([hidden])")) {
    await scene("url-pl2", null, async (shot) => {
      await hold(shot, 1.6);
      await page.click("#pl-to-results");
      await page.waitForTimeout(500);
      await hold(shot, 1.8);
      // 候補から 2 曲だけ入れてみせる（「選ぶ」ほうだと分かるように）
      const items = await page.$$(".result");
      for (const it of items.slice(0, 2)) { await it.click(); await hold(shot, 0.7); }
      await hold(shot, 1.0);
    });
  }
}

// ---- 4. 手入力 ----
if (want("manual")) {
  await clearGrid();
  await page.waitForTimeout(300);
  const src = TRACKS[0];
  await bring("#sub-manual");
  await scene("manual", rectRange(".pane-search", "#sub-manual", "#m-msg"), async (shot) => {
    await hold(shot, 0.6);
    await page.click("#m-image");
    await page.type("#m-image", src.image, { delay: 10 });
    await hold(shot, 0.4);
    await page.click("#m-title");
    await page.type("#m-title", src.title, { delay: 60 });
    await page.click("#m-artist");
    await page.type("#m-artist", src.artist, { delay: 60 });
    await hold(shot, 0.5);
    await page.click("#m-btn");
    await hold(shot, 1.4);
  });
}

// ---- 5. グリッドの窓（タップで入れ替え） ----
if (want("grid")) {
  await seed(9);
  await waitArt();
  await page.waitForTimeout(500);
  // **「大きく見る」はここでは撮らない**。あの窓は #grid-scroll ごとモーダルへ移すので、
  // グリッドの窓を切り取り続けると中身が抜けた枠が写る（利用者から「表示が乱れる」と報告）。
  // 画面ぜんぶを撮る別の場面（zoom）にしてある
  await scene("grid", rectSpan(".pane-grid", "#grid-msg"), async (shot) => {
    await hold(shot, 0.6);
    await page.click("#grid .cell:nth-child(1)");        // 1 つ目を選ぶ
    await hold(shot, 0.9);
    await page.click("#grid .cell:nth-child(5)");        // 5 つ目と入れ替え
    await hold(shot, 1.4);
  });
}

// ---- 6. 大きく見る（PC 向け） ----
if (want("zoom")) {
  await seed(256, [16, 16]);
  await page.waitForTimeout(1500);
  // **切り取らない**（モーダルは画面いっぱいに開くので、窓を切り取ると意味が無い）
  await scene("zoom", null, async (shot) => {
    await hold(shot, 1.0);
    await page.click("#zoom-btn");
    await page.waitForTimeout(400);
    await hold(shot, 1.6);
    await page.click("#grid .cell:nth-child(2)");
    await hold(shot, 0.8);
    await page.click("#grid .cell:nth-child(20)");
    await hold(shot, 1.2);
    await page.click("#zoom-modal-close");
    await page.waitForTimeout(400);
    await hold(shot, 0.8);
  });
}

// ---- 7. ドラッグ＆ドロップ（PC だけ。指では掴めない） ----
if (want("drag")) {
  await seed(9);
  await waitArt();
  await page.waitForTimeout(500);
  await scene("drag", rectSpan(".pane-grid", "#grid-msg"), async (shot) => {
    await hold(shot, 0.8);
    const from = await page.$("#grid .cell:nth-child(1)");
    const to = await page.$("#grid .cell:nth-child(6)");
    const a = await from.boundingBox(), b = await to.boundingBox();
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
    await page.mouse.down();
    // **1 手で運ばない**。途中のコマが無いと、何が起きたのか見ても分からない
    const steps = 14;
    for (let i = 1; i <= steps; i++) {
      await page.mouse.move(a.x + a.width / 2 + (b.x - a.x) * i / steps,
                            a.y + a.height / 2 + (b.y - a.y) * i / steps);
      await shot();
      await page.waitForTimeout(1000 / FPS);
    }
    await hold(shot, 0.5);
    await page.mouse.up();
    await hold(shot, 1.4);
  });
}

// ---- 8. 並びを保存／読み込み ----
if (want("io")) {
  await seed(9);
  await waitArt();
  await page.waitForTimeout(500);
  const tmp = path.join(outRoot, "_grid.json");
  // **マスも一緒に写す**。ボタンだけを切り取っていたので、押した結果（ファイルに落ちた・戻ってきた）が
  // 見えなかった（利用者から報告）。空にしてから読み込みで戻すと、何が起きたのか目で追える
  await scene("io", rectSpan(".pane-grid", ".msg-under"), async (shot) => {
    await hold(shot, 1.2);                            // 9 曲そろっているところ
    const [dl] = await Promise.all([
      page.waitForEvent("download", { timeout: 15000 }),
      page.click("#json-export"),
    ]);
    await dl.saveAs(tmp);
    await hold(shot, 2.0);                            // 「ファイルに保存しました」
    await page.click("#clear-btn");                   // わざと空にする
    await hold(shot, 1.6);
    await page.setInputFiles("#json-file", tmp);      // 「並びを読み込み」でファイルを選んだのと同じ
    await hold(shot, 2.2);                            // 9 曲が戻る
  });
  fs.rmSync(tmp, { force: true });
}

// ---- 9. 出力オプションの窓 ----
if (want("options")) {
  await seed(9);
  await waitArt();
  await page.waitForTimeout(400);
  // **下は「マスの間隔」まで入れる**（背景色・余白・間隔が切れている、と報告があった）
  await scene("options", rectRange(".pane-options", ".pane-options .pane-title", "#gap"), async (shot) => {
    await hold(shot, 0.6);
    for (const sel of ['input[name="ratio"][value="1:1"]', 'input[name="ratio"][value="9:16"]',
                       'input[name="ratio"][value="16:9"]']) {
      await page.click(`label:has(${sel})`);
      await hold(shot, 0.7);
    }
    const sw = await page.$$('#swatches label');
    for (const s of [sw[3], sw[5], sw[1]]) { await s.click(); await hold(shot, 0.6); }
    await dragThumb("#margin", 80, shot);
    await hold(shot, 0.6);
    await dragThumb("#gap", 90, shot);
    await hold(shot, 1.0);
  });
}

// ---- 10. パレット（8 色ひと組の入れ替え） ----
if (want("palette")) {
  await seed(9);
  await waitArt();
  await page.waitForTimeout(400);
  // 画面ぜんぶを撮る。**組を替えると背景色の見本だけでなく画面の装飾色まで変わる**のが要点。
  // **替えるたびに窓を閉じる**。開けっ放しだと暗い覆いが掛かったままで、
  // せっかく替えた色が沈んで見える（利用者から「くすんで見える」と報告）
  await scene("palette", null, async (shot) => {
    await hold(shot, 0.8);
    for (const i of [2, 3, 1]) {
      await page.click("#palette-btn");
      await page.waitForTimeout(300);
      await hold(shot, 0.7);
      const b = await page.$(`.pal-lane:nth-child(${i}) .pal-btns .btn`);
      if (b && !(await b.isDisabled())) { await b.click(); await hold(shot, 0.5); }
      await page.click("#pal-modal-close");
      await page.waitForTimeout(300);
      await hold(shot, 1.2);
    }
  });
}

// ---- 11. カスタムカラー ----
if (want("custom")) {
  await seed(9);
  await waitArt();
  await page.waitForTimeout(400);
  // 背景色の見出しが画面の上のほうに来るようにしておく（下に開くつまみまで入るように）
  await page.evaluate(() => document.querySelector(".swatches").scrollIntoView({ block: "start" }));
  await page.waitForTimeout(300);
  await scene("custom", rectFixed(".pane-options", ".swatches", 340), async (shot) => {
    await hold(shot, 0.8);
    await page.click("#bg-custom-btn");
    await page.waitForTimeout(250);
    await hold(shot, 0.8);
    await dragThumb("#hsv-h", 40, shot);
    await hold(shot, 0.4);
    await dragThumb("#hsv-s", 60, shot);
    await hold(shot, 0.4);
    await dragThumb("#hsv-v", -40, shot);
    await hold(shot, 1.6);
  });
}

// ---- 12〜13. スマホの画面だけの作り ----
if (want("sheet") || want("touchbar")) {
  const desktop = page;
  page = await openPage({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 2.625,
                          hasTouch: true, isMobile: true });

  // 「曲を探す」… 検索と候補を全画面のシートへ移す（狭い画面で 3 つの窓を並べられないため）
  if (want("sheet")) {
    await clearGrid();
    await page.waitForTimeout(400);
    await scene("sheet", null, async (shot) => {
      await hold(shot, 0.8);
      await page.click("#find-btn");
      await page.waitForTimeout(400);
      await hold(shot, 0.8);
      await page.fill("#q", "感電");
      await page.click("#search-btn");
      await page.waitForSelector(".result", { timeout: 20000 });
      await hold(shot, 1.0);
      // **クリックは DOM から呼ぶ**。シートの中は自前のスクロールバーで動かしているので、
      // Playwright の「見える位置まで送ってから押す」と噛み合わず、押せないまま待ち続ける
      await page.$eval(".result", (el) => el.click());
      await hold(shot, 1.0);
      // 候補を選ぶとシートは自分で閉じる。閉じていなければ「閉じる」を押す
      if (await page.$("#sheet:not([hidden])")) await page.click("#sheet-close");
      await page.waitForTimeout(400);
      await hold(shot, 1.0);
    });
  }

  // 自前のスクロールバー … 指ではブラウザのつまみを掴めないので、溝もつまみも自分で描いて動かす。
  // **出るのは「曲を探す」のシートの中**（グリッドの枠は中身が必ず収まる大きさに組むので出ない）
  if (want("touchbar")) {
    await clearGrid();
    await page.click("#find-btn");
    await page.waitForTimeout(400);
    await page.fill("#q", "感電");
    await page.click("#search-btn");
    await page.waitForSelector(".result", { timeout: 20000 });
    await page.waitForTimeout(1200);
    await scene("touchbar", null, async (shot) => {
      await hold(shot, 1.0);
      const th = await page.$("#sheet .tsb:not([hidden]) .tsb-thumb");
      const b = th && await th.boundingBox();
      if (b) {
        await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
        await page.mouse.down();
        for (let i = 1; i <= 18; i++) {
          await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2 + i * 16);
          await shot();
          await page.waitForTimeout(1000 / FPS);
        }
        await page.mouse.up();
      } else {
        console.warn("touchbar: つまみが出ていない");
      }
      await hold(shot, 1.2);
    });
  }
  page = desktop;
}

await browser.close();
