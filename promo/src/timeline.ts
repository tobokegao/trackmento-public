// 拍・小節の割り付けと、録画（events.json）との対応。
// 9:16（tall）と 16:9（wide）、日本語と英語で同じ拍割りを使う。
//
// 曲は Sherbet（**BPM 130.00 ちょうど** / 1 小節 1.846 秒 / 1 小節目の頭 = 0.52 秒 = 頭の無音のあとの最初の音）。全 77 小節だが、使うのは 47 小節（≒ 87 秒）。
// 拍は beats.json の固定の格子（2026-09-17 に全曲の櫛で測り直した。librosa の拍は 40〜100ms 遅れていた）。
// 録画は本編（9 マスを埋めて共有まで）と feat（新機能だけ）の 2 本立て。
// ① で 500 曲入れると並びが壊れるので、同じセッションでは撮れないため。
//
// v3（2026-09-17）。曲のキメと小節の対応は video-notes.md の「v3 の構成」。
// **28–42 小節目は v2 から動かさない**（A メロの頭・2 周目・キメ・サビ 2 の頭に合っていた）。
import beatsJson from "./beats.json";
import evTallJaMain from "../public/recordings/events.json";
import evTallJaFeat from "../public/recordings-feat/events.json";
import evTallEnMain from "../public/recordings-en/events.json";
import evTallEnFeat from "../public/recordings-feat-en/events.json";
import evWideJaMain from "../public/recordings-pc/events.json";
import evWideJaFeat from "../public/recordings-pc-feat/events.json";
import evWideEnMain from "../public/recordings-pc-en/events.json";
import evWideEnFeat from "../public/recordings-pc-feat-en/events.json";

export const FPS = 30;
export const BAR = 4;                                   // 4/4 拍子
const BEATS: number[] = beatsJson.beats;                // 拍（秒）。BPM 130 の固定の格子

export const beatTime = (i: number) => {
  if (i < BEATS.length) return BEATS[i];
  const step = BEATS[BEATS.length - 1] - BEATS[BEATS.length - 2];
  return BEATS[BEATS.length - 1] + step * (i - BEATS.length + 1);
};
export const beatFrame = (i: number) => Math.round(beatTime(i) * FPS);
export const sec = (s: number) => Math.round(s * FPS);
/** 小節番号（1 始まり）→ 拍番号（0 始まり） */
export const bar = (n: number) => (n - 1) * BAR;

// ---- 録画の操作時刻 ----
type Ev = { t: number; v?: number; name: string };
export type Kind = "tall" | "wide";        // 縦（スマホ表示）と横（PC 表示）
export type Lang = "ja" | "en";
export type Session = "main" | "feat";     // 本編と新機能

type Rec = { src: string; events: Ev[]; final: string };
const rec = (dir: string, events: unknown, final: string): Rec =>
  ({ src: `${dir}/session.mp4`, events: events as Ev[], final });

export const RECORDINGS: Record<Kind, Record<Lang, Record<Session, Rec>>> = {
  tall: {
    ja: { main: rec("recordings", evTallJaMain, "final.png"), feat: rec("recordings-feat", evTallJaFeat, "final.png") },
    en: { main: rec("recordings-en", evTallEnMain, "final.png"), feat: rec("recordings-feat-en", evTallEnFeat, "final.png") },
  },
  wide: {
    ja: { main: rec("recordings-pc", evWideJaMain, "final-pc.png"), feat: rec("recordings-pc-feat", evWideJaFeat, "final-pc.png") },
    en: { main: rec("recordings-pc-en", evWideEnMain, "final-pc.png"), feat: rec("recordings-pc-feat-en", evWideEnFeat, "final-pc.png") },
  },
};

/** Playwright の動画は実時間より遅い（フレーム落ち分が引き延ばされる）。最後の操作の v/t で率を出し、再生速度で戻す */
export const rate = (kind: Kind, lang: Lang, session: Session) => {
  const ev = RECORDINGS[kind][lang][session].events;
  const first = ev[0], last = [...ev].reverse().find((e) => e.v !== undefined && e.t > 10);
  return last ? (last.v! - (first.v ?? 0)) / (last.t - first.t) : 1;
};
export const evTime = (kind: Kind, lang: Lang, session: Session, name: string) => {
  const e = RECORDINGS[kind][lang][session].events.find((x) => x.name === name);
  if (!e) throw new Error(`${kind}/${lang}/${session} の events.json に ${name} がない`);
  return e.v ?? e.t;   // v = 動画内の時刻（scan_markers.py がマーカーから付ける）。無ければ実時間
};

