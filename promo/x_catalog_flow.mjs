// X に載せる短い動画の台本・1 段目「はじめて使う流れ」（2026-09-26）。決まりは x_catalog.mjs の頭と同じ。
// 段取りは題材の台帳（https://claude.ai/artifact/GZ3kefBb8ouyGpV5fc2MRo）の「撮影の段取り」。
//
// - **初めて見る人向け**。何手か続いて初めて伝わるものなので 1 本 8〜15 秒まで
// - **検索・URL・プレイリストの応答は k.mock で架空の曲に差し替える**（実在のジャケットを映さない。本物の相手にも問い合わせない）
// - 窓は k.arrange で「検索」「候補」「グリッド」を横に並べる（出力オプションは映さない）
import fs from "node:fs";
import { execFileSync } from "node:child_process";
import { ready, nico, GT } from "./x_catalog.mjs";

const square = () => JSON.parse(fs.readFileSync("promo/public/fake-tracks.json", "utf-8"));

/** 流れの場面の窓の置き方。左に検索、真ん中に候補、右にグリッド（グリッドの窓はマスとメッセージだけ） */
const ARRANGE_FLOW = {
  ".pane-search": { x: 24, y: 24, w: 400 },
  ".pane-results": { x: 444, y: 24, w: 360, h: 672 },
  ".pane-grid": { x: 824, y: 24, w: 432, only: ["#grid-scroll", "#grid-msg"] },
};
const ST = ".pane-search > .pane-title", RT = ".pane-results > .pane-title";
/** 表から入れる場面の窓の置き方。左に検索（一覧の欄）、右にグリッド。候補の窓は使わないので出さない */
const ARRANGE_LIST = {
  ".pane-search": { x: 150, y: 24, w: 480 },
  ".pane-grid": { x: 680, y: 24, w: 450, only: ["#grid-scroll", "#grid-msg"] },
};
/** トラック名をコピーして表に貼り戻す場面。左に一覧の欄、真ん中にグリッド、右に「できあがり」（コピーのボタンがある） */
const ARRANGE_COPY = {
  ".pane-search": { x: 24, y: 24, w: 520 },
  ".pane-grid": { x: 568, y: 24, w: 360, only: ["#grid-scroll", "#grid-msg"] },
  "#output": { x: 952, y: 24, w: 304 },
};
/** 共有の場面。左にグリッド、右に「できあがり」（見本・共有のボタン・共有したあとの URL） */
const ARRANGE_SHARE = {
  ".pane-grid": { x: 60, y: 24, w: 440, only: ["#grid-scroll", "#grid-msg"] },
  "#output": { x: 540, y: 16, w: 560 },
};
/** 共有の場面で「できあがり」の窓を縮める。見本の絵が入ると窓が 720px を超え、「共有ページを開く」が画面の外に出る */
const SHARE_CSS = "#output .msg-under, #output .support, #output .listed { display: none !important; }";
/** みんなのグリッドの場面。「載せる」のチェックは見せたいので、下の説明文と宣伝だけ隠す */
const FIND_CSS = "#output .msg-under, #output .support { display: none !important; }";
/** 架空の「みんなのグリッドを探す」ページ（promo/fake_find.py。本番の探すページは利用者の本物の題が並ぶので使わない） */
const fakeFind = (q, own) => execFileSync(".venv/Scripts/python", ["promo/fake_find.py", JSON.stringify({ q, own })],
  { env: { ...process.env, PYTHONUTF8: "1" }, encoding: "utf-8" });
/** 検索の窓で、使わない補助の欄を隠す（keep に書いた欄だけ残す） */
const onlySubs = (...keep) => ["#sub-bandcamp", "#sub-list", "#sub-manual"].filter((s) => !keep.includes(s))
  .map((s) => `${s} { display: none !important; }`).join(" ");

