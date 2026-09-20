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
