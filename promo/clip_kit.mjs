// 数秒の GIF を撮るための道具箱。X 向けの `x_clips.mjs` が使う。
// 中身は `gif_windows.mjs`（note の記事用）で詰めた撮り方を、ページごとに持てる形にしたもの。
// あちらで分かった落とし穴（矢印をコマごとに運ぶ・切り取りを画面の中に収める など）はそのまま残してある。
import fs from "node:fs";
import path from "node:path";

export const FPS = 10;

/** 画面を 1 つ開く。**公開版に無いソースは撮らない**（手元の .env に DISCOGS_TOKEN があると
    候補に出るが、本番では未設定なので画面に出ない） */
export async function openPage(browser, opts) {
  const c = await browser.newContext({ locale: "ja-JP", ...opts });
  // **カーソルは自前で描く**（システムのカーソルはスクリーンショットに写らない）。promo/cursor.js
  await c.addInitScript({ path: "promo/cursor.js" });
  const p = await c.newPage();
  await p.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle" });
  await p.waitForFunction(() => window.__setGridUI);
  // **消すのではなく隠す**。言語を替えるとソースの欄が描き直され、消した Discogs が戻ってくる
  await p.addStyleTag({ content: '#sources label:has(input[value="discogs"]) { display: none !important; }' });
  return p;
}

// ---- 撮る範囲（ページの中で評価する関数を返す。画面が動いても追従できるように） ----
export const rectOf = (sel, pad = 8) => new Function("", `
  const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect();
  return { x: r.x - ${pad}, y: r.y - ${pad}, width: r.width + ${pad * 2}, height: r.height + ${pad * 2} };`);

/** a と b を両方含む範囲 */
export const rectPair = (a, b) => new Function("", `
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  const q = document.querySelector(${JSON.stringify(b)}).getBoundingClientRect();
  const x = Math.min(p.x, q.x) - 8, y = Math.min(p.y, q.y) - 8;
  return { x, y, width: Math.max(p.right, q.right) - x + 8, height: Math.max(p.bottom, q.bottom) - y + 8 };`);

/** a の上端から b の下端まで（横幅は a） */
export const rectSpan = (a, b) => new Function("", `
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  const q = document.querySelector(${JSON.stringify(b)}).getBoundingClientRect();
  return { x: p.x - 8, y: p.y - 8, width: p.width + 16, height: q.bottom - p.y + 16 };`);

/** 横幅は w の窓、縦は a の上端から b の下端まで */
export const rectRange = (w, a, b) => new Function("", `
  const o = document.querySelector(${JSON.stringify(w)}).getBoundingClientRect();
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  const q = document.querySelector(${JSON.stringify(b)}).getBoundingClientRect();
  return { x: o.x - 8, y: p.y - 8, width: o.width + 16, height: q.bottom - p.y + 16 };`);

/** 横幅は w の窓、縦は a の上端から決め打ちの高さ。**途中で開く部分を入れるときはこちら**
    （閉じている間は高さが 0 なので、下端を要素から取るとコマごとに切り取りの大きさが変わる） */
export const rectFixed = (w, a, h) => new Function("", `
  const o = document.querySelector(${JSON.stringify(w)}).getBoundingClientRect();
  const p = document.querySelector(${JSON.stringify(a)}).getBoundingClientRect();
  return { x: o.x - 8, y: p.y - 8, width: o.width + 16, height: ${h} };`);

/** いくつかの要素をまとめて囲む範囲（窓をまたいで、操作する所と結果の出る所を一緒に撮る）。
    **見えていない要素（高さ 0）は数えない**（閉じている欄を入れると範囲が跳ねる） */
export const rectUnion = (...sels) => new Function("", `
  const rs = ${JSON.stringify(sels)}.map(s => document.querySelector(s)?.getBoundingClientRect()).filter(r => r && r.height > 0);
  const x = Math.min(...rs.map(r => r.x)) - 8, y = Math.min(...rs.map(r => r.y)) - 8;
  return { x, y, width: Math.max(...rs.map(r => r.right)) + 8 - x, height: Math.max(...rs.map(r => r.bottom)) + 8 - y };`);

