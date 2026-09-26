// X に載せる短い動画の台本・4 段目「スマホの画面」（2026-09-26）。決まりは x_catalog.mjs の頭と同じ。
// **phone: true** の場面は 390×844 のスマホの画面で撮り、XClip が 16:9 の真ん中にスマホの枠を描いてその中に映す（利用者の決定）。
// 押すのは k.tap（指の丸で出る）。送るのは k.swipe。窓の並べ直し（k.arrange）は使わない（スマホの画面はそのまま見せる）
import fs from "node:fs";
import { nico } from "./x_catalog.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));

/** 並べる（空きマスは null） */
async function place(k, cols, rows, cells, opts = {}) {
  await k.page.evaluate(({ cols, rows, cells, opts }) => {
    window.__setGridUI(cols, rows, { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true, margin: 16, gap: 16, bg: "mustard", bgCustom: null, ...opts }, cells);
    document.querySelector("#title").value = opts.title ?? "私を構成する9曲";
  }, { cols, rows, cells, opts });
  await k.hold(0.3);
  await k.waitArt();
}
const withHoles = (list, n, holes) => Array.from({ length: n }, (_, i) => (holes.includes(i) ? null : list[i % list.length]));
/** 要素を画面の上から y の所へ送る（撮る前） */
const scrollTo = (k, sel, y = 80) => k.page.evaluate(({ sel, y }) => window.scrollBy(0, document.querySelector(sel).getBoundingClientRect().top - y), { sel, y });
/** 検索の返事を架空の曲に（題に検索語を含むものしか残らないので、題を検索語＋付け足しにする） */
async function mockSearch(k, q, list) {
  const tails = ["", " (Live)", " - Remix", " (Acoustic)", " (Piano ver.)"];
  await k.mock({ itunes: () => list.map((t, i) => ({ ...t, source: "itunes", title: `${q}${tails[i % tails.length]}` })) });
}

