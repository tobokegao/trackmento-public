// **自動生成（promo/plan_gen.mjs）。手で直さない**。直すのは譜割りエディタの「場面」レーンの「動画の台本」。
// エディタの版: rev 6t1sjia（2026-09-19T19:59:30.313Z）
// 拍は 4 分音符・0 始まり（小節 n の頭 = (n - 1) * 4）。len も拍。off は印からの秒、speed は倍率
export type PlanShot = { id: string; beat: number; len: number; ev: string; off: number; jp: string; en: string; speed?: number };
export const PLAN_SHOTS: PlanShot[] = [
 {
  "id": "q34g03l",
  "beat": 36,
  "len": 4,
  "ev": "listed:check",
  "off": -0.8,
  "jp": "「みんなのグリッド」に載せて共有",
  "en": "List it on Everyone's grids",
  "speed": 1.4
 },
 {
  "id": "97t4txw",
  "beat": 40,
  "len": 4,
  "ev": "find:open",
  "off": -1.2,
  "jp": "曲名で、みんなの並びを探せる",
  "en": "Search everyone's grids by track",
  "speed": 1.6
 },
 {
  "id": "3oaiopo",
  "beat": 44,
  "len": 8,
  "ev": "io:save",
  "off": -0.2,
  "jp": "並びを保存して、\n読み込みで復活",
  "en": "Save your layout, load it back any time",
  "speed": 2
 },
 {
  "id": "qfvofd9",
  "beat": 52,
  "len": 4,
  "ev": "pal:pop",
  "off": -0.5,
  "jp": "パレットで配色ごと切り替え",
  "en": "Palettes swap the whole colour scheme",
  "speed": 1.2
 },
 {
  "id": "ggrg1as",
  "beat": 56,
  "len": 4,
  "ev": "pal:saved",
  "off": -0.55,
  "jp": "自作パレットは共有可能",
  "en": "Share your own palette as a file",
  "speed": 1.2
 },
 {
  "id": "5nrfx8t",
  "beat": 60,
  "len": 4,
  "ev": "add:vocadb",
  "off": -2,
  "jp": "VocaDB でサブスクに無い曲も",
  "en": "VocaDB finds what streaming doesn't",
  "speed": 2
 },
 {
  "id": "ntvo0x8",
  "beat": 64,
  "len": 4,
  "ev": "start",
  "off": 0,
  "jp": "曲名リストがより美しく",
  "en": "Better-looking track lists"
 },
 {
  "id": "mfejuzc",
  "beat": 68,
  "len": 4,
  "ev": "start",
  "off": -0.9,
  "jp": "トップ画面はこれだけ",
  "en": "This is the whole app",
  "speed": 0.5
 },
 {
  "id": "lgd0qty",
  "beat": 72,
  "len": 4,
  "ev": "start",
  "off": -0.9,
  "jp": "上にタイトル、真ん中にマス",
  "en": "Title on top, the grid in the middle",
  "speed": 0.5
 },
 {
  "id": "hx98afy",
  "beat": 76,
  "len": 4,
  "ev": "start",
  "off": -0.9,
  "jp": "下に共有と検索、出力の設定",
  "en": "Share, search and settings below",
  "speed": 0.5
 },
 {
  "id": "380i9jk",
  "beat": 80,
  "len": 4,
  "ev": "title-focus",
  "off": -0.2,
  "jp": "まずはタイトル",
  "en": "Start with a title"
 },
 {
  "id": "37o6me6",
  "beat": 84,
  "len": 4,
  "ev": "cell-tap",
  "off": -0.5,
  "jp": "枠をタップ",
  "en": "Tap a cell"
 },
 {
  "id": "blgvply",
  "beat": 88,
  "len": 4,
  "ev": "src:musicbrainz",
  "off": -0.4,
  "jp": "検索ソースは 4 種類",
  "en": "Four search sources",
  "speed": 1.5
 },
 {
  "id": "d0fv045",
  "beat": 92,
  "len": 4,
  "ev": "search:chikamichi",
  "off": -1.6,
  "jp": "曲を探す",
  "en": "Find tracks",
  "speed": 2
 },
 {
  "id": "dcj7rht",
  "beat": 96,
  "len": 4,
  "ev": "add:talk",
  "off": -2.2,
  "jp": "URL 検索も対応",
  "en": "Or paste a URL",
  "speed": 1.8
 },
 {
  "id": "eoqbxrm",
  "beat": 100,
  "len": 4,
  "ev": "multi:paste",
  "off": -1.4,
  "jp": "改行で区切って丸ごと挿入",
  "en": "One per line, all at once",
  "speed": 2
 },
 {
  "id": "9mxejt1",
  "beat": 104,
  "len": 4,
  "ev": "pl:fill",
  "off": -0.5,
  "jp": "Playlist の URL で一気に追加",
  "en": "A whole playlist in one paste",
  "speed": 3
 },
 {
  "id": "zd9g3ak",
  "beat": 108,
  "len": 4,
  "ev": "pl:rest",
  "off": -0.3,
  "jp": "最大 500 曲がまとめて入る",
  "en": "Up to 500 tracks at once",
  "speed": 1.3
 },
 {
  "id": "ilbkxxw",
  "beat": 112,
  "len": 4,
  "ev": "revive:paste",
  "off": -1.6,
  "jp": "消えた動画も",
  "en": "Even deleted videos",
  "speed": 1.5
 },
 {
  "id": "xg15614",
  "beat": 116,
  "len": 4,
  "ev": "revive:done",
  "off": -0.6,
  "jp": "otoDB からよみがえる",
  "en": "come back from otoDB"
 },
 {
  "id": "8gyp8m2",
  "beat": 120,
  "len": 4,
  "ev": "add:mitsuami",
  "off": -1.6,
  "jp": "手入力も可能",
  "en": "Or add your own",
  "speed": 1.6
 },
 {
  "id": "id60ky6",
  "beat": 124,
  "len": 4,
  "ev": "add:author",
  "off": -1.6,
  "jp": "ボカロの作者名も\nVocaDB から",
  "en": "Vocaloid producers filled in from VocaDB",
  "speed": 1.5
 },
 {
  "id": "zm32swp",
  "beat": 128,
  "len": 4,
  "ev": "zoom32:open",
  "off": -0.3,
  "jp": "「大きく見る」で細長い並びも見やすく",
  "en": "Enlarge to scroll through long rows",
  "speed": 1.8
 },
 {
  "id": "b03hory",
  "beat": 132,
  "len": 4,
  "ev": "add:ilovelove",
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
  "id": "kqv3bhm",
  "beat": 140,
  "len": 4,
  "ev": "ratio:16:9",
  "off": -0.3,
  "jp": "解像度は 5 種類",
  "en": "Five aspect ratios",
  "speed": 1.1
 },
 {
  "id": "uwohvic",
  "beat": 144,
  "len": 4,
  "ev": "list:beside",
  "off": -0.3,
  "jp": "曲名リストは 3 択",
  "en": "Three ways to show the track list",
  "speed": 1.3
 },
 {
  "id": "10gxz2c",
  "beat": 148,
  "len": 4,
  "ev": "bg:cerulean",
  "off": -0.3,
  "jp": "背景色は 8 色",
  "en": "Eight background colours"
 },
 {
  "id": "8h5qfvg",
  "beat": 152,
  "len": 4,
  "ev": "bg:custom",
  "off": -0.4,
  "jp": "カスタム色はつまみで",
  "en": "Or dial in any colour"
 },
 {
  "id": "e179xpp",
  "beat": 156,
  "len": 8,
  "ev": "share",
  "off": -0.2,
  "jp": "共有すると、送信の進み具合が見える",
  "en": "Share — with an upload progress bar",
  "speed": 1.3
 },
 {
  "id": "j91wlyz",
  "beat": 164,
  "len": 3.5,
  "ev": "share-ready",
  "off": -0.2,
  "jp": "画像と共有 URL",
  "en": "An image and a link"
 }
];
export const PLAN_TAIL: PlanShot[] = [
 {
  "id": "4yu6dbf",
  "beat": 192,
  "len": 4,
  "ev": "updates:page",
  "off": -0.1,
  "jp": "困ったら\n「更新情報」と「使い方」",
  "en": "Stuck? See Updates and the Guide",
  "speed": 0.8
 },
 {
  "id": "tail2yqnjh",
  "beat": 196,
  "len": 4,
  "ev": "guide:page",
  "off": -0.1,
  "jp": "困ったら\n「更新情報」と「使い方」",
  "en": "Stuck? See Updates and the Guide",
  "speed": 0.8
 }
];
/** 作った画の場面の頭（拍） */
export const PLAN_BEATS = {
 "intro": 0,
 "newurl": 12,
 "bandwidth": 20,
 "faster": 28,
 "timelapse": 167.5,
 "showcase": 172,
 "end-logo": 180,
 "end-url": 184,
 "end-free": 188,
 "tail": 192,
 "last": 200
} as const;
