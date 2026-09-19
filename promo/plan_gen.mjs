// 譜割りエディタ（https://claude.ai/artifact/KNEULMAUpPGXSYdrCmWC1Q）の中身から、動画の台本 src/plan.gen.ts を作る（2026-09-20）。
//
// なぜ: 場面の開始・長さ・字幕・録画の印を timeline.ts に手で書き写していた。写し間違いや、エディタと動画の食い違いが
// 起きうる（xxxbaaa さんの「AI に推測させない。決まった下書きから作る」）。**数字はエディタにだけ置き、ここで機械的に写す**。
// ズーム・枠・静止画のような見せ方の細かい値は timeline.ts の SHOT_EXTRAS（エディタの場面の ID ごと）に置く。
//
// 使い方: エディタの中身を promo/plan.json に保存してから（Claude がエディタの DB から読む。エディタの「JSON」ボタンでも可）
//   node plan_gen.mjs            # src/plan.gen.ts を書く
//   node plan_gen.mjs --check    # 書かずに、今の plan.gen.ts と食い違うかだけ見る（食い違えば終了コード 1）
import fs from "node:fs";

const SRC = "plan.json", OUT = "src/plan.gen.ts";
const doc = JSON.parse(fs.readFileSync(SRC, "utf8"));
const lane = doc.lanes.find((l) => l.name === "場面");
if (!lane) throw new Error("エディタに「場面」のレーンが無い");
const items = [...lane.items].sort((a, b) => a.t - b.t);
const errs = [];
const num = (v, d) => (v === undefined || v === null || v === "" ? d : Number(v));
const beat = (t) => t / 2;   // エディタの t は 8 分音符、動画の拍は 4 分音符

const shot = (it) => {
  if (!it.ev) errs.push(`「${it.label}」: 録画の印（ev）が空`);
  if (!it.jp) errs.push(`「${it.label}」: 字幕（日本語）が空`);
  const s = { id: it.id, beat: beat(it.t), len: beat(it.len), ev: it.ev || "", off: num(it.off, 0), jp: it.jp || "", en: it.en || it.jp || "" };
  const sp = num(it.speed, undefined); if (sp !== undefined && sp !== 1) s.speed = sp;
  if (!Number.isFinite(s.off) || (s.speed !== undefined && !(s.speed > 0))) errs.push(`「${it.label}」: ずらし・速さが数でない`);
  return s;
};
const SHOTS = items.filter((i) => i.kind === "rec").map(shot);
const TAIL = items.filter((i) => i.kind === "tail").map(shot);
const BEATS = {};
for (const it of items) {
  if (!it.kind || it.kind === "rec" || it.kind === "tail") continue;
  if (BEATS[it.kind] !== undefined) errs.push(`種類「${it.kind}」の場面が 2 つある`);
  BEATS[it.kind] = beat(it.t);
}
for (const k of ["intro", "newurl", "bandwidth", "faster", "timelapse", "showcase", "end-logo", "end-url", "end-free"]) if (BEATS[k] === undefined) errs.push(`種類「${k}」の場面が無い`);
const last = Math.max(...items.filter((i) => i.kind).map((i) => beat(i.t + i.len)));
const tailBeat = TAIL.length ? Math.min(...TAIL.map((s) => s.beat)) : last;
if (errs.length) { console.log("エディタの台本に足りないものがある:\n  " + errs.join("\n  ")); process.exit(1); }

const body = `// **自動生成（promo/plan_gen.mjs）。手で直さない**。直すのは譜割りエディタの「場面」レーンの「動画の台本」。
// エディタの版: rev ${doc.rev ?? "?"}（${doc.updatedAt ? new Date(doc.updatedAt).toISOString() : "?"}）
// 拍は 4 分音符・0 始まり（小節 n の頭 = (n - 1) * 4）。len も拍。off は印からの秒、speed は倍率
export type PlanShot = { id: string; beat: number; len: number; ev: string; off: number; jp: string; en: string; speed?: number };
export const PLAN_SHOTS: PlanShot[] = ${JSON.stringify(SHOTS, null, 1)};
export const PLAN_TAIL: PlanShot[] = ${JSON.stringify(TAIL, null, 1)};
/** 作った画の場面の頭（拍） */
export const PLAN_BEATS = ${JSON.stringify({ ...BEATS, tail: tailBeat, last }, null, 1)} as const;
`;
if (process.argv.includes("--check")) {
  const now = fs.existsSync(OUT) ? fs.readFileSync(OUT, "utf8") : "";
  const strip = (s) => s.replace(/^\/\/ エディタの版:.*$/m, "");
  if (strip(now) === strip(body)) { console.log("plan.gen.ts はエディタと同じ"); process.exit(0); }
  console.log("plan.gen.ts がエディタと食い違う（node plan_gen.mjs で書き直す）"); process.exit(1);
}
fs.writeFileSync(OUT, body);
console.log(`${OUT}: 録画のショット ${SHOTS.length}・エンドカードのあと ${TAIL.length}・作った画 ${Object.keys(BEATS).length}（${last / 4} 小節まで）`);