/** 同じ曲名の候補をいくつか作る（別の人のカバー・ライブ版など）。絵は架空のジャケットを順に使う */
function variants(title, list, n = 6, source = "itunes") {
  const tails = ["", " (Acoustic)", " - Remix", " (Live)", " -Instrumental-", " (2026 Remaster)", " (Piano ver.)", " - Short"];
  return Array.from({ length: n }, (_, i) => {
    const c = list[(i * 5) % list.length];
    return { source, title: title + tails[i % tails.length], artist: i % 3 === 2 ? c.artist : list[0].artist, album: null,
             image: c.image, thumb: c.thumb, external_url: `https://example.com/track/${i}` };
  });
}
/** 架空の曲をそのまま候補にする（出どころの札だけ替える） */
const as = (source, list, extra = {}) => list.map((t, i) => ({ ...t, source, external_url: `https://example.com/${source}/${i}`, ...extra }));

/** 空の 3×3 から始める（入れていくところを見せる） */
async function empty(k, size = [3, 3], opts = {}, first = []) {
  // seed(0) だと空の配列が「見本で埋める」扱いになるので、空きマスを null で渡す。first は先に入れておく曲
  await k.page.evaluate(({ size, opts, first }) => {
    const cells = Array(size[0] * size[1]).fill(null);
    first.forEach((t, i) => { cells[i] = t; });
    window.__setGridUI(size[0], size[1], { title: "私を構成する9曲", showTitle: true, sidebar: true, numbers: true,
                                         margin: 16, gap: 16, bg: "mustard", bgCustom: null, ...opts }, cells);
    document.querySelector("#title").value = "私を構成する9曲";
    window.scrollTo(0, 0);
  }, { size, opts, first });
  await k.hold(0.3);
  await k.waitArt();
}
/** 補助の欄（URL から・トラック名の一覧から・手入力）を開いておく（撮る前に。1 つ開くとほかは閉じる） */
async function openSub(k, sel) {
  if (await k.page.getAttribute(`${sel} > .sub-title`, "aria-expanded") !== "true") await k.page.click(`${sel} > .sub-title`);
}
/** 欄を空にしてから 1 字ずつ打つ */
async function retype(k, sel, text, perChar = 0.06) {
  await k.glide(sel, 0.35);
  await k.page.fill(sel, "");
  await k.hold(0.15);
  await k.type(sel, text, perChar);
}
/** 候補がそろうまで待つ */
const resultsAtLeast = (k, n, label = "候補") =>
  k.until(() => k.page.evaluate((n) => document.querySelectorAll("#results .result").length >= n, n), label, 15000);
/** 補助の欄だけを見せる場面（上の検索の欄は隠す） */
const subOnly = (sel) => onlySubs(sel) + " #search-form { display: none !important; }";

