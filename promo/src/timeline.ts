// 拍・小節の割り付けと、録画（events.json）との対応。
// 9:16（tall）と 16:9（wide）、日本語と英語で同じ拍割りを使う。
//
// 曲は Sherbet（**BPM 130.00 ちょうど** / 1 小節 1.846 秒 / 1 小節目の頭 = 0.52 秒 = 頭の無音のあとの最初の音）。使うのは 49 小節（≒ 90 秒）。
// 拍は beats.json の固定の格子（2026-09-17 に全曲の櫛で測り直した。librosa の拍は 40〜100ms 遅れていた）。
// 録画は本編（9 マスを埋めて共有まで）と feat（新機能だけ）の 2 本立て。
// ① で 500 曲入れると並びが壊れるので、同じセッションでは撮れないため。
//
// v5（2026-09-19 夜）。構成は譜割りエディタ（https://claude.ai/artifact/KNEULMAUpPGXSYdrCmWC1Q）で利用者が決めたもの。
import beatsJson from "./beats.json";
import { PLAN_SHOTS, PLAN_TAIL, PLAN_BEATS, PlanShot } from "./plan.gen";
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

/** 録画の時刻と実時間の比。capture.mjs で撮ったものは t = v なので 1（以前の実時間の録画のための名残） */
export const rate = (kind: Kind, lang: Lang, session: Session) => {
  const ev = RECORDINGS[kind][lang][session].events;
  const first = ev[0], last = [...ev].reverse().find((e) => e.v !== undefined && e.t > 10);
  return last ? (last.v! - (first.v ?? 0)) / (last.t - first.t) : 1;
};
export const evTime = (kind: Kind, lang: Lang, session: Session, name: string) => {
  const e = RECORDINGS[kind][lang][session].events.find((x) => x.name === name);
  if (!e) throw new Error(`${kind}/${lang}/${session} の events.json に ${name} がない`);
  return e.v ?? e.t;   // v = 動画内の時刻（capture.mjs がコマ番号 ÷ 30 で付ける）
};

// ---- 構成（拍番号は 0 始まり。小節 n の頭 = bar(n)）。v5（2026-09-19 夜）: 譜割りエディタで組み直した 50 小節 ----
// 1–3   イントロ
// 4–5   新しい URL は trackmento.com（作った画。録画にはアドレス欄が映らないので）
// 6–7   さらに軽くなりました（作った画）/ 8–9 共有がさらに速く（作った画）
// 10–17 新しくなったところ: みんなのグリッド 2 / 探す 2 / パレット 2 / VocaDB / 曲名リスト（静止画 16 枚を 16 分ずつ）
// 18–20 トップ画面の説明
// 21–31 入れ方 / 32 ボカロの作者名も VocaDB から / 33–35 大きく見る・埋めて並べる
// 36–41 出力と共有（36 = 曲名リストは 3 択。41 は 3.5 拍）
// 42–43 タイムラプス（キメに乗る）/ 44–45 できあがり / 46–48 エンドカード / 49–50 困ったら更新情報と使い方（録画）
// v4 から外したもの: ローマ字（8–9）、全部外す → 元に戻す（32）
// 曲の区切りとキメは 2026-09-18 に聴き直して 1 小節後ろへ直した（A メロ 28–43、サビ 2 は 44 から、キメは 42 小節 4.5 拍〜43 小節）
// **小節の割り付けは譜割りエディタから作る**（2026-09-20）。数字は src/plan.gen.ts（エディタの「場面」レーンの「動画の台本」）にだけ置き、
// ここでは名前を付けるだけ。直すときはエディタで直して node plan_gen.mjs
export const NEWURL_BEAT = PLAN_BEATS.newurl;       // 新しい URL（作った画）
export const INTRO_END = NEWURL_BEAT;               // イントロはそこまで
export const BANDWIDTH_BEAT = PLAN_BEATS.bandwidth; // さらに軽くなりました（作った画）
export const FASTER_BEAT = PLAN_BEATS.faster;       // 共有がさらに速く（作った画）
export const TIMELAPSE_BEAT = PLAN_BEATS.timelapse; // タイムラプス（キメの頭から）
export const SHOWCASE_BEAT = PLAN_BEATS.showcase;   // できあがり
export const END_BEAT = PLAN_BEATS["end-logo"];     // エンドカード（ロゴ → URL → 無料）
export const URL_BEAT = PLAN_BEATS["end-url"];
export const FREE_BEAT = PLAN_BEATS["end-free"];
export const TAIL_BEAT = PLAN_BEATS.tail;           // 困ったら「更新情報」と「使い方」（録画。エンドカードはここで終わる）
export const LAST_BEAT = PLAN_BEATS.last;           // 動画の終わり
export const FADE_FROM = END_BEAT;                  // 音楽のフェードアウト開始
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
  capStill?: boolean;                                                                             // 字幕を動かさずに出したまま（前のショットから続けて見せる）
  scrap?: boolean;                                                                                // stills をスクラップブックのように角度・位置をばらして重ねていく（v6）
  explorer?: { ev: string; beats?: [number, number, number]; hide?: number; file?: string };  // hide = 窓を引っ込める拍、file = 出すファイル名（録画に名前が無いとき）                                     // beats = ショットの頭からの拍（窓が出る・ファイルが入る・選択の青が点滅し始める）                                                                      // その操作の時刻に「ファイルが保存された」窓を重ねる（v6、パレットの保存）
};