// ---- 構成（拍番号は 0 始まり。小節 n の頭 = bar(n)） ----
// 1–3   イントロ
// 4–5   ⑥ さらに軽くなりました（録画なし）
// 6–14  **新しくなったところ**: みんなのグリッド 2 / パレット 2 / 曲名リスト 2（静止画）/ ローマ字 / VocaDB / 大きく見る
// 15–17 トップ画面の説明（3 小節）
// 18–27 入れ方（v2 のまま）/ 28–32 並べる〜ほぼ完成 / 33–38 出力と共有（37 = 送信の進み具合）
// 39–40 タイムラプス / 41–42 できあがり（キメで 4 枚を切り替え）/ 43 全部外す → 元に戻す / 44–46 エンドカード
export const INTRO_END = bar(4);            // イントロは 3 小節
export const BANDWIDTH_BEAT = bar(4);       // ⑥「さらに軽くなりました」（録画なしのシーン、2 小節）
export const FLOW_BEAT = bar(6);            // 録画のショットはここから
export const TIMELAPSE_BEAT = bar(39);
export const SHOWCASE_BEAT = bar(41);       // できあがり（2 小節、キメに乗せる）
export const CODA_BEAT = bar(43);           // 全部外す → 元に戻す（1 小節、サビ 2 の頭）
export const END_BEAT = bar(44);            // エンドカード（ロゴ 1 小節 → URL 1 小節 → 無料 1 小節）
export const URL_BEAT = bar(45);
export const FREE_BEAT = bar(46);
export const LAST_BEAT = bar(47);
export const FADE_FROM = END_BEAT;          // 音楽のフェードアウト開始
export const DURATION_FRAMES = beatFrame(LAST_BEAT) + 12;

/** 録画を見せるショット。ev = 操作名、off = その何秒前/後から、speed = 早回し倍率、zoom = 画面のどこを拡大するか（0〜1） */
export type Shot = {
  beat: number; len: number; ev: string; off: number; speed?: number; jp: string; en: string;
  rec?: Session;                                                                                  // 既定は本編（main）。新機能は feat
  zoom?: { x: number; y: number; s: number }; zoomPc?: { x: number; y: number; s: number };   // zoom = スマホ録画、zoomPc = PC 録画
  hl?: { x: number; y: number; w: number; h: number };                                           // スマホ録画で枠線で強調する範囲（割合）
  still?: boolean;                                                                                // 録画を最初のコマで止める（裏で操作が進まないように）
  ab?: string;                                                                                    // 前半にこの画（v1 の見た目）を出して見くらべる。public/ のファイル名
  fx?: "glitchOut" | "flashIn";                                                                   // glitchOut: 末尾 1 小節のジャンプ演出、flashIn: 冒頭 1 拍の反転
  stills?: string[];                                                                              // 録画ではなく静止画（public/stills/<名前>.png、横は -pc）を順に出す
  stillBeats?: number[];                                                                          // stills を切り替える拍（ショットの頭からの拍数）
  labels?: { jp: string; en: string }[];                                                          // stills ごとの添え書き
};

