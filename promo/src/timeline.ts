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
type Ev = { t: number; v?: number; name: string; rect?: Rect };
/** 録画の中の四角（画面の幅・高さに対する割合）。capture.mjs の markRect が印に添える */
export type Rect = { x: number; y: number; w: number; h: number };
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
/** 印に添えた四角（markRect）。無ければ例外（赤枠の位置が分からないまま描かない） */
export const evRect = (kind: Kind, lang: Lang, session: Session, name: string): Rect => {
  const e = RECORDINGS[kind][lang][session].events.find((x) => x.name === name);
  if (!e || !e.rect) throw new Error(`${kind}/${lang}/${session} の events.json に ${name} の rect がない`);
  return e.rect;
};
/** 四角の付いた印を時刻の順に（横の動画のカメラが追う先。capture.mjs の tap / type / markRect が添える） */
export const evRects = (kind: Kind, lang: Lang, session: Session): { t: number; rect: Rect }[] =>
  RECORDINGS[kind][lang][session].events.filter((e) => e.rect).map((e) => ({ t: e.v ?? e.t, rect: e.rect! })).sort((a, b) => a.t - b.t);
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
// 2026-09-21 の初見向け（16:9 のサムネ中心）: 作った画は hook（正方形 → 16:9 の見くらべ）・points（3 つの特徴）・showcase・エンドカード。
// 新しい URL・さらに軽く・共有がさらに速く・タイムラプスは外した（利用者の判断）
export const HOOK_BEAT = PLAN_BEATS.hook;           // つかみ: サムネを切らずに並べる（作った画）
export const POINTS_BEAT = PLAN_BEATS.points;       // 3 つの特徴（作った画）
export const INTRO_END = HOOK_BEAT;                 // イントロはそこまで
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
  sites?: boolean;                                                                                // 字幕の下に URL 対応サイトのバッジを 8 分音符 3 連で並べる（SITES）
  hlEv?: string;                                                                                  // 赤枠: この印に添えた rect（capture.mjs の markRect）の位置を囲む。縦・横とも
  noCam?: boolean;                                                                                // 横でもカメラを寄せず、画面全体を見せる（2026-09-22、利用者の指定）
  kime?: number[];                                                                                // キメ（ショットの頭からの拍）で一段ずつ寄り、最後のキメから横に引き伸ばして白へ
  explorer?: { ev: string; beats?: [number, number, number]; hide?: number; file?: string };  // hide = 窓を引っ込める拍、file = 出すファイル名（録画に名前が無いとき）                                     // beats = ショットの頭からの拍（窓が出る・ファイルが入る・選択の青が点滅し始める）                                                                      // その操作の時刻に「ファイルが保存された」窓を重ねる（v6、パレットの保存）
};

/** 17 小節目の静止画 16 枚（promo/make_stills.py が作る）。16 分音符（0.25 拍）ずつ */
const SMART = Array.from({ length: 16 }, (_, i) => `smart-${String(i + 1).padStart(2, "0")}`);

/** 特徴の 3 行（6–8 小節の作った画。1 小節に 1 行ずつ出す） */
export const POINTS: { jp: string; en: string }[] = [
  { jp: "曲単位で並べる", en: "One cell per song" },
  { jp: "ニコニコも YouTube も", en: "Niconico & YouTube too" },
  { jp: "登録なし・無料", en: "Free, no sign-up" },
];

/** ショットの見せ方の細かい値（エディタの場面の ID ごと）。開始・長さ・字幕・印・ずらし・速さはエディタ（plan.gen.ts）から来る。
    zoom = スマホ録画の拡大（**横の録画は手で決めず、操作した場所をカメラが追う**。2026-09-22、利用者の指摘で手書きの zoomPc をやめた）、hlEv = 赤枠（その印の rect の位置）、fx = 演出、stills = 静止画、capStill = 字幕を出したまま、
    kime = キメ（ショットの頭からの拍）で寄り、最後のキメから横に引き伸ばして白へ（タイムラプスから移した演出）。
    2026-09-21 の初見向けの構成。**赤枠は録画の印の位置（capture.mjs の markRect）から描く**ので、撮り直しても枠がずれない */
