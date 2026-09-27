// Instagram・TikTok 向けの短い動画・スマホ版の台本（続き）。決まりは x_catalog_sp.mjs の頭と同じ。
// 元は x_catalog_flow.mjs（はじめて使う流れ）の 8 本と x_catalog_intro.mjs の howto-intro（2026-09-27）。
// 差し替え方（検索・URL・共有・探すページの返事）は元の台本と同じ。スマホでは検索と候補がシートに入る
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import { ready, nico } from "./x_catalog.mjs";
import { variants, as, empty } from "./x_catalog_flow.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));

/** 要素を画面の上から y の所へ送る（撮る前） */
const scrollTo = (k, sel, y = 60) => k.page.evaluate(({ sel, y }) => window.scrollBy(0, document.querySelector(sel).getBoundingClientRect().top - y), { sel, y });
/** 空のグリッドから始める（グリッドが画面の上のほうに来るように送る） */
async function start(k, size, opts, first) {
  await empty(k, size, opts, first);
  await scrollTo(k, "#grid-scroll", 60);
  await k.hold(0.2);
  k.wide(0);
  await k.park(300, 640);
}
const sheetShown = (k) => k.until(() => k.page.evaluate(() => !document.querySelector("#sheet").hidden), "シートが開く", 5000);
const sheetGone = (k) => k.until(() => k.page.evaluate(() => document.querySelector("#sheet").hidden), "シートが閉じる", 5000);
const resultsAtLeast = (k, n) => k.until(() => k.page.evaluate((n) => document.querySelectorAll("#results .result").length >= n, n), "候補", 15000);
/** シートの中を、候補の窓の頭が上から y の所に来るまで送る */
async function toResults(k, y = 150, sec = 0.5) {
  const dy = await k.page.evaluate((y) => document.querySelector(".pane-results").getBoundingClientRect().top - y, y);
  if (dy > 4) await k.swipe(dy, sec, "#sheet-body");
}
/** シートの中の欄を、上から y の所へ送る（撮りながら） */
async function sheetTo(k, sel, y = 200, sec = 0.4) {
  const dy = await k.page.evaluate(({ sel, y }) => document.querySelector(sel).getBoundingClientRect().top - y, { sel, y });
  if (Math.abs(dy) > 4) await k.swipe(dy, sec, "#sheet-body");
}
/** 「トラックを探す」でシートを開く */
async function openFind(k) {
  await k.tap("#find-btn");
  await sheetShown(k);
  await k.hold(0.3);
}
/** シートの中の補助の欄（URL から・トラック名の一覧から・手入力）を指で開く */
async function tapSub(k, sel, y = 170) {
  await k.tap(`${sel} > .sub-title`);
  await k.hold(0.3);
  await sheetTo(k, sel, y);
}
/** 欄を空にしてから 1 字ずつ打つ（指で押してから） */
async function retype(k, sel, text, perChar = 0.06) {
  await k.tap(sel);
  await k.page.fill(sel, "");
  await k.hold(0.15);
  await k.type(sel, text, perChar);
}
/** 架空の「みんなのグリッドを探す」ページ（promo/fake_find.py。元の f-find と同じ） */
const fakeFind = (q, own) => execFileSync(".venv/Scripts/python", ["promo/fake_find.py", JSON.stringify({ q, own })],
  { env: { ...process.env, PYTHONUTF8: "1" }, encoding: "utf-8" });
/** 共有の場面で「できあがり」の窓を縮める（説明文と宣伝を隠す。元の SHARE_CSS と同じ） */
const SHARE_CSS = "#output .msg-under, #output .support, #output .listed { display: none !important; }";
const FIND_CSS = "#output .msg-under, #output .support { display: none !important; }";
const shareDone = (k) => k.page.evaluate(() => !document.querySelector("#share-done").hidden && document.querySelector("#up-modal").hidden);

