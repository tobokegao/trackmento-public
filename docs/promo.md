# 紹介動画と記事の素材

note の記事用の GIF・写真・表の撮り方。動画そのものの作り方は `video-notes.md`。

（`CLAUDE.md` から分けたもの。2026-09-20。中身は当時のまま）

- **記事用の GIF・写真**（2026-09-16）。`node promo/gif_windows.mjs <出力> [場面|all]` がコマを撮り、
  `scripts/make_gifs.py <出力>` が GIF にする（色 200、縦長は幅を落とす）。写真は `promo/shots.mjs`、
  表の画像は `promo/shoot_tables.mjs`、note に貼る HTML は `scripts/build_note_paste.py`
  - **カーソルは `promo/cursor.js` を `addInitScript` で入れて自前で描く**。システムのカーソルは
    スクリーンショットに写らない（OS が重ねているだけで、ページの絵ではない）。矢印＋押した合図の輪、
    指の画面では丸。**HTML5 のドラッグ中は mousemove が来ない**ので `dragover` からも位置を拾う
  - 撮影に使う `window.__setGridUI` は画面も描き直す版（`__setGrid` は割り付けを測るだけで描かない）
  - **記事をまるごと今の仕様に合わせ直す手順**（2026-09-16 の夜にやった順）:
    1. `gh workflow run render-check.yml` で点検を回し、`gh run view <id> --log` を scratchpad に落とす
    2. `scripts/note_charts.py <ログ…>` … ログの要約から `outputs/note/series.json` に足して 3 枚のグラフを描く
       （matplotlib は venv に入れてあるが `requirements.txt` には入れない。本番には要らない）。
       共有数の日付は UTC の日（09:00 JST で切り替わる）
    3. `node promo/gif_windows.mjs outputs/note/frames all` → `scripts/make_gifs.py outputs/note/frames`（15 本、数分）
    4. `node promo/shots.mjs outputs/note listed`（画面の写真。find は 8001 の別サーバーが要る）
    5. `outputs/note/note-article.md` と `trackmento-story.html` を直す（両方に同じ文がある）
    6. `node promo/shoot_tables.mjs outputs/note/trackmento-story.html outputs/note`（表の画像。story の表から撮る）
    7. `scripts/build_note_paste.py`（note に貼る HTML と、アーティファクト版 `note-paste-artifact.html`）
    8. アーティファクトを 2 つ更新（story: LqMEwkwDwu6jFkk5N3N3ih、貼り付け用: AVDUx4d3UEsUMdUqEJRXSs）

- **X に載せる 1 機能 1 本の短い動画**（2026-09-25）。機能が増えて 1 本の紹介動画に収まらなくなったので、
  細かい機能ごとに数秒の動画を作って小分けに投稿する（利用者の方針。16:9・文字は入れない・MP4 と GIF）
  1. `node promo/x_clips.mjs <出力>/frames [id,id,…|all|pc|phone]` … 台本 `promo/x_catalog.mjs` の場面を撮る
     （1 場面ずつ新しいページで。道具は `promo/clip_kit.mjs`）。手元のサーバー（`PUBLIC_MODE=1`、8000）が要る
  2. `scripts/make_x_clips.py <出力>/frames [id …]` … 1280x720 に組んで `<出力>/x/<id>.mp4` と `.gif`。
     切り取った窓は地の模様の上の真ん中に置く（最大 2 倍）。MP4 は Remotion 同梱の ffmpeg で書く
  - 曲は `promo/stills-tracks.json`（`grids/` は手元の並びで中身が決まっていない）。16:9 のサムネが要る場面は `stills-tracks-nico.json`
  - **撮る範囲は最初の 1 回だけ測る**（`follow: true` の場面だけ毎コマ）。毎コマ測ると範囲が伸び縮みして窓が跳ねる
  - **1280 幅では 3×3 のマスが「小さい扱い」**（96px 未満）で × と曲名の帯が出ない。× を押す場面は 2×2 にする
  - **Playwright の `mouse.wheel` は Ctrl を押していても ctrlKey が付かない**。拡大の場面は `ctrlWheel`（ページの中で WheelEvent を送る）
  - 候補の元ネタ（細かい機能 104 件の棚卸し）は台帳にまとめる予定