export const SHOTS: Shot[] = [
  // ---- 6〜14 小節目: 新しくなったところ ----
  { beat: bar(6), len: 4, ev: "listed:check", off: -0.8, rec: "feat", speed: 1.4, jp: "「みんなのグリッド」に載せて共有", en: "List it on Everyone's grids", zoom: { x: 0.2, y: 0.6, s: 1.3 }, zoomPc: { x: 0.6, y: 0.9, s: 1.5 } },
  { beat: bar(7), len: 4, ev: "find:page", off: -0.2, rec: "feat", speed: 1.1, jp: "曲名で、みんなの並びを探せる", en: "Search everyone's grids by track" },
  { beat: bar(8), len: 4, ev: "pal:pop", off: -0.5, rec: "feat", speed: 1.2, jp: "パレットで配色ごと切り替え", en: "Palettes swap the whole colour scheme" },
  { beat: bar(9), len: 4, ev: "pal:copy", off: -0.3, rec: "feat", speed: 1.5, jp: "自作の組はコピーして渡せる", en: "Copy your own palette to share it" },
  { beat: bar(10), len: 8, ev: "start", off: 0, rec: "feat", jp: "曲名リストが賢くなりました", en: "Smarter track lists",
    stills: ["smart-a", "smart-b", "smart-c"], stillBeats: [0, 2, 4],
    labels: [{ jp: "曲が多いと回り込み", en: "Wraps around when there are many" }, { jp: "細長い並びは柱に", en: "Tall grids get a column" }, { jp: "少なければ大きく", en: "Few tracks? Bigger text" }] },
  { beat: bar(12), len: 4, ev: "romaji:search", off: -0.6, rec: "feat", speed: 1.4, jp: "英語の画面なら曲名もローマ字に", en: "In English, titles come romanized", zoomPc: { x: 0, y: 0.4, s: 1.6 } },
  { beat: bar(13), len: 4, ev: "vocadb:search", off: -1.4, rec: "feat", speed: 1.6, jp: "VocaDB でサブスクに無い曲も", en: "VocaDB finds what streaming doesn't", zoomPc: { x: 0, y: 0.4, s: 1.6 } },
  { beat: bar(14), len: 4, ev: "zoom:open", off: -0.3, rec: "feat", speed: 1.2, jp: "「大きく見る」で 256 マスも並べ替え", en: "Zoom in to sort 256 cells" },

  // ---- 15〜17 小節目: トップ画面の説明（3 小節） ----
  { beat: bar(15), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "トップ画面はこれだけ", en: "This is the whole app" },
  { beat: bar(16), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "上にタイトル、真ん中にマス", en: "Title on top, the grid in the middle", hl: { x: 0.056, y: 0.138, w: 0.889, h: 0.542 }, zoomPc: { x: 0.6, y: 0.35, s: 1.35 } },
  { beat: bar(17), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "下に共有と検索、出力の設定", en: "Share, search and settings below", hl: { x: 0.056, y: 0.734, w: 0.889, h: 0.154 }, zoomPc: { x: 0.6, y: 0.85, s: 1.5 } },

  // ---- 18〜27 小節目: 入れ方（v2 のまま） ----
  { beat: bar(18), len: 4, ev: "title-focus", off: -0.2, jp: "まずはタイトル", en: "Start with a title" },
  { beat: bar(19), len: 4, ev: "cell-tap", off: -0.5, jp: "枠をタップ", en: "Tap a cell", zoomPc: { x: 0.52, y: 0.36, s: 1.8 } },
  { beat: bar(20), len: 4, ev: "src:musicbrainz", off: -0.4, jp: "検索ソースは 4 種類", en: "Four search sources", zoomPc: { x: 0, y: 0.43, s: 1.9 } },
  { beat: bar(21), len: 4, ev: "search:chikamichi", off: -1.6, speed: 2, jp: "曲を探す", en: "Find tracks", zoomPc: { x: 0, y: 0.3, s: 1.7 } },
  { beat: bar(22), len: 4, ev: "url:talk", off: -1.6, speed: 1.4, jp: "URL 検索も対応", en: "Or paste a URL", zoomPc: { x: 0, y: 0.74, s: 1.7 } },
  { beat: bar(23), len: 4, ev: "multi:got", off: -1.8, rec: "feat", speed: 1.6, jp: "改行で区切って丸ごと挿入", en: "One per line, all at once" },
  { beat: bar(24), len: 4, ev: "pl:paste", off: -1.8, rec: "feat", speed: 1.6, jp: "Playlist の URL で一気に追加", en: "A whole playlist in one paste" },
  { beat: bar(25), len: 4, ev: "pl:fill", off: -1.2, rec: "feat", jp: "最大 500 曲がまとめて入る", en: "Up to 500 tracks at once" },
  { beat: bar(26), len: 4, ev: "revive:paste", off: -1.6, rec: "feat", speed: 1.5, jp: "消えた動画も", en: "Even deleted videos" },
  { beat: bar(27), len: 4, ev: "revive:done", off: -0.6, rec: "feat", jp: "otoDB からよみがえる", en: "come back from otoDB" },
  // ---- 28〜32 小節目: 埋めて並べる（動かさない） ----
  { beat: bar(28), len: 4, ev: "manual:mitsuami", off: -0.6, speed: 1.2, jp: "手入力も可能", en: "Or add your own", zoomPc: { x: 0, y: 1, s: 1.7 } },
  { beat: bar(29), len: 4, ev: "add:ilovelove", off: -0.4, jp: "枠が全部埋まったら", en: "Once every cell is full", zoomPc: { x: 0.6, y: 0.45, s: 1.5 } },
  { beat: bar(30), len: 4, ev: "select:1", off: -0.2, speed: 1.2, jp: "タップで入れ替え", en: "Tap two cells to swap", zoomPc: { x: 0.6, y: 0.45, s: 1.6 } },
  { beat: bar(31), len: 4, ev: "reorder-done", off: -0.3, jp: "並べ終わったら", en: "Once you're done", zoomPc: { x: 0.6, y: 0.45, s: 1.4 } },
  { beat: bar(32), len: 4, ev: "reorder-done", off: 0.6, still: true, jp: "ほぼ完成です", en: "Almost there", zoom: { x: 0.5, y: 0.45, s: 1.35 }, zoomPc: { x: 0.6, y: 0.45, s: 1.35 } },
  // ---- 33〜38 小節目: 出力と共有 ----
  { beat: bar(33), len: 4, ev: "open-options", off: -0.3, fx: "flashIn", jp: "出力方法を設定", en: "Choose how it comes out", zoomPc: { x: 1, y: 0.42, s: 1.5 } },
  { beat: bar(34), len: 4, ev: "ratio:16:9", off: -0.3, speed: 1.1, jp: "解像度は 5 種類", en: "Five aspect ratios", zoomPc: { x: 1, y: 0.3, s: 1.9 } },
  { beat: bar(35), len: 4, ev: "bg:cerulean", off: -0.3, jp: "背景色は 8 色", en: "Eight background colours", zoomPc: { x: 1, y: 0.62, s: 1.9 } },
  { beat: bar(36), len: 4, ev: "bg:custom", off: -0.4, jp: "カスタム色はつまみで", en: "Or dial in any colour", zoomPc: { x: 1, y: 0.67, s: 2.0 } },
  { beat: bar(37), len: 4, ev: "share", off: -0.2, jp: "共有すると、送信の進み具合が見える", en: "Share — with an upload progress bar", zoomPc: { x: 0.55, y: 0.7, s: 1.6 } },
  { beat: bar(38), len: 4, ev: "share-ready", off: -0.2, jp: "画像と共有 URL", en: "An image and a link", zoomPc: { x: 0.6, y: 0.5, s: 1.3 } },
];

