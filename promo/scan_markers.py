# 使い方: PYTHONUTF8=1 python scan_markers.py public/recordings/session.mp4 public/recordings/events.json <ffmpeg.exe の絶対パス>
# 依存: numpy, pillow（.venv には入れず別環境で可）
# 動画右下のマーカー色を全フレーム読み、events.json の各操作に動画時刻 v を付ける
import json, subprocess, sys, os, glob, numpy as np
from PIL import Image
mp4, ev_path, ffmpeg = sys.argv[1], sys.argv[2], sys.argv[3]
d = os.path.join(os.environ["TMP"], "mk"); os.makedirs(d, exist_ok=True)
for f in glob.glob(os.path.join(d, "*.png")): os.remove(f)
r = subprocess.run([ffmpeg, "-y", "-v", "error", "-i", mp4, "-vf", sys.argv[4] if len(sys.argv) > 4 else "crop=20:20:1056:1896", os.path.join(d, "%05d.png")], capture_output=True)
if r.returncode: print(r.stderr.decode(errors="replace")); sys.exit(1)
files = sorted(glob.glob(os.path.join(d, "*.png")))
fps = 25.0
idx = []
for f in files:
    m = np.asarray(Image.open(f).convert("RGB")).astype(float).mean(axis=(0, 1))
    q = np.rint(m / 51).astype(int).clip(0, 5)
    idx.append(int(q[0] + 6 * q[1] + 36 * q[2]))
events = json.load(open(ev_path, encoding="utf-8"))
first = {}
for f, i in enumerate(idx):
    if i not in first: first[i] = f
for i, e in enumerate(events):
    if i in first: e["v"] = round(first[i] / fps, 3)
json.dump(events, open(ev_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("frames", len(idx), "matched", sum("v" in e for e in events), "/", len(events))
for e in events: print(f'{e["t"]:7.2f} -> {e.get("v", "?"):>7} {e["name"]}')
