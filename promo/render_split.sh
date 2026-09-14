#!/usr/bin/env bash
# 動画を何回かに分けて書き出し、つなぐ。
#
# v2 は録画を 8 本（本編 / feat × 言語）参照するので、通しで書き出すと
# OffthreadVideo がメモリを食い尽くして途中で落ちる（実測で 154〜1883 フレームの間で毎回）。
# フレームの範囲を区切ると 1 回あたりの山が低くなり、間でプロセスが終わるので溜まらない。
#
# 使い方: bash render_split.sh <Composition の id> <出力ファイル> [1 回あたりのフレーム数]
#   例: bash render_split.sh Promo out/v2-tall-ja.mp4 560
set -euo pipefail
cd "$(dirname "$0")"

COMP="${1:?Composition の id（Promo / PromoWide / PromoEn / PromoWideEn）}"
OUT="${2:?出力ファイル}"
CHUNK="${3:-560}"
FF="$PWD/node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe"
# 総フレーム数は timeline.ts の DURATION_FRAMES（拍から出す）。第 4 引数で上書きできる
TOTAL="${4:-$(node -e '
const b = require("./src/beats.json").beats;
const FPS = 30, LAST = 160;                       // LAST_BEAT = bar(41) = 拍 160
const t = LAST < b.length ? b[LAST] : b[b.length-1] + (b[b.length-1]-b[b.length-2])*(LAST-b.length+1);
console.log(Math.round(t*FPS) + 12);
')}"
[ -n "$TOTAL" ] || { echo "総フレーム数が取れません"; exit 1; }

work="$(mktemp -d)"
list="$work/list.txt"
: > "$list"
i=0
start=0
while [ "$start" -lt "$TOTAL" ]; do
  end=$((start + CHUNK - 1))
  [ "$end" -ge "$TOTAL" ] && end=$((TOTAL - 1))
  part="$work/part-$(printf '%03d' "$i").mp4"
  echo "==== $COMP: $start〜$end / $TOTAL ===="
  # 音は入れない（--muted）。分けて書き出した音をつなぐと、AAC の頭に入る無音のぶん
  # 境目で音が途切れて聞こえる。音は最後に一本で付ける
  npx remotion render "$COMP" "$part" --frames="$start-$end" --muted \
    --concurrency=1 --timeout=600000 --offthreadvideo-cache-size-in-bytes=268435456 --log=error
  echo "file '$(cygpath -m "$part" 2>/dev/null || echo "$part")'" >> "$list"
  i=$((i + 1))
  start=$((end + 1))
done

echo "==== つなぐ（$i 本）===="
"$FF" -y -hide_banner -loglevel error -f concat -safe 0 -i "$list" -c copy "$work/video.mp4"

# 音を付ける。Remotion の Audio と同じで、エンドカードの頭からフェードアウトする
DUR="$(node -e "console.log(($TOTAL / 30).toFixed(3))")"
FADE_AT="$(node -e 'const b=require("./src/beats.json").beats; const END=144; console.log((END<b.length?b[END]:b[b.length-1]).toFixed(3));')"
FADE_LEN="$(node -e "console.log(($DUR - $FADE_AT).toFixed(3))")"
echo "     音: 0〜${DUR}s、${FADE_AT}s からフェードアウト"
"$FF" -y -hide_banner -loglevel error -i "$work/video.mp4" -i public/sherbet.mp3 \
  -filter_complex "[1:a]atrim=0:${DUR},asetpts=PTS-STARTPTS,afade=t=out:st=${FADE_AT}:d=${FADE_LEN}[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -movflags +faststart "$OUT"
rm -rf "$work"
ls -la "$OUT"
