// 動画を**区切りごとに**書き出し、中身が変わった区切りだけ描き直してつなぐ（2026-09-20、render_split.sh の置き換え）。
//
// 区切りは 2 小節ずつ。区切りの指紋は「その区切りにかかるショットの設定（前後 1 小節ぶんも含む）」
// 「そのショットが使う録画の場面（capture.mjs の take）の指紋」「使う静止画」と、全体にかかるもの
// （Scenes.tsx・フォント・曲・timeline.ts のショット以外の値）から作る。指紋が前回と同じ区切りは控えをそのまま使う。
// 1 か所を直したときに全部を描き直さない（xxxbaaa さんの「本当の費用は 1 か所の直しで何回作り直すか」）。
//
// 使い方: node render_cached.mjs <Composition の id> <出力ファイル> [--force] [--dry]
//   例: node render_cached.mjs Promo out/v9-tall-ja.mp4
//   --dry は描かずに、描き直す区切りだけ示す
//   --only 17-18 は、その小節にかかる区切りだけ描き直し、ほかは前の控えをそのまま使う。
//     Scenes.tsx のように全体にかかるファイルを直すと、どの区切りに効くかは機械では分からないので全部描き直しになる。
//     直したのが一部の場面だけだと分かっているときに使う（外れていると、ほかの区切りが古い絵のまま残る）
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import os from "node:os";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { buildSync } from "esbuild";

const [COMP, OUTFILE] = process.argv.slice(2).filter((a, i, all) => !a.startsWith("--") && all[i - 1] !== "--only");
if (!COMP || !OUTFILE) { console.log("使い方: node render_cached.mjs <Promo|PromoWide|PromoEn|PromoWideEn> <出力.mp4> [--force] [--dry]"); process.exit(1); }
const FORCE = process.argv.includes("--force"), DRY = process.argv.includes("--dry");
const ONLY = (() => { const i = process.argv.indexOf("--only"); if (i < 0) return null; const [a, b] = process.argv[i + 1].split("-").map(Number); return [a, b ?? a]; })();
const ROOT = path.resolve(".");
const FF = path.resolve("node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe");
const KIND = COMP.includes("Wide") ? "wide" : "tall", LANG = COMP.endsWith("En") ? "en" : "ja";
const CACHE = path.resolve(`out/chunks/${COMP}`);
fs.mkdirSync(CACHE, { recursive: true });
const BARS_PER_CHUNK = 2;

const sha = (s) => crypto.createHash("sha1").update(s).digest("hex").slice(0, 16);
const fileKey = (f) => { try { return sha(fs.readFileSync(f)); } catch { return "missing"; } };

// ---- timeline.ts をそのまま読む（esbuild で 1 本の JS にして import する）
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "tl-"));
const tlJs = path.join(tmp, "timeline.mjs");
buildSync({ entryPoints: ["src/timeline.ts"], bundle: true, format: "esm", platform: "node", outfile: tlJs, loader: { ".json": "json" }, logLevel: "error" });
const T = await import(pathToFileURL(tlJs).href);
const { SHOTS, TAIL_SHOTS, RECORDINGS, beatFrame, beatTime, DURATION_FRAMES, BAR, FPS } = T;

// ---- 全体にかかるもの
const walk = (d) => fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }).flatMap((e) => e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]) : [];
const globalParts = [
  COMP,
  ...["src/Scenes.tsx", "src/Root.tsx", "src/index.ts", "src/beats.json", "remotion.config.ts", "package-lock.json",
    "public/sherbet.mp3", "public/final.png", "public/final-pc.png", "public/v1-look.png", "public/v1-look-pc.png"].map(fileKey),
  ...walk("public/fonts").sort().map(fileKey),
  // timeline.ts の、ショットと録画以外の値（小節の割り付け・作った画の数字など）
  JSON.stringify(Object.entries(T).filter(([k, v]) => !["SHOTS", "TAIL_SHOTS", "RECORDINGS"].includes(k) && typeof v !== "function").sort()),
];
const G = sha(globalParts.join("|"));

// ---- 録画の場面の範囲（capture.mjs の events.json は、印ごとに take と takeKey を持つ）
function takesOf(session) {
  const ev = RECORDINGS[KIND][LANG][session].events;
  const starts = ev.filter((e) => e.name.startsWith("take:")).map((e) => ({ name: e.take, key: e.takeKey, t: e.v ?? e.t }));
  return starts.map((s, i) => ({ ...s, end: i + 1 < starts.length ? starts[i + 1].t : Infinity }));
}
const TAKES = { main: takesOf("main"), feat: takesOf("feat") };
const oldStyle = !TAKES.main.length || !TAKES.feat.length;   // capture.mjs より前の録画（場面の区切りが無い）
const sessionKey = (s) => fileKey(path.join("public", RECORDINGS[KIND][LANG][s].src));
/** 録画の [a, b] 秒にかかる場面の指紋 */
function recKey(session, a, b) {
  if (oldStyle) return sessionKey(session);
  return TAKES[session].filter((t) => t.end > a - 0.5 && t.t < b + 0.5).map((t) => t.key).join(",");
}
function shotKey(s) {
  const session = s.rec ?? "main";
  const ev = RECORDINGS[KIND][LANG][session].events.find((x) => x.name === s.ev);
  const at = ev ? (ev.v ?? ev.t) : 0;
  const dur = (beatTime(s.beat + s.len) - beatTime(s.beat)) * (s.speed ?? 1);
  const parts = [JSON.stringify(s), s.stills ? "" : recKey(session, at + s.off - 1, at + s.off + dur + 1)];
  for (const n of s.stills || []) parts.push(fileKey(`public/stills/${n}${KIND === "tall" ? "" : "-pc"}.png`));
  return sha(parts.join("|"));
}
const ALL = [...SHOTS, ...TAIL_SHOTS];

