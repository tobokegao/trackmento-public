// 拍・小節の割り付けと、録画（events.json）との対応。
// 9:16（tall）と 16:9（wide）、日本語と英語で同じ拍割りを使う。
//
// 曲は Sherbet（BPM 129.20 / 1 小節 1.858 秒 / 拍 0 = 0.557 秒）。全 40 小節 = 74.3 秒。
// 録画は本編（9 マスを埋めて共有まで）と feat（新機能だけ）の 2 本立て。
// ① で 500 曲入れると並びが壊れるので、同じセッションでは撮れないため。
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
// 1–3 イントロ / 4–8 画面説明（⑤見た目の見くらべ 2 小節もここ）/ 9 タイトル /
// 10–13 入れ方 / 14 複数 URL / 15–16 ①プレイリスト / 17–18 ②復活 / 19–22 並べる /
// 23 ほぼ完成 / 24 ④日英 / 25 ⑥重たくない / 26 出力設定 / 27 解像度 / 28–29 ③256 マス /
// 30–33 色と共有 / 34 タイムラプス / 35–36 できあがり / 37–39 エンドカード
//
// カウントダウン（3,2,1,GO）は v2 では使わない
export const INTRO_END = bar(4);            // イントロは 3 小節
export const FLOW_BEAT = bar(9);            // 操作の流れはここから
export const TIMELAPSE_BEAT = bar(34);
export const SHOWCASE_BEAT = bar(35);       // できあがり（2 小節）
export const BANDWIDTH_BEAT = bar(25);      // ⑥「重たくなくなりました」（録画なしのシーン）
export const END_BEAT = bar(37);            // エンドカード（ロゴ 1 小節 → URL 1 小節 → 無料 1 小節）
export const URL_BEAT = bar(38);
export const FREE_BEAT = bar(39);
export const LAST_BEAT = bar(40);
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
};

