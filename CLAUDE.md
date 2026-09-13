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

## 変更したら回すもの（忘れると本番が壊れる／気付けない）

| 何を変えたか | 回すもの | 忘れるとどうなるか |
| --- | --- | --- |
| `frontend/index.html` の固定文字 | `scripts/build_fonts.py` → `scripts/upload_fonts_r2.py` | **本番でフォントが 404**（断片名にハッシュが入るため） |
| 同上 | `scripts/check_i18n.py` | 英語表示でそこだけ日本語のまま残る（警告は出ない） |
| 描画（`render.py` か `renderShareCanvas`） | `scripts/compare_render.py` | サーバー描画とブラウザ描画がずれる（描けない端末だけ見た目が変わる） |
| マスの上限 | 4 か所すべて（下記） | 並びが黙って潰れる |

上限の 4 か所: `frontend/index.html` の `MAX_SIDE_CELLS`（1 辺 32）と `MAX_CELLS`（総数 256）、
`backend/grids.py` の `MAX_COLS` / `MAX_ROWS`（1 辺）、`backend/config.py` の `max_cells()`（総数）。

すべて `PYTHONUTF8=1 .venv/Scripts/python …` で実行する（cp932 で落ちる）。

## 開発メモ

- 構成: `backend/`（FastAPI、sources/、cache.py、grids.py、render.py、share.py、uploads.py、config.py）、`frontend/index.html`（単一 HTML）、`cli.py`、`fonts/`（OFL 同梱）
- R2（`backend/storage.py`）: 共有画像・並び JSON・アップロード画像・分割フォントの置き場所。バケット `trackmento-shares`、公開 URL は `R2_PUBLIC_URL`。**転送量が無料なので、Render の課金対象から逃がしたいものはここに置く**
  - バケットの設定（CORS・ライフサイクル）は API トークンの権限では変えられない。Cloudflare のダッシュボードから操作する。CORS は本番と `localhost:8000` / `127.0.0.1:8000` を GET で許可済み（Canvas は fetch + `createImageBitmap` で読むので、これが無いと共有画像を作れない）
  - ライフサイクルは 7 日。共有は期限切れで自然に消える
  - `uploads.read_bytes` は R2 に無ければローカルの `uploads/` も見る（手元で R2 を設定した後も、それ以前に保存した画像を読めるように）
- 描画は 2 系統: Web は端末の Canvas で描いて `/share/upload` に送る（`frontend/index.html` の `renderShareCanvas`）。サーバー描画（`backend/render.py`）は CLI と、描けない端末のフォールバック（`/share`）。レイアウト・色・文字の省略規則は両方同じ式。**片方変更時は他方も変更**し、`scripts/compare_render.py` で両方の描画を突き合わせる（差は輪郭のみが正常）。
  手順はスクリプトの docstring。サーバーは `PUBLIC_MODE=1 SHARE_BUDGET_GB=0 SHARE_LIMIT_PER_DAY=0 SHARE_LIMIT_PER_IP_DAY=0` で立てる（R2 が無料枠を超えていると 507、本番の共有数を復元して 1 日上限にも当たる）。
  **見るのは「ぼかし後の差 > 32」**。輪郭のズレはぼかすと消え、マスや文字の位置のズレだけが残る。
  実測（2026-09-14、4x4 / 12x20 / 16x16）で 0.00〜0.24%。ここが 1% を超えたらレイアウトがずれている。
  **テスト共有は必ず `clean` で R2 から消す**