/** 17 小節目の静止画 16 枚（promo/make_stills.py が作る）。16 分音符（0.25 拍）ずつ */
const SMART = Array.from({ length: 16 }, (_, i) => `smart-${String(i + 1).padStart(2, "0")}`);

/** ショットの見せ方の細かい値（エディタの場面の ID ごと）。開始・長さ・字幕・印・ずらし・速さはエディタ（plan.gen.ts）から来る。
    zoom = スマホ録画・zoomPc = PC 録画の拡大、hl = 枠線、fx = 演出、stills = 静止画、explorer = 保存の窓、capStill = 字幕を出したまま。
    赤枠（hl）は 9/19 の録画で測った（1080x1920）。早回しとズーム（zoomPc）は v3 の値のまま */
const SHOT_EXTRAS: Record<string, Partial<Shot>> = {
  "q34g03l": {"zoom": {"x": 0.2, "y": 0.6, "s": 1.3}, "zoomPc": {"x": 0.6, "y": 0.9, "s": 1.5}},   // 「みんなのグリッド」に載せて共有
  "97t4txw": {},   // 曲名で、みんなの並びを探せる
  "3oaiopo": {"explorer": {"ev": "io:save", "beats": [0.5, 1, 2], "hide": 4, "file": "trackmento-grid-2026-09-19.json"}},   // 並びを保存/読み取るで復活
  "qfvofd9": {},   // パレットで配色ごと切り替え
  "ggrg1as": {"explorer": {"ev": "pal:saved", "beats": [1, 2, 3]}},   // 自作パレットは共有可能
  "5nrfx8t": {"zoomPc": {"x": 0, "y": 0.4, "s": 1.6}},   // VocaDB でサブスクに無い曲も
  "ntvo0x8": {"rec": "feat", "stills": SMART, "stillBeats": SMART.map((_, i) => i * 0.25), "scrap": true},   // 曲名リストが賢くなりました
  "mfejuzc": {},   // トップ画面はこれだけ
  "lgd0qty": {"zoomPc": {"x": 0.6, "y": 0.35, "s": 1.35}, "hl": {"x": 0.056, "y": 0.138, "w": 0.889, "h": 0.5953, "pt": 11, "pb": 18}},   // 上にタイトル、真ん中にマス
  "hx98afy": {"zoomPc": {"x": 0.6, "y": 0.85, "s": 1.5}, "hl": {"x": 0.056, "y": 0.751, "w": 0.889, "h": 0.1646, "pt": 12, "pb": 18}},   // 下に共有と検索、出力の設定
  "380i9jk": {},   // まずはタイトル
  "37o6me6": {"zoomPc": {"x": 0.52, "y": 0.36, "s": 1.8}},   // 枠をタップ
  "blgvply": {"zoomPc": {"x": 0, "y": 0.43, "s": 1.9}},   // 検索ソースは 4 種類
  "d0fv045": {"zoomPc": {"x": 0, "y": 0.3, "s": 1.7}},   // 曲を探す
  "dcj7rht": {"zoomPc": {"x": 0, "y": 0.74, "s": 1.7}},   // URL 検索も対応
  "eoqbxrm": {},   // 改行で区切って丸ごと挿入
  "9mxejt1": {},   // Playlist の URL で一気に追加
  "zd9g3ak": {},   // 最大 500 曲がまとめて入る
  "ilbkxxw": {},   // 消えた動画も
  "xg15614": {},   // otoDB からよみがえる
  "8gyp8m2": {"zoomPc": {"x": 0, "y": 1, "s": 1.7}},   // 手入力も可能
  "id60ky6": {},   // ボカロの作者名も VocaDB から
  "zm32swp": {},   // 「大きく見る」で細長い並びも見やすく
  "b03hory": {"zoomPc": {"x": 0.6, "y": 0.45, "s": 1.5}},   // 枠が全部埋まったら
  "vx9a2lo": {"zoomPc": {"x": 0.6, "y": 0.45, "s": 1.6}},   // タップで入れ替え
  "kqv3bhm": {"zoomPc": {"x": 1, "y": 0.3, "s": 1.9}, "fx": "flashIn"},   // 解像度は 5 種類
  "uwohvic": {"zoomPc": {"x": 1, "y": 0.5, "s": 1.8}},   // 曲名リストは 3 択（横・マスに重ねる・なし）
  "10gxz2c": {"zoomPc": {"x": 1, "y": 0.62, "s": 1.9}},   // 背景色は 8 色
  "8h5qfvg": {"zoomPc": {"x": 1, "y": 0.67, "s": 2}},   // カスタム色はつまみで
  "e179xpp": {"zoomPc": {"x": 0.55, "y": 0.7, "s": 1.6}},   // 共有すると、送信の進み具合が見える
  "j91wlyz": {"zoomPc": {"x": 0.6, "y": 0.5, "s": 1.3}},   // 画像と共有 URL
  "4yu6dbf": {},   // 困ったら「更新情報」
  "tail2yqnjh": {"capStill": true},   // 困ったら「使い方」
};
/** 印がどちらの録画（本編・新機能）にあるか。縦・日本語の録画で探す（4 本とも同じ台本で撮るので同じ） */
const sessionOf = (ev: string): Session =>
  RECORDINGS.tall.ja.main.events.some((e) => e.name === ev) ? "main"
    : RECORDINGS.tall.ja.feat.events.some((e) => e.name === ev) ? "feat"
    : (() => { throw new Error(`印「${ev}」がどちらの録画にも無い（capture.mjs の台本か、エディタの「録画の印」を見直す）`); })();
