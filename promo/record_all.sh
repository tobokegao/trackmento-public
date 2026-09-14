#!/usr/bin/env bash
# 紹介動画の録画を 8 本すべて撮り、mp4 に変換して、マーカー時刻（events.json の v）を付ける。
#
# 8 本 = MODE（スマホ / pc）× SCENE（本編 / feat）× LANG_UI（日本語 / en）。
# 本編は 9 マスを埋めて共有まで、feat は新機能だけ（プレイリストで 500 曲入れるので本編とは同じセッションで撮れない）。
#
# 前提:
#   - ローカルの uvicorn が 8000 番で動いていること。**共有の 1 日上限を外して立てる**
#     （本番の共有数を復元するので、外さないと share で止まる）:
#       PUBLIC_MODE=1 DISCOGS_TOKEN= SHARE_BUDGET_GB=0 SHARE_LIMIT_PER_DAY=0 SHARE_LIMIT_PER_IP_DAY=0 \
#         PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
#   - uploads/ に手入力用の 2 枚があること
#   - **DISCOGS_TOKEN= を付けて立てる**。手元には .env にトークンがあるので検索ソースが 4 つ出るが、
#     本番はトークンを置いていないので 3 つ（iTunes / MusicBrainz / otoDB）。画面を本番と揃える
#   - SCAN_PY に numpy と pillow の入った python を渡すこと（.venv には numpy が無いので別環境）
#
# 使い方:
#   SCAN_PY=/path/to/python bash record_all.sh            # 8 本すべて
#   SCAN_PY=/path/to/python ONLY=feat bash record_all.sh  # feat の 4 本だけ
set -euo pipefail

cd "$(dirname "$0")"
FF="$PWD/node_modules/@remotion/compositor-win32-x64-msvc/ffmpeg.exe"
# scan_markers.py は Python の subprocess で ffmpeg を起動するので、Windows が解釈できる形で渡す
FF_WIN="$(cygpath -m "$FF" 2>/dev/null || echo "$FF")"
SCAN_PY="${SCAN_PY:?numpy と pillow の入った python のパスを SCAN_PY に渡してください}"
ONLY="${ONLY:-all}"

for MODE_V in "" pc; do
  for SCENE_V in "" feat; do
    for LANG_V in "" en; do
      [ "$ONLY" = feat ] && [ -z "$SCENE_V" ] && continue
      [ "$ONLY" = main ] && [ -n "$SCENE_V" ] && continue
      dir="public/recordings${MODE_V:+-pc}${SCENE_V:+-feat}${LANG_V:+-en}"
      echo "==== $dir を撮る（MODE='$MODE_V' SCENE='$SCENE_V' LANG_UI='$LANG_V'）===="
      MODE="$MODE_V" SCENE="$SCENE_V" LANG_UI="$LANG_V" node record.mjs

      "$FF" -y -hide_banner -loglevel error -i "$dir/session.webm" \
        -c:v libx264 -crf 18 -preset fast -pix_fmt yuv420p -r 25 "$dir/session.mp4"

      # マーカーは画面の右下。実ピクセルは DPR で変わる（スマホ 2 倍 / PC 1.5 倍）ので切り出す位置も変える
      if [ "$MODE_V" = pc ]; then crop="crop=20:20:1896:1056"; else crop="crop=20:20:1056:1896"; fi
      # 直接 head に渡すと、head が先に終わったところで SIGPIPE になり pipefail で止まる。
      # いったん受け取ってから表示する
      scan_out="$(PYTHONUTF8=1 "$SCAN_PY" scan_markers.py "$dir/session.mp4" "$dir/events.json" "$FF_WIN" "$crop")"
      echo "$scan_out" | head -3

      # MusicBrainz はブラウザから直接叩くので、続けて撮るとレート制限に当たる。1 本ごとに間を置く
      sleep 20
    done
  done
done
echo "==== 全部おわり ===="
