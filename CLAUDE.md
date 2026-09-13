# TRACKMENTO (musicgrid-local) — Claude Code 向けメモ

曲単位ジャケットグリッド画像生成ローカルツール。仕様・経緯は `musicgrid-local-spec.md`。
本ファイルは主に **Remote Control（スマホ）で曲追加→画像 URL 受取** 手順。

## 起動（PC 側、毎回）

```bash
cd musicgrid-local
.venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000   # API + 画像配信
claude --remote-control TRACKMENTO                                             # スマホの Claude アプリから接続
```

- Web UI: http://localhost:8000/ 。生成 PNG は `outputs/` から `/outputs/<file>.png` で配信
- `.env` の `PUBLIC_BASE_URL` が `auto` なら LAN IP（例 `http://192.168.3.14:8000`）で URL 返却。
  スマホで開く場合 `localhost` でなく LAN IP か Tailscale URL 必須
- 実際のベース URL はサーバー起動ログ `[public] PNG の URL は ...` で確認

## CLI（Bash から呼ぶ。Python は必ず `.venv/Scripts/python`）

```bash
.venv/Scripts/python cli.py add    --artist "A" --title "T" [--grid NAME] [--source itunes|mb|discogs|otodb] [--first]
.venv/Scripts/python cli.py add    --url "https://xxx.bandcamp.com/track/..." [--grid NAME]     # Bandcamp / SoundCloud / Spotify / YouTube / ニコニコ動画 / bilibili の URL
.venv/Scripts/python cli.py add    --image "https://.../cover.jpg" --artist "A" --title "T" [--grid NAME]   # 手入力
.venv/Scripts/python cli.py pick   --index N [--grid NAME]     # 直前の候補から選ぶ
.venv/Scripts/python cli.py search --artist "A" --title "T"    # 候補を見るだけ（pick で選べる）
.venv/Scripts/python cli.py list   [--grid NAME]
.venv/Scripts/python cli.py move   --from N --to M [--grid NAME]
.venv/Scripts/python cli.py remove --index N [--grid NAME]
.venv/Scripts/python cli.py share  [--grid NAME] [--size 3x3] [--ratio 1:1|4:5|16:9|9:16|free] [--sidebar|--no-sidebar]   # PNG + 共有ページ URL
.venv/Scripts/python cli.py render [--grid NAME] ...                                                          # PNG だけ（オプションは share と同じ）
                                   [--title "…"] [--no-title] [--numbers|--no-numbers] [--bg paper|ink|mustard|cerulean|lavender|vermilion|mint|pink]
                                   [--bg-custom "#rrggbb"] [--margin 48] [--gap 12]
.venv/Scripts/python cli.py clear  [--grid NAME]
.venv/Scripts/python cli.py grids
```

- 番号 N は画面番号バッジ同一、**1 始まり**
- 既定グリッド `default`。状態は `grids/<NAME>.json` 保存、Web UI と共有
  （Web は起動時 localStorage とサーバーの新しい方を読込。開いたままの Web には「サーバーから読み直す」ボタン）
- `share` / `render` は指定オプションをグリッド JSON にも保存。次回以降省略可
- `share` は画像（JPEG 品質 90）と並びスナップショットを `shares/<id>.{jpg,json}` 保存、共有ページ `http://…/s/<id>` の URL 出力。
  共有ページ内容: 画像・曲リスト・「TRACKMENTO で開く」（`/?share=<id>` でその並びを Web 読込）
- `share` / `render` 最終行は必ず `URL: http://...`
- 検索結果・画像は `cache.sqlite3` にキャッシュ。再取得は Web の `/search?...&nocache=true`

## スマホからの依頼への対応手順

### 「○○の『△△』を追加して」
1. `cli.py add --artist "○○" --title "△△"` 実行
2. 曲名＋アーティスト一致候補あれば自動で次の空きマスへ。出力「NN 番に追加: …」をそのまま伝達
   （検索順 iTunes → MusicBrainz → Discogs（--source mb,discogs 等で絞込可）。iTunes は曲名・アーティスト名にクエリ含むもののみ返却、完全一致先頭）
3. **候補複数時は必ず番号付き提示、ユーザーの番号返答後** `cli.py pick --index N` で確定。勝手に選ばない
4. 未発見時の順: `--source discogs` / `--source mb`（音MAD は `--source otodb`）→ Bandcamp / SoundCloud / Spotify / YouTube / ニコニコ動画 / bilibili なら URL 受取→ `--url URL` → 画像 URL 受取→ `--image URL --artist --title`
5. 空きマスなしの場合、`remove --index N` で除外か `render --size 4x6` 等で拡張かをユーザーに確認

### 「今の並びは？」
`cli.py list` 出力をそのまま返却（番号・曲名・アーティスト・ソース）。

