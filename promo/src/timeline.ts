// 拍・小節の割り付けと、録画（events.json）との対応。
// 9:16（tall）と 16:9（wide）、日本語と英語で同じ拍割りを使う。
//
// 曲は Sherbet（**BPM 130.00 ちょうど** / 1 小節 1.846 秒 / 1 小節目の頭 = 0.52 秒 = 頭の無音のあとの最初の音）。使うのは 49 小節（≒ 90 秒）。
// 拍は beats.json の固定の格子（2026-09-17 に全曲の櫛で測り直した。librosa の拍は 40〜100ms 遅れていた）。
// 録画は本編（9 マスを埋めて共有まで）と feat（新機能だけ）の 2 本立て。
// ① で 500 曲入れると並びが壊れるので、同じセッションでは撮れないため。
//
// v4（2026-09-19）。構成は譜割りエディタ（https://claude.ai/artifact/KNEULMAUpPGXSYdrCmWC1Q）で利用者が決めたもの。
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

const beatAt = (i: number) => {
  if (i < BEATS.length) return BEATS[i];
  const step = BEATS[BEATS.length - 1] - BEATS[BEATS.length - 2];
  return BEATS[BEATS.length - 1] + step * (i - BEATS.length + 1);
};
/** 拍番号 → 秒。**拍の途中（0.25 拍＝16 分音符など）も扱う**（v4 でタイムラプスが 42 小節 4.5 拍から始まり、
    17 小節の静止画が 16 分ずつ切り替わるため）。整数の拍のあいだは直線で結ぶ */
