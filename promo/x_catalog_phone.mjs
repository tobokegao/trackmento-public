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
    what: "スマホでも「PC 版の表示」に切り替えられる。窓は指で題名バーを掴んで動かせる",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9));
      await k.page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await k.hold(0.3);
      k.wide(0);
      await k.park(200, 700);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#view-pc");
      await k.hold(0.6);
      await k.page.evaluate(() => window.scrollTo(0, 0));
      await k.hold(1.0);
      await k.drag(".pane-results > .pane-title", { dx: 60, dy: 220 }, 1.0, [0.3, 0.5]);
      await k.hold(1.0);
      // スマホ版に戻す（撮影の片付け。映さない）
      await k.page.$eval("#win-reset", (el) => el.click()).catch(() => {});
      await k.page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      await k.hold(0.3);
      await k.tap("#view-sp");
      await k.hold(0.6);
    },
  },
  {
    id: "sp-editor",
    phone: true,
    what: "スマホでマスを押すと、グリッドのすぐ下に編集の欄が出る（トラック名・メモ・このマスのサムネ余白）",
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
      await k.hold(1.6);
      await k.tap("#e-close");
      await k.hold(0.6);
      await scrollTo(k, "#grid-scroll", 60);
      await k.hold(0.6);
    },
  },
  {
    id: "sp-share-target",
    phone: true,
    what: "Android でホーム画面に追加しておくと、ほかのアプリの「共有」から URL を送れる（送ると自動で取り込む）",
    async setup(k) {
      const wide = nico();
      await k.mock({ url: () => ({ ...wide[2], source: "youtube", external_url: "https://www.youtube.com/watch?v=AbCdEfGhIjK" }) });
      await place(k, 3, 3, withHoles(square(), 9, [3, 4, 5, 6, 7, 8]));
      // 撮影用の擬似の共有シート（本物の Android の共有シートは撮れないので、ページの上に描く。サイトの機能ではない）
      await k.stage(`.x-share, .x-share * { box-sizing: border-box; font: 15px/1.4 "Roboto", "Noto Sans JP", sans-serif; }
        .x-share { position: fixed; inset: 0; z-index: 90; background: rgba(0,0,0,.35); display: flex; align-items: flex-end; }
        .x-share .s { width: 100%; background: #fff; border-radius: 18px 18px 0 0; padding: 18px 16px 28px; }
        .x-share .h { color: #444; margin-bottom: 4px; } .x-share .u { color: #777; font-size: 12px; margin-bottom: 16px; word-break: break-all; }
        .x-share .apps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px 8px; }
        .x-share .a { display: grid; justify-items: center; gap: 6px; font-size: 12px; color: #333; }
        .x-share .a i { width: 48px; height: 48px; border-radius: 50%; background: #ddd; }
        .x-share .a.tm i { background: #fff url('/icon-192.png') center / 100% no-repeat; border: 1px solid #ccc; }`);
      await k.page.evaluate(() => {
        const d = document.createElement("div"); d.className = "x-share"; d.id = "x-share";
        d.innerHTML = `<div class="s"><div class="h">共有</div><div class="u">https://www.youtube.com/watch?v=AbCdEfGhIjK</div>
          <div class="apps"><div class="a"><i></i>メッセージ</div><div class="a"><i></i>メール</div><div class="a tm" id="x-share-tm"><i></i>TRACKMENTO</div><div class="a"><i></i>コピー</div></div></div>`;
        document.body.append(d);
      });
      k.wide(0);
      await k.park(300, 500);
    },
    async run(k) {
      await k.hold(1.0);
      await k.tap("#x-share-tm");
      await k.page.evaluate(() => document.querySelector("#x-share")?.remove());
      // 共有から開いたのと同じ URL で開き直す（manifest の share_target が /?st_url=… で開く）
      await k.page.goto("http://127.0.0.1:8000/?st_url=" + encodeURIComponent("https://www.youtube.com/watch?v=AbCdEfGhIjK"), { waitUntil: "domcontentloaded" });
      for (let i = 0; i < 200 && !(await k.page.evaluate(() => !!window.__setGridUI)); i++) { await k.page.clock.runFor(50); await new Promise((r) => setTimeout(r, 50)); }
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#results .result").length >= 1), "取り込み", 15000);
      await k.hold(0.8);
      // 取り込んだ曲はシートの下の候補に入るので、そこまで送って見せる
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
    what: "スマホのスライダーは、つまみを掴んだときだけ動く（ページを送ろうとして溝に触れても値が飛ばない）",
    async setup(k) {
      await place(k, 3, 3, square().slice(0, 9), { gap: 16 });
      // スマホでは出力オプションの窓が畳まれて始まるので開く
      if (await k.page.evaluate(() => document.querySelector(".pane-options").dataset.collapsed === "true")) await k.page.click(".pane-options > .pane-title .fold");
      await scrollTo(k, "#gap", 420);
      k.wide(0);
      await k.park(300, 700);
    },
    async run(k) {
      await k.hold(0.8);
      // 溝の右のほうを押しても値は変わらない（つまみから離れた所を指で押す）
      const r = await k.page.locator("#gap").boundingBox();
      const x = r.x + r.width * 0.8, y = r.y + r.height / 2;
      await k.page.evaluate(() => {});   // （印はページの外で付ける）
      await k.hold(0.1);
      await k.glide("#gap", 0.01).catch(() => {});
      await k.tapAt(x, y);
      await k.hold(1.0);
      await k.dragThumb("#gap", 120, 0.9);
      await k.hold(1.0);
      await k.dragThumb("#gap", -120, 0.6);
      await k.hold(0.6);
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