- フォント: Web は `fonts/split/`（`scripts/build_fonts.py` が IBM Plex Sans JP / DotGothic16 を unicode-range で分割した WOFF2 ＋ `fonts.<hash>.css`）を `<!--__FONT_LINK__-->` 経由で読む。**`frontend/index.html` の固定文字（ラベル・説明文）を変えたら次の 3 つを順に実行する**
  1. `python scripts/build_fonts.py` … 断片と `fonts.<hash>.css` を作り直す（先頭断片に UI の全文字を入れる設計。忘れると初回表示で断片を大量に読む）
  2. `.venv/Scripts/python scripts/upload_fonts_r2.py` … 増えた断片を R2 に上げる。**これを忘れると本番でフォントが 404 になる**（断片名にハッシュが入るので、文字が変わると別ファイルになる）
  3. `PYTHONUTF8=1 .venv/Scripts/python scripts/check_i18n.py` … 日本語の文言と EN 表のずれを見つける。
     **EN 表は日本語の文面そのものが鍵なので、文言を 1 文字直すだけで英語がそこだけ日本語に戻る**（警告は出ない）

  断片は R2 から配る（`/fonts-css/<name>` が CSS の `src` を R2 の公開 URL に差し替えて返す）。Render 前段の Cloudflare は Web Service の応答をキャッシュせず、フォントが新規訪問 1 回あたり 210KB（実測）で転送量の大半を占めていたため。`FONTS_FROM_R2=0` で従来どおりサーバーから配る。R2 側の CORS 設定と、CSP の `font-src` / `connect-src` への公開 URL の追加が前提（`_r2_origin()` が組み立てる）。共有画像の描画前は `loadShareFonts` が描く文字を渡して必要断片だけ読む。サーバー描画は `fonts/*.ttf` のまま。共有ページはシステムフォント（Silkscreen のみ読む）
- `/image-proxy` は一度取った画像を R2（`imgcache/`）にも置き、**二度目以降は本体を返さず 302 で R2 へ送る**。画像 1 枚 77KB に対して 302 の応答は数百バイトなので、Render の転送量がほぼ無くなる。`IMAGE_TO_R2=0` で従来どおり本体を返す
  - ブラウザは共有画像を作るとき `fetch` + `createImageBitmap` で読むので、別オリジンから返すには R2 の CORS と CSP の `connect-src` が要る（フォントを R2 に移したときに整えた）。`<img crossOrigin>` ではないので、この 2 つが揃っていれば Canvas は汚染されない
  - **R2 への書き込みは応答の後ろに回す**（`_image_to_r2_bg`）。`put` は `connect_timeout` 3 秒 × リトライ 3 回＋バックオフで 10 秒を超えることがあり、`await` するとそのまま利用者の待ち時間になる（`/s/*` を 14.3 秒 → 1.0 秒にしたのと同じ話）。次回以降 302 で返すためのキャッシュなので、落としても応答は正しい。R2 が不調なときに溜め込まないよう走っている本数は `IMAGE_R2_TASKS_MAX`（既定 64）で頭打ちにする
  - **画像取得のタイムアウトは共有クライアントと分ける**（`IMAGE_FETCH_TIMEOUT`、既定 12 秒 / connect 5 秒）。`app.state.http` の既定 30 秒は MusicBrainz や roxy に合わせたもので、画像には長すぎる。遅い配信元 1 本が `_PROXY_SEM` の枠を 30 秒占有すると 16 枠が飽和し、後続が 20 秒待たされて 503 になる（2026-09-14 に実際に起きていた。点検で `/image-proxy` 最大 24.0 秒・5xx 5 件）。サーバー側描画（`render.py`）も 12 秒なので、そちらに揃えてある
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
  - 単体 URL … `fromurl.fetch` が直接取得に失敗したら roxy に聞く（`_ROXY_FALLBACK`）。`sm12345` や `BV…` のような
    ID だけの貼付は `fromurl.normalize()` がそのサイトの URL に組み立ててから同じ流れに乗せる。
    **ID をそのまま roxy に投げてはいけない**（roxy が扱えるのはニコニコだけなので BV… と YouTube の 11 文字は必ず失敗し、
    毎回 roxy への無駄打ちになる。以前はそうなっていた）
  - プレイリスト … **こちらは失敗しない**。ニコニコのマイリスト API は消えた動画にも「削除された動画」という
    タイトルと灰色のサムネイルを付けて返すため、例外にならず素通りする。`playlist.is_gone()` で
    決まり文句のタイトルを見つけ、`_fill_from_otodb()` が roxy で差し替える（並び順は変えない。
    リンク先は元の動画のまま残す）。roxy は 1 件ずつ各サイトへ取りに行くので、上限 24 件・並列 6・全体 25 秒で打ち切る
