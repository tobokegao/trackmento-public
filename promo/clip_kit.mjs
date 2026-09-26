// X 向けの短い動画（1 機能 1 本）を撮る道具箱。`x_clips.mjs` が使う。
//
// 撮り方は本編の `capture.mjs` と同じ（2026-09-25 に中間案として切り替え）:
// - **ページの時計を止め**、1/30 秒ずつ進めては画面ぜんぶを 1 枚撮る。CSS のアニメーションも同じ時刻に合わせる
// - **カーソル・押した合図・カメラの行き先は描かずに、印（events.json）だけ残す**。描くのは Remotion（src/XClip.tsx）。
//   カメラが操作する所へ寄る・カーソルがなめらかに動く・終わりが始めにつながる、はそちらで作る
// - 撮ったコマは take.mp4 にまとめ、public/xclips/<id>/ に置く（Remotion が staticFile で読む）
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

export const FPS = 30;
const FF = path.resolve("promo/node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe");
const START_TIME = new Date("2026-09-25T12:00:00+09:00");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 画面を 1 つ開く（時計を止めた状態で）。**公開版に無いソースは撮らない**（手元の .env に DISCOGS_TOKEN があると
    候補に出るが、本番では未設定なので画面に出ない） */
export async function openPage(browser, opts) {
  const c = await browser.newContext({ locale: "ja-JP", permissions: ["clipboard-read", "clipboard-write"], ...opts });   // トラック名のコピー→貼り付けの場面のため
  const p = await c.newPage();
  await p.clock.install({ time: START_TIME });
  await p.goto("http://127.0.0.1:8000/", { waitUntil: "domcontentloaded" });
  for (let i = 0; i < 200 && !(await p.evaluate(() => !!window.__setGridUI)); i++) { await p.clock.runFor(50); await sleep(50); }
  // **消すのではなく隠す**。言語を替えるとソースの欄が描き直され、消した Discogs が戻ってくる
  await p.addStyleTag({ content: '#sources label:has(input[value="discogs"]) { display: none !important; }' });
  return p;
}