export const beatTime = (i: number) => {
  const f = Math.floor(i), fr = i - f;
  return fr ? beatAt(f) + (beatAt(f + 1) - beatAt(f)) * fr : beatAt(f);
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

// ---- 構成（拍番号は 0 始まり。小節 n の頭 = bar(n)）。v4（2026-09-19）: 譜割りエディタで確定した 49 小節 ----
// 1–3   イントロ
// 4–5   新しい URL は trackmento.com（作った画。録画にはアドレス欄が映らないので）
// 6–7   さらに軽くなりました（作った画）
// 8–17  新しくなったところ: ローマ字 2 / みんなのグリッド 2 / 探す 2 / パレット 2 / VocaDB / 曲名リスト（静止画 16 枚を 16 分ずつ）
// 18–20 トップ画面の説明
// 21–31 入れ方 / 32 全部外す → 元に戻す / 33–36 埋めて並べる（36 は 2 拍ずつ）
// 37–42 出力と共有（37 = 曲名リストは 3 択。42 は 3.5 拍）
// 42.4.5–43 タイムラプス（4.5 拍。キメに乗る）/ 44–45 できあがり（2 拍ずつ 4 枚）/ 46–48 エンドカード / 49 終わり
// 曲の区切りとキメは 2026-09-18 に聴き直して 1 小節後ろへ直した（A メロ 28–43、サビ 2 は 44 から、キメは 42 小節 4.5 拍〜43 小節）
export const INTRO_END = bar(4);            // イントロは 3 小節
export const NEWURL_BEAT = bar(4);          // 新しい URL（作った画、2 小節）
export const BANDWIDTH_BEAT = bar(6);       // さらに軽くなりました（作った画、2 小節）
export const FLOW_BEAT = bar(8);            // 録画のショットはここから
export const TIMELAPSE_BEAT = bar(42);         // 42〜43 小節目の 2 小節。キメ（42 小節 4.5 拍〜43 小節 3.5 拍）で拡大する
export const SHOWCASE_BEAT = bar(44);       // できあがり（2 小節。本編で作った 1 枚をそのまま見せる）
export const END_BEAT = bar(46);            // エンドカード（ロゴ 1 小節 → URL 1 小節 → 無料 1 小節）
export const URL_BEAT = bar(47);
export const FREE_BEAT = bar(48);
export const LAST_BEAT = bar(50);           // 49 小節目（終わり）まで
export const FADE_FROM = END_BEAT;          // 音楽のフェードアウト開始（46 小節）
export const DURATION_FRAMES = beatFrame(LAST_BEAT) + 12;

/** 録画を見せるショット。ev = 操作名、off = その何秒前/後から、speed = 早回し倍率、zoom = 画面のどこを拡大するか（0〜1） */
export type Shot = {
  beat: number; len: number; ev: string; off: number; speed?: number; jp: string; en: string;
  rec?: Session;                                                                                  // 既定は本編（main）。新機能は feat
  zoom?: { x: number; y: number; s: number }; zoomPc?: { x: number; y: number; s: number };   // zoom = スマホ録画、zoomPc = PC 録画
  hl?: { x: number; y: number; w: number; h: number; pt?: number; pb?: number };                                           // スマホ録画で枠線で強調する範囲（割合）
  still?: boolean;                                                                                // 録画を最初のコマで止める（裏で操作が進まないように）
  ab?: string;                                                                                    // 前半にこの画（v1 の見た目）を出して見くらべる。public/ のファイル名
  fx?: "glitchOut" | "flashIn";                                                                   // glitchOut: 末尾 1 小節のジャンプ演出、flashIn: 冒頭 1 拍の反転
  stills?: string[];                                                                              // 録画ではなく静止画（public/stills/<名前>.png、横は -pc）を順に出す
  stillBeats?: number[];                                                                          // stills を切り替える拍（ショットの頭からの拍数）
  labels?: { jp: string; en: string }[];                                                          // stills ごとの添え書き
};

/** 17 小節目の静止画 16 枚（promo/make_stills.py が作る）。16 分音符（0.25 拍）ずつ */
const SMART = Array.from({ length: 16 }, (_, i) => `smart-${String(i + 1).padStart(2, "0")}`);

// 赤枠（hl）は 9/19 の録画で測った（1080x1920）。上: タイトル欄 265px 〜 マスの下の説明文 1408px、下: ボタン 1442px 〜「マスを全部外す」1758px。
// pt / pb は枠線が上下のすきま（ラベル 251〜265、説明文とボタン 1408〜1442、次の説明文 1758〜1784）に収まる値
// 早回し（speed）とズーム（zoomPc）は v3 の場面ごとの値をそのまま使う（エディタでは扱わないと決めた。2026-09-18）
export const SHOTS: Shot[] = [
  // ---- 8〜17 小節目: 新しくなったところ ----
  { beat: bar(8), len: 8, ev: "romaji:search", off: -0.6, rec: "feat", speed: 1.4, jp: "英語画面なら曲名もローマ字に", en: "In English, titles come romanized", zoomPc: { x: 0, y: 0.4, s: 1.6 } },
  { beat: bar(10), len: 8, ev: "listed:check", off: -0.8, rec: "feat", speed: 1.4, jp: "「みんなのグリッド」に載せて共有", en: "List it on Everyone's grids", zoom: { x: 0.2, y: 0.6, s: 1.3 }, zoomPc: { x: 0.6, y: 0.9, s: 1.5 } },
  { beat: bar(12), len: 8, ev: "find:page", off: -0.2, rec: "feat", speed: 1.1, jp: "曲名で、みんなの並びを探せる", en: "Search everyone's grids by track" },
  { beat: bar(14), len: 4, ev: "pal:pop", off: -0.5, rec: "feat", speed: 1.2, jp: "パレットで配色ごと切り替え", en: "Palettes swap the whole colour scheme" },
  { beat: bar(15), len: 4, ev: "pal:copy", off: -0.3, rec: "feat", speed: 1.5, jp: "自作パレットは共有可能", en: "Copy your own palette to share it" },
  { beat: bar(16), len: 4, ev: "vocadb:search", off: -1.4, rec: "feat", speed: 1.6, jp: "VocaDB でサブスクに無い曲も", en: "VocaDB finds what streaming doesn't", zoomPc: { x: 0, y: 0.4, s: 1.6 } },
  { beat: bar(17), len: 4, ev: "start", off: 0, rec: "feat", jp: "曲名リストが賢くなりました", en: "Smarter track lists",
    stills: SMART, stillBeats: SMART.map((_, i) => i * 0.25) },

  // ---- 18〜20 小節目: トップ画面の説明 ----
  { beat: bar(18), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "トップ画面はこれだけ", en: "This is the whole app" },
  { beat: bar(19), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "上にタイトル、真ん中にマス", en: "Title on top, the grid in the middle", hl: { x: 0.056, y: 0.138, w: 0.889, h: 0.5953, pt: 11, pb: 18 }, zoomPc: { x: 0.6, y: 0.35, s: 1.35 } },
  { beat: bar(20), len: 4, ev: "start", off: -0.9, speed: 0.5, jp: "下に共有と検索、出力の設定", en: "Share, search and settings below", hl: { x: 0.056, y: 0.751, w: 0.889, h: 0.1646, pt: 12, pb: 18 }, zoomPc: { x: 0.6, y: 0.85, s: 1.5 } },

  // ---- 21〜31 小節目: 入れ方 ----
  { beat: bar(21), len: 4, ev: "title-focus", off: -0.2, jp: "まずはタイトル", en: "Start with a title" },
  { beat: bar(22), len: 4, ev: "cell-tap", off: -0.5, jp: "枠をタップ", en: "Tap a cell", zoomPc: { x: 0.52, y: 0.36, s: 1.8 } },
  { beat: bar(23), len: 4, ev: "src:musicbrainz", off: -0.4, speed: 1.5, jp: "検索ソースは 4 種類", en: "Four search sources", zoomPc: { x: 0, y: 0.43, s: 1.9 } },
  { beat: bar(24), len: 4, ev: "search:chikamichi", off: -1.6, speed: 2, jp: "曲を探す", en: "Find tracks", zoomPc: { x: 0, y: 0.3, s: 1.7 } },
  { beat: bar(25), len: 4, ev: "url:talk", off: -1.6, speed: 1.4, jp: "URL 検索も対応", en: "Or paste a URL", zoomPc: { x: 0, y: 0.74, s: 1.7 } },
  { beat: bar(26), len: 4, ev: "multi:got", off: -1.8, rec: "feat", speed: 1.6, jp: "改行で区切って丸ごと挿入", en: "One per line, all at once" },
  { beat: bar(27), len: 4, ev: "pl:paste", off: -1.8, rec: "feat", speed: 1.6, jp: "Playlist の URL で一気に追加", en: "A whole playlist in one paste" },
  { beat: bar(28), len: 4, ev: "pl:fill", off: -1.2, rec: "feat", jp: "最大 500 曲がまとめて入る", en: "Up to 500 tracks at once" },
  { beat: bar(29), len: 4, ev: "revive:paste", off: -1.6, rec: "feat", speed: 1.5, jp: "消えた動画も", en: "Even deleted videos" },
  { beat: bar(30), len: 4, ev: "revive:done", off: -0.6, rec: "feat", jp: "otoDB からよみがえる", en: "come back from otoDB" },
  { beat: bar(31), len: 4, ev: "manual:mitsuami", off: -0.6, speed: 1.2, jp: "手入力も可能", en: "Or add your own", zoomPc: { x: 0, y: 1, s: 1.7 } },
  // ---- 32 小節目: 全部外す → 確認の窓 → 元に戻す（v3 では最後の場面だった） ----
  { beat: bar(32), len: 4, ev: "clear:tap", off: -0.4, rec: "feat", speed: 1.3, jp: "作り直すときは「マスを全部外す」", en: "Clear all to start over — and undo if you slip" },
  // ---- 33 小節目: 大きく見る（32×1 を指で送る。16×16 の場面はエディタで外した） ----
  { beat: bar(33), len: 4, ev: "zoom32:open", off: -0.3, rec: "feat", speed: 1.8, jp: "「大きく見る」で細長い並びも見やすく", en: "Enlarge to scroll through long rows" },
  // ---- 34〜35 小節目: 埋めて並べる ----
  { beat: bar(34), len: 4, ev: "add:ilovelove", off: -0.4, jp: "枠が全部埋まったら", en: "Once every cell is full", zoomPc: { x: 0.6, y: 0.45, s: 1.5 } },
  { beat: bar(35), len: 4, ev: "select:1", off: -0.2, speed: 1.2, jp: "タップで入れ替え", en: "Tap two cells to swap", zoomPc: { x: 0.6, y: 0.45, s: 1.6 } },
  // ---- 36〜42 小節目: 出力と共有 ----
  { beat: bar(36), len: 4, ev: "list:overlay", off: -0.5, fx: "flashIn", jp: "曲名リストは 3 択（横・マスに重ねる・なし）", en: "Track list: beside, on the covers, or hidden", zoomPc: { x: 1, y: 0.5, s: 1.8 } },
  { beat: bar(37), len: 4, ev: "ratio:16:9", off: -0.3, speed: 1.1, jp: "解像度は 5 種類", en: "Five aspect ratios", zoomPc: { x: 1, y: 0.3, s: 1.9 } },
  { beat: bar(38), len: 4, ev: "bg:cerulean", off: -0.3, jp: "背景色は 8 色", en: "Eight background colours", zoomPc: { x: 1, y: 0.62, s: 1.9 } },
  { beat: bar(39), len: 4, ev: "bg:custom", off: -0.4, jp: "カスタム色はつまみで", en: "Or dial in any colour", zoomPc: { x: 1, y: 0.67, s: 2.0 } },
  { beat: bar(40), len: 4.5, ev: "share", off: -0.2, jp: "共有すると、送信の進み具合が見える", en: "Share — with an upload progress bar", zoomPc: { x: 0.55, y: 0.7, s: 1.6 } },
  { beat: bar(41) + 0.5, len: 3.5, ev: "share-ready", off: -0.2, jp: "画像と共有 URL", en: "An image and a link", zoomPc: { x: 0.6, y: 0.5, s: 1.3 } },
];

/** タイムラプスの中のキメ（ショットの頭からの拍数）。1 つごとに寄り、最後の 1 つは横へも振る */
export const TIMELAPSE_KIME = [3.5, 4.5, 5.5, 6.5];

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
