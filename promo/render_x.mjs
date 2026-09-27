// X に載せる短い動画を書き出す（Remotion の XClip。素材は x_clips.mjs が撮った public/xclips/<id>/）。
//   node render_x.mjs [id,id,…|all] [--gif] [--tall]
// 出力は out/x/<id>.mp4（1280x720、30 コマ/秒、音なし）。--gif を付けると 10 コマ/秒の GIF も書く（note など MP4 を貼れない所向け）。
// --tall は縦 9:16（Instagram のリール・TikTok 向け。XClipTall、1080x1920）で out/tall/<id>.mp4。
// 頭の見出しは public/xclips-titles.json（先に `python x_titles.py`。無ければここで作る）。
// 束ね（bundle）は 1 回だけ作り、1 本ずつ render を呼ぶ（render_cached.mjs と同じ）。
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const args = process.argv.slice(2);
const gif = args.includes("--gif");
const tall = args.includes("--tall");
const comp = tall ? "XClipTall" : "XClip", dir = tall ? "out/tall" : "out/x";
if (tall && !fs.existsSync("public/xclips-titles.json")) {
  execFileSync(process.platform === "win32" ? "../.venv/Scripts/python" : "../.venv/bin/python", ["x_titles.py"], { stdio: "inherit", env: { ...process.env, PYTHONUTF8: "1" } });
}
const only = args.find((a) => !a.startsWith("--")) ?? "all";
const have = fs.readdirSync("public/xclips").filter((d) => fs.existsSync(`public/xclips/${d}/events.json`));
const ids = only === "all" ? have : only.split(",");
const missing = ids.filter((i) => !have.includes(i));
if (missing.length) { console.error("素材が無い（先に x_clips.mjs で撮る）:", missing.join(" ")); process.exit(1); }

fs.mkdirSync(dir, { recursive: true });
const bundle = fs.mkdtempSync(path.join(os.tmpdir(), "xclip-"));
execFileSync("npx", ["remotion", "bundle", "src/index.ts", "--out-dir", bundle, "--log=error"], { stdio: "inherit", shell: true });
const props = (id) => JSON.stringify(JSON.stringify({ id }));   // シェルを通すので二重に包む
for (const id of ids) {
  const t0 = Date.now();
  execFileSync("npx", ["remotion", "render", bundle, comp, `${dir}/${id}.mp4`, `--props=${props(id)}`,
    "--codec=h264", "--crf=18", "--log=error"], { stdio: "inherit", shell: true });
  if (gif) {
    execFileSync("npx", ["remotion", "render", bundle, comp, `${dir}/${id}.gif`, `--props=${props(id)}`,
      "--codec=gif", "--every-nth-frame=3", "--log=error"], { stdio: "inherit", shell: true });
  }
  const kb = (f) => (fs.statSync(f).size / 1024).toFixed(0) + " KB";
  console.log(`${id}  mp4 ${kb(`${dir}/${id}.mp4`)}${gif ? `  gif ${kb(`${dir}/${id}.gif`)}` : ""}  ${((Date.now() - t0) / 1000).toFixed(0)} 秒`);
}
fs.rmSync(bundle, { recursive: true, force: true });