const toShot = (p: PlanShot): Shot => {
  const { id, ...rest } = p;
  const rec = sessionOf(p.ev);
  return { ...rest, ...(rec !== "main" ? { rec } : {}), ...(SHOT_EXTRAS[id] || {}) };   // 印が両方にあるとき（start）は SHOT_EXTRAS の rec が勝つ
};
export const SHOTS: Shot[] = PLAN_SHOTS.map(toShot);
/** エンドカードのあとの録画。音楽はフェードの途中 */
export const TAIL_SHOTS: Shot[] = PLAN_TAIL.map(toShot);

/** 8–9 小節「共有がさらに速く」（作った画）。2026-09-19 にスマホの共有画像を小さくした（最大辺 2000px・JPEG 0.78） */
export const FASTER_ROWS: { jp: string; en: string; from: string; to: string }[] = [
  { jp: "スマホの共有画像", en: "Share image on phones", from: "465KB", to: "327KB" },
  { jp: "送信にかかる時間", en: "Upload time", from: "100%", to: "約 70%" },
];

/** タイムラプスの中のキメ（ショットの頭からの拍数）。1 つごとに寄り、最後の 1 つは横へも振る */
export const TIMELAPSE_KIME = [0, 1, 2, 3];   // タイムラプスの頭からの拍（42.4.5 / 43.1.5 / 43.2.5 / 43.3.5）。最後の 1 つで横に引き伸ばす

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