export default [
  {
    id: "sp-sheet",
    phone: true,
    what: "スマホでは「トラックを探す」で検索のシートが開く。空きマスを押すと、そのマスに入れるトラックを探せる",
    async setup(k) {
      const sq = square();
      await mockSearch(k, "夜明けのシグナル", [sq[15], sq[9], sq[12]]);   // 1 番と違う曲（同じ曲だと「同じトラック」の知らせが出て話がそれる）
      await place(k, 3, 3, withHoles(sq, 9, [4, 6, 7, 8]));
      await scrollTo(k, "#grid-scroll", 60);
      k.wide(0);
      await k.park(300, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#find-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#sheet").hidden), "シート", 5000);
      await k.hold(0.5);
      await k.tap("#q");
      await k.type("#q", "夜明けのシグナル", 0.07);
      await k.tap("#search-btn");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#results .result").length >= 3), "候補", 15000);
      await k.hold(0.8);
      await k.tap("#results li:nth-child(1) .result");
      await k.until(() => k.page.evaluate(() => document.querySelector("#sheet").hidden), "シートが閉じる", 5000);
      await k.waitArt();
      await k.hold(1.0);
      await k.tap("#grid .cell:nth-child(7)");   // 空きマス → その番号でシートが開く（5 番はさっき入った）
      await k.until(() => k.page.evaluate(() => !document.querySelector("#sheet").hidden), "シート", 5000);
      await k.hold(1.4);
      await k.tap("#sheet-close");
      await k.hold(0.8);
    },
  },
  {
    id: "sp-scroll",
    phone: true,
    what: "スマホのスクロールバーは自前で描いている。上下の三角で少しずつ、つまみを掴めば一気に送れる",
    async setup(k) {
      await place(k, 4, 16, Array.from({ length: 64 }, (_, i) => square()[i % 24]), { title: "今年のベスト 64" });
      await scrollTo(k, "#grid-scroll", 90);
      k.wide(0);
      await k.park(360, 500);
    },
    async run(k) {
      await k.hold(0.8);
      const bar = ".pane-grid .tsb";
      for (let i = 0; i < 3; i++) { await k.tap(`${bar} .tsb-down`, { sec: i ? 0.15 : 0.4 }); await k.hold(0.35); }
      await k.hold(0.4);
      await k.drag(`${bar} .tsb-thumb`, { dx: 0, dy: 260 }, 0.9);
      await k.hold(0.8);
      await k.drag(`${bar} .tsb-thumb`, { dx: 0, dy: -400 }, 0.8);
      await k.hold(0.8);
    },
  },
  {
    id: "sp-view",
    phone: true,
    what: "スマホでもページのいちばん下の「PC 版の表示」で PC の画面にできる。「スマホ版の表示」で戻る",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await k.hold(0.3);
      k.wide(0);   // スマホ版の引きの絵から（利用者の指定）
      await k.park(200, 600);
    },
    async run(k) {
      await k.hold(1.0);
      await k.look(["#view-pc", "#view-sp"], 0.7);   // リンクに寄る
      await k.hold(0.6);
      await k.tap("#view-pc");
      await k.waitReload();   // 切り替えはページを読み直す
      // 撮影用のブラウザは幅 1024 の画面を縮めて見せないので、実機と同じく画面の幅に合わせて縮める（390 / 1024）
      const cdp = await k.page.context().newCDPSession(k.page);
      await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 390 / 1024 });
      for (let i = 0; i < 5; i++) { await k.page.clock.runFor(50); await new Promise((r) => setTimeout(r, 50)); }
      // PC 版も引きの絵から、いちばん下の「スマホ版の表示」に寄る
      await k.page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      k.wide(0);   // PC 版は画面ぜんぶが縮めて入る（リンクは右下）
      await k.hold(1.4);
      await k.look(["#view-pc", "#view-sp"], 0.7);
      await k.hold(0.6);
      await k.tap("#view-sp");
      await k.waitReload();
      await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
      await k.page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      k.wide(0);
      await k.hold(1.0);
    },
  },
  {
    id: "sp-editor",
    phone: true,
    what: "スマホでマスを押すと、グリッドのすぐ下に編集の欄が出る。トラック名を直したり、このマスだけサムネの入れ方を変えたりできる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await scrollTo(k, "#grid-scroll", 60);
      k.wide(0);
      await k.park(300, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#grid .cell:nth-child(5)");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#editor").hidden), "編集欄", 5000);
      await k.hold(0.8);
      // 欄を使うところを見せる（出るだけだと、どこの何か分かりにくい、と利用者）
      await k.tap("#e-title");
      await k.page.fill("#e-title", "");
      await k.type("#e-title", "迷子の自販機 (Remix)", 0.06);
      await k.hold(0.6);
      await scrollTo(k, "#e-fit-seg", 520);
      await k.hold(0.3);
      await k.tap('#e-fit-seg label:has(input[value="blur"])');
      await k.hold(0.6);
      await scrollTo(k, "#grid-scroll", 60);
      await k.hold(1.4);
      await k.tap("#e-close");
      await k.hold(0.6);
    },
  },
  {
    id: "sp-share-target",
    phone: true,
    // 本物の YouTube のページを開くので、Android の Chrome の名乗りで開く（スマホ向けのページになる）
    ctx: { userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36" },
    what: "Android でホーム画面に追加しておくと、YouTube などの「共有」から TRACKMENTO に URL を送れる（送ると自動で取り込む）",
    async setup(k) {
      await place(k, 3, 3, withHoles(square(), 9, [3, 4, 5, 6, 7, 8]));
      // **共有元は本物の YouTube のページ**（2026-09-26、利用者の指定）。スマホの YouTube の「共有」はブラウザの共有シート（navigator.share）を
      // 呼ぶので、それを撮影用の Android の共有シートに差し替える（本物のシートは撮れない）。TRACKMENTO の絵はページに埋め込む
      // （よそのページの安全設定で、手元のサーバーの画像は読めない）
      const icon = "data:image/png;base64," + fs.readFileSync("frontend/icon-192.png").toString("base64");
      await k.page.addInitScript(({ icon }) => {
        const show = (url) => {
          const st = document.createElement("style");
          st.textContent = `.x-share,.x-share *{box-sizing:border-box;font:15px/1.4 "Roboto","Noto Sans JP",sans-serif}
            .x-share{position:fixed;inset:0;z-index:2147483000;background:rgba(0,0,0,.45);display:flex;align-items:flex-end}
            .x-share .s{width:100%;background:#fff;color:#222;border-radius:18px 18px 0 0;padding:18px 16px 28px}
            .x-share .h{margin-bottom:4px}.x-share .u{color:#777;font-size:12px;margin-bottom:16px;word-break:break-all}
            .x-share .apps{display:grid;grid-template-columns:repeat(4,1fr);gap:16px 8px}.x-share .a{display:grid;justify-items:center;gap:6px;font-size:12px;color:#333}
            .x-share .a i{width:48px;height:48px;border-radius:50%;background:#ddd}.x-share .a.tm i{background:#fff url('${icon}') center/100% no-repeat;border:1px solid #ccc}`;
          // YouTube は TrustedTypes で innerHTML を使わせないので、部品ごとに組み立てる
          const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
          const d = el("div", "x-share"), sh = el("div", "s"), apps = el("div", "apps");
          for (const [name, cls, id] of [["メッセージ", "a"], ["メール", "a"], ["TRACKMENTO", "a tm", "x-share-tm"], ["コピー", "a"]]) {
            const a = el("div", cls); if (id) a.id = id; a.append(el("i"), name); apps.append(a);
          }
          sh.append(el("div", "h", "共有"), el("div", "u", url), apps); d.append(sh);
          document.body.append(st, d);
        };
        Object.defineProperty(navigator, "share", { configurable: true, value: async (data) => { show((data && data.url) || location.href); } });
        Object.defineProperty(navigator, "canShare", { configurable: true, value: () => true });
      }, { icon });
      await k.page.goto("https://m.youtube.com/watch?v=CQ-DZfQhXcc", { waitUntil: "domcontentloaded", timeout: 30000 });
      for (let i = 0; i < 70; i++) { await k.page.clock.runFor(100); await new Promise((r) => setTimeout(r, 100)); }
      // 広告の枠があれば撮影のときだけ隠す（撮るたびに中身が替わり、よその商品が映るため）
      await k.page.addStyleTag({ content: "ytm-promoted-sparkles-web-renderer, ad-slot-renderer, ytm-companion-slot, .ytp-ad-module, ytm-statement-banner-renderer { display: none !important; }" });
      await k.page.evaluate(() => window.scrollTo(0, 0));
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      await k.hold(1.4);
      const share = k.page.locator('button[aria-label*="共有"], [aria-label="共有"]').first();
      const box = await share.boundingBox();
      await k.tapAt(box.x + box.width / 2, box.y + box.height / 2);
      await k.until(() => k.page.evaluate(() => !!document.querySelector("#x-share-tm")), "共有シート", 8000).catch(async () => {
        await k.page.evaluate(() => navigator.share({ url: "https://www.youtube.com/watch?v=CQ-DZfQhXcc" }));   // YouTube 側の窓が出たときの保険
      });
      await k.hold(1.0);
      await k.tap("#x-share-tm");
      // 共有から開いたのと同じ URL で開く（manifest の share_target が /?st_url=… で開く）。取り込みは本物（手元のサーバーが YouTube に問い合わせる）
      await k.page.goto("http://127.0.0.1:8000/?st_url=" + encodeURIComponent("https://www.youtube.com/watch?v=CQ-DZfQhXcc"), { waitUntil: "domcontentloaded" });
      for (let i = 0; i < 200 && !(await k.page.evaluate(() => !!window.__setGridUI)); i++) { await k.page.clock.runFor(50); await new Promise((r) => setTimeout(r, 50)); }
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#results .result").length >= 1), "取り込み", 30000);
      await k.until(() => k.page.evaluate(() => [...document.querySelectorAll("#results img")].every((i) => i.complete)), "サムネ", 15000).catch(() => {});
      await k.hold(0.6);
      await k.swipe(await k.page.evaluate(() => { const r = document.querySelector("#results").getBoundingClientRect(); return Math.max(0, r.top - 300); }), 0.7, "#sheet .sheet-body");
      await k.hold(1.0);
      await k.tap("#results li:nth-child(1) .result");
      await k.waitArt();
      await k.hold(1.4);
    },
  },
  {
    id: "sp-slider",
    phone: true,
    what: "スマホのスライダーは、つまみを掴んだときだけ動く（ページを送ろうとして溝に触れても値が飛ばない）。右は同じ並びのグリッド",
    async setup(k) {
      const cells = square().slice(0, 9);
      await place(k, 3, 3, cells, { gap: 16 });
      if (await k.page.evaluate(() => document.querySelector(".pane-options").dataset.collapsed === "true")) await k.page.click(".pane-options > .pane-title .fold");
      await scrollTo(k, "#gap", 420);
      // **2 台目のスマホ**（右）にグリッドを映し、コマごとに左のマスの間隔を写す（2026-09-26、利用者の案）
      const p2 = await k.page.context().newPage();
      await p2.clock.install({ time: new Date("2026-09-25T12:00:00+09:00") });
      await p2.goto("http://127.0.0.1:8000/", { waitUntil: "domcontentloaded" });
      for (let i = 0; i < 200 && !(await p2.evaluate(() => !!window.__setGridUI)); i++) { await p2.clock.runFor(50); await new Promise((r) => setTimeout(r, 50)); }
      await p2.evaluate((cells) => { window.__setGridUI(3, 3, { title: "私を構成する9曲", gap: 16 }, cells); }, cells);
      for (let i = 0; i < 20; i++) { await p2.clock.runFor(100); await new Promise((r) => setTimeout(r, 50)); }
      await p2.evaluate(() => window.scrollBy(0, document.querySelector("#grid-scroll").getBoundingClientRect().top - 60));
      k.setTwin(p2, async () => {
        const v = await k.page.$eval("#gap", (g) => g.value);
        await p2.evaluate((v) => { const g = document.querySelector("#gap"); if (g.value !== v) { g.value = v; g.dispatchEvent(new Event("input", { bubbles: true })); } }, v);
      });
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      await k.hold(0.8);
      // 溝の右のほうを押しても値は変わらない（つまみから離れた所を指で押す）
      const r = await k.page.locator("#gap").boundingBox();
      await k.tapAt(r.x + r.width * 0.8, r.y + r.height / 2);
      await k.hold(1.0);
      await k.dragThumb("#gap", 120, 1.0);
      await k.hold(1.0);
      await k.dragThumb("#gap", -120, 0.8);
      await k.hold(0.8);
    },
  },
  {
    id: "sp-inapp",
    phone: true,
    what: "X や LINE のアプリの中で開くと、ブラウザで開き直す案内と「URL をコピー」が出る（アプリの中では保存や共有がうまく動かないことがあるため）",
    async setup(k) {
      await k.page.goto("http://127.0.0.1:8000/?x=inapp#inapp", { waitUntil: "domcontentloaded" });   // 読み込み直す（# だけ替えるとページが読み直されず、案内が出ない）
      for (let i = 0; i < 200 && !(await k.page.evaluate(() => !!window.__setGridUI)); i++) { await k.page.clock.runFor(50); await new Promise((r) => setTimeout(r, 50)); }
      await place(k, 3, 3, square().slice(0, 9));
      await k.page.evaluate(() => window.scrollTo(0, 0));
      k.wide(0);
      await k.park(300, 500);
    },
    async run(k) {
      await k.hold(1.2);
      await k.tap("#inapp-copy");
      await k.hold(1.6);
    },
  },
];