- R2 クライアント（`storage.py` の `Config`）の `connect_timeout` は 3 秒。**ここを長くしてはいけない**。
  boto3 はリトライ 3 回＋指数バックオフなので、接続待ちが 10 秒だと 1 回つながらなかっただけで
  利用者の待ち時間が 14 秒になる（実際に共有ページ `/s/*` の最大応答が 14.3 秒になっていた）。
  R2 への TCP 接続が 1 秒を超えることはまずないので、短くしても取りこぼさない
- 日本語 / 英語の切り替え（2026-09-14）
  - **画面**: `frontend/index.html` の `EN` 表と `tr()`。**日本語の文面をそのまま鍵にして英語を引く**ので、原文がコードに残る。
    `${…}` を含む文面は `` tr`…` `` とタグ付きテンプレートで呼び、鍵は raw を `"{}"` でつないだもの。英語側の差し込み位置は
    `{0}` `{1}` … で書く（語順が日本語と変わるため）。**関数名は `tr`**（`t` はトラック変数として多用されているので使えない）
  - HTML に直接書いた文言は起動時に `snapI18n()` で控えを取り、`applyI18n()` が差し替える。
    **後から足した利用者のデータ（曲名・アーティスト名）は控えに無いので触らない**という作り
  - `SOURCE_LABEL` / `SWATCHES` の値は日本語のまま持ち、**使う側で `tr()` を通す**。表は起動時に 1 回しか評価されないため、
    リテラルを `tr()` でくるむと切り替えに追従しない
  - 言語を変えたら `reRenderForLang()` が描き直す。**`renderResults` は候補が空のときに呼ぶと「該当なし」に化ける**ので、
    件数があるときだけ呼ぶ
  - `__RETENTION__` は `main.py` が HTML 全体を置換するので、EN 表の鍵と DOM の文字列は必ず同じ値になる（そこは心配しなくてよい）
  - **共有ページ・案内ページ**（`backend/share.py` の `TEXT` と `t()`）はサーバーで組み立てるので別仕組み。
    `main.py` の `_lang_for(request)` が **開いた人の Accept-Language** で選ぶ。共有ページは受け取った人が開くものなので、
    共有した人が画面で選んだ言語ではなく開く人の設定に合わせる
  - 連絡先は日本語 `/ja/about/`・英語 `/about/` でページが別。画面側は `#about-link` の href を切り替える
- UI デザインは Hallmark 方針（仕様書「UI デザイン方針」）。色・フォントは CSS 変数トークン経由、角丸なし
- 本番の点検: `PYTHONUTF8=1 .venv/Scripts/python scripts/render_check.py --hours 2`（Render API でログ・イベント・帯域・メモリを要約。`.env` の `RENDER_API_KEY`。**手元の `.env` には入っていないので、ローカルで動かすなら Render → Account Settings → API Keys で発行して足す**。GitHub Actions 側は Secrets にある）。`gh workflow run render-check.yml` でいつでも回せる
  - GitHub Actions `render-check.yml` が 2 時間おきに同じ点検を回し、異常時は Issue（ラベル render-check）に書く。ただし **GitHub の cron は大幅に間引かれ、`*/10` 指定でも実測 2〜5 時間おきだった**（`keepalive.yml` の schedule を止めたのはこのため。フリープランに戻すなら外部の監視サービスが要る）
  - `[ua]` は経路ごとの User-Agent 種別（人／プレビュー／検索／AI／その他ボット／不明）の内訳。**生の UA は残さない**（指紋になるため）。
    種別を分けているのは対策が別だから。**「プレビュー」は X などがリンクカードを作るための取得なので止めてはいけない**
    （robots.txt で `/s/` を塞ぐと X のカードが出なくなる）。「検索」「AI」「その他ボット」は robots.txt で減らせる
  - 判定の閾値はインスタンスの種類から出す（`PLAN_SPECS` と `_PLAN_RE`。API は `1c_2g` のような形式を返す）。`CHECK_*` の環境変数で上書きできる
  - 「uptime のリセットがデプロイ回数より多い」は、無停止デプロイ中に新旧プロセスの `[health]` が交互に出るため一度は誤検知していた。5 分以内に続く戻りは同じ入れ替えとしてまとめている