### 「N 番と M 番を入れ替えて」「N 番を消して」
`cli.py move --from N --to M` / `cli.py remove --index N`。結果の並びをそのまま返却。

### 「画像にして」「共有して」「16:9 で曲名リスト付きにして」
1. 指定あれば `cli.py share --ratio 16:9 --sidebar --title "…"`。なければ `cli.py share`
2. 出力の並び一覧と **`URL:` 行を省略せずそのまま返却**。スマホ側はその URL（共有ページ）で PNG 保存や
   「TRACKMENTO で開く」で並び読込可。画像のみ要望時は `画像:` 行も添付
3. `注意: サーバーが応答しません` 出力時、uvicorn 起動後に URL 伝達

### 「全部消して」
`cli.py clear` 実行前に一度確認（取消不可）。

## 開発メモ

- 構成: `backend/`（FastAPI、sources/、cache.py、grids.py、render.py、share.py、uploads.py、config.py）、`frontend/index.html`（単一 HTML）、`cli.py`、`fonts/`（OFL 同梱）
- R2（`backend/storage.py`）: 共有画像・並び JSON・アップロード画像・分割フォントの置き場所。バケット `trackmento-shares`、公開 URL は `R2_PUBLIC_URL`。**転送量が無料なので、Render の課金対象から逃がしたいものはここに置く**
  - バケットの設定（CORS・ライフサイクル）は API トークンの権限では変えられない。Cloudflare のダッシュボードから操作する。CORS は本番と `localhost:8000` / `127.0.0.1:8000` を GET で許可済み（Canvas は fetch + `createImageBitmap` で読むので、これが無いと共有画像を作れない）
  - ライフサイクルは 7 日。共有は期限切れで自然に消える
  - `uploads.read_bytes` は R2 に無ければローカルの `uploads/` も見る（手元で R2 を設定した後も、それ以前に保存した画像を読めるように）
- 描画は 2 系統: Web は端末の Canvas で描いて `/share/upload` に送る（`frontend/index.html` の `renderShareCanvas`）。サーバー描画（`backend/render.py`）は CLI と、描けない端末のフォールバック（`/share`）。レイアウト・色・文字の省略規則は両方同じ式。**片方変更時は他方も変更**し、Playwright でブラウザ描画とサーバー描画の画素差を比較する（差は輪郭のみが正常）
- フォント: Web は `fonts/split/`（`scripts/build_fonts.py` が IBM Plex Sans JP / DotGothic16 を unicode-range で分割した WOFF2 ＋ `fonts.<hash>.css`）を `<!--__FONT_LINK__-->` 経由で読む。**`frontend/index.html` の固定文字（ラベル・説明文）を変えたら次の 2 つを順に実行する**
  1. `python scripts/build_fonts.py` … 断片と `fonts.<hash>.css` を作り直す（先頭断片に UI の全文字を入れる設計。忘れると初回表示で断片を大量に読む）
  2. `.venv/Scripts/python scripts/upload_fonts_r2.py` … 増えた断片を R2 に上げる。**これを忘れると本番でフォントが 404 になる**（断片名にハッシュが入るので、文字が変わると別ファイルになる）

  断片は R2 から配る（`/fonts-css/<name>` が CSS の `src` を R2 の公開 URL に差し替えて返す）。Render 前段の Cloudflare は Web Service の応答をキャッシュせず、フォントが新規訪問 1 回あたり 210KB（実測）で転送量の大半を占めていたため。`FONTS_FROM_R2=0` で従来どおりサーバーから配る。R2 側の CORS 設定と、CSP の `font-src` / `connect-src` への公開 URL の追加が前提（`_r2_origin()` が組み立てる）。共有画像の描画前は `loadShareFonts` が描く文字を渡して必要断片だけ読む。サーバー描画は `fonts/*.ttf` のまま。共有ページはシステムフォント（Silkscreen のみ読む）
- `/image-proxy` は一度取った画像を R2（`imgcache/`）にも置き、**二度目以降は本体を返さず 302 で R2 へ送る**。画像 1 枚 77KB に対して 302 の応答は数百バイトなので、Render の転送量がほぼ無くなる。`IMAGE_TO_R2=0` で従来どおり本体を返す
  - ブラウザは共有画像を作るとき `fetch` + `createImageBitmap` で読むので、別オリジンから返すには R2 の CORS と CSP の `connect-src` が要る（フォントを R2 に移したときに整えた）。`<img crossOrigin>` ではないので、この 2 つが揃っていれば Canvas は汚染されない
  - `imgcache/` は `r2_prune.py` が 7 日で消すため、SQLite 側は 6 日（`cache.R2_IMAGE_TTL`）で `r2key` を無効とみなす。**この大小を逆にすると、R2 から消えた後もリダイレクトし続けて 404 になる**