export const SHOTS: Shot[] = [
  // 4〜8 小節目: トップ画面の説明（5 小節）。⑤ 見た目の見くらべ（2 小節）もここに畳む
  { beat: bar(4), len: 2, ev: "start", off: -0.9, speed: 0.5, jp: "トップ画面はこれだけ", en: "This is the whole app" },
  { beat: bar(4) + 2, len: 2, ev: "start", off: -0.9, speed: 0.5, jp: "上にタイトル", en: "Title on top", hl: { x: 0.03, y: 0.118, w: 0.94, h: 0.09 }, zoomPc: { x: 0.6, y: 0.2, s: 1.5 } },
  { beat: bar(5), len: 2, ev: "start", off: -0.9, speed: 0.5, jp: "真ん中に 3×3 のマス", en: "Nine cells in the middle", hl: { x: 0.03, y: 0.18, w: 0.94, h: 0.52 }, zoomPc: { x: 0.6, y: 0.45, s: 1.3 } },
  { beat: bar(5) + 2, len: 2, ev: "start", off: -0.9, speed: 0.5, jp: "下に共有と検索のボタン", en: "Share and search below", hl: { x: 0.03, y: 0.716, w: 0.94, h: 0.2 }, zoomPc: { x: 0.6, y: 0.85, s: 1.5 } },
  // 出力の設定は画面の外にあるので、スクロールして見せる（1 小節）
  { beat: bar(6), len: 4, ev: "look:options", off: -0.4, rec: "feat", speed: 0.9, jp: "出力の設定もここに", en: "Output settings too", zoomPc: { x: 1, y: 0.5, s: 1.4 } },
  // ⑤ 見た目の見くらべ。前半 1 小節が v1、後半 1 小節が今（BeforeAfter が切り替える）
  { beat: bar(7), len: 8, ev: "look:scroll", off: -0.6, rec: "feat", speed: 1.2, ab: "v1-look", jp: "見た目はもっとダサく", en: "Now even uglier", zoom: { x: 0.5, y: 0.78, s: 1.2 }, zoomPc: { x: 0.3, y: 0.5, s: 1.35 } },
  // 9〜13 小節目: 入れ方
  { beat: bar(9), len: 4, ev: "title-focus", off: -0.2, jp: "まずはタイトル", en: "Start with a title" },
  { beat: bar(10), len: 4, ev: "cell-tap", off: -0.5, jp: "枠をタップ", en: "Tap a cell", zoomPc: { x: 0.52, y: 0.36, s: 1.8 } },
  { beat: bar(11), len: 4, ev: "search:chikamichi", off: -1.6, speed: 2, jp: "曲を探す", en: "Find tracks", zoomPc: { x: 0, y: 0.3, s: 1.7 } },
  { beat: bar(12), len: 4, ev: "src:musicbrainz", off: -0.4, jp: "検索ソースは 3 種類", en: "Three search sources", zoomPc: { x: 0, y: 0.43, s: 1.9 } },
  { beat: bar(13), len: 4, ev: "url:talk", off: -1.6, speed: 1.4, jp: "URL 検索も対応", en: "Or paste a URL", zoomPc: { x: 0, y: 0.74, s: 1.7 } },
  // 14 小節目: 複数 URL
  { beat: bar(14), len: 4, ev: "multi:got", off: -1.8, rec: "feat", speed: 1.6, jp: "改行で区切って一気に挿入", en: "One per line, all at once" },
  // 15〜16 小節目: ① プレイリスト
  { beat: bar(15), len: 4, ev: "pl:paste", off: -1.8, rec: "feat", speed: 1.6, jp: "プレイリストの URL 内の曲も\nまとめて追加できる", en: "A whole playlist in one paste" },
  { beat: bar(16), len: 4, ev: "pl:fill", off: -1.2, rec: "feat", jp: "最大 500 曲がまとめて入る", en: "Up to 500 tracks at once" },
  // 17〜18 小節目: ② 消えた動画の復活
  { beat: bar(17), len: 4, ev: "revive:paste", off: -1.6, rec: "feat", speed: 1.5, jp: "消えた動画も", en: "Even deleted videos" },
  { beat: bar(18), len: 4, ev: "add:revive", off: -0.8, rec: "feat", jp: "otoDB からよみがえる", en: "come back from otoDB" },
  // 19〜22 小節目: 埋めて並べる
  { beat: bar(19), len: 4, ev: "manual:mitsuami", off: -0.6, speed: 1.2, jp: "手入力も可能", en: "Or add your own", zoomPc: { x: 0, y: 1, s: 1.7 } },
  { beat: bar(20), len: 4, ev: "add:ilovelove", off: -0.4, jp: "枠が全部埋まったら", en: "All nine in", zoomPc: { x: 0.6, y: 0.45, s: 1.5 } },
  { beat: bar(21), len: 4, ev: "select:1", off: -0.2, speed: 1.2, jp: "タップで入れ替え", en: "Tap two cells to swap", zoomPc: { x: 0.6, y: 0.45, s: 1.6 } },
  { beat: bar(22), len: 4, ev: "reorder-done", off: -0.3, jp: "並べ終わったら", en: "Once you're done", zoomPc: { x: 0.6, y: 0.45, s: 1.4 } },
  // 23 小節目: ほぼ完成（寄ったまま止める。跳ねる演出はしない）
  { beat: bar(23), len: 4, ev: "reorder-done", off: 0.6, still: true, jp: "ほぼ完成です", en: "Almost there", zoom: { x: 0.5, y: 0.45, s: 1.35 }, zoomPc: { x: 0.6, y: 0.45, s: 1.35 } },
  // 24 小節目: ④ 日本語 / 英語（ボタンに寄る）
  { beat: bar(24), len: 4, ev: "lang:switched", off: -1.2, rec: "feat", jp: "日本語↔英語 切り替えボタン", en: "Japanese / English switch", zoom: { x: 0.97, y: 0.02, s: 2.1 }, zoomPc: { x: 1, y: 0, s: 2.0 } },
  // 25 小節目は ⑥「重たくなくなりました」（録画ではないので SHOTS には無い。Scenes.tsx が別に描く）
  // 26〜27 小節目: 出力オプション
  { beat: bar(26), len: 4, ev: "open-options", off: -0.3, fx: "flashIn", jp: "出力方法を設定", en: "Output settings", zoomPc: { x: 1, y: 0.42, s: 1.5 } },
  { beat: bar(27), len: 4, ev: "ratio:16:9", off: -0.3, speed: 1.1, jp: "解像度は 5 種類", en: "Five aspect ratios", zoomPc: { x: 1, y: 0.3, s: 1.9 } },
  // 28〜29 小節目: ③ 256 マス
  { beat: bar(28), len: 4, ev: "pl:filled", off: -0.6, rec: "feat", jp: "マスは最大 256", en: "Up to 256 cells" },
  { beat: bar(29), len: 4, ev: "cells:wide", off: -1.2, rec: "feat", speed: 1.1, jp: "縦長も横長も自由", en: "Any shape you like", zoom: { x: 0.5, y: 0.86, s: 1.5 }, zoomPc: { x: 1, y: 0.2, s: 1.8 } },
  // 30〜33 小節目: 色と共有
  { beat: bar(30), len: 4, ev: "bg:cerulean", off: -0.3, jp: "選べる背景色", en: "Pick a background", zoomPc: { x: 1, y: 0.62, s: 1.9 } },
  { beat: bar(31), len: 4, ev: "bg:custom", off: -0.4, jp: "カスタム色も", en: "Or any color", zoomPc: { x: 1, y: 0.67, s: 2.0 } },
  { beat: bar(32), len: 4, ev: "share", off: -0.4, jp: "トラックを共有", en: "Share", zoomPc: { x: 0.55, y: 0.7, s: 1.8 } },
  { beat: bar(33), len: 4, ev: "share-ready", off: -0.2, jp: "画像と共有 URL", en: "An image and a link", zoomPc: { x: 0.6, y: 0.5, s: 1.3 } },
];

/** URL 検索の対応サイト（8 分音符 3 連で 1 つずつ出す） */
export const SITES = ["YouTube", "ニコニコ", "Bandcamp", "SoundCloud", "Spotify", "bilibili", "Apple Music"];
export const SITES_EN = ["YouTube", "Niconico", "Bandcamp", "SoundCloud", "Spotify", "bilibili", "Apple Music"];

/** ⑥「重たくなくなりました」で出す数字（録画ではなく作った画で見せる） */
export const BANDWIDTH_ROWS: { jp: string; en: string; from: string; to: string }[] = [
  { jp: "日本語フォント", en: "Japanese fonts", from: "210KB", to: "~0KB" },
  { jp: "Bandcamp のジャケット", en: "Bandcamp covers", from: "6.5MB", to: "19KB" },
  { jp: "otoDB のサムネ", en: "otoDB thumbnails", from: "166KB", to: "22KB" },
  { jp: "画像の待ち時間", en: "Image wait", from: "3.8秒", to: "1.5秒" },
];

/** タイムラプス: 録画の始まりから PNG 完成までを 16 分割して 1 小節に詰める */
export const TIMELAPSE_STEPS = 16;
export const timelapseTimes = (kind: Kind, lang: Lang) => {
  const a = evTime(kind, lang, "main", "start"), b = evTime(kind, lang, "main", "share-ready");
  return Array.from({ length: TIMELAPSE_STEPS }, (_, i) => a + ((b - a) * i) / (TIMELAPSE_STEPS - 1));
};
