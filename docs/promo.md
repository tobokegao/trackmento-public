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
  - **2026-09-26 に 11 本とも今の画面で撮り直した**（出力オプションのグループボックス・三角・呼び名が変わったため）。台本の直し: 「マス枠」「サムネ余白」は既定で畳んだ「枠とサムネ」の三角の中なので撮る前に開く（`openCellsMore`）、`bg-image` は「画像」を選ぶとまず既定の模様が敷かれ選ぶ窓は開かないので、続けて「画像を選ぶ…」を押す、**`k.arrange` の `only` は `.pane-body` の直の子にしか効かない**ので、出力オプションはグループボックス（`.gbox:has(…)`）を指し、中のほかの欄は `ARRANGE_BG_CSS` で隠す
- **サイトの「使い方の動画」（`/howto`）に同じ動画を載せる**（2026-09-26、利用者の依頼。名前は利用者と決めた。案内のリンクも同じ名前。編集画面の下のリンクには、はじめ sp-view の撮り直しを避けて足さなかったが、2026-09-27 に利用者の判断で足し、sp-view を撮り直した）。問いと答え（日英）は `backend/howto.py` の
  `SECTIONS`（答えは台本の `what` を使い方のページの口調に直したもの）。66 本。p-os9・p-logo・p-counts（見た目の紹介）と lang・zoom-wheel（ほかの問いと重なる）は載せない
  - **GIF にしない**。同じ動画で GIF は MP4 の約 4 倍（`color-sort`: 9.8MB 対 2.3MB）
  - **題（`<details>` の summary）を押したときだけ読む**。`<video preload="none">` で、開くとページの数行の JS が `play()`（muted なのでスマホでも流れる）。
    閉じたままの問いは 1 バイトも読まない（手元で確かめた）。CSP に `media-src 'self' <R2>` を足した
  - 動画は R2 の `howto/<id>.<ハッシュ>.mp4` から配る（Render の転送量を使わない）。**撮り直したら `render_x.mjs` のあと
    `PYTHONUTF8=1 .venv/Scripts/python scripts/upload_howto_r2.py` を回し、書き換わった `backend/howto_videos.json` をコミット**する。
    表に無い id の問いはページに出ない。`howto/` は `r2_prune.py` の `KEEP_PREFIXES`。古いキーは `--prune` で消す
  - 新しく撮った動画を載せるときは `SECTIONS` に 1 問足してから上げる
  - **ページを知らせる動画 `howto-intro`**（2026-09-27、利用者の依頼。`promo/x_catalog_intro.mjs`）。/howto の頭から「スマホで使う」まで送り、「YouTube のアプリから直接送れますか？」を押して、答えと動画に寄る。**ページの `<video>` はコマ送りで撮る**（`k.setOnFrame` で毎コマ止めて1/30 秒ずつ `currentTime` を進め、`seeked` を待ってから撮る。止めた時計のままだと動画だけ実時間で流れ、コマ撮りでは早回しになる）。操作の帯（controls）は撮るあいだだけ外す。動画は R2 のもの（手元のサーバーでも `howto_videos.json` の R2 の URL を読む）。`howto.ids()` に無いので /howto には上がらない
  - 撮影の途中でブラウザが落ちる（`Target crashed`）と、あとの場面が全部失敗する。落ちた場面から名指しで撮り直せばよい
  - **グリッドに寄る場面も窓を並べ直す**（2026-09-26、利用者の指摘）。そのままだと 16:9 に広げた端にほかの窓が半分映って字が切れ、`stash` は横 × 縦の欄とグリッドが離れていてカメラが引きすぎた。`ARRANGE_GRID`（グリッドの窓だけ真ん中）と `ARRANGE_STASH`（グリッドと横 × 縦の欄だけ）で置き、**カメラの範囲に窓のタイトルバー（`GT` / `OT`）も入れる**（入れないと上で切れる）
  - **2026-09-26 から台本を段ごとのファイルに分けた**。1 段目「はじめて使う流れ」は `promo/x_catalog_flow.mjs`（`x_clips.mjs` が `x_catalog.mjs` と合わせて読む）。
    段取り（137 件を 71 本にまとめたもの）は題材の台帳の「撮影の段取り」。方針は初めて見る人向け・スマホは 16:9 の中（メモリ `x-clips-direction`）
  - **検索・URL・プレイリストの応答は `k.mock` で架空の曲に差し替える**（実在のジャケットを映さない。本物の相手にも問い合わせない）。
    iTunes はブラウザから直接引くので iTunes の返事の形に直して返す。**絵の URL は `/uploads/…` の相対のまま**渡す（絶対 URL だと画面が `/image-proxy` に回し、手元の宛先なのでサーバーが断る）
  - 空のグリッドから始めるときは `seed(0)` を使わない（空の配列は「見本で埋める」扱い）。`x_catalog_flow.mjs` の `empty` で空きマスを null で渡す
  - **共有を押す場面は手元のサーバーを `SHARE_BUDGET_GB=120` で起動する**（本番と同じ。既定の 9.5 だと R2 がもう 29GB あるので 507 で断られる）。
    共有 URL の欄に `127.0.0.1:8000` が映らないよう、`f-share` は返事の URL だけ `https://trackmento.com` に替え、共有ページは手元のサーバーで開く
  - **撮影が途中で失敗しても `uploads.json` は書く**（9/26 に共有が記録されないまま R2 に残り、直近 30 分の一覧から架空の曲名で見分けて消した）。手元の架空の絵（`/uploads/fa4e…`）は記録しない
  - **`f-find`（みんなのグリッド）は本番に何も置かずに撮る**: 共有の返事・探すページ・× で外す返事をすべて差し替える。探すページは `promo/fake_find.py` が架空の題で `share.find_html` を組む（本番の探すページには利用者の本物の題が並ぶため使わない）。架空の共有の ID は `fa4e…` で、`uploads.json` には記録しない
  - **3 段目「並べる操作」は `promo/x_catalog_ops.mjs`**（2026-09-26、22 本）。検索の返事・共有ページ（`promo/fake_share_page.py` がサイトと同じ `share.page_html` で組む）・
    保存と開くの窓（撮影のときだけページに描く擬似の窓 `fakeDialog`。ヘッドレスでは本物の窓が出ない）はすべて差し替え。道具に `k.drag`・`k.lookPart` を足した。
    **並べ直した窓（`k.arrange`）でもポップアップメニュー（`#popmenu`）が映るようにした**（隠れていると項目を押せなかった）
  - **4 段目「スマホの画面」は `promo/x_catalog_phone.mjs`**（2026-09-26、7 本）。台本に `phone: true` を付けると 390×844・指の画面で撮り（`x_clips.mjs` の `PHONE`）、
    `XClip` が録画の縦長を見て 16:9 の真ん中にスマホの枠を描き、その中に映す（利用者の決定。縦 9:16 は作らない）。指は矢印ではなく半透明の丸（`Finger`）。
    押すのは `k.tap` / `k.tapAt`（touchscreen）、送るのは `k.swipe`。スマホでは出力オプションの窓が畳まれて始まる。`#inapp` の案内は読み込み直さないと出ない（`?x=…#inapp` で開く）
  - **スマホ 2 台を並べる**（`k.setTwin(page2, sync)`、`sp-slider`）。2 台目も同じ時計で進め、コマごとに `sync()` で 1 台目の状態を写して撮る → `take2.mp4`。`XClip` が右に並べる（指の印は 1 台目だけ）
  - **スマホの「PC 版の表示」はページを読み直す**（`k.waitReload`）。撮影用のブラウザは幅 1024 の画面を縮めないので、CDP の `Emulation.setPageScaleFactor`（390/1024）で実機と同じく縮める。
    座標は `visualViewport.scale` を掛けて画面の座標にする（`rectOf`）
  - **`sp-share-target` は本物の YouTube のページ**（CQ-DZfQhXcc、利用者の指定。はじめはニコニコ動画だったが、ニコニコの「共有」は独自の窓で送れなかった）をAndroid の Chrome の名乗り（台本の `ctx.userAgent`）で開く。スマホの YouTube の「共有」は `navigator.share` を呼ぶので、`addInitScript` でそれを撮影用の Android の共有シートに差し替える。**YouTube は TrustedTypes で innerHTML を使わせない**ので部品ごとに組み立て、TRACKMENTO の絵は data: で埋め込む（よそのページの安全設定で手元のサーバーの画像は読めない）。取り込みは本物
  - **2 段目「できあがりと見た目の切り替え」は `promo/x_catalog_result.mjs`**（2026-09-26、15 本）。設定を替えたら「更新」を押し、できあがりの見本が変わるところを見せる
    （見本は自動では作り直さないため）。窓は左に出力オプションの欄（`keepField` でその欄だけ残す）、右にできあがり（`arrangeOut`）。
    **`keepField` は `k.arrange` より先に呼ぶ**（`only` の指定が目印を見る。逆だと欄ごと隠れた）。見本は `OUT_FIT` で高さ 540px までに収める（縦長 9:16 で窓がはみ出した）
  - `color-sort` は白黒の架空のジャケット（明るさを段階的に）で撮る（カラフルな絵だと色相の順が伝わりにくい、と利用者。白黒は明るい順にそろう）。
    `bg-image` は「できあがりを見る」を押して見本の窓に寄る（グリッドの見本はマスの隙間にしか画像が見えない）
  - 題材の台帳（2026-09-25 夜に今の画面で数え直した 142 件。型・映え・撮り直しの判定付き、撮る／保留／外すは台帳の db に保存）:
    https://claude.ai/artifact/GZ3kefBb8ouyGpV5fc2MRo 。元は `~/Tools/board-style/pages/x-clips-ledger.html`（データは流し込み。セッションの scratchpad の inventory.json が元なので、直すときは Artifact の read で今の版を取る）