- ジャケットの取得サイズは書き出しのマス（600px = `CELL_PX`）に合わせる。それ以上の解像度は縮小されて捨てられるだけで、転送量（Render の課金対象）が増える。配信元ごとに `clamp_size()` を持ち、`/image-proxy` から呼んで保存済みのグリッドにも効かせる。**やっているのは URL の書き換えだけで、こちらで圧縮や再エンコードはしない**（配信元が用意している小さい版をそのまま返す。Bandcamp の `_16` で取ったものは配信元から直接取ったバイト列と完全に一致する＝画質の劣化なし）
  - iTunes `itunes.clamp_size` … `/1000x1000bb.jpg` → `/600x600bb.jpg`（171KB → 77KB）
  - Bandcamp `bandcamp.clamp_size` … 欲しい実寸を満たす最小のサイズコードを選ぶ（`_7` 150px/11KB → `_9` 210px/20KB →
    `_4` 300px/34KB → `_16` 700px/88KB）。**原寸 `_0` は 1 枚 6.5MB あった**。コードと実寸の対応は総当たりで調べた値を `_CODE_PX` に持つ
  - bilibili `video.clamp_size` … 指定なし（原寸）→ `@600w_600h_1c`（640KB → 50KB）
  - otoDB だけは例外で、`/image-proxy` がサーバー側で縮める（`imgtools.shrink_bytes`）。URL に大きさ指定の仕組みが無く、
    常に 1280x720 / 平均 166KB を返すため、256 マスだと合計 41.5MB になる。**マスは正方形で中央を切り抜くので短辺を基準に縮める**
    （長辺で縮めると短辺が足りず拡大ボケする）。刻みは 200px 単位（200/400/600）で、キャッシュと R2 のキーは `<url>#px=<N>` と分ける。
    短辺 200px で 1 枚 22.6KB（256 マスで 5.7MB、-86%）。これだけ JPEG 品質 85 で再エンコードするので原本とはバイト列が変わる
  - 実測して問題が無かったもの: SoundCloud 78KB、YouTube 32KB、ニコニコ 10KB、Spotify 120KB（640px）、Cover Art Archive は `front-250`（28KB）が最小で 250/500/1200 の 3 段階しかない
    （ブラウザから直接読むので Render を通らない）
- 消えた動画（削除・非公開）は otoDB で埋める。otoDB のサムネイルは元動画が消えても CDN に残るため
  - **roxy が未登録の動画を各サイトから取りに行くのはニコニコだけ**（2026-09 実測）。YouTube / bilibili /
    SoundCloud は生きている URL でも 404 `Cannot fallback` になる。otoDB に登録済みの作品なら
    他のサイト出典でも引ける可能性はあるが未確認。SoundCloud 対応を足すならここが確認できてから
  - **roxy の応答には Cache-Control が無い**ので、結果を `cache.sqlite3` の search テーブルに
    擬似ソース `roxy`（`otodb.ROXY_CACHE`）として 1 日覚える。**見つからなかった分も空リストで覚える**
    （消えた動画の大半は otoDB にも無く、そちらのほうが多い）。同じプレイリストを貼り直しても roxy を叩かない
  - roxy はもともと「人が表計算に 1 件ずつ貼る」ような使われ方を想定した小さなサービスで、公開サイトから
    まとめて自動で叩くうちは例外的。**`playlist._ROXY_SEM` はモジュール変数にしてプロセス全体で 1 つ持つ**
    （リクエストごとに作ると、同時に n 人がプレイリストを貼ったときに n 倍の並列で殴ることになる）。
    利用者が何人いても roxy から見た同時接続は既定 3（`ROXY_CONCURRENCY` で変更可）
- otoDB の API は**匿名の GET を 60 秒キャッシュする**（otoDB 側 `middleware.py` の `AnonymousReadOnlyCacheMiddleware`）。
  実測で初回 364〜597ms、2 回目以降 29〜33ms。`Cache-Control: max-age=60` が返る。ログインしないので常にこの対象。
  画像は `cdn.otodb.net`（CDN）なのでオリジンには行かない。検索は `offset` でページングできる
  （1 ページ 30 件が上限。31 以上の `limit` は 422。`otodb.PAGE` / `MAX_PAGES`）
  - 単体 URL … `fromurl.fetch` が直接取得に失敗したら roxy に聞く（`_ROXY_FALLBACK`）。`sm12345` のような ID だけの貼付も roxy へ
  - プレイリスト … **こちらは失敗しない**。ニコニコのマイリスト API は消えた動画にも「削除された動画」という
    タイトルと灰色のサムネイルを付けて返すため、例外にならず素通りする。`playlist.is_gone()` で
    決まり文句のタイトルを見つけ、`_fill_from_otodb()` が roxy で差し替える（並び順は変えない。
    リンク先は元の動画のまま残す）。roxy は 1 件ずつ各サイトへ取りに行くので、上限 24 件・並列 6・全体 25 秒で打ち切る
