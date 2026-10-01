# 環境変数の一覧

`.env`（手元）とRenderのダッシュボード（本番）。**リポジトリに鍵を書かない**。
`render.yaml` の `sync: false` は「値はダッシュボードで入れる」の意味。

（`CLAUDE.md` から分けたもの。2026-09-20。中身は当時のまま）

## 環境変数の一覧

`.env`（手元）とRenderのダッシュボード（本番）で設定する。**リポジトリに鍵を書かない**。
`render.yaml` に `sync: false` と書いてあるものは、値をダッシュボードで入れるという意味。

**動きが変わるもの**

| 変数 | 既定 | 何が変わるか |
| --- | --- | --- |
| `PUBLIC_MODE` | 空（ローカル） | 1で公開モード。CORSを開き、並びをブラウザごとの `u-<id>.json` に分け、ディスクを自動で掃除する。**手元でブラウザ確認するときも1を付ける**（付けないと利用者の `grids/default.json` を上書きする） |
| `TRUST_PROXY` | 空 | 1でプロキシのヘッダ（`CF-Connecting-IP` → `X-Forwarded-For`）から利用者のIPを取る。直接公開しているのに1にすると、偽装でレート制限を逃れられる |
| `PUBLIC_BASE_URL` | `auto` | 返すURLのベース。`auto` はLAN IP（ローカル）／リクエストのホスト（公開モード）。本番は固定値にしてある（OGタグがHostヘッダに振られないように） |
| `CORS_ORIGINS` / `FRONTEND_URL` | 空 | フロントを別ホスト（GitHub Pages）に置く構成のときだけ使う。今の本番はRenderが `/` も配信するので未設定 |
| `RATE_LIMIT` | 120 | IPごとの1分あたりのAPI上限 |
| `MAX_CELLS` / `MAX_SIDE` | 256 / 2400（公開モード） | マスの総数と、サーバー描画PNGの最大辺。**`MAX_CELLS` を変えるなら他の3か所も**（下の表） |

**R2（Cloudflare）**

| 変数 | 何に使うか |
| --- | --- |
| `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` | 読み書きの鍵。揃っていないと `get_storage()` が黙ってローカルの `shares/` に落ちる |
| `R2_PUBLIC_URL` | 公開URL（今は `https://img.trackmento.com`）。**CSPの `font-src` / `img-src` / `connect-src` はここから自動で組む**ので、手で書き足さない |
| `R2_ENDPOINT` | 通常は空（アカウントIDから組む） |
| `FONTS_FROM_R2` | 0でフォントをサーバーから配る（従来の動き）。既定はR2から |

**画像の中継（`/image-proxy`）**

| 変数 | 既定 | 何が変わるか |
| --- | --- | --- |
| `IMAGE_TO_R2` | 1 | 一度取った画像をR2に置き、二度目から302でR2へ送る。0で従来どおり本体を返す |
| `IMAGE_FETCH_TIMEOUT` | 12秒 | 配信元からの取得の待ち時間。**共有クライアントの30秒と分けてある**（遅い1本が枠を占有すると全体が詰まる） |
| `IMG_SLOW_TTL` | 300秒 | 読み取りが時間切れになった画像を覚えて、取りに行かない秒数。つながらなかったとき（`IMG_UNREACHABLE_TTL`、600秒）より短い（2026-09-25） |
| `IMAGE_PROXY_CONCURRENCY` | 16 | 同時に取りに行く本数 |
| `IMAGE_R2_TASKS_MAX` | 64 | 応答の後ろで走らせるR2書き込みの上限 |
| `IMAGE_INDEX_MAX` | — | 起動時に読む `imgcache/` の索引の上限 |

**共有の制限**

| 変数 | 本番 | 何が変わるか |
| --- | --- | --- |
| `SHARE_BUDGET_GB` | 120（既定9.5） | R2の使用量の目安。超えると `/share` が507を返す |
| `SHARE_LIMIT_PER_DAY` | 0＝無制限（公開時の既定1500） | 1日の共有数。**手元の検証では0（無制限）にする**。本番の共有数を復元すると上限に当たる |
| `SHARE_LIMIT_PER_IP_DAY` | 50 | IPごとの1日の共有数（2026-09-19に0＝無制限 → 50。`render.yaml`） |
| `SHARE_RETENTION_DAYS` | 30 | 共有ページの表示に使う保存日数（`__RETENTION__` としてHTMLにも差し込まれる） |

**外部サービスの鍵**（無くても動く）

`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`（Spotifyの公式Web API。**無いと曲名とジャケット300pxだけの
oEmbedに落ち、アーティスト名が空になる。プレイリストはまとめて取れない**。**本番は鍵を入れていない**——開発者登録にSpotify Premiumが要るため）、
`YOUTUBE_API_KEY`（YouTube Data API v3。**無いと再生リストをまとめて取れない**。単体の動画はoEmbedなので要らない）、
`DISCOGS_TOKEN`（Discogs検索。未設定なら候補に出ない）、
`ITUNES_PROXY_URL` / `ITUNES_PROXY_TOKEN`（iTunesが国から弾かれるときの迂回）、
`GOOGLE_SITE_VERIFICATION`（Search ConsoleのHTMLタグ）、
`RENDER_API_KEY` / `RENDER_SERVICE_NAME`（点検スクリプトがRenderのAPIを叩く）、
`ROXY_CONCURRENCY`（otoDBのroxyへの同時接続。既定3）、
`CHECK_*`（点検の判定しきい値の上書き）。
