# TRACKMENTO (musicgrid-local) — Claude Code 向けメモ

## これは何か

**好きな曲のジャケットを格子状に並べて 1 枚の画像にする道具**。「私を構成する 9 曲」のような
画像を、音楽サブスクに入っていなくても、どのサイトの曲でも混ぜて作れるようにしたもの。

本番 https://trackmento.onrender.com/ 。手元では同じコードをローカルの uvicorn で動かす。
仕様と経緯の原本は `musicgrid-local-spec.md`。このファイルは**作業する人がまず読むもの**。

### 何が他と違うか

- **曲単位**で扱う。アルバム単位の似た道具は多いが、曲ごとのジャケットを並べられるものは少ない
- **出どころを混ぜられる**。iTunes・MusicBrainz・otoDB の検索に加えて、Bandcamp / SoundCloud /
  YouTube / ニコニコ動画 / bilibili / Spotify / Apple Music の URL を貼っても入る。
  ジャケットが無い曲は画像 URL を手で入れてもいい
- **プレイリストを丸ごと**入れられる（最大 500 曲）。マイリストやセットの URL を 1 本貼るだけ
- **消えた動画がよみがえる**。削除済みのニコニコ動画でも、otoDB（音MAD データベース）に
  登録があればタイトル・作者・サムネイルを引ける
- **登録なし・無料**。並びはブラウザとサーバーの両方に持ち、共有は 7 日で自然に消える

## 全体の仕組み

```
ブラウザ (frontend/index.html — 単一 HTML)
  │  検索 / URL から取得 / 並べ替え
  │  共有画像は **ブラウザの Canvas で描いて** サーバーへ送る
  ▼
FastAPI (backend/)
  ├ sources/      … 各サイトから曲とジャケットを取る
  ├ merge.py      … 出どころの違う結果を 1 つにまとめる（重複を消す）
  ├ cache.py      … 検索結果と画像を SQLite に覚える
  ├ grids.py      … 並びの検証と保存（grids/<名前>.json）
  ├ render.py     … **サーバー側の描画**（CLI と、Canvas が使えない端末のため）
  ├ share.py      … 共有ページ（/s/<id>）の組み立て
  ├ storage.py    … R2（Cloudflare）への読み書き
  └ main.py       … 経路・CSP・画像の中継・ログ
  ▼
Cloudflare R2 (img.trackmento.com)
   共有画像・並びの控え・アップロード画像・分割フォント・画像キャッシュ
```

**要点は「描画が 2 系統ある」こと。** ふだんはブラウザが Canvas で描いて `/share/upload` に送る
（サーバーの CPU を使わないため）。Canvas が使えない端末だけ `/share` でサーバーが描く。
この 2 つは**同じ絵にならなければいけない**ので、レイアウトの式・色・文字の省略規則を
両方に同じものを書いてある。片方だけ直すと、一部の端末でだけ見た目が変わる。

## なぜこの形なのか（設計の判断）

- **サーバーにお金をかけない**。Render の転送量が課金対象なので、出せるものは R2 から出す。
  R2 は転送量が無料。フォント・共有画像・画像キャッシュを全部そちらに逃がしてある
- **画像は「小さい版を選ぶ」**。こちらで圧縮せず、配信元が用意している小さい版の URL に
  書き換えるだけ（`clamp_size`）。画質が落ちないうえ、転送量が減る
- **ブラウザに描かせる**。無料プランだった頃、サーバー描画が重なるとヘルスチェックに落ちて
  再起動していた。Canvas に逃がしてからその問題が消えた
- **状態をサーバーに持ちすぎない**。並びはブラウザの localStorage が主で、サーバーは控え。
  登録が要らないのはこのため

## デザインと言葉づかい

見た目は **Mac OS 9（プラチナ）風**に寄せてある。角丸を使わない、影は真っ黒を右下にずらす、
タイトルバーは縞模様、スクロールバーは溝とつまみの立体感まで作る。今どきのフラットな
Web ツールとは逆を行く。**素っ気なさと厚みの同居**が持ち味なので、装飾を足すときは
「OS 9 のダイアログに出てきそうか」を基準にする。

- 色とフォントは **CSS 変数のトークン経由**でしか使わない（`--color-ink` など）。
  直接 `#000` と書くと、後で一括で変えられなくなる
- 文字は 3 種類。本文は IBM Plex Sans JP、数字や記号は Silkscreen（ピクセル）、
  補助は DotGothic16。**ピクセルフォントは小さくすると字形が潰れる**ので、
  10px まで落とすくらいなら消す（マスが小さいときの番号バッジがそれ）
- 言葉は**やわらかい日本語**にする。「エクスポート」ではなく「並びを保存」、
  「グリッドサイズ」ではなく「横 × 縦」。専門語を避けるほうが、音楽好きに届く
- 英語は**日本語の文面そのものを鍵**にして引く（`EN` 表）。原文がコードに残るので読みやすいが、
  **日本語を 1 文字直すと英語がそこだけ日本語に戻る**。`scripts/check_i18n.py` で必ず確かめる

## ファイルの役割（どこを見れば何があるか）