- 動作確認は各ステップごとブラウザで（`claude-in-chrome` または手動）。サーバー `--reload` なし起動時、コード変更後再起動必要

## 調べ直さないための覚え書き（一度引っかかったもの）

- **Render の「プラン」は 2 つある**。課金アカウントの種別（Billing の Current Plan。Pro など）と、サービスのインスタンスタイプ（サービス画面のバッジ。Free / Standard など）は別物。**ワークスペースが Pro でもインスタンスが Free ならスリープするし 512MB 上限**。混同すると「スリープしないから keepalive は不要」のような誤った判断をする。インスタンスの実体は点検の「インスタンス: `1c_2g`」行か、`unbilled-charges.csv` の Services 行（`charge` が Free なら Free インスタンス）で確認する
- **画像が `/image-proxy` を通るかはホストで決まる**。`frontend/index.html` の `DIRECT_IMAGE_HOSTS`（mzstatic / coverartarchive.org / archive.org）はブラウザが直接読むので **Render の転送量に乗らない**。それ以外（Bandcamp・SoundCloud・YouTube・ニコニコ・bilibili・Discogs・otoDB）はサーバーを通る。帯域を調べるときは、まずここで対象を絞る
- **`raise HTTPException(...)` で返した 5xx は `[error]` に出ない**。`http_error` が握るので `unhandled_error` を通らず、点検では「エラー行 0・5xx N」としか分からなかった。理由（detail）を見るために `[5xx]` という別の印を足してある（`main.py` の `_log_5xx` が理由ごとに数え、`_load_monitor` が `[stats]` と同じ 60 秒窓で `[5xx] <件数> <status> <パス種別> <理由>` を出す。上位 `_5XX_TOP` 件＋残りは「ほか」にまとめる）。
  **`[error]` に混ぜてはいけない**。あちらは「想定外の例外」を数えて判定に使う枠なので、配信元都合の 502 を入れると閾値が鈍る。`render_check.py` 側は `FIVEXX_RE` で拾って要約に内訳を出すだけで、判定は従来どおり `[stats]` の 5xx 合計で見る
- **`[stats]` のログに転送量は入っていない**（件数・所要時間・5xx のみ）。どの経路が何バイト出しているかはログから分からないので、`curl` で実際のサイズを測るか、ブラウザの `performance.getEntriesByType('resource')` の `transferSize` を見る。件数が多い経路が重いとは限らない（実例: `/grids/*` は最多だが 1 件 3.6KB、フォントは件数が少ないのに 210KB）
- **Render 前段の Cloudflare は Web Service の応答をキャッシュしない**（`cf-cache-status: DYNAMIC`）。`Cache-Control` を付けても効かないので、転送量を減らすには R2 へ逃がすしかない
- **`python -c "from backend import storage"` のような直接実行では `.env` が読まれない**（`backend.main` が `load_dotenv` する）。環境変数が無いと `get_storage()` が LocalStorage に落ちるため、R2 を見ているつもりでローカルの `shares/` を見ていることがある。**サーバー経由では 404 なのに手元のスクリプトでは取れる、という食い違いはたいていこれ**。スクリプトから触るときは `.env` を自分で読む（`scripts/upload_fonts_r2.py` の冒頭が例）
- **R2 の CORS は本番と `localhost:8000` / `127.0.0.1:8000` だけ許可**している。検証用に別のポート（8001 など）でサーバーを立てると、R2 から読むフォントや画像が CORS で弾かれて「実装が壊れている」ように見える。**ブラウザで確かめるときは 8000 を使う**
- **フォントや CSS の検証では必ずハードリロード**（Ctrl+Shift+R）する。`fonts.<hash>.css` は `immutable` で 1 年キャッシュするうえ、CORS や CSP で失敗した結果もキャッシュされる。普通の再読み込みだと、直したのに古い失敗が残って「断片を 249 件読んでいる」のような誤った観測になる
- **同じ知識が 2 か所以上にある所の一覧**（今回のバグはすべてここから出た）。片方だけ直すと壊れる:
  - 描画: `backend/render.py` と `frontend/index.html` の `renderShareCanvas`（定数・レイアウト式・文字の省略規則）
    → `scripts/compare_render.py` で突き合わせられる。丸めは `render.py` の `rnd()` が JS の `Math.round` に
    合わせてある（**Python の `round()` は偶数丸めなので使ってはいけない**）
  - 検索の絞り込み: `backend/sources/itunes.py` と frontend の `itunesSearch`（ブラウザから直接 iTunes を叩くため）
  - 曲名の正規化: `backend/merge.py` の `_n()` と frontend の `nkey()`。
    **Python の `casefold()` は ß を ss に畳むが JS の `toLowerCase()` は畳まない**ので手で合わせてある
  - マスの上限: 4 か所（上の表）
  - 文言: 日本語の原文と `EN` 表 → `scripts/check_i18n.py`
  - 色・比率・`CELL_PX` / `GAP_PX` / `MAX_SIDE`: `render.py` と `index.html`（2026-09-14 時点で一致を確認済み）