const SHOT_EXTRAS: Record<string, Partial<Shot>> = {
  "mfejuzc": {},   // トップ画面はこれだけ
  "lgd0qty": {"hlEv": "tour:title"},     // 上にタイトル
  "1i5fh4b": {"hlEv": "tour:grid"},      // 真ん中にマス
  "hx98afy": {"hlEv": "tour:buttons"},   // 下に共有と検索
  "rk4o4sz": {"hlEv": "tour:options"},   // 出力の設定
  "380i9jk": {},   // まずはタイトル
  "6g6osts": {},   // マスの形を「横長 16:9」に
  "37o6me6": {},   // 枠をタップ
  "dcj7rht": {"sites": true},   // 動画の URL を貼るだけ（対応サイトのバッジを出す）
  "eoqbxrm": {},   // 改行で区切って丸ごと挿入
  "blgvply": {},   // 曲名でも探せる
  "9mxejt1": {},   // マイリストの URL で一気に
  "zd9g3ak": {},   // 最大 500 曲がまとめて入る
  "ilbkxxw": {},   // 削除された動画も
  "xg15614": {},   // otoDB からよみがえる
  "ss0evau": {},   // 転載でも、元の作者が分かる
  "5nrfx8t": {},   // VocaDB でサブスクに無い曲も
  "id60ky6": {},   // ボカロの作者名も VocaDB から
  "8gyp8m2": {},   // ジャケットが無ければ手入力
  "2n7pkfo": {},   // 正方形が混ざったら「ぼかして埋める」
  "b03hory": {},   // 枠が全部埋まったら
  "vx9a2lo": {},   // タップで入れ替え
  "zm32swp": {"noCam": true},   // 「大きく見る」で並べ替え（窓の中を拡大して見せるので、カメラは寄らない。2026-09-22）
  "kqv3bhm": {},   // 縦横の比率は 5 種類（冒頭の反転は利用者がキメのレーンから外した）
  "uwohvic": {},   // 曲名リストは 3 択
  "10gxz2c": {},   // 背景色は 8 色
  "8h5qfvg": {},   // カスタム色はつまみで
  "qfvofd9": {"noCam": true},   // パレットで配色ごと切り替え（窓が大きいので寄らない。2026-09-22、利用者の指定）
  // 共有: キメ（エディタの「キメ」のレーン 42.4.5・43.1.5・43.2.5・43.3.5）で寄り、最後のキメから横に引き伸ばして白へ
  "e179xpp": {"kime": [3.5, 4.5, 5.5, 6.5]},
  "q34g03l": {"zoom": {"x": 0.2, "y": 0.6, "s": 1.3}},   // 「みんなのグリッド」に載せて共有
  "j91wlyz": {},   // 画像と共有 URL
  "97t4txw": {"noCam": true},   // 曲名で、みんなの並びを探せる（寄らない。2026-09-22、利用者の指定）
  "xc3oxx2": {},   // 見つけた並びを開ける
  "ntvo0x8": {"rec": "feat", "stills": SMART, "stillBeats": SMART.map((_, i) => i * 0.25), "scrap": true},   // 曲が多くても曲名がきれいに収まる
  "tail2yqnjh": {},   // 困ったら「使い方」
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

/** URL 検索の対応サイト（8 分音符 3 連で 1 つずつ出す） */
// bilibili は 2026-09-20 に対応をやめた（利用者規約 4.2.11）ので外した
export const SITES = ["YouTube", "ニコニコ", "Bandcamp", "SoundCloud", "Spotify", "Apple Music"];
export const SITES_EN = ["YouTube", "Niconico", "Bandcamp", "SoundCloud", "Spotify", "Apple Music"];