export default [
  {
    id: "f-search",
    what: "トラック名で探して、候補を押すと空きマスに入る。候補には出どころの札が付く",
    async setup(k) {
      const list = square();
      await k.mock({ itunes: (term) => variants(term, list) });
      await empty(k);
      await k.arrange(ARRANGE_FLOW); await k.stage(onlySubs());
      await k.look([ST, "#search-form"]);
      await k.park(700, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.glide("#q", 0.4);
      await k.type("#q", "夜明けのシグナル", 0.07);
      await k.hold(0.3);
      await k.press("#search-btn");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#results .result").length > 3), "候補", 10000);
      await k.look([ST, RT, "#search-form", "#results"], 0.7);
      await k.hold(1.0);
      await k.look([RT, GT, "#results", "#grid"], 0.7);
      await k.press("#results li:nth-child(1) .result");
      await k.hold(0.6);
      await k.press("#results li:nth-child(3) .result");
      await k.hold(0.6);
      await k.press("#results li:nth-child(2) .result");
      await k.waitArt();
      await k.hold(1.4);
    },
  },
  {
    id: "f-sources",
    what: "ソースを VocaDB にするとボカロの原曲、otoDB にすると音MAD が見つかる（otoDB は消えた動画のサムネも出る）",
    async setup(k) {
      const sq = square(), wide = nico();
      const MAD = ["", "の歌", " 2nd", "メドレー", "リミックス", "ループ"];
      await k.mock({ search: (p) => p.source === "vocadb"
        ? variants(p.q, sq.slice(6), 5, "vocadb").map((t, i) => ({ ...t, artist: `${sq[6 + i].artist} feat. 初音ミク` }))
        : as("otodb", wide.slice(0, 6)).map((t, i) => ({ ...t, title: `【音MAD】${p.q}${MAD[i]}` })) });
      await empty(k);
      await k.arrange(ARRANGE_FLOW); await k.stage(onlySubs());
      await k.look([ST, "#search-form"]);
      await k.park(700, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press('#sources label:has(input[value="vocadb"])');
      await retype(k, "#q", "はんぶんこの月");
      await k.press("#search-btn");
      await resultsAtLeast(k, 3);
      await k.look([ST, RT, "#search-form", "#results"], 0.6);
      await k.hold(1.6);
      await k.look([ST, "#search-form"], 0.6);
      await k.press('#sources label:has(input[value="otodb"])');
      await retype(k, "#q", "迷子の自販機");
      await k.press("#search-btn");
      await k.until(() => k.page.evaluate(() => document.querySelector("#results .badge")?.dataset.source === "otodb"), "otoDB の候補", 15000);
      await k.look([ST, RT, "#search-form", "#results"], 0.6);
      await k.hold(1.8);
      await k.look([ST, "#search-form"], 0.6);
      await k.press('#sources label:has(input[value="itunes"])');   // 始めと同じ iTunes に戻して終わる
      await k.hold(0.6);
    },
  },
  {
    id: "f-url",
    what: "動画やストアのページの URL を貼ると 1 曲取れる。ニコニコなら sm… の ID だけでもいい",
    async setup(k) {
      const wide = nico();
      let n = 0;
      await k.mock({ url: () => ({ ...wide[(n++ * 3 + 1) % wide.length], source: "nicovideo", external_url: "https://www.nicovideo.jp/watch/sm45000000" }) });
      await empty(k, [3, 3], { cellRatio: "16:9" });
      await k.arrange(ARRANGE_FLOW); await k.stage(subOnly("#sub-bandcamp"));
      await openSub(k, "#sub-bandcamp");
      await k.look([ST, "#sub-bandcamp"]);
      await k.park(700, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.glide("#bc-url", 0.4);
      await k.type("#bc-url", "https://www.nicovideo.jp/watch/sm45012345", 0.035);
      await k.press("#bc-btn");
      await resultsAtLeast(k, 1);
      await k.look([ST, RT, "#sub-bandcamp", "#results"], 0.6);
      await k.hold(1.0);
      await k.look([ST, "#sub-bandcamp"], 0.5);
      await k.glide("#bc-url", 0.4);
      await k.type("#bc-url", "sm45067890", 0.07);
      await k.press("#bc-btn");
      await resultsAtLeast(k, 2);
      await k.look([ST, RT, GT, "#sub-bandcamp", "#results", "#grid"], 0.6);
      await k.hold(0.8);
      await k.press("#results li:nth-child(2) .result");
      await k.hold(0.4);
      await k.press("#results li:nth-child(1) .result");
      await k.waitArt();
      await k.hold(1.4);
    },
  },
  {
    id: "f-multi-url",
    what: "違うサイトの URL を 1 行に 1 つずつ貼れば、まとめて取れる（YouTube・SoundCloud・Bandcamp を混ぜても）",
    async setup(k) {
      const sq = square(), wide = nico();
      await k.mock({ url: (u) => u.includes("youtube") ? { ...wide[4], source: "youtube" }
        : u.includes("soundcloud") ? { ...sq[11], source: "soundcloud" } : { ...sq[14], source: "bandcamp" } });
      await empty(k);
      await k.arrange(ARRANGE_FLOW); await k.stage(subOnly("#sub-bandcamp"));
      await openSub(k, "#sub-bandcamp");
      await k.look([ST, "#sub-bandcamp"]);
      await k.park(700, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.glide("#bc-url", 0.4);
      // **1 回で打つ**。k.type は欄を押してから打つので、分けると押した所（2 行目の頭など）にカーソルが移って行が混ざる
      await k.type("#bc-url", "https://www.youtube.com/watch?v=AbCdEfGhIjK\nhttps://soundcloud.com/tsubame/night-walk\nhttps://violet.bandcamp.com/track/violet-hour", 0.03);
      await k.hold(0.3);
      await k.press("#bc-btn");
      await resultsAtLeast(k, 3);
      await k.look([ST, RT, "#sub-bandcamp", "#results"], 0.6);
      await k.hold(2.2);
    },
  },
  {
    id: "f-playlist",
    what: "マイリストや再生リストの URL を 1 本貼るだけで、まとめて取れる（最大 500 曲）。「マスに入れる」で順に埋まる",
    async setup(k) {
      const wide = nico();
      await k.mock({ playlist: () => [...wide, ...wide.slice(0, 3)].map((t, i) => ({ ...t, source: "nicovideo", external_url: `https://www.nicovideo.jp/watch/sm4500${1000 + i}` })) });
      await empty(k, [3, 3], { cellRatio: "16:9", title: "好きな音MAD" });
      await k.arrange(ARRANGE_FLOW); await k.stage(subOnly("#sub-bandcamp"));
      await openSub(k, "#sub-bandcamp");
      await k.look([ST, "#sub-bandcamp"]);
      await k.park(700, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.glide("#bc-url", 0.4);
      await k.type("#bc-url", "https://www.nicovideo.jp/mylist/73019452", 0.035);
      await k.press("#bc-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pl-modal").hidden), "まとめて取れた窓", 15000);
      await k.hold(0.2);
      await k.look(["#pl-modal .sheet-head", "#pl-to-grid", "#pl-summary"], 0.6);
      await k.hold(1.2);
      await k.press("#pl-to-grid");
      await k.waitArt();
      await k.look([ST, RT, GT, "#grid", "#results"], 0.7);
      await k.hold(2.4);
    },
  },
  {
    id: "f-playlist-pick",
    what: "まとめて取った曲を「候補に置いて選ぶ」と、候補に並べて好きなものだけ入れられる",
    async setup(k) {
      const wide = nico();
      await k.mock({ playlist: () => wide.map((t, i) => ({ ...t, source: "youtube", external_url: `https://www.youtube.com/watch?v=x${i}` })) });
      await empty(k, [3, 3], { cellRatio: "16:9", title: "好きな音MAD" });
      await k.arrange(ARRANGE_FLOW); await k.stage(subOnly("#sub-bandcamp"));
      await openSub(k, "#sub-bandcamp");
      await k.look([ST, "#sub-bandcamp"]);
      await k.park(700, 500);
    },
    async run(k) {
      await k.hold(0.8);
      await k.glide("#bc-url", 0.4);
      await k.type("#bc-url", "https://www.youtube.com/playlist?list=PLx7fAkEpLaYl1sT", 0.035);
      await k.press("#bc-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#pl-modal").hidden), "まとめて取れた窓", 15000);
      await k.hold(0.2);
      await k.look(["#pl-modal .sheet-head", "#pl-to-grid", "#pl-summary"], 0.6);
      await k.hold(1.0);
      await k.press("#pl-to-results");
      await resultsAtLeast(k, 6);
      await k.look([RT, GT, "#results", "#grid"], 0.7);
      for (const n of [3, 1, 5]) { await k.press(`#results li:nth-child(${n}) .result`); await k.hold(0.35); }
      await k.waitArt();
      await k.hold(1.4);
    },
  },
  {
    id: "f-list",
    what: "アーティスト名とトラック名の表を打って「一覧から入れる」。1 行ずつ探して、ぴったり合えばマスへ",
    async setup(k) {
      const sq = square();
      await k.mock({ itunes: (term) => sq.filter((t) => term.includes(t.title) && term.includes(t.artist)).map((t) => ({ ...t, source: "itunes" })) });
      await empty(k);
      await k.arrange(ARRANGE_LIST); await k.stage(subOnly("#sub-list"));
      await openSub(k, "#sub-list");
      await k.look([ST, "#sub-list"]);
      await k.park(700, 560);
    },
    async run(k) {
      const sq = square();
      await k.hold(0.8);
      for (const [i, t] of [sq[3], sq[7], sq[13]].entries()) {
        const cell = (key) => `#list-rows input[data-row="${i}"][data-key="${key}"]`;
        await k.glide(cell("artist"), 0.3);
        await k.type(cell("artist"), t.artist, 0.05);
        await k.page.focus(cell("title"));
        await k.type(cell("title"), t.title, 0.05);
      }
      await k.hold(0.3);
      await k.press("#list-btn");
      await k.look([ST, GT, "#sub-list", "#grid"], 0.7);
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#grid img").length >= 3), "一覧から入る", 20000);
      await k.waitArt();
      await k.hold(2.0);
    },
  },
  {
    id: "f-copy-paste",
    what: "「トラック名をコピー」で番号付きの一覧に。表に貼ると行と列に分かれて戻る（Excel の表も同じように貼れる）",
    async setup(k) {
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await k.arrange(ARRANGE_COPY); await k.stage(subOnly("#sub-list"));
      await openSub(k, "#sub-list");
      await k.look([GT, "#grid", "#output"]);
      await k.park(900, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#text-copy");
      await k.hold(1.0);
      await k.look([ST, "#sub-list", GT, "#grid"], 0.7);
      await k.glide('#list-rows input[data-row="0"][data-key="artist"]', 0.5);
      await k.page.click('#list-rows input[data-row="0"][data-key="artist"]');
      await k.hold(0.2);
      await k.key("Control+v");
      await k.until(() => k.page.evaluate(() => document.querySelectorAll("#list-rows .list-row").length >= 9), "貼り付け", 5000);
      await k.look([ST, "#sub-list"], 0.6);
      await k.hold(2.4);
    },
  },
  {
    id: "f-manual",
    what: "手元の画像でも入れられる。「端末から画像を選択…」で選び、トラック名とアーティスト名を入れて追加（撮影日時などは消して保存）",
    async setup(k) {
      const sq = square();
      // 端末から上げた画像は、本番の R2 に置かずに手元の架空の絵で返す
      await k.page.route(/\/upload$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ url: sq[21].image }) }));
      await empty(k, [3, 3], {}, sq.slice(0, 4));
      await k.arrange(ARRANGE_FLOW); await k.stage(subOnly("#sub-manual"));
      await openSub(k, "#sub-manual");
      await k.look([ST, "#sub-manual"]);
      await k.park(700, 560);
    },
    async run(k) {
      await k.hold(0.8);
      const fc = k.page.waitForEvent("filechooser");
      await k.press("#m-file-btn");
      await (await fc).setFiles({ name: "ねこじゃらし.jpg", mimeType: "image/jpeg", buffer: fs.readFileSync("uploads/" + square()[21].image.split("/").pop()) });
      await k.until(() => k.page.evaluate(() => !!document.querySelector("#m-image").value), "画像の取り込み", 10000);
      await k.hold(0.8);
      await k.glide("#m-artist", 0.4);
      await k.type("#m-artist", "まるいち", 0.07);
      await k.hold(0.3);
      await k.press("#m-btn");
      await resultsAtLeast(k, 1);
      await k.look([ST, RT, GT, "#sub-manual", "#results", "#grid"], 0.7);
      await k.hold(0.6);
      await k.press("#results li:nth-child(1) .result");   // 手入力の曲も候補の先頭に入る。押すとマスへ
      await k.waitArt();
      await k.hold(1.8);
    },
  },
  {
    id: "f-share",
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
      await k.arrange(ARRANGE_SHARE); await k.stage(SHARE_CSS);
      await k.look([GT, "#grid", "#output"]);
      await k.park(900, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#share-btn");
      await k.until(() => k.page.evaluate(() => !document.querySelector("#up-modal").hidden), "送信中の窓", 10000).catch(() => {});
      await k.live(() => k.page.evaluate(() => !document.querySelector("#share-done").hidden && document.querySelector("#up-modal").hidden), { min: 0.8, timeout: 90 });
      await k.hold(0.6);
      await k.look(["#output"], 0.6);
      await k.hold(1.4);
      // 新しいタブではなく同じ画面で、手元のサーバーの共有ページを開く（本番の URL に行かない）
      await k.page.evaluate(() => { const a = document.querySelector("#open-share"); a.removeAttribute("target"); a.href = new URL(a.href).pathname; });
      await k.press("#open-share");
      await k.page.waitForURL(/\/s\/[0-9a-f]{12}/, { timeout: 20000 });
      await k.until(() => k.page.evaluate(() => [...document.images].every((i) => i.complete)), "共有ページ", 20000);
      k.wide(0);
      await k.hold(2.6);
    },
  },
  {
    id: "f-find",
    what: "「みんなのグリッドに載せる」にチェックして共有すると、トラック名やアーティスト名で探せるようになる。自分の並びは × で外せる",
    async setup(k) {
      // **本番には何も置かない**: 共有の返事も探すページも差し替える（載せると本番の探すページに出てしまうため）
      const own = { id: "fa4e0ab1c2d3", title: "私を構成する9曲" };
      await k.page.route(/\/share\/upload$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        id: own.id, url: `https://trackmento.com/s/${own.id}`, image: "/uploads/fa4e010000000000.jpg", png: "/uploads/fa4e010000000000.jpg",
        ext: "jpg", width: 2400, height: 1350, ownerKey: "clip-owner-key-0000", listed: true }) }));
      await k.page.route(/\/find(\?.*)?$/, (route) => {
        const q = new URL(route.request().url()).searchParams.get("q") || "";
        route.fulfill({ status: 200, contentType: "text/html; charset=utf-8", body: fakeFind(q, own) });
      });
      // 「× で外す」の返事も差し替える（架空の共有なので本物のサーバーには無い）
      await k.page.route(/\/s\/fa4e[0-9a-f]+\/unlist$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: own.id, action: "unlist" }) }));
      await ready(k, 9, [3, 3], {}, square().slice(0, 9));
      await k.arrange(ARRANGE_SHARE); await k.stage(FIND_CSS);
      await k.look([GT, "#grid", "#output"]);
      await k.park(900, 600);
    },
    async run(k) {
      await k.hold(0.8);
      await k.press("#opt-listed");
      await k.hold(0.5);
      await k.press("#share-btn");
      await k.live(() => k.page.evaluate(() => !document.querySelector("#share-done").hidden && document.querySelector("#up-modal").hidden), { min: 0.8, timeout: 90 });
      await k.hold(0.8);
      // 「みんなのグリッド」の文字から探すページへ（新しいタブではなく同じ画面で）
      await k.page.evaluate(() => document.querySelector("#find-link").removeAttribute("target"));
      await k.press("#find-link");
      await k.page.waitForURL(/\/find/, { timeout: 20000 });
      await k.hold(0.2);
      await k.look(["main h1", "form.find", "main section"], 0);
      await k.hold(1.4);
      await k.type('form.find input[name="q"]', "シグナル", 0.09);
      await k.hold(0.3);
      await k.key("Enter");
      await k.page.waitForURL(/\/find\?q=/, { timeout: 20000 });
      await k.hold(0.2);
      await k.look(["main h1", "form.find", "main ol"], 0);
      await k.hold(1.4);
      await k.press(".own-rm");
      await k.until(() => k.page.evaluate(() => !!document.querySelector(".odlg")), "確認の窓", 5000);
      await k.look([".odlg-panel"], 0.5);
      await k.hold(1.0);
      await k.press('.odlg-btns .btn:not(.odlg-default)');   // 「外す」（既定は「やめる」）
      await k.look(["main h1", "form.find", "main ol"], 0.5);
      await k.hold(1.8);
    },
  },
];
