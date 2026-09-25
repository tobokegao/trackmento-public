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
  細かい機能ごとに数秒の動画を作って小分けに投稿する（利用者の方針。16:9・文字は入れない・MP4、要れば GIF）。
  **画面は本物を撮り、演出（カメラ・カーソル・押した合図・繰り返しのつなぎ）は Remotion で足す**（同日、利用者と決めた中間案。
  画面ごと Remotion で作り直す案は、サイトの 3 つ目の実装になってすぐずれるのでやめた）
  1. `node promo/x_clips.mjs [id,id,…|all]` … 台本 `promo/x_catalog.mjs` の場面を撮る（道具は `promo/clip_kit.mjs`）。
     本編の `capture.mjs` と同じく**ページの時計を止めて 30 コマ/秒**で画面ぜんぶ（1280x720、倍率 2）を撮り、
     `promo/public/xclips/<id>/take.mp4` と `events.json`（カメラの行き先・カーソル・押した印）を書く。手元のサーバー（`PUBLIC_MODE=1`、8000）が要る
  2. `cd promo && node render_x.mjs [id,…|all] [--gif]` … Remotion の `XClip`（`src/XClip.tsx`）で `promo/out/x/<id>.mp4`。1 本 20 秒ほど
  - カメラは `k.look([セレクタ…])` の四角に寄る（16:9 に広げ、2 倍まで）。カーソルと輪は Remotion が描く（ページには描かない）
  - 終わりの 0.5 秒で最初の絵を溶かし込む（X の繰り返し再生のつなぎ目を消す）
  - **押したキーは画面の下にキーの絵で出す**（`k.key`。キーボードの操作は画面に跡が残らず、ひとりでに動いたように見える。利用者の指摘）
  - **曲はすべて架空**（ジャケットも題もアーティスト名も。2026-09-25、利用者の指定「動画に実在のジャケットを映さない」）。
    `promo/fake_covers.py` が図形と色だけで正方形 24 枚・16:9 を 12 枚描き、手元の `uploads/fa4e….jpg`（git の外）に置いて、
    一覧を `promo/public/fake-tracks.json` / `fake-tracks-wide.json` に書く。`x_clips.mjs` は一覧が無ければ先にこれを回す。
    **本番の R2 には上げない**（手元のサーバーは R2 に無いアップロード画像を手元の `uploads/` から読む）。色で並べ替えが映えるよう色相を散らし、白黒も 3 枚
  - 画面の欄の見本の文（検索欄の「例: 感電」「e.g. Never Gonna Give You Up」など）はサイトそのものの文なので、そのまま映る
  - **押したあとにボタンがずれたら矢印もついて行く**（`press`）。色で並べ替えは押すと上の 3 行の説明が 1 行に替わり、ボタンが上がる
  - **1280 幅では 3×3 のマスが「小さい扱い」**（96px 未満）で × と曲名の帯が出ない。× を押す場面は 2×2 にする
  - **Playwright の `mouse.wheel` は Ctrl を押していても ctrlKey が付かない**。拡大の場面は `ctrlWheel`（ページの中で WheelEvent を送る）
  - Remotion 同梱の ffmpeg には fps・select などのフィルタが無い。GIF は Remotion の `--codec=gif`（`remotion.config.ts` は GIF のとき CRF を渡さない）
  - **窓は `k.arrange({ セレクタ: { x, y, w, h?, only? } })` で好きな位置に並べる**（2026-09-25）。書いた窓だけを画面に固定して置き、ほかは隠す。
    `only` はその窓の中身のうち残すもの（背景色の欄だけ、など）。台本に書いたほかの窓は `only` でも消さない（「できあがり」はグリッドの窓の中にある）。
    背景色の場面は `ARRANGE_BG`（左にグリッド、真ん中に背景色の欄、右に「できあがり」）。サイトの「窓を動かす」とは別（撮影のときだけ）
  - **`bg-image` の見本の画像は `promo/public/x-bg-logo.png`**（git の外。2026-09-25、利用者の指定「もう少しイラスト調に。Tobokegao のロゴを」）。
    ロゴの画像（正方形。上がトボケガオの文字、下が顔）から文字の部分だけを切り出し、幅 360px にして 16:9 の白地に互い違いに敷き詰めたもの。
    真ん中に 1 つ大きく置くと、ほとんどがマスの裏に隠れて見えなかった。元の画像は利用者が貼ったもの（E ドライブの gainen フォルダにある。この PC からは見えないことがある）
  - `promo/public/x-bg-sample.jpg`（メッシュグラデーション）は今は使っていない。グラデーション背景の機能を作るときの見本として残す。
    グラデーションは利用者が挙げた作例（After Effects の作例 4 件）から 3 つの決まりで作る: ① **色は OKLab で混ぜ、鮮やかさを別に平均して保つ**
    （sRGB のまま混ぜると境目が濁る） ② **色相の近い色で組み、離れた色を隣に置くなら中間色を挟む**（オレンジと青を隣に置いたら境目に筋が出た）
    ③ **座標をフラクタルノイズ（粗い〜細かい 4 段）でゆらす**（タービュレントディスプレイスと同じ考え。直線的な移り変わりが水彩や雲のようなむらになる）。
    仕上げに細かい粒を足して JPEG の縞を消す。穏やかな画像なので濃さが 5 割になり、見本でも見える
  - **撮影で上げた画像は本番の R2 に残る**（手元のサーバーも .env の R2 を使う）。`x_clips.mjs` が `/upload` の返事を `public/xclips/<id>/uploads.json` に記録するので、
    撮ったら `PYTHONUTF8=1 .venv/Scripts/python scripts/clean_x_uploads.py` で消す（記録した分だけ。利用者の画像には触れない）
  - 2026-09-25 の撮り直しで 11 本（前の 8 本＋ `undo-buttons` / `bg-modes` / `bg-image`）
  - `color-sort` は白黒の架空のジャケット（明るさを段階的に）で撮る（カラフルな絵だと色相の順が伝わりにくい、と利用者。白黒は明るい順にそろう）。
    `bg-image` は「できあがりを見る」を押して見本の窓に寄る（グリッドの見本はマスの隙間にしか画像が見えない）
  - 候補の元ネタ（細かい機能 104 件の棚卸し）は台帳にまとめる予定