/** ページ 1 枚ぶんの道具。コマの数・印・カーソルの位置はここで持つ */
export function makeKit(page, tracks) {
  let frames = 0, frameDir = null, events = [];
  const vp = page.viewportSize();
  const nFrames = (sec) => Math.max(1, Math.round(sec * FPS));
  const ev = (type, extra = {}) => events.push({ f: frames, type, ...extra });

  /** 1 コマ進めて撮る。撮影前（frameDir が無い間）は時計だけ進める */
  async function frame() {
    const dt = Math.round((frames + 1) * 1000 / FPS) - Math.round(frames * 1000 / FPS);
    await page.clock.runFor(dt);
    if (!frameDir) return;
    await page.evaluate(() => {
      const now = performance.now();
      for (const a of document.getAnimations()) {
        if (a.__t0 === undefined) a.__t0 = now - (Number(a.currentTime) || 0);
        a.pause(); a.currentTime = now - a.__t0;
      }
    }).catch(() => {});
    frames++;
    fs.writeFileSync(path.join(frameDir, `${String(frames).padStart(5, "0")}.jpg`), await page.screenshot({ type: "jpeg", quality: 92 }));
  }
  /** sec 秒ぶんのコマを撮る */
  async function hold(sec) { for (let i = 0, n = nFrames(sec); i < n; i++) await frame(); }
  /** 撮らずに待つ（時計は進める。タイマー待ちの処理が止まらないように） */
  async function until(fn, label = "", timeout = 60000) {
    const t0 = Date.now();
    for (;;) {
      if (await fn().catch(() => false)) return true;
      if (Date.now() - t0 > timeout) throw new Error(`待ちきれない: ${label}`);
      await page.clock.runFor(50); await sleep(50);
    }
  }
  /** 撮りながら待つ（待つ様子を見せたいとき）。実時間とコマをおおよそ合わせる。min 秒は必ず撮る */
  async function live(fn, { timeout = 30, min = 0 } = {}) {
    const t0 = Date.now();
    for (let i = 0; ; i++) {
      const a = Date.now();
      await frame();
      if (i / FPS >= min && await fn().catch(() => false)) return true;
      if (Date.now() - t0 > timeout * 1000) return false;
      const rest = 1000 / FPS - (Date.now() - a); if (rest > 0) await sleep(rest);
    }
  }

  /** 要素をまとめた四角（画面の CSS px）。見えていない要素（大きさ 0）は数えない */
  const rectOf = (sels) => page.evaluate((sels) => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const s of sels) for (const el of document.querySelectorAll(s)) {
      const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
      x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top); x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom);
    }
    return x1 > x0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
  }, sels);

  /** カメラの行き先を決める（sels の要素をまとめた四角に寄る）。sec 秒かけて移る。撮影前なら最初の構図になる */
  async function look(sels, sec = 0.6) {
    const rect = await rectOf(sels);
    if (!rect) throw new Error(`look: ${sels.join(", ")} が見えていない`);
    ev("cam", { rect, dur: frameDir ? nFrames(sec) : 0 });
  }
  /** 要素の一部に寄る（fx, fy, fw, fh は要素の幅・高さに対する割合。書き出しの見本の番号バッジなど、小さいものを見せるとき。2026-09-26） */
  async function lookPart(sel, fx, fy, fw, fh, sec = 0.6) {
    const r = await rectOf([sel]);
    if (!r) throw new Error(`lookPart: ${sel} が見えていない`);
    ev("cam", { rect: { x: r.x + r.w * fx, y: r.y + r.h * fy, w: r.w * fw, h: r.h * fh }, dur: frameDir ? nFrames(sec) : 0 });
  }
  /** カメラを引く（画面ぜんぶ） */
  const wide = (sec = 0.6) => ev("cam", { rect: { x: 0, y: 0, w: vp.width, h: vp.height }, dur: frameDir ? nFrames(sec) : 0 });

  /** カーソルを置く（動かさずにその場へ。撮影前に最初の位置を決めるのに使う） */
  async function park(x, y) { ev("cursor", { x, y, dur: 0 }); await page.mouse.move(x, y); }
  /** カーソルを出さない（キーボードの場面）。**ページのマウスも画面の外へ出す**（乗せたままだと × が赤いまま残る） */
  async function hideCursor() { ev("hide"); await page.mouse.move(-10, -10); }
  /** 要素の真ん中の座標 */
  async function centerOf(sel) {
    const b = await page.locator(sel).first().boundingBox();
    if (!b) throw new Error(`見えていない: ${sel}`);
    return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
  }
  /** カーソルを要素まで運ぶ（動きは Remotion が描く。ページのマウスは着く直前に動かして、:hover を出す） */
  async function glide(sel, sec = 0.45) {
    const to = await centerOf(sel);
    const n = nFrames(sec);
    ev("cursor", { x: to.x, y: to.y, dur: n });
    for (let i = 0; i < n; i++) {
      if (i === n - 2) await page.mouse.move(to.x, to.y);
      await frame();
    }
  }
  /** 運んで押す。押した瞬間が印の時刻（Remotion が波紋を描く） */
  async function press(sel, { sec = 0.45 } = {}) {
    await glide(sel, sec);
    await hold(0.12);
    const { x, y } = await centerOf(sel);
    ev("down", { x, y });
    await page.mouse.down(); await frame();
    await page.mouse.up(); await frame();
    // **押したあとにボタンがずれたら、矢印もついて行く**（色で並べ替えを押すと、上の 3 行の説明が 1 行のメッセージに
    // 替わってボタンが上がる。矢印だけ残ると、下のリンクを押したように見える。gif_windows.mjs で利用者から指摘があった件）
    const el = page.locator(sel).first();
    const b = (await el.count()) && await el.boundingBox().catch(() => null);
    if (b) {
      const to = { x: b.x + b.width / 2, y: b.y + b.height / 2 };
      if (Math.hypot(to.x - x, to.y - y) > 2) { ev("cursor", { ...to, dur: nFrames(0.15) }); await page.mouse.move(to.x, to.y); }
    }
  }
  /** 指で押す（スマホの場面。印は press と同じなので、XClip は指の丸と輪を描く） */
  async function tap(sel, { sec = 0.4 } = {}) {
    await glide(sel, sec);
    await hold(0.1);
    const { x, y } = await centerOf(sel);
    ev("down", { x, y });
    await page.touchscreen.tap(x, y); await frame(); await frame();
  }
  /** 指で座標を押す（要素の真ん中でない所を押すとき） */
  async function tapAt(x, y, sec = 0.4) {
    ev("cursor", { x, y, dur: nFrames(sec) }); await hold(sec);
    ev("down", { x, y });
    await page.touchscreen.tap(x, y); await frame(); await frame();
  }
  /** 画面を指で送る（スマホの場面。dy だけ少しずつ送る。送り方はページの scrollBy） */
  async function swipe(dy, sec = 0.6, sel = null) {
    const n = nFrames(sec);
    for (let i = 0; i < n; i++) {
      await page.evaluate(({ d, sel }) => (sel ? document.querySelector(sel) : window).scrollBy(0, d), { d: dy / n, sel });
      await frame();
    }
  }
  /** キーを押す（押した印も残す。Remotion で押したキーを出すときに使える） */
  async function key(k) { ev("key", { key: k }); await page.keyboard.press(k); await frame(); }
  /** 1 字ずつ打つ */
  async function type(sel, text, perChar = 0.06) {
    await page.locator(sel).first().click();
    for (const ch of text) { await page.keyboard.insertText(ch); await hold(perChar); }
  }
  /** 掴んで運ぶ（マスのドラッグ・窓の題名バーなど）。from は掴む要素、to は運ぶ先の要素か {dx, dy}。
      Chromium ではマウスを少しずつ動かすと HTML5 のドラッグも起きる（2026-09-26） */
  async function drag(from, to, sec = 0.8, grab = null) {
    const a = grab ? await (async () => { const b = await page.locator(from).first().boundingBox(); return { x: b.x + b.width * grab[0], y: b.y + b.height * grab[1] }; })() : await centerOf(from);
    const b = typeof to === "string" ? await centerOf(to) : { x: a.x + to.dx, y: a.y + to.dy };
    ev("cursor", { x: a.x, y: a.y, dur: nFrames(0.35) }); await hold(0.35);
    await page.mouse.move(a.x, a.y);
    ev("down", { x: a.x, y: a.y, ring: false });
    await page.mouse.down(); await frame();
    const n = nFrames(sec);
    for (let i = 1; i <= n; i++) {
      const t = i / n, e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      const x = a.x + (b.x - a.x) * e, y = a.y + (b.y - a.y) * e;
      ev("cursor", { x, y, dur: 1 });
      await page.mouse.move(x, y); await frame();
    }
    await page.mouse.up(); await frame();
  }
  /** つまみを掴んで動かす（つまみの位置は画面側の thumbOnly と同じ式。幅 19px） */
  async function dragThumb(sel, dx, sec = 0.5) {
    const c = await page.evaluate((sel) => {
      const el = document.querySelector(sel), r = el.getBoundingClientRect(), T = 19;
      const min = +el.min || 0, max = +el.max || 100, t = max > min ? (+el.value - min) / (max - min) : 0;
      return { x: r.left + T / 2 + t * (r.width - T), y: r.top + r.height / 2 };
    }, sel);
    ev("cursor", { x: c.x, y: c.y, dur: nFrames(0.3) }); await hold(0.3);
    ev("down", { x: c.x, y: c.y, ring: false });
    await page.mouse.move(c.x, c.y); await page.mouse.down();
    const n = nFrames(sec);
    for (let i = 1; i <= n; i++) {
      // **手で動かしたような速さ**（ゆっくり動き出し、途中で速く、止まる前に減速。2026-09-26、利用者の指摘「等速だと機械っぽい」）
      const t = i / n, e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
      const x = c.x + dx * e;
      ev("cursor", { x, y: c.y, dur: 1 });
      await page.mouse.move(x, c.y); await frame();
    }
    await page.mouse.up();
  }
  /** Ctrl＋ホイール（トラックパッドの 2 本指と同じ）。**Playwright の mouse.wheel は Ctrl を押していても
      ctrlKey が付かない**ので、ページの中で WheelEvent を送る */
  const ctrlWheel = (x, y, dy) => page.evaluate(({ x, y, dy }) => {
    document.elementFromPoint(x, y)?.dispatchEvent(new WheelEvent("wheel", { deltaY: dy, clientX: x, clientY: y, ctrlKey: true, bubbles: true, cancelable: true }));
  }, { x, y, dy });

  /** **窓を好きな位置に並べる**（2026-09-25）。台本に書いた窓だけを画面の上に置き、ほかは隠す。
      layout は { セレクタ: { x, y, w, h?, only? } }（CSS px）。only を渡すと、その窓の中身（.pane-body の子）は
      only のセレクタに当たるものだけ残す（背景色の欄だけ見せる、など）。窓は並びの流れから外して画面に固定する
      （サイトの「窓を動かす」とは別。撮影のときだけ）。見本の窓などのモーダルはそのまま前に出る */
  async function arrange(layout) {
    const lines = ["body * { visibility: hidden !important; } .modal, .modal *, .popmenu, .popmenu * { visibility: visible !important; }"];   // ポップアップメニュー（#popmenu）も前に出す（2026-09-26。隠れたままだと項目を押せなかった）
    const others = Object.keys(layout).join("):not(");
    for (const [sel, o] of Object.entries(layout)) {
      lines.push(`${sel}, ${sel} * { visibility: visible !important; }`);
      lines.push(`${sel} { position: fixed !important; left: ${o.x}px !important; top: ${o.y}px !important; width: ${o.w}px !important; ` +
                 `${o.h ? `height: ${o.h}px !important; overflow: hidden !important; ` : ""}margin: 0 !important; transform: none !important; z-index: 50 !important; }`);
      // 台本に書いたほかの窓は、中身を絞っても消さない（「できあがり」の窓はグリッドの窓の中にある）
      if (o.only) lines.push(`${sel} > .pane-body > :not(${o.only.join("):not(")}):not(${others}) { display: none !important; }`);
      // 並べた窓の中にある別の窓（グリッドの窓の中の「できあがり」など）は、台本に無ければ見せない
      lines.push(`${sel} .pane:not(${others}) { display: none !important; }`);
    }
    await page.addStyleTag({ content: lines.join(" ") });
    await page.evaluate(() => window.scrollTo(0, 0));
  }

  /** 撮るあいだだけ見た目を足す（場面に関係のない部品を隠すなど） */
  const stage = (css) => page.addStyleTag({ content: css });
  /** 要素を画面の縦の位置 y（CSS px）へ送る（撮る前に。撮りながら送るとカメラと二重に動く） */
  const scrollTo = (sel, y = 80) => page.evaluate(({ sel, y }) => {
    window.scrollBy(0, document.querySelector(sel).getBoundingClientRect().top - y);
  }, { sel, y });

  /** **検索と URL 取得の応答を架空の曲に差し替える**（2026-09-26。動画に実在のジャケットを映さないため）。
      撮る前に 1 回呼ぶ。spec は { itunes?(term) → 曲の配列, search?(params) → 曲の配列, url?(url) → 曲 or null, playlist?(url) → 曲の配列 }。
      曲は fake-tracks.json と同じ形（source・title・artist・image…）。source を itunes / vocadb / otodb などにすると候補の札もそれになる。
      iTunes はブラウザから直接引く（itunesSearch）ので、iTunes の返事の形に直して返す。絵は手元のサーバーの /uploads/（**相対のまま渡す**。
      絶対 URL にすると画面が /image-proxy に回し、手元の宛先なのでサーバーが断る） */
  async function mock(spec) {
    const json = (route, body, headers = {}) => route.fulfill({ status: 200, contentType: "application/json", headers, body: JSON.stringify(body) });
    if (spec.itunes) await page.route(/^https:\/\/itunes\.apple\.com\/search/, (route) => {
      const term = new URL(route.request().url()).searchParams.get("term") || "";
      json(route, { results: spec.itunes(term).map((t, i) => ({ wrapperType: "track", trackName: t.title, artistName: t.artist,
        collectionName: t.album || null, artworkUrl100: t.thumb || t.image, trackViewUrl: t.external_url || `https://music.apple.com/jp/album/x?i=${900000 + i}` })) });
    });
    if (spec.search) await page.route(/\/search\?/, (route) => {
      const u = new URL(route.request().url());
      if (u.hostname !== "127.0.0.1") return route.fallback();
      json(route, spec.search(Object.fromEntries(u.searchParams)));
    });
    if (spec.url || spec.playlist) await page.route(/\/from-(url|playlist)$/, (route) => {
      const { url } = JSON.parse(route.request().postData() || "{}");
      const got = route.request().url().endsWith("/from-playlist") ? spec.playlist?.(url) : spec.url?.(url);
      if (!got || (Array.isArray(got) && !got.length)) return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "見つかりませんでした" }) });
      json(route, got);
    });
  }

  /** n マスぶん曲を入れる。足りなければ**繰り返して埋める**。list で曲の一覧を差し替えられる */
  const seed = (n, size = [3, 3], opts = {}, list = tracks) => page.evaluate(({ tracks, n, size, opts }) => {
    window.__setGridUI(size[0], size[1], { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true,
                                         margin: 16, gap: 16, bg: "mustard", bgCustom: null, ...opts },
                     Array.from({ length: n }, (_, i) => tracks[i % tracks.length]));
    document.querySelector("#title").value = opts.title ?? "私を構成する9曲";
    window.scrollTo(0, 0);
  }, { tracks: list, n, size, opts });

  /** ジャケットが出そろうまで待つ（読み込み中の市松が写り込まないように） */
  const waitArt = () => until(() => page.evaluate(() => {
    const imgs = [...document.querySelectorAll("#grid img")];
    return imgs.length > 0 && imgs.every((i) => i.complete && i.naturalWidth > 0);
  }), "ジャケット", 30000).catch(() => {});

  /** 撮り始める（ここから先の印とコマが動画になる）。撮影前に置いた印（最初の構図・カーソル）は 0 コマ目に寄せる */
  function start(dir) {
    fs.rmSync(dir, { recursive: true, force: true });
    frameDir = path.join(dir, "frames");
    fs.mkdirSync(frameDir, { recursive: true });
    for (const e of events) e.f = 0;
    frames = 0;
  }
  /** 撮り終える。take.mp4 と events.json を書く */
  async function finish(dir, meta) {
    execFileSync(FF, ["-y", "-v", "error", "-framerate", String(FPS), "-i", path.join(frameDir, "%05d.jpg"),
      "-c:v", "libx264", "-preset", "medium", "-crf", "14", "-pix_fmt", "yuv420p", "-g", "15", "-movflags", "+faststart", path.join(dir, "take.mp4")]);
    fs.rmSync(frameDir, { recursive: true, force: true });
    const dpr = await page.evaluate(() => devicePixelRatio);
    fs.writeFileSync(path.join(dir, "events.json"), JSON.stringify({ ...meta, fps: FPS, frames, vw: vp.width, vh: vp.height, dpr, events }, null, 1));
    return frames;
  }

  return { page, tracks, frame, hold, until, live, look, lookPart, wide, park, hideCursor, glide, press, tap, tapAt, swipe, key, type, drag, dragThumb,
           ctrlWheel, arrange, stage, scrollTo, seed, mock, waitArt, start, finish };
}