/** ページ 1 枚ぶんの道具。矢印の位置（cursorAt）はページごとに持つ */
export function makeKit(page, tracks) {
  let cursorAt = { x: 640, y: 360 };
  const tick = () => page.waitForTimeout(1000 / FPS);

  /** 指定の秒数ぶん、その場のコマを撮る（何も起きていない間の「ため」にも使う） */
  async function hold(shot, sec) {
    const n = Math.max(1, Math.round(sec * FPS));
    for (let i = 0; i < n; i++) { await shot(); await tick(); }
  }

  /** 矢印をその要素の真ん中まで**コマを撮りながら**運ぶ。`page.click` は一瞬で飛ぶので、
      何を押したのか見ても分からない */
  async function glide(sel, shot, steps = 5) {
    const b = await (await page.$(sel)).boundingBox();
    const to = { x: b.x + b.width / 2, y: b.y + b.height / 2 };
    for (let i = 1; i <= steps; i++) {
      await page.mouse.move(cursorAt.x + (to.x - cursorAt.x) * i / steps, cursorAt.y + (to.y - cursorAt.y) * i / steps);
      await shot(); await tick();
    }
    cursorAt = to;
  }

  /** 運んで押す。**押したあとに画面がずれたら、矢印もボタンについて行く** */
  async function press(sel, shot) {
    await glide(sel, shot);
    await hold(shot, 0.2);
    await page.mouse.down(); await shot();
    await page.mouse.up();
    await page.waitForTimeout(80);
    const el = await page.$(sel);
    const b = el && await el.boundingBox();
    if (b) { cursorAt = { x: b.x + b.width / 2, y: b.y + b.height / 2 }; await page.mouse.move(cursorAt.x, cursorAt.y); }
  }

  /** 矢印を座標へ置く（撮らない）。場面の頭で、押す所から少し離しておくのに使う */
  async function park(x, y) { cursorAt = { x, y }; await page.mouse.move(x, y); }

  /** 文字を 1 字ずつ打つ（打つ間もコマを撮る） */
  async function type(sel, text, shot, perChar = 1) {
    await page.click(sel);
    for (const ch of text) {
      await page.keyboard.type(ch);
      for (let i = 0; i < perChar; i++) { await shot(); await tick(); }
    }
  }

  /** 折りたたまれている補助フォームを開き、画面の中へ入れる */
  async function bring(sel) {
    await page.evaluate((sel) => {
      const box = document.querySelector(sel);
      if (box && box.dataset.collapsed === "true") box.querySelector(".sub-title")?.click();
      box?.scrollIntoView({ block: "center" });
    }, sel);
    await page.waitForTimeout(300);
  }

  /** つまみをマウスで掴んで動かす（矢印キーだと焦点の枠が付き、勝手に動いて見える）。
      つまみの位置は画面側の thumbOnly と同じ式（つまみの幅 19px） */
  async function dragThumb(sel, dx, shot, steps = 4) {
    const c = await page.evaluate((sel) => {
      const el = document.querySelector(sel), r = el.getBoundingClientRect(), T = 19;
      const min = +el.min || 0, max = +el.max || 100, t = max > min ? (+el.value - min) / (max - min) : 0;
      return { x: r.left + T / 2 + t * (r.width - T), y: r.top + r.height / 2 };
    }, sel);
    await page.mouse.move(c.x, c.y);
    await page.mouse.down();
    for (let i = 1; i <= steps; i++) {
      await page.mouse.move(c.x + dx * i / steps, c.y);
      await shot(); await tick();
    }
    await page.mouse.up();
    cursorAt = { x: c.x + dx, y: c.y };
  }

  /** n マスぶん曲を入れる。足りなければ**繰り返して埋める**。list で曲の一覧を差し替えられる */
  const seed = (n, size = [3, 3], opts = {}, list = tracks) => page.evaluate(({ tracks, n, size, opts }) => {
    window.__setGridUI(size[0], size[1], { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true,
                                         margin: 16, gap: 16, bg: "mustard", bgCustom: null, ...opts },
                     Array.from({ length: n }, (_, i) => tracks[i % tracks.length]));
    document.querySelector("#title").value = opts.title ?? "私を構成する9曲";
    window.scrollTo(0, 0);
  }, { tracks: list, n, size, opts });

  /** 要素を画面の縦の位置 y（CSS px）へ送る（切り取る範囲を画面の中に収めるため） */
  const scrollTo = (sel, y = 80) => page.evaluate(({ sel, y }) => {
    window.scrollBy(0, document.querySelector(sel).getBoundingClientRect().top - y);
  }, { sel, y });

  /** 撮るあいだだけ見た目を足す（場面に関係のない部品を隠すなど）。戻すときは返り値の関数を呼ぶ */
  async function stage(css) {
    const tag = await page.addStyleTag({ content: css });
    return () => tag.evaluate((el) => el.remove());
  }

  /** Ctrl＋ホイール（トラックパッドの 2 本指と同じ）。**Playwright の mouse.wheel は Ctrl を押していても
      ctrlKey が付かない**ので、ページの中で WheelEvent を送る */
  const ctrlWheel = (x, y, dy) => page.evaluate(({ x, y, dy }) => {
    document.elementFromPoint(x, y)?.dispatchEvent(new WheelEvent("wheel", { deltaY: dy, clientX: x, clientY: y, ctrlKey: true, bubbles: true, cancelable: true }));
  }, { x, y, dy });

  /** マスを空にする（`seed(0)` は「今ある曲で埋め直す」になるので使えない） */
  async function clearGrid() {
    await seed(9);
    await page.click("#clear-btn");
    await page.click("#confirm-yes");
    await page.waitForTimeout(200);
  }

  /** ジャケットが出そろうまで待つ（読み込み中の市松が写り込まないように） */
  const waitArt = () => page.waitForFunction(() => {
    const imgs = [...document.querySelectorAll("#grid img")];
    return imgs.length > 0 && imgs.every(i => i.complete && i.naturalWidth > 0);
  }, null, { timeout: 30000 }).catch(() => {});

  return { page, tracks, scrollTo, stage, ctrlWheel, hold, glide, press, park, type, bring, dragThumb, seed, clearGrid, waitArt, tick };
}

