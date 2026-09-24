// X に載せる短い動画を書き出す（Remotion の XClip。素材は x_clips.mjs が撮った public/xclips/<id>/）。
//   node render_x.mjs [id,id,…|all] [--gif]
// 出力は out/x/<id>.mp4（1280x720、30 コマ/秒、音なし）。--gif を付けると 10 コマ/秒の GIF も書く（note など MP4 を貼れない所向け）。
// 束ね（bundle）は 1 回だけ作り、1 本ずつ render を呼ぶ（render_cached.mjs と同じ）。
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";

const args = process.argv.slice(2);
const gif = args.includes("--gif");
const only = args.find((a) => !a.startsWith("--")) ?? "all";
const have = fs.readdirSync("public/xclips").filter((d) => fs.existsSync(`public/xclips/${d}/events.json`));
const ids = only === "all" ? have : only.split(",");
const missing = ids.filter((i) => !have.includes(i));
if (missing.length) { console.error("素材が無い（先に x_clips.mjs で撮る）:", missing.join(" ")); process.exit(1); }

fs.mkdirSync("out/x", { recursive: true });
const bundle = fs.mkdtempSync(path.join(os.tmpdir(), "xclip-"));
execFileSync("npx", ["remotion", "bundle", "src/index.ts", "--out-dir", bundle, "--log=error"], { stdio: "inherit", shell: true });
const props = (id) => JSON.stringify(JSON.stringify({ id }));   // シェルを通すので二重に包む
for (const id of ids) {
  const t0 = Date.now();
  execFileSync("npx", ["remotion", "render", bundle, "XClip", `out/x/${id}.mp4`, `--props=${props(id)}`,
    "--codec=h264", "--crf=18", "--log=error"], { stdio: "inherit", shell: true });
  if (gif) {
    execFileSync("npx", ["remotion", "render", bundle, "XClip", `out/x/${id}.gif`, `--props=${props(id)}`,
      "--codec=gif", "--every-nth-frame=3", "--log=error"], { stdio: "inherit", shell: true });
  }
  const kb = (f) => (fs.statSync(f).size / 1024).toFixed(0) + " KB";
  console.log(`${id}  mp4 ${kb(`out/x/${id}.mp4`)}${gif ? `  gif ${kb(`out/x/${id}.gif`)}` : ""}  ${((Date.now() - t0) / 1000).toFixed(0)} 秒`);
}
fs.rmSync(bundle, { recursive: true, force: true });
