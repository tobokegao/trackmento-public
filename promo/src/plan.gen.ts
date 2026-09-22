// **自動生成（promo/plan_gen.mjs）。手で直さない**。直すのは譜割りエディタの「場面」レーンの「動画の台本」。
// エディタの版: rev v20wide（2026-09-22T03:40:40.389Z）
// 拍は 4 分音符・0 始まり（小節 n の頭 = (n - 1) * 4）。len も拍。off は印からの秒、speed は倍率
export type PlanShot = { id: string; beat: number; len: number; ev: string; off: number; jp: string; en: string; speed?: number };
export const PLAN_SHOTS: PlanShot[] = [
 {
  "id": "mfejuzc",
  "beat": 32,
  "len": 4,
  "ev": "start",
  "off": -0.9,
  "jp": "トップ画面はこれだけ",
  "en": "This is the whole app",
  "speed": 0.5
 },
 {
  "id": "lgd0qty",
  "beat": 36,
  "len": 4,
  "ev": "tour:title",
  "off": -0.2,
  "jp": "上にタイトル",
  "en": "Title on top",
  "speed": 0.6
 },
 {
  "id": "1i5fh4b",
  "beat": 40,
  "len": 4,
  "ev": "tour:grid",
  "off": -0.2,
  "jp": "真ん中にマス",
  "en": "The grid in the middle",
  "speed": 0.6
 },
 {
  "id": "hx98afy",
  "beat": 44,
  "len": 4,
  "ev": "tour:buttons",
  "off": -0.2,
  "jp": "下に共有と検索",
  "en": "Share and search below",
  "speed": 0.6
 },
 {
  "id": "rk4o4sz",
  "beat": 48,
  "len": 4,
  "ev": "tour:options",
  "off": -0.3,
  "jp": "出力の設定",
  "en": "Output settings",
  "speed": 0.8
 },
 {
  "id": "380i9jk",
  "beat": 52,
  "len": 4,
  "ev": "title-focus",
  "off": -0.2,
  "jp": "まずはタイトル",
  "en": "Start with a title"
 },
 {
  "id": "6g6osts",
  "beat": 56,
  "len": 4,
  "ev": "cellratio:16:9",
  "off": -0.6,
  "jp": "マスの形を「横長 16:9」に",
  "en": "Set the cells to 16:9",
  "speed": 1.81
 },
 {
  "id": "37o6me6",
  "beat": 60,
  "len": 4,
  "ev": "cell-tap",
  "off": -0.5,
  "jp": "枠をタップ",
  "en": "Tap a cell"
 },
 {
  "id": "dcj7rht",
  "beat": 64,
  "len": 4,
  "ev": "add:talk",
  "off": -2.2,
  "jp": "動画の URL を貼るだけ",
  "en": "Just paste a video URL",
  "speed": 1.8
 },
 {
  "id": "eoqbxrm",
  "beat": 68,
  "len": 4,
  "ev": "multi:paste",
  "off": -1.4,
  "jp": "改行で区切って丸ごと挿入",
  "en": "One per line, all at once",
  "speed": 2
 },
 {
  "id": "blgvply",
  "beat": 72,
  "len": 8,
  "ev": "search:saishu",
  "off": -1.6,
  "jp": "曲名でも探せる（4 か所から）",
  "en": "Or search by title (4 sources)",
  "speed": 2
 },
 {
  "id": "9mxejt1",
  "beat": 80,
  "len": 4,
  "ev": "pl:fill",
  "off": -0.5,
  "jp": "マイリストや再生リストの\nURL で一気に",
  "en": "A whole playlist in one paste",
  "speed": 3
 },
 {
  "id": "zd9g3ak",
  "beat": 84,
  "len": 8,
  "ev": "pl:rest",
  "off": -0.3,
  "jp": "最大 500 曲がまとめて入る",
  "en": "Up to 500 tracks at once",
  "speed": 0.6
 },
 {
  "id": "ilbkxxw",
  "beat": 92,
  "len": 4,
  "ev": "revive:paste",
  "off": -1.6,
  "jp": "削除された動画も",
  "en": "Even deleted videos",
  "speed": 1.5
 },
 {
  "id": "xg15614",
  "beat": 96,
  "len": 4,
  "ev": "revive:done",
  "off": -0.6,
  "jp": "otoDB からよみがえる",
  "en": "come back from otoDB"
 },
 {
  "id": "ss0evau",
  "beat": 100,
  "len": 8,
  "ev": "origin:select",
  "off": -0.4,
  "jp": "転載でも、\n元の作者が分かる",
  "en": "Reuploads? Find\nthe original creator",
  "speed": 1.52
 },
 {
  "id": "5nrfx8t",
  "beat": 108,
  "len": 4,
  "ev": "add:vocadb",
  "off": -2,
  "jp": "VocaDB でサブスクに無い曲も",
  "en": "VocaDB finds what streaming doesn't",
  "speed": 2
 },
 {
  "id": "id60ky6",
  "beat": 112,
  "len": 4,
  "ev": "add:author",
  "off": -1.6,
  "jp": "ボカロの作者名も\nVocaDB から",
  "en": "Vocaloid producers filled in from VocaDB",
  "speed": 1.5
 },
 {
  "id": "8gyp8m2",
  "beat": 116,
  "len": 8,
  "ev": "add:kumikyoku",
  "off": -3.33,
  "jp": "動画 ID だけでも入る",
  "en": "Even just a video ID works",
  "speed": 1.17
 },
 {
  "id": "2n7pkfo",
  "beat": 124,
  "len": 8,
  "ev": "fit:blur",
  "off": -0.4,
  "jp": "形の違うサムネは\n切り抜くか、ぼかして埋める",
  "en": "Odd-shaped thumbnails: crop,\nor fill with a blur",
  "speed": 2.62
 },
 {
  "id": "b03hory",
  "beat": 132,
  "len": 4,
  "ev": "add:mahiro",
  "off": -0.4,
  "jp": "枠が全部埋まったら",
  "en": "Once every cell is full"
 },
 {
  "id": "vx9a2lo",
  "beat": 136,
  "len": 4,
  "ev": "select:1",
  "off": -0.2,
  "jp": "タップで入れ替え",
  "en": "Tap two cells to swap",
  "speed": 1.2
 },
 {
  "id": "zm32swp",
  "beat": 140,
  "len": 4,
  "ev": "zoom32:open",
  "off": -0.3,
  "jp": "「大きく見る」で並べ替え",
  "en": "Rearrange in the big view",
  "speed": 1.8
 },
 {
  "id": "kqv3bhm",
  "beat": 144,
  "len": 4,
  "ev": "ratio:16:9",
  "off": -0.3,
  "jp": "縦横の比率は 5 種類",
  "en": "Five aspect ratios",
  "speed": 1.1
 },
 {
  "id": "uwohvic",
  "beat": 148,
  "len": 4,
  "ev": "list:beside",
  "off": -0.3,
  "jp": "曲名リストは 3 択",
  "en": "Three ways to show the track list",
  "speed": 1.3
 },
 {
  "id": "10gxz2c",
  "beat": 152,
  "len": 4,
  "ev": "bg:cerulean",
  "off": -0.3,
  "jp": "背景色は 8 色",
  "en": "Eight background colours"
 },
 {
  "id": "8h5qfvg",
  "beat": 156,
  "len": 4,
  "ev": "bg:custom",
  "off": -0.4,
  "jp": "カスタム色はつまみで",
  "en": "Or dial in any colour"
 },
 {
  "id": "qfvofd9",
  "beat": 160,
  "len": 4,
  "ev": "pal:pop",
  "off": -0.5,
  "jp": "パレットで配色ごと切り替え",
  "en": "Palettes swap the whole colour scheme",
  "speed": 1.2
 },
 {
  "id": "e179xpp",
  "beat": 164,
  "len": 8,
  "ev": "share",
  "off": -0.2,
  "jp": "「トラックを共有」で\n画像と共有ページ",
  "en": "Share for an image\nand a share page",
  "speed": 1.3
 },
 {
  "id": "q34g03l",
  "beat": 180,
  "len": 8,
  "ev": "listed:check",
  "off": -0.8,
  "jp": "「みんなのグリッド」に載せて共有",
  "en": "List it on Everyone's grids",
  "speed": 1.4
 },
 {
  "id": "j91wlyz",
  "beat": 188,
  "len": 4,
  "ev": "share:output",
  "off": 0,
  "jp": "画像と共有 URL",
  "en": "An image and a link"
 },
 {
  "id": "97t4txw",
  "beat": 192,
  "len": 4,
  "ev": "find:open",
  "off": -1.2,
  "jp": "曲名で、みんなの並びを探せる",
  "en": "Search everyone's grids by track",
  "speed": 1.6
 },
 {
  "id": "xc3oxx2",
  "beat": 196,
  "len": 4,
  "ev": "find:app-tap",
  "off": -0.3,
  "jp": "見つけた並びを、\nそのまま読み込める",
  "en": "Load a grid you found,\nas is",
  "speed": 1.24
 },
 {
  "id": "ntvo0x8",
  "beat": 200,
  "len": 4,
  "ev": "start",
  "off": 0,
  "jp": "曲が多くても\n曲名がきれいに収まる",
  "en": "Track lists fit neatly,\neven with many songs"
 }
];
export const PLAN_TAIL: PlanShot[] = [
 {
  "id": "tail2yqnjh",
  "beat": 216,
  "len": 8,
  "ev": "guide:page",
  "off": -0.1,
  "jp": "困ったら「使い方」",
  "en": "Stuck? See the Guide",
  "speed": 0.8
 }
];
/** 作った画の場面の頭（拍） */
export const PLAN_BEATS = {
 "intro": 0,
 "hook": 12,
 "points": 20,
 "showcase": 172,
 "end-logo": 204,
 "end-url": 208,
 "end-free": 212,
 "tail": 216,
 "last": 224
} as const;