// ---- 区切り
const lastBeat = ALL.reduce((m, s) => Math.max(m, s.beat + s.len), 0);
const chunks = [];
for (let b = 0; ; b += BAR * BARS_PER_CHUNK) {
  const f0 = b === 0 ? 0 : beatFrame(b), f1 = Math.min(DURATION_FRAMES, beatFrame(b + BAR * BARS_PER_CHUNK)) - 1;
  if (f0 > DURATION_FRAMES - 1) break;
  const lo = b - BAR, hi = b + BAR * (BARS_PER_CHUNK + 1);   // 前後 1 小節ぶんのショットも数える（場面の入れ替わりの演出）
  const parts = [G, `${f0}-${f1}`, ...ALL.filter((s) => s.beat < hi && s.beat + s.len > lo).map(shotKey)];
  // タイムラプス（本編の録画を頭から終わりまで早回し）と、できあがりの静止画は本編の録画全体にかかる
  if (b + BAR * BARS_PER_CHUNK > T.TIMELAPSE_BEAT - BAR && b < T.SHOWCASE_BEAT + BAR) parts.push(oldStyle ? sessionKey("main") : TAKES.main.map((t) => t.key).join(","));
  chunks.push({ i: chunks.length, beat: b, f0, f1, key: sha(parts.join("|")) });
  if (f1 >= DURATION_FRAMES - 1) break;
}
const fileOf = (c) => path.join(CACHE, `${String(c.i).padStart(3, "0")}-${c.key}.mp4`);
const prevOf = (c) => fs.readdirSync(CACHE).find((f) => f.startsWith(`${String(c.i).padStart(3, "0")}-`));
let dirty = chunks.filter((c) => FORCE || !fs.existsSync(fileOf(c)));
if (ONLY) {
  // 指定の小節にかかる区切りだけ描く。ほかは前の控えを今の指紋の名前に付け替えて使う
  const inRange = (c) => c.beat / BAR + 1 <= ONLY[1] && c.beat / BAR + BARS_PER_CHUNK >= ONLY[0];
  const keep = dirty.filter((c) => !inRange(c) && prevOf(c));
  if (!DRY) for (const c of keep) fs.renameSync(path.join(CACHE, prevOf(c)), fileOf(c));
  dirty = chunks.filter((c) => inRange(c) || (!fs.existsSync(fileOf(c)) && !keep.includes(c)));
  console.log(`--only ${ONLY[0]}-${ONLY[1]}: 前の控えを使う区切り ${keep.length} 個`);
}
console.log(`${COMP}: 区切り ${chunks.length} 個（${BARS_PER_CHUNK} 小節ずつ）、描き直すのは ${dirty.length} 個${oldStyle ? "（録画は古い形式: 録画が変わると全部描き直し）" : ""}`);
for (const c of dirty) console.log(`  ${String(c.i).padStart(2)}: ${c.beat / BAR + 1} 小節〜  フレーム ${c.f0}〜${c.f1}`);
if (DRY) process.exit(0);

// ---- 描く。束ね（bundle）は 1 回だけ作って使い回す
if (dirty.length) {
  const bundle = path.join(tmp, "bundle");
  console.log("==== 束ねる ====");
  execFileSync("npx", ["remotion", "bundle", "src/index.ts", "--out-dir", bundle, "--log=error"], { stdio: "inherit", shell: true });
  for (const c of dirty) {
    console.log(`==== ${c.i}: ${c.f0}〜${c.f1} ====`);
    const part = path.join(tmp, `part-${c.i}.mp4`);
    execFileSync("npx", ["remotion", "render", bundle, COMP, part, `--frames=${c.f0}-${c.f1}`, "--muted",
      "--concurrency=1", "--timeout=600000", "--offthreadvideo-cache-size-in-bytes=268435456", "--log=error"], { stdio: "inherit", shell: true });
    for (const f of fs.readdirSync(CACHE)) if (f.startsWith(`${String(c.i).padStart(3, "0")}-`)) fs.rmSync(path.join(CACHE, f));
    fs.renameSync(part, fileOf(c));
  }
}

// ---- 音（全体にかかるものだけで決まる）
const audio = path.join(CACHE, `audio-${G}.wav`);
if (!fs.existsSync(audio)) {
  console.log("==== 音を書き出す ====");
  for (const f of fs.readdirSync(CACHE)) if (f.startsWith("audio-")) fs.rmSync(path.join(CACHE, f));
  execFileSync("npx", ["remotion", "render", COMP, audio, "--codec=wav", "--log=error"], { stdio: "inherit", shell: true });
}

// ---- つなぐ
const list = path.join(tmp, "list.txt");
fs.writeFileSync(list, chunks.map((c) => `file '${fileOf(c).replace(/\\/g, "/")}'`).join("\n"));
const video = path.join(tmp, "video.mp4");
execFileSync(FF, ["-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list, "-c", "copy", video]);
fs.mkdirSync(path.dirname(path.resolve(OUTFILE)), { recursive: true });
execFileSync(FF, ["-y", "-hide_banner", "-loglevel", "error", "-i", video, "-i", audio, "-map", "0:v", "-map", "1:a",
  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", path.resolve(OUTFILE)]);
fs.rmSync(tmp, { recursive: true, force: true });
console.log(`done ${OUTFILE}（描き直し ${dirty.length} / ${chunks.length}）`);