export default [
  {
    id: "f-sources-sp",
    phone: true,
    what: "ソースを VocaDB にするとボカロの原曲、otoDB にすると音MAD が見つかる（otoDB は消えた動画のサムネも出る）",
    async setup(k) {
      const sq = square(), wide = nico();
      const MAD = ["", "の歌", " 2nd", "メドレー", "リミックス", "ループ"];
      await k.mock({ search: (p) => p.source === "vocadb"
        ? variants(p.q, sq.slice(6), 5, "vocadb").map((t, i) => ({ ...t, artist: `${sq[6 + i].artist} feat. 初音ミク` }))
        : as("otodb", wide.slice(0, 6)).map((t, i) => ({ ...t, title: `【音MAD】${p.q}${MAD[i]}` })) });
      await start(k);
    },
    async run(k) {
      await k.hold(0.8);
      await openFind(k);
      await k.tap('#sources label:has(input[value="vocadb"])');
      await k.hold(0.2);
      await retype(k, "#q", "はんぶんこの月");
      await k.tap("#search-btn");
      await resultsAtLeast(k, 3);
      await k.hold(0.3);
      await toResults(k);
      await k.hold(1.6);
      await sheetTo(k, "#q", 190, 0.5);   // 上へ戻して、ソースを替える
      await k.tap('#sources label:has(input[value="otodb"])');
      await k.hold(0.2);
      await retype(k, "#q", "迷子の自販機");
      await k.tap("#search-btn");
      await k.until(() => k.page.evaluate(() => document.querySelector("#results .badge")?.dataset.source === "otodb"), "otoDB の候補", 15000);
      await k.hold(0.3);
      await toResults(k);
      await k.hold(2.0);
    },
  },
  {
    id: "f-multi-url-sp",
    phone: true,
    what: "違うサイトの URL を 1 行に 1 つずつ貼れば、まとめて取れる（YouTube・SoundCloud・Bandcamp を混ぜても）",
    async setup(k) {
      const sq = square(), wide = nico();
      await k.mock({ url: (u) => u.includes("youtube") ? { ...wide[4], source: "youtube" }
        : u.includes("soundcloud") ? { ...sq[11], source: "soundcloud" } : { ...sq[14], source: "bandcamp" } });
      await start(k);
    },
    async run(k) {
      await k.hold(0.8);
      await openFind(k);
      await tapSub(k, "#sub-bandcamp");
      await k.tap("#bc-url");
      // **1 回で打つ**（分けると押した所にカーソルが移って行が混ざる。元の f-multi-url と同じ）
      await k.type("#bc-url", "https://www.youtube.com/watch?v=AbCdEfGhIjK\nhttps://soundcloud.com/tsubame/night-walk\nhttps://violet.bandcamp.com/track/violet-hour", 0.025);
      await k.hold(0.3);
      await k.tap("#bc-btn");
      await resultsAtLeast(k, 3);
      await k.hold(0.3);
      await toResults(k);
      await k.hold(2.4);
    },
  },
  {
    id: "f-playlist-pick-sp",
    phone: true,
    what: "まとめて取ったトラックを「候補に置いて選ぶ」と、候補に並べて好きなものだけマスに入れられる",
    async setup(k) {
      const wide = nico();
      await k.mock({ playlist: () => wide.map((t, i) => ({ ...t, source: "youtube", external_url: `https://www.youtube.com/watch?v=x${i}` })) });
      await start(k, [3, 3], { cellRatio: "16:9", title: "好きな音MAD" });
    },
    async run(k) {
      await k.hold(0.8);
      await openFind(k);
      await tapSub(k, "#sub-bandcamp");
      await k.tap("#bc-url");
      await k.type("#bc-url", "https://www.youtube.com/playlist?list=PLx7fAkEpLaYl1sT", 0.03);
      await k.tap("#bc-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pl-modal").hidden), "まとめて取れた窓", 15000);
      await k.hold(1.0);
      await k.tap("#pl-to-results");
      await resultsAtLeast(k, 6);
      await k.hold(0.3);
      await toResults(k);
      await k.hold(0.6);
      // 候補を押すとシートが閉じてマスに入る。開き直すと候補は残っているので、続けて選ぶ
      for (const [i, n] of [3, 6].entries()) {
        if (i) { await openFind(k); await toResults(k, 150, 0.4); await k.hold(0.2); }
        await k.tap(`#results li:nth-child(${n}) .result`);
        await sheetGone(k);
        await k.waitArt();
        await k.hold(i ? 1.8 : 0.6);
      }
    },
  },
  {
    id: "f-list-sp",
    phone: true,
    what: "アーティスト名とトラック名の表を打って「一覧から入れる」。1 行ずつ探して、ぴったり合えばマスへ",
    async setup(k) {
      const sq = square();
      await k.mock({ itunes: (term) => sq.filter((t) => term.includes(t.title) && term.includes(t.artist)).map((t) => ({ ...t, source: "itunes" })) });
      await start(k);
    },
    async run(k) {
      const sq = square();
      await k.hold(0.8);
      await openFind(k);
      await tapSub(k, "#sub-list", 130);
      for (const [i, t] of [sq[3], sq[7], sq[13]].entries()) {
        const cell = (key) => `#list-rows input[data-row="${i}"][data-key="${key}"]`;
        await k.tap(cell("artist"), { sec: 0.3 });
        await k.type(cell("artist"), t.artist, 0.05);
        await k.tap(cell("title"), { sec: 0.25 });
        await k.type(cell("title"), t.title, 0.05);
      }
      await k.hold(0.3);
      await k.tap("#list-btn");
      await k.hold(0.4);
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#grid img").length >= 3), "一覧から入る", 20000);
      await k.hold(0.8);   // 「3 トラックをマスに入れました」
      await k.tap("#sheet-close");
      await sheetGone(k);
      await k.waitArt();
      await k.hold(2.0);
    },
  },
  {
    id: "f-copy-paste-sp",
    phone: true,
    what: "「トラック名をコピー」で番号付きの一覧に。「トラック名の一覧から」の表に貼ると、行と列に分かれて戻る",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await scrollTo(k, "#grid-scroll", 40);   // グリッドと「トラック名をコピー」を 1 画面に
      await k.hold(0.2);
      k.wide(0);
      await k.park(300, 640);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#text-copy");
      await k.hold(1.2);   // 「9 トラックの名前をコピーしました」
      await openFind(k);
      await tapSub(k, "#sub-list", 130);
      const first = '#list-rows input[data-row="0"][data-key="artist"]';
      // 長押しで出る「貼り付け」の吹き出し（撮影用に描く。ヘッドレスでは端末の吹き出しが出ない）
      await k.tap(first);
      await k.hold(0.4);
      await k.page.evaluate((sel) => {
        const r = document.querySelector(sel).getBoundingClientRect();
        const b = document.createElement("div");
        b.id = "x-paste";
        b.textContent = "貼り付け";
        Object.assign(b.style, { position: "fixed", left: `${r.left}px`, top: `${r.top - 46}px`, zIndex: 2147483000, padding: "9px 16px",
          background: "#303134", color: "#fff", font: '14px/1.2 "Roboto","Noto Sans JP",sans-serif', borderRadius: "8px", boxShadow: "0 2px 6px rgba(0,0,0,.35)" });
        b.addEventListener("mousedown", (e) => e.preventDefault());
        document.body.append(b);
      }, first);
      await k.hold(0.5);
      await k.tap("#x-paste");
      await k.page.evaluate(() => document.querySelector("#x-paste").remove());
      await k.page.focus(first);
      await k.page.keyboard.press("Control+v");   // 吹き出しの「貼り付け」の中身（キーの印は残さない）
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#list-rows .list-row").length >= 9), "貼り付け", 5000);
      await k.hold(0.6);
      await sheetTo(k, "#list-rows", 190, 0.5);
      await k.hold(2.4);
    },
  },
  {
    id: "f-manual-sp",
    phone: true,
    what: "手元の画像でも入れられる。「端末から画像を選択…」で選び、トラック名とアーティスト名を入れて追加（撮影日時などは消して保存）",
    async setup(k) {
      const sq = square();
      // 端末から上げた画像は、本番の R2 に置かずに手元の架空の絵で返す
      await k.page.route(/\/upload$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ url: sq[21].image }) }));
      await start(k, [3, 3], {}, sq.slice(0, 4));
    },
    async run(k) {
      await k.hold(0.8);
      await openFind(k);
      await tapSub(k, "#sub-manual", 180);
      const fc = k.page.waitForEvent("filechooser");
      await k.tap("#m-file-btn");
      await (await fc).setFiles({ name: "ねこじゃらし.jpg", mimeType: "image/jpeg", buffer: fs.readFileSync("uploads/" + square()[21].image.split("/").pop()) });
      await k.until(() => k.page.evaluate(() => !!document.querySelector("#m-image").value), "画像の取り込み", 10000);
      await k.hold(0.8);
      await k.tap("#m-artist");
      await k.type("#m-artist", "まるいち", 0.07);
      await k.hold(0.3);
      await k.tap("#m-btn");
      await resultsAtLeast(k, 1);
      await k.hold(0.3);
      await toResults(k);
      await k.hold(0.6);
      await k.tap("#results li:nth-child(1) .result");   // 手入力のトラックも候補の先頭に入る。押すとマスへ
      await sheetGone(k);
      await k.waitArt();
      await k.hold(1.8);
    },
  },
  {
    id: "f-share-sp",
    phone: true,
    what: "「トラックを共有」で画像と URL ができる。共有ページでは曲名からそれぞれのページへ飛べる（共有は 30 日で消える）",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      if (await k.page.isChecked("#opt-listed")) await k.page.uncheck("#opt-listed");   // みんなのグリッドには載せない
      // 共有 URL の欄に手元のサーバーの宛先（127.0.0.1:8000）が映らないよう、返事の URL だけ本番の形に替える
      await k.page.route(/\/share\/upload$/, async (route) => {
        const r = await route.fetch(), j = await r.json();
        if (j.url) j.url = j.url.replace(/^https?:\/\/[^/]+/, "https://trackmento.com");
        await route.fulfill({ response: r, json: j });
      });
      await k.stage(SHARE_CSS);
      await scrollTo(k, "#grid-scroll", 40);
      await k.hold(0.2);
      k.wide(0);
      await k.park(300, 640);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#share-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#up-modal").hidden), "送信中の窓", 10000).catch(() => {});
      await k.live(() => shareDone(k), { min: 0.8, timeout: 90 });
      await k.hold(0.6);
      // できた URL と「共有ページを開く」が見える所まで送る
      await k.swipe(await k.page.evaluate(() => Math.max(0, document.querySelector("#open-share").getBoundingClientRect().bottom - 780)), 0.6);
      await k.hold(1.4);
      // 新しいタブではなく同じ画面で、手元のサーバーの共有ページを開く（本番の URL に行かない）
      await k.page.evaluate(() => { const a = document.querySelector("#open-share"); a.removeAttribute("target"); a.href = new URL(a.href).pathname; });
      await k.tap("#open-share");
      await k.page.waitForURL(/\/s\/[0-9a-f]{12}/, { timeout: 20000 });
      await k.until(() => k.page.evaluate(() => [...document.images].every((i) => i.complete)), "共有ページ", 20000);
      // 共有ページの下の「この URL: …」にも手元の宛先が出るので、本番の形に書き替える（撮る前に）
      await k.page.evaluate(() => {
        const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        for (let n; (n = w.nextNode());) if (n.nodeValue.includes("127.0.0.1")) n.nodeValue = n.nodeValue.replace(/https?:\/\/127\.0\.0\.1:8000/g, "https://trackmento.com");
      });
      await k.hold(1.4);
      // 曲名の一覧（それぞれのページへのリンク）まで送る
      await k.swipe(await k.page.evaluate(() => { const l = document.querySelector("main ol, ol"); return l ? Math.max(0, l.getBoundingClientRect().top - 200) : 300; }), 0.8);
      await k.hold(1.8);
    },
  },
  {
    id: "f-find-sp",
    phone: true,
    what: "「みんなのグリッドに載せる」にチェックして共有すると、トラック名やアーティスト名で探せるようになる。自分の並びは × で外せる",
    async setup(k) {
      // **本番には何も置かない**: 共有の返事も探すページも差し替える（元の f-find と同じ）
      const own = { id: "fa4e0ab1c2d3", title: "私を構成する9曲" };
      await k.page.route(/\/share\/upload$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        id: own.id, url: `https://trackmento.com/s/${own.id}`, image: "/uploads/fa4e010000000000.jpg", png: "/uploads/fa4e010000000000.jpg",
        ext: "jpg", width: 2400, height: 1350, ownerKey: "clip-owner-key-0000", listed: true }) }));
      await k.page.route(/\/find(\?.*)?$/, (route) => {
        const q = new URL(route.request().url()).searchParams.get("q") || "";
        route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: fakeFind(q, own) });
      });
      await k.page.route(/\/s\/fa4e[0-9a-f]+\/unlist$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: own.id, action: "unlist" }) }));
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await k.stage(FIND_CSS);
      await scrollTo(k, "#grid-scroll", 40);
      await k.hold(0.2);
      k.wide(0);
      await k.park(300, 640);
    },
    async run(k) {
      await k.hold(0.8);
      await k.tap("#opt-listed");
      await k.hold(0.5);
      await k.tap("#share-btn");
      await k.live(() => shareDone(k), { min: 0.8, timeout: 90 });
      await k.hold(0.8);
      // 「みんなのグリッド」の文字から探すページへ（新しいタブではなく同じ画面で）
      await k.page.evaluate(() => document.querySelector("#find-link").removeAttribute("target"));
      await k.tap("#find-link");
      await k.page.waitForURL(/\/find/, { timeout: 20000 });
      await k.page.evaluate(() => document.activeElement?.blur());
      await k.hold(1.4);
      await k.tap('form.find input[name="q"]');
      await k.type('form.find input[name="q"]', "シグナル", 0.09);
      await k.hold(0.3);
      await k.tap('form.find button[type="submit"]');
      await k.page.waitForURL(/\/find\?q=/, { timeout: 20000 });
      await k.page.evaluate(() => document.activeElement?.blur());
      await k.hold(1.4);
      await k.tap(".own-rm");
      await k.until(() => k.page.evaluate(() => !!document.querySelector(".odlg")), "確認の窓", 5000);
      await k.hold(1.0);
      await k.tap('.odlg-btns .btn:not(.odlg-default)');   // 「外す」（既定は「やめる」）
      await k.hold(1.8);
    },
  },
  {
    id: "howto-intro-sp",
    phone: true,
    what: "「使い方の動画」のページ。知りたいことの題を押すと、その操作の数秒の動画が流れる（題は YouTube のアプリから直接送れますか？）",
    async setup(k) {
      await k.page.goto("http://127.0.0.1:8000/howto", { waitUntil: "domcontentloaded" });
      for (let i = 0; i < 30; i++) { await k.page.clock.runFor(100); await new Promise((r) => setTimeout(r, 50)); }
      await k.page.evaluate(() => document.fonts && document.fonts.ready);
      // ページの動画はコマ送りで撮る（元の howto-intro と同じ。操作の帯は撮るあいだだけ外す）
      await k.page.evaluate(() => document.querySelector("#sp-share-target video").removeAttribute("controls"));
      await k.page.evaluate(() => window.scrollTo(0, 0));
      k.wide(0);
      await k.park(300, 640);
    },
    async run(k) {
      const CLIP = "#sp-share-target";
      await k.hold(1.4);                                                    // 題「使い方の動画」と頭の説明
      await k.swipe(await k.page.evaluate((sel) => document.querySelector(sel).getBoundingClientRect().top - 420, CLIP), 1.4);   // 「スマホで使う」の問いまで
      await k.hold(0.5);
      await k.tap(CLIP + " summary");
      await k.until(() => k.page.evaluate((sel) => { const v = document.querySelector(sel + " video"); return v.readyState >= 2 && v.duration > 0; }, CLIP), "動画", 30000);
      await k.page.evaluate((sel) => { const v = document.querySelector(sel + " video"); v.pause(); v.__t = 0; }, CLIP);
      k.setOnFrame(() => k.page.evaluate((sel) => new Promise((res) => {
        const v = document.querySelector(sel + " video");
        v.pause();
        v.__t = (v.__t + 1 / 30) % v.duration;
        v.addEventListener("seeked", () => res(), { once: true });
        v.currentTime = v.__t;
      }), CLIP));
      // 題と答えと動画が 1 画面に入るよう送る
      await k.swipe(await k.page.evaluate((sel) => document.querySelector(sel).getBoundingClientRect().top - 60, CLIP), 0.8);
      const dur = await k.page.evaluate((sel) => document.querySelector(sel + " video").duration, CLIP);
      await k.hold(Math.min(dur, 9) + 0.4);
    },
  },
];
