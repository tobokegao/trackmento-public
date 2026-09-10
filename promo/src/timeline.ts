// 拍・小節の割り付けと、録画（events.json）との対応。Promo（9:16）と Wide（16:9）で共有する
import beatsJson from "./beats.json";
import eventsPhone from "../public/recordings/events.json";
import eventsPc from "../public/recordings-pc/events.json";

export const FPS = 30;
export const BAR = 4;                                   // 4/4 拍子
const BEATS: number[] = beatsJson.beats;                // librosa の拍（秒）

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
export type Kind = "tall" | "wide";
/** 縦（tall）はスマホ表示の録画、横（wide）は PC 表示の録画 */
export const RECORDINGS: Record<Kind, { src: string; events: Ev[]; final: string }> = {
  tall: { src: "recordings/session.mp4", events: eventsPhone as never, final: "final.png" },
  wide: { src: "recordings-pc/session.mp4", events: eventsPc as never, final: "final-pc.png" },
};
/** Playwright の動画は実時間より遅い（フレーム落ち分が引き延ばされる）。最後の操作の v/t で率を出し、再生速度で戻す */
export const rate = (kind: Kind) => {
  const ev = RECORDINGS[kind].events;
  const first = ev[0], last = [...ev].reverse().find((e) => e.v !== undefined && e.t > 10);
  return last ? (last.v! - (first.v ?? 0)) / (last.t - first.t) : 1;
};
export const evTime = (kind: Kind, name: string) => {
  const e = RECORDINGS[kind].events.find((x) => x.name === name);
  if (!e) throw new Error(`${kind} の events.json に ${name} がない`);
  return e.v ?? e.t;   // v = 動画内の時刻（scan_markers.py がマーカーから付ける）。無ければ実時間
};

// ---- 構成（拍番号は 0 始まり。小節 n の頭 = bar(n)） ----
export const INTRO_END = bar(3);            // イントロは 2 小節
export const COUNTDOWN_BEAT = bar(8);       // 3, 2, 1, GO（8 小節目）
export const FLOW_BEAT = bar(9);            // 操作の流れはここから
export const TIMELAPSE_BEAT = bar(24);
export const SHOWCASE_BEAT = bar(25);       // できあがり（2 小節）
export const END_BEAT = bar(27);            // エンドカード（あなたの 9 曲は？ 1 小節 → URL 1 小節 → 無料 2 小節）
export const URL_BEAT = bar(28);
export const FREE_BEAT = bar(29);
export const LAST_BEAT = bar(31);
export const FADE_FROM = END_BEAT;          // 音楽のフェードアウト開始
export const DURATION_FRAMES = beatFrame(LAST_BEAT) + 12;

/** 録画を見せるショット。ev = 操作名、off = その何秒前/後から、speed = 早回し倍率、zoom = 画面のどこを拡大するか（0〜1） */
export type Shot = {
  beat: number; len: number; ev: string; off: number; speed?: number; jp: string; en: string;
  zoom?: { x: number; y: number; s: number }; zoomPc?: { x: number; y: number; s: number };   // zoom = スマホ録画、zoomPc = PC 録画
  hl?: { x: number; y: number; w: number; h: number };                                           // スマホ録画で枠線で強調する範囲（割合）
  still?: boolean;                                                                                // 録画を最初のコマで止める（裏で操作が進まないように）
  fx?: "glitchOut" | "flashIn";                                                                   // glitchOut: 末尾 1 小節のジャンプ演出、flashIn: 冒頭 1 拍の反転
};