| ファイル | 役割 | 触るときの注意 |
| --- | --- | --- |
| `frontend/index.html` | 画面すべて。CSS も JS も 1 枚に入っている | 固定文字を変えたら**フォントの作り直しと i18n の照合**が要る（下の表） |
| `backend/main.py` | 経路、CSP、`/image-proxy`、ログ、起動処理 | CSP は `R2_PUBLIC_URL` から自動で組む。手で書き足さない |
| `backend/render.py` | サーバー側の描画 | `renderShareCanvas` と**対で直す**。`rnd()` を使う（Python の `round()` は偶数丸め） |
| `backend/grids.py` | 並びの検証・保存 | マスの上限をここだけ小さくすると**並びが黙って潰れる** |
| `backend/cache.py` | 検索結果と画像の SQLite キャッシュ | 画像の期限は R2 の掃除（7 日）より短い 6 日。逆にすると 404 が出続ける |
| `backend/storage.py` | R2 の読み書き | `connect_timeout` は 3 秒のまま。長くすると利用者の待ち時間が跳ねる |
| `backend/sources/*` | 各サイトからの取得 | 取れるサイズを URL で選ぶ `clamp_size` を各自が持つ |
| `backend/merge.py` | 出どころ違いの結果をまとめる | 曲名の正規化はブラウザの `nkey()` と**同じ規則**にする |
| `cli.py` | スマホから使うための命令 | サーバーが動いていないと使えない |
| `scripts/` | 点検・突き合わせ・フォント生成 | 下の「変更したら回すもの」に載っているものは必ず回す |
| `promo/` | 紹介動画（Remotion + Playwright） | 詳しくは `video-notes.md` |

### データはどこにあるか

- `grids/<名前>.json` … 並び。公開モードではブラウザごとに `u-<id>.json` に分かれる。**git 管理外**
- `cache.sqlite3` … 検索結果と画像。**デプロイのたびに消える**（コンテナのディスクなので）
- R2 … 共有画像・並びの控え・アップロード画像・フォント断片・画像キャッシュ。7 日で消える
- `outputs/` … CLI で書き出した PNG

## はじめて動かすまで（セットアップ）

何も無い状態から手元で動かす手順。**Windows 前提**（パスは `.venv/Scripts/`。macOS / Linux なら `.venv/bin/`）。