/** 地の模様だけを撮る（窓をすべて隠して、紙の色と粒だけにする）。16:9 に組むときの背景に使う */
export async function captureDesk(page, file) {
  const y = await page.evaluate(() => window.scrollY);
  await page.evaluate(() => window.scrollTo(0, 0));
  const tag = await page.addStyleTag({ content: "body > * { visibility: hidden !important; }" });
  await page.screenshot({ path: file });
  await tag.evaluate((el) => el.remove());
  await page.evaluate((y) => window.scrollTo(0, y), y);
}

/** 場面を 1 つ撮る。clipOf は撮る範囲を返す関数（null なら画面ぜんぶ）。
    コマは <dir>/f000.png…、組むときに要る情報は <dir>/meta.json */
export async function record(page, dir, clipOf, steps, meta = {}, follow = false) {
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });
  await captureDesk(page, path.join(dir, "desk.png"));
  let i = 0;
  const vp = page.viewportSize();
  // **撮る範囲は最初に 1 回だけ決める**（follow のときだけ毎コマ測り直す）。毎コマ測ると、
  // マスの形を替えたときなどに範囲が伸び縮みして、組んだ動画の中で窓が跳ねる
  const fixed = clipOf && !follow ? await page.evaluate(clipOf) : null;
  const shot = async () => {
    let clip = fixed ? { ...fixed } : clipOf ? await page.evaluate(clipOf) : undefined;
    // **切り取りは画面の中に収める**。はみ出すと Playwright がその範囲を撮れずに固まる
    if (clip) {
      const x = Math.max(0, clip.x), y = Math.max(0, clip.y);
      clip = { x, y, width: Math.min(clip.x + clip.width, vp.width) - x, height: Math.min(clip.y + clip.height, vp.height) - y };
    }
    await page.screenshot({ path: path.join(dir, `f${String(i++).padStart(3, "0")}.png`), clip });
  };
  await steps(shot);
  const dpr = await page.evaluate(() => devicePixelRatio);
  fs.writeFileSync(path.join(dir, "meta.json"), JSON.stringify({ ...meta, dpr, viewport: vp, frames: i, full: !clipOf }, null, 2));
  return i;
}
