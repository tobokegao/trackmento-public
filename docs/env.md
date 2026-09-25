# 環境変数の一覧

`.env`（手元）と Render のダッシュボード（本番）。**リポジトリに鍵を書かない**。
`render.yaml` の `sync: false` は「値はダッシュボードで入れる」の意味。

（`CLAUDE.md` から分けたもの。2026-09-20。中身は当時のまま）

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
| `IMG_SLOW_TTL` | 300 秒 | 読み取りが時間切れになった画像を覚えて、取りに行かない秒数。つながらなかったとき（`IMG_UNREACHABLE_TTL`、600 秒）より短い（2026-09-25） |
| `IMAGE_PROXY_CONCURRENCY` | 16 | 同時に取りに行く本数 |
| `IMAGE_R2_TASKS_MAX` | 64 | 応答の後ろで走らせる R2 書き込みの上限 |
| `IMAGE_INDEX_MAX` | — | 起動時に読む `imgcache/` の索引の上限 |

**共有の制限**

| 変数 | 本番 | 何が変わるか |
| --- | --- | --- |
| `SHARE_BUDGET_GB` | 120（既定 9.5） | R2 の使用量の目安。超えると `/share` が 507 を返す |
| `SHARE_LIMIT_PER_DAY` | 0＝無制限（公開時の既定 1500） | 1 日の共有数。**手元の検証では 0（無制限）にする**。本番の共有数を復元すると上限に当たる |
| `SHARE_LIMIT_PER_IP_DAY` | 50 | IP ごとの 1 日の共有数（2026-09-19 に 0＝無制限 → 50。`render.yaml`） |
| `SHARE_RETENTION_DAYS` | 30 | 共有ページの表示に使う保存日数（`__RETENTION__` として HTML にも差し込まれる） |

**外部サービスの鍵**（無くても動く）

`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`（Spotify の公式 Web API。**無いと曲名とジャケット 300px だけの
oEmbed に落ち、アーティスト名が空になる。プレイリストはまとめて取れない**。**本番は鍵を入れていない**——開発者登録に Spotify Premium が要るため）、
`YOUTUBE_API_KEY`（YouTube Data API v3。**無いと再生リストをまとめて取れない**。単体の動画は oEmbed なので要らない）、
`DISCOGS_TOKEN`（Discogs 検索。未設定なら候補に出ない）、
`ITUNES_PROXY_URL` / `ITUNES_PROXY_TOKEN`（iTunes が国から弾かれるときの迂回）、
`GOOGLE_SITE_VERIFICATION`（Search Console の HTML タグ）、
`RENDER_API_KEY` / `RENDER_SERVICE_NAME`（点検スクリプトが Render の API を叩く）、
`ROXY_CONCURRENCY`（otoDB の roxy への同時接続。既定 3）、
`CHECK_*`（点検の判定しきい値の上書き）。