- **`scrollbar-color` / `scrollbar-width` を書くと、Chrome は `::-webkit-scrollbar-*` を丸ごと無視する**。
  スクロールバーの見た目を作り込むときにこれを併記すると、指定が一切効かず幅が既定の 15px のままになる。
  Firefox 用の指定は `@supports not selector(::-webkit-scrollbar)` に閉じ込めること
- **スクロールバーの部品に外へ出る `box-shadow`（`0 0 0 1px` など）を使ってはいけない**。WebKit は部品の外側を
  描き直さないので、つまみを動かすと縁の線が溝に残る。縁は `border` で部品の内側に描く
- **グリッドの項目に `align-self: stretch` を付けても、その項目の中身が行の高さを押し広げる**。
  候補ペインをグリッドと同じ高さにしたときは `height: 0` ＋ `min-height: 100%` で「行の高さを決めるときに
  中身を数えさせない」形にした（これが無いと候補が増えるたびグリッドまで高くなる）
- **スクロール領域の中で `transform: translateX()` を使うと横方向のはみ出しになる**。`.result:hover` の 2px ずらしで
  横スクロールバーが出入りし、そのたび縦バーの長さが変わっていた。`overflow-x: hidden` ＋ `padding-right` で受ける
- **`scripts/build_fonts.py` はソースのコメントを除いてから文字を集める**（2026-09-14 から）。
  日本語のコメントまで先頭断片に入れると 4 割ほど無駄に太るため。先頭断片は合計 365KB → 287KB になった。
  取りこぼしてもその文字が別の断片から読まれるだけで壊れない
- **`[ua]` の実測（2026-09-14）で `/s/*` の人以外アクセスの 71% が「プレビュー」だった**（X などのリンクカード生成）。
  robots.txt で `/s/` を塞ぐと **X のカードが出なくなる**ので触らない、と判断済み。検索・AI ボットは合わせて数十件で誤差
- **マスの上限は 3 か所にあり、ずれると並びが黙って壊れる**。`frontend/index.html` の `MAX_SIDE_CELLS`（1 辺）と
  `MAX_CELLS`（総数）、`backend/grids.py` の `MAX_COLS` / `MAX_ROWS`（1 辺）、`backend/config.py` の `max_cells()`（総数）。
  **`grids.py` の側を小さくしてはいけない**。`GridDoc` の検証は cols/rows を黙って丸め、はみ出したマスを stash に移すので、
  16x16 の並びを保存した瞬間に 12x12 へ潰れる（2026-09-14 に実際に起きていた。上限を 256 に上げたとき
  `grids.py` と `applyData` の 12 を直し忘れていた）