1. **Python 3.14**（本番の Docker が `python:3.14-slim`。3.11 以上なら動くが、本番と揃えるほうが安全）

   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -r requirements.txt
   ```

2. **`.env` を作る**。無くても動く（検索は iTunes と MusicBrainz、保存はローカルの `shares/`）。
   入れると増えるものは次の節の表。最低限の形:

   ```
   MB_USER_AGENT=trackmento/0.1 (https://github.com/あなた/…)    # MusicBrainz は連絡先入りの UA を要求する
   PUBLIC_BASE_URL=auto
   ```

3. **起動**

   ```bash
   PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

   `PYTHONUTF8=1` は必須に近い。付けないと Windows の既定が cp932 で、日本語のタイトルを扱うときに落ちる。

4. **確認**。http://localhost:8000/ を開き、適当なアーティストで検索 → マスに入る →「トラックを共有」で
   画像ができれば一通り動いている。起動ログの `[public] PNG の URL は …` が、返ってくる URL のベース。

- **動画（`promo/`）を触るときだけ** Node と `npm install` が要る。Remotion（React で動画を書く）と
  Playwright（画面を録る）を使う。素材の作り方は `video-notes.md`
- **`scripts/` を動かすとき**も同じ venv を使う。`python` を直に叩くと `.env` が読まれず、
  R2 を見ているつもりでローカルの `shares/` を見ていることがある（下の覚え書き参照）

## 環境変数の一覧

`.env`（手元）と Render のダッシュボード（本番）で設定する。**リポジトリに鍵を書かない**。
`render.yaml` に `sync: false` と書いてあるものは、値をダッシュボードで入れるという意味。

**動きが変わるもの**

| 変数 | 既定 | 何が変わるか |
| --- | --- | --- |
| `PUBLIC_MODE` | 空（ローカル） | 1 で公開モード。CORS を開き、並びをブラウザごとの `u-<id>.json` に分け、ディスクを自動で掃除する。**手元でブラウザ確認するときも 1 を付ける**（付けないと利用者の `grids/default.json` を上書きする） |
| `TRUST_PROXY` | 空 | 1 でプロキシのヘッダ（`CF-Connecting-IP` → `X-Forwarded-For`）から利用者の IP を取る。直接公開しているのに 1 にすると、偽装でレート制限を逃れられる |
| `PUBLIC_BASE_URL` | `auto` | 返す URL のベース。`auto` は LAN IP（ローカル）／リクエストのホスト（公開モード）。本番は固定値にしてある（OG タグが Host ヘッダに振られないように） |
| `CORS_ORIGINS` / `FRONTEND_URL` | 空 | フロントを別ホスト（GitHub Pages）に置く構成のときだけ使う。今の本番は Render が `/` も配信するので未設定 |
| `RATE_LIMIT` | 120 | IP ごとの 1 分あたりの API 上限 |
| `MAX_CELLS` / `MAX_SIDE` | 256 / 2400（公開モード） | マスの総数と、サーバー描画 PNG の最大辺。**`MAX_CELLS` を変えるなら他の 3 か所も**（下の表） |

**R2（Cloudflare）**

| 変数 | 何に使うか |
| --- | --- |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` | 読み書きの鍵。揃っていないと `get_storage()` が黙ってローカルの `shares/` に落ちる |
| `R2_PUBLIC_URL` | 公開 URL（今は `https://img.trackmento.com`）。**CSP の `font-src` / `img-src` / `connect-src` はここから自動で組む**ので、手で書き足さない |
| `R2_ENDPOINT` | 通常は空（アカウント ID から組む） |
| `FONTS_FROM_R2` | 0 でフォントをサーバーから配る（従来の動き）。既定は R2 から |

**画像の中継（`/image-proxy`）**

| 変数 | 既定 | 何が変わるか |
| --- | --- | --- |
| `IMAGE_TO_R2` | 1 | 一度取った画像を R2 に置き、二度目から 302 で R2 へ送る。0 で従来どおり本体を返す |
| `IMAGE_FETCH_TIMEOUT` | 12 秒 | 配信元からの取得の待ち時間。**共有クライアントの 30 秒と分けてある**（遅い 1 本が枠を占有すると全体が詰まる） |
| `IMAGE_PROXY_CONCURRENCY` | 16 | 同時に取りに行く本数 |
| `IMAGE_R2_TASKS_MAX` | 64 | 応答の後ろで走らせる R2 書き込みの上限 |
| `IMAGE_INDEX_MAX` | — | 起動時に読む `imgcache/` の索引の上限 |

**共有の制限**

| 変数 | 本番 | 何が変わるか |
| --- | --- | --- |
| `SHARE_BUDGET_GB` | 9.5 | R2 の使用量の目安。超えると `/share` が 507 を返す |
| `SHARE_LIMIT_PER_DAY` | 200 | 1 日の共有数。**手元の検証では 0（無制限）にする**。本番の共有数を復元すると上限に当たる |
| `SHARE_LIMIT_PER_IP_DAY` | 20 | IP ごとの 1 日の共有数 |
| `SHARE_RETENTION_DAYS` | 7 | 共有ページの表示に使う保存日数（`__RETENTION__` として HTML にも差し込まれる） |

**外部サービスの鍵**（無くても動く）

`DISCOGS_TOKEN`（Discogs 検索。未設定なら候補に出ない）、`LASTFM_API_KEY`、
`ITUNES_PROXY_URL` / `ITUNES_PROXY_TOKEN`（iTunes が国から弾かれるときの迂回）、
`GOOGLE_SITE_VERIFICATION`（Search Console の HTML タグ）、
`RENDER_API_KEY` / `RENDER_SERVICE_NAME`（点検スクリプトが Render の API を叩く）、
`ROXY_CONCURRENCY`（otoDB の roxy への同時接続。既定 3）、
`CHECK_*`（点検の判定しきい値の上書き）。

## 本番はどう動いているか（デプロイ）

- **Render**（`render.yaml` の Blueprint ＋ `Dockerfile`）。`master` に push すると自動でデプロイ。
  ヘルスチェックは `/health`。インスタンスは Standard（`1c_2g`）
- **デプロイのたびにコンテナのディスクが消える**。つまり `cache.sqlite3`（検索結果と画像の対応）も消える。
  そのままだと R2 に画像があるのに配信元から取り直すので、**起動時に `imgcache/` を一覧して索引を作る**
  （`main.py` の `_seed_image_index`。起動ログの `[storage] imgcache の索引: N 件`）。
  一覧は数千件でも 1 回で済み、`head_object` を 1 件ずつ叩くより安い
- **Cloudflare** が前段にいるが、**Web Service の応答はキャッシュしない**（`cf-cache-status: DYNAMIC`）。
  転送量を減らすには R2 へ逃がすしかない、という制約はここから来ている
- **R2 のカスタムドメイン** `img.trackmento.com`。もとは `*.r2.dev` を使っていたが、あちらは
  レート制限があり 256 マスの書き出しで詰まった。ドメインを当ててからは制限が無く、実測で大幅に速くなった。
  **コードの変更は要らず、`R2_PUBLIC_URL` を差し替えるだけ**（CSP も CORS もそこから組む）
- **GitHub Actions**: `render-check.yml`（2 時間おきの点検、異常なら Issue）、`r2-prune.yml`（7 日での掃除）、
  `audit.yml`（依存の脆弱性と起動テスト）、`pages.yml`。`keepalive.yml` は Standard にしてから止めてある

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
  - **公開 URL は独自ドメイン `https://img.trackmento.com`**（2026-09-14 に `pub-….r2.dev` から移した）。
    `r2.dev` は Cloudflare が開発用としていてレート制限があり、256 マスの共有画像を作るときに
    ブラウザからの読み取りが大量に落ちていた（`/image-proxy` が 527 件 → 1402 件に増えた原因）。
    独自ドメインなら制限が無く、**Cloudflare の CDN キャッシュも効く**（`cf-cache-status: HIT`。R2 への読み取り自体が減る）
  - **移し替えはコードを 1 行も変えずに済む**。`R2_PUBLIC_URL` を差し替えるだけで、CSP（`_r2_origin()`）も
    フォントの配信元（`/fonts-css/*`）も画像の 302 先も追従する。URL はすべて `public_url()` で都度組み立てていて、
    どこにも焼き付けていない。本番は Render の環境変数、手元は `.env`
  - **`r2.dev` の公開アクセスはすぐ切らない**。配布済みの共有ページの HTML には古い URL が埋まっている。
    共有は 7 日で消えるので、1 週間経ってから切る
  - `uploads.read_bytes` は R2 に無ければローカルの `uploads/` も見る（手元で R2 を設定した後も、それ以前に保存した画像を読めるように）
- 描画は 2 系統: Web は端末の Canvas で描いて `/share/upload` に送る（`frontend/index.html` の `renderShareCanvas`）。サーバー描画（`backend/render.py`）は CLI と、描けない端末のフォールバック（`/share`）。レイアウト・色・文字の省略規則は両方同じ式。**片方変更時は他方も変更**し、`scripts/compare_render.py` で両方の描画を突き合わせる（差は輪郭のみが正常）。
  手順はスクリプトの docstring。サーバーは `PUBLIC_MODE=1 SHARE_BUDGET_GB=0 SHARE_LIMIT_PER_DAY=0 SHARE_LIMIT_PER_IP_DAY=0` で立てる（R2 が無料枠を超えていると 507、本番の共有数を復元して 1 日上限にも当たる）。
  **見るのは「ぼかし後の差 > 32」**。輪郭のズレはぼかすと消え、マスや文字の位置のズレだけが残る。
  **3px のぼかしで 1% 未満、または 6px で 0.3% 未満**なら正常。マスが少ないと文字が大きく、3px では
  輪郭が消えきらない（2026-09-14 の実測で 4x4 が 1.65%。6px まで掛けると 0.15%、行の位置は完全に一致）。
  16x16 は 0.06%、12x20 は 0.15%、8x8（流し込み）は 0.66%。
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
  - **デプロイのたびに `cache.sqlite3` はコンテナごと消えるが、R2 の `imgcache/` は残る**。SQLite が対応表を忘れるだけで、
    直後は既存の URL が 302 ではなく 200（本体）で返り、配信元から取り直して R2 に上げ直していた（本体 68KB × 件数が
    そのまま Render の転送量になる）。**起動時に `imgcache/` を一覧してメモリに索引を作る**（`main.py` の
    `_seed_image_index` / `_IMG_INDEX`。sha1 の頭 20 桁 → (キー, 最終更新)）。`_image_r2_redirect` は
    SQLite が忘れていても索引で引けるので、デプロイ直後から 302 に戻る
    - **1 件ずつ `head_object` を投げる案より一覧のほうが安い**。本番の `imgcache/` は 5,609 件・371MB・平均 68KB で、
      一覧は 1000 件ごとに 1 回の Class A（6 回）で済む。ミスごとに 1 往復する head 方式だと件数ぶん増える。
      **取得前には分からない拡張子**（jpg 5598 / png 7 / webp 4）を知らなくても引けるのも一覧側の利点
    - 索引の期限も 6 日（`R2_IMAGE_TTL`）。R2 側の掃除 7 日より短い、という上と同じ関係を守る
    - 上限は `IMAGE_INDEX_MAX`（既定 20 万件・約 30MB）。起動を止めないよう一覧は起動後のタスクで回し、失敗は握りつぶす
      （取り直すだけで壊れない）。**索引が載るまで数秒かかる**ので、起動直後のログにはまだ出ない
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
  - **「その動画が消えているか」は otoDB の API だけで分かる**。`/api/work/sources?work_id=N` が返す
    `work_status` が **1 なら削除済み**（生きているものは 0）。`platform` は 1=YouTube / 2=ニコニコ。
    roxy を 1 件ずつ叩かなくても復活のデモに使える動画を探せるので、**候補探しでは roxy を叩かない**
    （検索 `/api/work/search?query=…&limit=30` → work ごとに sources、で足りる）
  - **「有名 × 削除済み」は珍しい**。転載の多い作品は誰かが再アップし続けるので生き残り、
    消えるのは 1 本しか上がっていない作品が多い。2026-09-14 に 75 work を調べて、
    ソースが 5 件以上あって削除済みを含むのは 1 件だけだった（動画の素材探しの結論は `video-notes.md`）
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
  - **`?lang=en` / `?lang=ja` を付けると言語を指定できる**（2026-09-15）。画面（`frontend/index.html`）は
    localStorage にも覚え、共有ページ・案内ページ（`main.py` の `_lang_for`）は Accept-Language より優先する。
    **日本語環境の人に英語の画面を見せるリンクが作れる**（海外向けの案内、動画や SNS からの誘導）。
    例: `https://trackmento.onrender.com/?lang=en`
- 書き出し画像は**四辺に最低でも内容の短辺の 3.5% の余白**を残す（`render.py` の `_frame` と frontend の `frame`）。
  「余白」のスライダーの既定 16px は出力にすると 10px 足らずで、絵が枠に貼り付いて見えた。
  スライダーはそのまま効く（3.5% は下限）。比率合わせで余りが出る辺だけ 4% に広がる、という不揃いも無くなる
- リンクカード（`share.py` の `_og_jpeg` と frontend の `encodeShare`）は 1200×630 で、**四辺に 3% ずつ
  安全代を残す**（`OG_SAFE = 0.94`）。1200×630 は X の summary_large_image の比率だが、受け取る側
  （X の表示位置・Discord・LINE・スマホの幅）で数 % 切られることがあり、いっぱいに収めると端のマスや曲名が欠ける
- **パレット（背景色の 6 色 ＝ 画面の配色）**（2026-09-15）。背景色の見出しの「パレット」ボタンでオーバーレイが開き、
  6 色ひと組を選べる。組み込みは「リソ」（もとからの 6 色）と「ポップ」（色見本から取った 6 色）。自作の組も作れる
  - 組を切り替えると**背景色の見本と画面の装飾色が同時に変わる**。装飾色は `--color-mustard` などの
    6 スロットの中身を差し替える形（36 か所ある参照はそのまま）。**見本だけは固定値で塗る**
    （`var(--color-…)` にすると、組を変えたときに見本の色まで変わってしまう）
  - 自作の組は 16 進で持ち、選ぶと**カスタムカラー**（`bg: "custom"` ＋ `bgCustom`）として保存される。
    描画の仕組みは触っていない。組み込みの色は今までどおり色の名前で保存する
  - **読み込んだ並びの色は、今の組に入っていなくても受け付ける**（`ALL_BG_KEYS`）。別の組の色なら組ごと切り替える。
    ここを今の組だけで見ていたとき、`rose` の共有を開くと `paper` に戻って**サーバー描画と 93% ずれた**
  - 6 色は「コピー」で色コードとして書き出し、貼り付けて読み込める（区切りは何でもよい。6 つちょうど必要）
  - 自作の組の色は、**その色を押すとオーバーレイの中に HSV のつまみが開く**（もう一度押すと閉じる）。
    `input type="color"` は使わない。**OS の色ダイアログは画面を止めるので、動画の撮影でも都合が悪い**
    （カスタムカラーのつまみと同じ部品・同じ操作にそろえてある）
  - 色の値は **`backend/render.py` の TOKENS・frontend の CSS 変数・TOKENS_RGB の 3 か所**にある。片方だけ変えない
- UI デザインは Hallmark 方針（仕様書「UI デザイン方針」）。色・フォントは CSS 変数トークン経由、角丸なし
- 本番の点検: `PYTHONUTF8=1 .venv/Scripts/python scripts/render_check.py --hours 2`（Render API でログ・イベント・帯域・メモリを要約。`.env` の `RENDER_API_KEY`。**手元の `.env` には入っていないので、ローカルで動かすなら Render → Account Settings → API Keys で発行して足す**。GitHub Actions 側は Secrets にある）。`gh workflow run render-check.yml` でいつでも回せる
  - GitHub Actions `render-check.yml` が 2 時間おきに同じ点検を回し、異常時は Issue（ラベル render-check）に書く。ただし **GitHub の cron は大幅に間引かれ、`*/10` 指定でも実測 2〜5 時間おきだった**（`keepalive.yml` の schedule を止めたのはこのため。フリープランに戻すなら外部の監視サービスが要る）
  - `[ua]` は経路ごとの User-Agent 種別（人／プレビュー／検索／AI／その他ボット／不明）の内訳。**生の UA は残さない**（指紋になるため）。
    種別を分けているのは対策が別だから。**「プレビュー」は X などがリンクカードを作るための取得なので止めてはいけない**
    （robots.txt で `/s/` を塞ぐと X のカードが出なくなる）。「検索」「AI」「その他ボット」は robots.txt で減らせる
  - 判定の閾値はインスタンスの種類から出す（`PLAN_SPECS` と `_PLAN_RE`。API は `1c_2g` のような形式を返す）。`CHECK_*` の環境変数で上書きできる
  - 「uptime のリセットがデプロイ回数より多い」は、無停止デプロイ中に新旧プロセスの `[health]` が交互に出るため一度は誤検知していた。5 分以内に続く戻りは同じ入れ替えとしてまとめている
- **検索は既定で iTunes だけ**（2026-09-15 から）。MusicBrainz は「1 秒に 1 リクエスト」の制限があり、
  常に一緒に引くと検索が 2 秒かかっていた（iTunes だけなら 0.06〜0.5 秒。本番実測 2052ms → 58ms）。
  **見つからなかったときだけ MusicBrainz で引き直す**ので、iTunes に無い音源の取りこぼしは埋まる
  - サーバー（`main.py` の `DEFAULT_SOURCES` / `FALLBACK_SOURCE`）: `source` の指定が無くて 0 件なら MusicBrainz。
    **指定があるときは足さない**（利用者が選んだ通りに返す）
  - 画面（`frontend/index.html`）: 選んだソースで 0 件かつ失敗も無いときだけ MusicBrainz を直接引き、
    「iTunes に無かったので MusicBrainz でも探しました。」と添える
  - 画面のソース選択の既定は前から iTunes だけだったので、**遅かったのは `source` を省く呼び出し**（CLI・API）
- 動作確認は各ステップごとブラウザで（`claude-in-chrome` または手動）。サーバー `--reload` なし起動時、コード変更後再起動必要

## 調べ直さないための覚え書き（一度引っかかったもの）

- **Render の「プラン」は 2 つある**。課金アカウントの種別（Billing の Current Plan。Pro など）と、サービスのインスタンスタイプ（サービス画面のバッジ。Free / Standard など）は別物。**ワークスペースが Pro でもインスタンスが Free ならスリープするし 512MB 上限**。混同すると「スリープしないから keepalive は不要」のような誤った判断をする。インスタンスの実体は点検の「インスタンス: `1c_2g`」行か、`unbilled-charges.csv` の Services 行（`charge` が Free なら Free インスタンス）で確認する
- **`Content-Type` を付けずに画像を返す配信元がある**。otoDB の CDN が実際にそうで、200 で中身も画像、
  `Content-Length` も `ETag` もあるのに型だけ無い。ヘッダだけ見て弾いていたため、
  **otoDB のサムネイルが 1 枚も表示できていなかった**（2026-09-14 に気付いて直した。音MAD のジャケットと、
  消えた動画の復活で取れたサムネが全部 415）。`fetch_image` は型が無いときに中身の先頭
  （マジックナンバー）で JPEG / PNG / GIF / WebP を見分ける。**ヘッダを信用しきってはいけない**
- **`/fonts-css/*` は 1 年の immutable で配っているのに、中身は R2 の公開ドメインで変わる**。
  ファイル名は断片の中身から作るので、ドメインを替えても名前は同じまま。**以前来た人のブラウザは
  古い CSS（`r2.dev` を指す）を使い続け、CSP が新しいドメインしか許していないのでフォントが 1 つも読めなくなる**
  （2026-09-14 に本番で実際に起きた。日本語がシステムフォントになり、`document.fonts.load` が失敗するので
  **共有画像もブラウザで作れずサーバー描画に落ちていた**。`/share` の 503「混み合っています」はこれが原因）。
  `<link>` の URL に R2 の公開 URL のハッシュを `?o=` で付けて、ドメインを替えたらキャッシュを踏まないようにしてある
- **曲名リストは 1 行に入らなければ 2 段にする**（`render.py` の `_row_plan` / `_wrap_line`、frontend の `rowPlan` / `wrapLine`）。
  折る位置は「(feat. …)」の手前 → 空白や区切りの記号 → 字の途中、の順。**アーティスト名は必ず残す**
  （以前は長い曲名だとアーティストを丸ごと落としていて、利用者から「アーティスト名が消える」と報告があった）。
  段が増えると行の高さを取り直すので、右サイドバーでは全曲の文字が少し小さくなる。**割り付けは 1 度しか計算しない**
  （小さくした字で計算し直すと、入る・入らないを行き来する）
  - 右サイドバーの幅は**比率で余る幅まで広げる**。高さはグリッドで決まるので、狭くしたぶんは余白になって捨てられるだけ
  - **段は 2 つまで**と決めた（2026-09-14）。3×3・16:9 の実測で 1 行に全角 48 字、2 段で 96 字入る。
    実在する曲名はまず届かない（例の `雨天決行 (feat. 可不, 重音テト & ナースロボ＿タイプT)` が 34 字）。
    3 段まで許すと、1 曲が 3 段取ったとき 9 曲で 11 行ぶんになり**他の 8 曲の文字が 2 割小さくなる**。
    96 字を超える題名だけ 2 段目の末尾を「…」で切る（アーティスト名はそれでも残す）
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
  - 曲名リストの組み方（1 曲 1 行ではないほう）: `render.py` の `_row_plan` / `_plan_rows` / `_split_title` /
    `_sidebar` と frontend の `rowPlan` / `planRows` / `splitTitle` / `sidebar`。2026-09-15 に他サービスを
    参考にして作り直した。**曲名とアーティスト名は上下 2 行**（横に並べると長い曲名でアーティストが押し出される）、
    **文字が小さくなるなら列を増やす**（25 曲で 2 列。出力で何 px になるかで決める。上限 3 列）
    - **サイドバーの幅は文字を測って決めない**。比率があるときは比率から決まる残り幅、無いときはグリッドと同じ幅。
      文字の幅は PIL と Canvas で数 px 違い、幅を実測で決めると**中央寄せのグリッドまで 1〜2px ずれる**
      （突き合わせでグリッド側に 6% の差が出て、原因を探して行き着いた）。16px 刻みに丸める案は、
      境目をまたぐと逆に 16px ずれるので却下
    - 列の間隔は `LIST_COL_GAP`（マスの間隔の 5 倍）。マスと同じ間隔だと隣の列の曲名と近すぎて、
      どちらの列か迷う
    - 曲名が 1 行に入らないときだけ 2 行に折る。**折る位置は「行の真ん中にいちばん近い切れ目」**
      （2 行の長さがそろうように）。「(feat. …)」の手前は少し優遇していて、ちょうどよい位置なら選ばれる。
      2 行目がわずかにはみ出すだけなら**縮めて収める**（0.92 → 0.86 → 0.8）。「…」で切るのは最後
  - 曲名リストの流し込み: `render.py` の `_flow_rows` / `FLOW_*` と frontend の `flowRows` / `FLOW_*`。
    **折り返しは字の単位。ただし両端をそろえること**がずれを抑える鍵。
    字で折ると PIL と Canvas のわずかな計測差で折り返す位置が変わるが、行ごとに右端でそろえていれば
    そこで吸収され、次の行へ積み上がらない（`compare_render.py` のぼかし後の差: 両端そろえ無し 3.19% →
    **両端そろえ有り 0.71%**。基準は 1%）。曲の単位で折れば 0.05% まで下がるが、
    行の頭がいつも番号になって規則的に見えるので採らなかった
    - 余りの配分は**空白 1 つぶんまで**。上限を付けないと、1 行の曲数が少ないときに切れ目が間延びする
    - **曲の切れ目（全角空白 1 つぶん）は必ず描く**。幅だけ取って描かないでいると、余りの無い行で
      曲と曲がくっつく（利用者の画像で「Chevon06 例え話」のように番号が前の曲名に貼り付いていた。
      2026-09-14 に直した）。行末に来た切れ目は数に入れない（使っていない送りを幅に含めると余りの配分がずれる）
    - **折り返しの判定は字幅を 1px に丸めてから行う**。PIL と Canvas の字幅は 1px 未満だけ違い、
      生の値で足すと境目の字で折る・折らないが入れ替わって、そこから先の行が全部ずれる
      （丸める前 2.28% → 丸めた後 0.66%）。描くときは実寸のまま
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

## これまでの経緯（なぜ今の形になったか）

コードだけ見ても分からない「順番」を残す。**多くの作りは、実際に起きた事故への対処**。

- **2026-09-09 — 作り始めから公開まで（1 日）**。iTunes の検索と `/image-proxy` から始め、
  MusicBrainz + Cover Art Archive、Bandcamp、SoundCloud、YouTube / ニコニコ / bilibili / Spotify と
  出どころを足した。見た目は途中で「昔の Macintosh 風」に舵を切り、サイト名も
  トラックグリッド → **TRACKMENTO** に変えた。同じ日に公開運用（SSRF 対策・マス数上限・
  レート制限・共有の容量上限）と R2 への保存まで入れて、Render に出した
- **2026-09-13 — 転送量との戦い**。公開後、Render の転送量が無料枠を大きく超えた。
  調べると**フォントが新規訪問 1 回あたり 210KB**で最も重く、次がジャケット画像だった。
  順に、フォントを R2 から配る → 画像も R2 に置いて二度目から 302 で返す →
  各配信元で小さい版の URL を選ぶ（`clamp_size`）→ otoDB だけサーバー側で縮める、と進めた。
  結果、直近は 1.24 GB/2h → 0.42 GB/2h
- **2026-09-13 — プレイリストと「消えた動画」**。URL を 1 本貼るだけで最大 500 曲入るようにした。
  ニコニコのマイリストは**削除済みの動画も「削除された動画」という題と灰色の画像で返してくる**ので、
  それを見つけて otoDB（音MAD データベース）で差し替える仕組みを足した。otoDB の roxy は
  小さなサービスなので、同時接続を**プロセス全体で 3**に抑え、結果（見つからなかった分も）を 1 日覚える
- **2026-09-13 — 共有ページが 14 秒**。原因は R2 クライアントの `connect_timeout` 10 秒。
  boto3 はリトライ 3 回＋バックオフなので、1 回つながらないだけで待ち時間が跳ねていた。3 秒にして 1.0 秒に
- **2026-09-13〜14 — 英語対応と OS 9 風スクロールバー**。画面は「日本語の文面そのものを鍵にして
  英語を引く」形にした。共有ページだけは**開いた人の Accept-Language** で選ぶ（共有した人の設定ではない）
- **2026-09-14 — 二重実装の総点検**。16×16 の並びが保存した瞬間に 12×12 へ潰れる事故が起きた。
  上限が 4 か所にあり、直し忘れがあったため。これを機に「同じ知識が 2 か所以上にある所」を洗い出して
  一覧にし（下の覚え書き）、描画（`compare_render.py`）と文言（`check_i18n.py`）は
  **突き合わせるスクリプト**を用意した
- **2026-09-14 — デプロイでキャッシュが消える問題**。`cache.sqlite3` はコンテナのディスクなので
  デプロイのたびに消え、R2 に画像があるのに取り直していた。起動時に `imgcache/` を一覧して索引を作って解決
- **2026-09-14 — 独自ドメイン**。`*.r2.dev` のレート制限で 256 マスの書き出しが詰まっていた。
  `trackmento.com` を取り、R2 に `img.trackmento.com` を当てて解消（コードの変更なし）
- **2026-09-14 — Content-Type を付けない配信元**。otoDB の CDN が `Content-Type` を返さないため、
  本番でサムネイルが全部 415 になっていた。**中身の先頭バイトで種類を見分ける**ようにした（`_sniff_image_type`）
- **紹介動画**（`promo/`）。Playwright で実際の画面を録り、Remotion で曲の拍に合わせて並べる。
  日本語・英語 × 縦・横の 4 本。作り方は `video-notes.md`

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
- **書き出し画像へのワードマーク（右下に TRACKMENTO）は入れないと決めた**（2026-09-14）。
  余白は比率合わせで出る余りなので、**並びによって大きさも位置も変わり、常に同じ見え方で置ける場所が無い**。
  初期値オフの設定にしても、オプトインのウォーターマークはまず有効にされないので宣伝としても効かない。
  出どころを知らせたいなら、利用者の画像ではなく **OG カード（1200×630）側に入れる**ほうが筋がよい（未着手）
- **`/s/*` の robots.txt は触らない**と決めた。`[ua]` の実測で人以外アクセスの 71% が「プレビュー」
  （X などのリンクカード生成）だったため。塞ぐと X のカードが出なくなる。検索・AI ボットは合わせて数十件で誤差
- 候補パネルの上限は 500 にしたが、`/search` エンドポイントには `limit` を渡す口が無いので
  **検索結果は今も 30 件のまま**。増やしたくなったら `otodb.search` の offset ページングが使える（実装済み）
- インスタンスは Standard（`1c_2g`、約 $25/月）＋ Workspace Pro（$25/月）。**バズが収まったら下げる判断が要る**
  （メモリは最大 195MB / 2048MB、CPU は最大 0.046 / 1.0 とかなり余っている）

## 直近の数字（2026-09-14 23:30 の点検）

判定は「異常あり」だが**中身は誤検知**（下記）。**フォント修正（21:3x デプロイ）の効果が出た回**。
括弧内は 20:37 の値。

- **`/share`（サーバー描画）が上位の経路から消え、503 も 0 になった**（前回 2 件）。
  残る共有の 503 は `/share/upload` の 2 件だけで、これは受け口の同時本数（`_UPLOAD_SEM` = 3）。
  **フォントが読めずブラウザ描画が落ちていた、という見立ては裏が取れた**
- **`/s/*` の最大応答 1.5 秒**（12.4 → 12.8 秒が 2 回続いていた）。ここも直った
- CPU 最大 0.084、メモリ最大 194MB、`[health] rss` 最大 270MB、エラー行 0、`[loop] lag` 0 行
- 要求: `/grids/*` **9769 件**（6438）、`/image-proxy` **4792 件**（2980）、`/search` **2158 件**（1252）、
  `/s/*` **1623 件**（880）、`/` **1305 件**（1140）、`/from-url` **681 件**（371）。**また 1.5 倍**
- 本日の共有数 **9039 件**（20:37 時点で 5948）
- 帯域: **1.21 GB/2h**（0.66）、最大 0.55 GB/時
- 5xx 12 件。`502 /image-proxy 画像サーバーが 404`（7）、`429`（3）、`503 /share/upload`（2）

### 誤検知だったもの

「uptime のリセットがデプロイ回数より多い（3 回 > 2 回）」は、**窓が始まる直前に終わったデプロイ**が
数に入らなかったため。リセットの時刻（21:31 / 22:07 / 22:18）は自分の push と一致している。
`render_check.py` はイベントを**窓の 20 分前から**取るようにした。

### 次に手を入れるところ（帯域）

**ブラウザが共有画像を描くとき、ジャケットは R2 からではなく Render の本体を通っている**。
`/image-proxy` は二度目以降 R2 へ 302 で送るが、**CORS の fetch が別オリジンへ 302 されると
ブラウザは `Origin: null` で取りに行く**。R2 の CORS は本番と localhost を名指ししているだけなので
`null` に応えず、ブラウザは弾かれて `&direct=1`（本体をそのまま返す）で取り直す。実測:

```
Origin: null                       → Access-Control-Allow-Origin なし（弾かれる）
Origin: https://trackmento.onrender.com → ACAO あり
```

**フォントが直ってブラウザ描画が戻ったぶん、この経路の帯域が増えた**（0.66 → 1.21 GB/2h。
要求数の伸びは 1.5 倍なので、それ以上に増えている）。加えて `direct=1` は SQLite にも無ければ
配信元まで取りに行くので、`502 … 429`（配信元のレート制限）や最大 12.6 秒はここから出ている。

**2026-09-15 00:0x に R2 の CORS の許可オリジンへ `*` を足して直した**（Cloudflare のダッシュボード。
API トークンでは変えられない）。バケットはもともと公開なので、GET を `*` に開いても危険は増えない。
本番のブラウザで 302 を追って R2 から読めることを確認済み。

- **効果が出きるまで 1 日かかる**。Cloudflare は `Vary: Origin` 付きで 1 日キャッシュ（`max-age=86400`）するので、
  **設定前に `Origin: null` で取得して「CORS ヘッダ無し」として覚えられた分**は期限切れまでそのまま返る。
  確かめるときは `?cb=…` を付けてキャッシュを外す（付けずに測って「効いていない」と誤読しかけた）
- 直す前の帯域は **1.21 GB/2h**。ここからどこまで下がるかを次の点検で見る
- コード側で直す手もあった（302 をやめ、R2 の URL をブラウザに教えて直接読ませる。リダイレクトが
  無ければ `Origin` は本番のままなので今の CORS で通る）。**CORS で済んだので入れていない**

### 次回に見るもの

- **`/share/upload` の 503**。2 時間で 5 件を超えたら `_UPLOAD_SEM` を 3 → 8 に上げる（受け取って保存するだけで
  CPU はほぼ使わない。効いている理由は本文を抱えたまま並ぶとメモリが膨らむことだけ）
- **帯域**。上の CORS を直したら下がるはず。直す前の基準が 1.21 GB/2h
- **点検自体が落ちることがある**。09-14 08:25 の実行は Render API への接続が切れて
  `URLError: <urlopen error [Errno 104] Connection reset by peer>` となり、「異常あり」で Issue が立った（#11）。
  直後の再実行は「正常」。**本番の異常と区別がつかないので、Issue を見たらまず再実行する**