/** 43 小節目: 全部外す → 元に戻す（できあがりのあと、エンドカードの前） */
export const CODA: Shot = { beat: CODA_BEAT, len: 4, ev: "clear:tap", off: -0.4, rec: "feat", speed: 1.3, jp: "作り直すときは「マスを全部外す」。間違えても元に戻せる", en: "Clear all to start over — and undo if you slip" };

/** できあがり（41–42 小節目）: 4 枚の出力を曲のキメで切り替える。切り替えの拍はショットの頭からの拍数
    （41 の頭 / 41 の 8 分音符 8 拍目 = 3.5 拍 / 42 の 2 拍目 = 4.5 / 42 の 4 拍目 = 5.5。6 拍目からは最後の 1 枚を伸ばす） */
export const SHOWCASE_STILLS = ["show-1", "show-2", "show-3", "show-4"];
export const SHOWCASE_SWITCH = [0, 3.5, 4.5, 5.5];

/** URL 検索の対応サイト（8 分音符 3 連で 1 つずつ出す） */
export const SITES = ["YouTube", "ニコニコ", "Bandcamp", "SoundCloud", "Spotify", "bilibili", "Apple Music"];
export const SITES_EN = ["YouTube", "Niconico", "Bandcamp", "SoundCloud", "Spotify", "bilibili", "Apple Music"];

/** ⑥「さらに軽くなりました」で出す数字（録画ではなく作った画で見せる。v3 は 2026-09-16 の対策の数字） */
export const BANDWIDTH_ROWS: { jp: string; en: string; from: string; to: string }[] = [
  { jp: "1 アクセスあたりの転送量", en: "Data per request", from: "90KB", to: "27KB" },
  { jp: "画面本体", en: "The page itself", from: "273KB", to: "82KB" },
  { jp: "共有画像", en: "Shared image", from: "501KB", to: "413KB" },
  { jp: "出来上がりの落とし直し", en: "Re-downloading the result", from: "毎回", to: "ゼロ" },
];

/** タイムラプス: 録画の始まりから PNG 完成までを 16 分割して 1 小節に詰める */
export const TIMELAPSE_STEPS = 16;
export const timelapseTimes = (kind: Kind, lang: Lang) => {
  const a = evTime(kind, lang, "main", "start"), b = evTime(kind, lang, "main", "share-ready");
  return Array.from({ length: TIMELAPSE_STEPS }, (_, i) => a + ((b - a) * i) / (TIMELAPSE_STEPS - 1));
};