- **ブラウザで動作を確かめるときは `PUBLIC_MODE=1` を付けて起動する**。付けないとグリッド名が `default` になり、
  **`grids/default.json`（利用者の並び）をテストで上書きしてしまう**（2026-09-14 に実際にやった。
  幸い `grids/default.json.bak-*` が残っていたので復元できた）。公開モードならブラウザごとの `u-….json` に分かれる
  ```bash
  PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
  ```
  R2 の CORS は `localhost:8000` / `127.0.0.1:8000` だけ許可しているので**ポートは 8000 固定**
- **`grids/` と `shares/` は `.gitignore`**。並びを壊しても git では戻せない。ただし `shares/<id>.json` は共有したときの並びのスナップショットなので、**そこから失われたマスを復元できる**（実例: 1 マス目だけ消えたグリッドを、同じ並びの共有 JSON から戻した）

## 次にやること・保留中（2026-09-14 時点）

- **otoDB 開発者（SnO₂WMaN さん）からの返答待ち**。2026-09-13 深夜に Discord で送った内容:
  1. roxy への問い合わせ頻度はどこまで許容されるか（うちは同時接続 3・1 リストあたり 24 件・結果を 1 日キャッシュ）
  2. roxy は otoDB 登録済みの作品なら **ニコニコ以外**（SoundCloud / YouTube / bilibili）の URL でも引けるのか
     （実測では未登録・登録済みを問わず 404 `Cannot fallback`。yt-dlp を使っているので技術的制約ではなさそう）
  3. サムネイルのサイズ指定（優先度低。こちらで縮小して解決済み）
  - **2 が「引ける」なら SoundCloud のプレイリストでも穴埋めを足す**。`playlist.is_gone()` の仕組みは既にあるので追加は数行
- **AdSense の審査待ち**（「準備中」）。ads.txt と meta タグは本番で配信済み・ID も一致、設定側の問題は無い
  - **承認後、自動広告をオンにするだけでは広告は出ない**。TRACKMENTO は nonce ベースの CSP で固めているので、
    `script-src` に `pagead2.googlesyndication.com`、`frame-src` に `googleads.g.doubleclick.net`、
    `img-src` / `connect-src` にも追加が要る（`backend/main.py` の CSP ヘッダ）
  - そもそも広告を出すかは未決。Bandcamp のカンパ導線を置いた直後なので、承認が下りてから相談する
- **動画制作**（Remotion 予定）。要点は `video-notes.md`、素材と手順は `promo/`
  - **`grids/default.json` は動画（`promo/public/final.png`）と同じ状態に揃えてある**（9 曲・3x3・
    タイトル「私を構成する9選」）。`grids/*.bak` は古い状態なので、そこから戻すと逆戻りする
- **`/s/*` の robots.txt は触らない**と決めた。`[ua]` の実測で人以外アクセスの 71% が「プレビュー」
  （X などのリンクカード生成）だったため。塞ぐと X のカードが出なくなる。検索・AI ボットは合わせて数十件で誤差
- 候補パネルの上限は 500 にしたが、`/search` エンドポイントには `limit` を渡す口が無いので
  **検索結果は今も 30 件のまま**。増やしたくなったら `otodb.search` の offset ページングが使える（実装済み）
- インスタンスは Standard（`1c_2g`、約 $25/月）＋ Workspace Pro（$25/月）。**バズが収まったら下げる判断が要る**
  （メモリは最大 195MB / 2048MB、CPU は最大 0.046 / 1.0 とかなり余っている）

## 直近の数字（2026-09-14 00:10 の点検）

判定「正常」。以下は次回の比較用。

- 帯域: 今月累計 **109 GB / 25 GB 含む** → 超過 85GB ＝ **$12.75**。直近は 0.42 GB/2h（対策前は 1.24 GB/2h）
- 共有数 5803 件/日、メモリ最大 173MB、CPU 最大 0.031、判定「正常」
- R2: ストレージ 12.96GB（30 日平均 7.9GB なので無料枠内）。**09-11 の PNG 5.3GB が 09-18 に期限切れで消える**
  - Class A 操作は直近 24 時間で 18.5k。30 日換算 555k で無料枠 100 万の 56%。増え方だけ見ておく
- `/s/*` の最大応答は 14.3 秒 → **1.0 秒**（R2 の接続待ちを 10 秒 → 3 秒にした効果）