- UI デザインは Hallmark 方針（仕様書「UI デザイン方針」）。色・フォントは CSS 変数トークン経由、角丸なし
- 本番の点検: `PYTHONUTF8=1 .venv/Scripts/python scripts/render_check.py --hours 2`（Render API でログ・イベント・帯域・メモリを要約。`.env` の `RENDER_API_KEY`。**手元の `.env` には入っていないので、ローカルで動かすなら Render → Account Settings → API Keys で発行して足す**。GitHub Actions 側は Secrets にある）。`gh workflow run render-check.yml` でいつでも回せる
  - GitHub Actions `render-check.yml` が 2 時間おきに同じ点検を回し、異常時は Issue（ラベル render-check）に書く。ただし **GitHub の cron は大幅に間引かれ、`*/10` 指定でも実測 2〜5 時間おきだった**（`keepalive.yml` の schedule を止めたのはこのため。フリープランに戻すなら外部の監視サービスが要る）
  - 判定の閾値はインスタンスの種類から出す（`PLAN_SPECS` と `_PLAN_RE`。API は `1c_2g` のような形式を返す）。`CHECK_*` の環境変数で上書きできる
  - 「uptime のリセットがデプロイ回数より多い」は、無停止デプロイ中に新旧プロセスの `[health]` が交互に出るため一度は誤検知していた。5 分以内に続く戻りは同じ入れ替えとしてまとめている
- 動作確認は各ステップごとブラウザで（`claude-in-chrome` または手動）。サーバー `--reload` なし起動時、コード変更後再起動必要

## 調べ直さないための覚え書き（一度引っかかったもの）

- **Render の「プラン」は 2 つある**。課金アカウントの種別（Billing の Current Plan。Pro など）と、サービスのインスタンスタイプ（サービス画面のバッジ。Free / Standard など）は別物。**ワークスペースが Pro でもインスタンスが Free ならスリープするし 512MB 上限**。混同すると「スリープしないから keepalive は不要」のような誤った判断をする。インスタンスの実体は点検の「インスタンス: `1c_2g`」行か、`unbilled-charges.csv` の Services 行（`charge` が Free なら Free インスタンス）で確認する
- **画像が `/image-proxy` を通るかはホストで決まる**。`frontend/index.html` の `DIRECT_IMAGE_HOSTS`（mzstatic / coverartarchive.org / archive.org）はブラウザが直接読むので **Render の転送量に乗らない**。それ以外（Bandcamp・SoundCloud・YouTube・ニコニコ・bilibili・Discogs・otoDB）はサーバーを通る。帯域を調べるときは、まずここで対象を絞る
- **`[stats]` のログに転送量は入っていない**（件数・所要時間・5xx のみ）。どの経路が何バイト出しているかはログから分からないので、`curl` で実際のサイズを測るか、ブラウザの `performance.getEntriesByType('resource')` の `transferSize` を見る。件数が多い経路が重いとは限らない（実例: `/grids/*` は最多だが 1 件 3.6KB、フォントは件数が少ないのに 210KB）
- **Render 前段の Cloudflare は Web Service の応答をキャッシュしない**（`cf-cache-status: DYNAMIC`）。`Cache-Control` を付けても効かないので、転送量を減らすには R2 へ逃がすしかない
- **`python -c "from backend import storage"` のような直接実行では `.env` が読まれない**（`backend.main` が `load_dotenv` する）。環境変数が無いと `get_storage()` が LocalStorage に落ちるため、R2 を見ているつもりでローカルの `shares/` を見ていることがある。**サーバー経由では 404 なのに手元のスクリプトでは取れる、という食い違いはたいていこれ**。スクリプトから触るときは `.env` を自分で読む（`scripts/upload_fonts_r2.py` の冒頭が例）
- **R2 の CORS は本番と `localhost:8000` / `127.0.0.1:8000` だけ許可**している。検証用に別のポート（8001 など）でサーバーを立てると、R2 から読むフォントや画像が CORS で弾かれて「実装が壊れている」ように見える。**ブラウザで確かめるときは 8000 を使う**
- **フォントや CSS の検証では必ずハードリロード**（Ctrl+Shift+R）する。`fonts.<hash>.css` は `immutable` で 1 年キャッシュするうえ、CORS や CSP で失敗した結果もキャッシュされる。普通の再読み込みだと、直したのに古い失敗が残って「断片を 249 件読んでいる」のような誤った観測になる
- **`grids/` と `shares/` は `.gitignore`**。並びを壊しても git では戻せない。ただし `shares/<id>.json` は共有したときの並びのスナップショットなので、**そこから失われたマスを復元できる**（実例: 1 マス目だけ消えたグリッドを、同じ並びの共有 JSON から戻した）