export const SHOTS: Shot[] = [
  // 3〜7 小節目: トップ画面の説明（5 小節）
  { beat: bar(3), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "トップ画面はこれだけ", en: "This is the whole app" },
  { beat: bar(4), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "上にタイトル", en: "Title on top", hl: { x: 0.027, y: 0.116, w: 0.946, h: 0.065 }, zoomPc: { x: 0.6, y: 0.2, s: 1.5 } },
  { beat: bar(5), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "真ん中に 3×3 のマス", en: "Nine cells in the middle", hl: { x: 0.031, y: 0.179, w: 0.938, h: 0.528 }, zoomPc: { x: 0.6, y: 0.45, s: 1.3 } },
  { beat: bar(6), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "下に共有と検索のボタン", en: "Share and search below", hl: { x: 0.027, y: 0.747, w: 0.946, h: 0.12 }, zoomPc: { x: 0.6, y: 0.85, s: 1.5 } },
  { beat: bar(7), len: 4, ev: "title-focus", off: -0.2, jp: "まずはタイトルを入力", en: "Start with a title" },
  // 8 小節目: カウントダウン（映像はタイトル入力後のまま）
  { beat: bar(8), len: 4, ev: "title-done", off: 0.0, still: true, jp: "", en: "" },
  // 9〜12 小節目: 曲の追加方法
  { beat: bar(9), len: 4, ev: "cell-tap", off: -0.5, jp: "枠をタップ", en: "Tap a cell", zoomPc: { x: 0.52, y: 0.36, s: 1.8 } },
  { beat: bar(10), len: 4, ev: "search:chikamichi", off: -1.6, speed: 2, jp: "曲を探す", en: "Find tracks", zoomPc: { x: 0, y: 0.3, s: 1.7 } },
  { beat: bar(11), len: 4, ev: "src:musicbrainz", off: -0.4, jp: "検索ソースは3種類", en: "Three search sources", zoom: { x: 0.3, y: 0.6, s: 1.3 }, zoomPc: { x: 0, y: 0.43, s: 1.9 } },
  { beat: bar(12), len: 4, ev: "url:talk", off: -1.6, speed: 1.4, jp: "URL検索も対応", en: "Or paste a URL", zoomPc: { x: 0, y: 0.74, s: 1.7 } },
  { beat: bar(13), len: 2, ev: "manual:mitsuami", off: -0.6, speed: 1.2, jp: "手入力も可能", en: "Or add your own", zoomPc: { x: 0, y: 1, s: 1.7 } },
  // 13〜16 小節目
  { beat: bar(13) + 2, len: 2, ev: "add:ilovelove", off: -0.4, jp: "枠が全部埋まったら", en: "All nine in", zoomPc: { x: 0.6, y: 0.45, s: 1.5 } },
  { beat: bar(14), len: 4, ev: "select:1", off: -0.2, speed: 1.2, jp: "タップで入れ替え", en: "Tap two cells to swap", zoomPc: { x: 0.6, y: 0.45, s: 1.6 } },
  { beat: bar(15), len: 4, ev: "reorder-done", off: -0.3, jp: "並べ終わったら", en: "Once you're done", zoomPc: { x: 0.6, y: 0.45, s: 1.4 } },
  { beat: bar(16), len: 4, ev: "reorder-done", off: 0.6, still: true, fx: "glitchOut", jp: "ほぼ完成です", en: "Almost there", zoom: { x: 0.5, y: 0.45, s: 1.3 }, zoomPc: { x: 0.6, y: 0.45, s: 1.3 } },
  // 17〜20 小節目: 出力オプション
  { beat: bar(17), len: 4, ev: "open-options", off: -0.3, fx: "flashIn", jp: "出力方法を設定", en: "Output settings", zoomPc: { x: 1, y: 0.42, s: 1.5 } },
  { beat: bar(18), len: 4, ev: "ratio:16:9", off: -0.3, speed: 1.1, jp: "解像度は4種類", en: "Four aspect ratios", zoomPc: { x: 1, y: 0.3, s: 1.9 } },
  { beat: bar(19), len: 4, ev: "bg:cerulean", off: -0.3, jp: "選べる背景色", en: "Pick a background", zoomPc: { x: 1, y: 0.62, s: 1.9 } },
  { beat: bar(20), len: 4, ev: "bg:custom", off: -0.4, jp: "カスタム色も", en: "Or any color", zoomPc: { x: 1, y: 0.67, s: 2.0 } },
  // 21〜23 小節目: 共有
  { beat: bar(21), len: 4, ev: "share", off: -0.4, jp: "トラックを共有", en: "Share", zoomPc: { x: 0.55, y: 0.7, s: 1.8 } },
  { beat: bar(22), len: 4, ev: "share-ready", off: -0.2, jp: "PNG と共有 URL", en: "A PNG and a link", zoomPc: { x: 0.6, y: 0.5, s: 1.3 } },
  { beat: bar(23), len: 4, ev: "share-page", off: 0.0, speed: 1.5, jp: "共有ページ", en: "Open the share page" },
];

/** URL 検索の対応サイト（8 分音符 3 連で 1 つずつ出す） */
export const SITES = ["YouTube", "ニコニコ動画", "Bandcamp", "SoundCloud", "Spotify", "bilibili"];

/** タイムラプス: 録画の始まりから PNG 完成までを 16 分割して 1 小節に詰める */
export const TIMELAPSE_STEPS = 16;
export const timelapseTimes = (kind: Kind) => {
  const a = evTime(kind, "start"), b = evTime(kind, "share-ready");
  return Array.from({ length: TIMELAPSE_STEPS }, (_, i) => a + ((b - a) * i) / (TIMELAPSE_STEPS - 1));
};
