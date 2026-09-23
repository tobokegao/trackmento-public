# TRACKMENTO

「私を構成する9枚」「好きな曲9選」のようなジャケットグリッド画像を、
**曲単位・手動選択・複数の出どころの横断検索**で作る Web ツール。
https://trackmento.com/ で公開している（登録不要・無料）。同じコードを手元の uvicorn でも動かせる。

検索対象は iTunes・MusicBrainz・otoDB（音MAD）・VocaDB（ボカロ）。iTunes に無い音源も、
Bandcamp・SoundCloud・Spotify・Apple Music・YouTube・ニコニコ動画の URL を貼れば拾える
（ニコニコのマイリスト・Bandcamp のプレイリスト・YouTube の再生リスト・Apple Music のプレイリストは最大 500 曲まとめて読める）。
Discogs はトークンを置いたときだけ使える（公開版では使っていない）。
仕様と経緯は `trackmento-spec.md`、作業する人向けのメモは `CLAUDE.md`（詳しい話は `docs/` に分けてある）を参照。
不具合の報告・要望は[お問い合わせフォーム](https://forms.gle/2ktpQAXMjJrkFJFz8)へ。

## セットアップ

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
copy .env.example .env          # Windows（macOS / Linux は cp）。必要なら API キーを記入
```

## 起動

```bash
PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

ブラウザで http://localhost:8000 を開く。開発中は `--reload` を付けると便利。
Windows では `PYTHONUTF8=1` が要る（既定の cp932 だと日本語のタイトルを扱うときに落ちる）。
ブラウザで動作を確かめるときは `PUBLIC_MODE=1` も付ける（付けないと自分の `grids/default.json` を上書きする）。
フォントは `fonts/` に同梱（OFL）しているため、オフラインでも書き出し結果は変わらない。

## CLI（Claude Code / Remote Control から使う）

```bash
.venv/Scripts/python cli.py add --artist "Artist" --title "Song"   # 候補が複数なら番号付きで表示
.venv/Scripts/python cli.py pick --index 2                        # 番号で確定
.venv/Scripts/python cli.py add --url "https://xxx.bandcamp.com/track/..."      # Bandcamp / SoundCloud / Spotify / Apple Music / YouTube / ニコニコ動画
.venv/Scripts/python cli.py add --image "https://.../cover.jpg" --artist "A" --title "T"
.venv/Scripts/python cli.py list
.venv/Scripts/python cli.py move --from 1 --to 3
.venv/Scripts/python cli.py remove --index 2
.venv/Scripts/python cli.py share --ratio 16:9 --sidebar --title "私を構成する9曲"   # 画像 + 共有ページ URL
.venv/Scripts/python cli.py render                                                  # PNG だけ
.venv/Scripts/python cli.py clear
```

`share` / `render` の最後の行は `URL: http://...` となる。`share` は画像（JPEG）と並びのスナップショットを保存し（R2 を設定していなければ `shares/`）、共有ページ（`/s/<id>`）から画像の保存や「TRACKMENTO で開く」ができる。`render` は PNG を `outputs/` に書き出す。
グリッドの状態は `grids/<name>.json` に保存され、Web UI と共有される（Web 側は自動保存＋「サーバーから読み直す」）。
スマホからの運用手順は `CLAUDE.md` を参照。

## 公開する（誰でも使えるようにする）

このアプリは検索の中継・画像プロキシ・共有の保存をサーバー側（FastAPI）で行うため、
**静的ホスティング（GitHub Pages）だけでは動かない**。次のどちらかで公開する。

### A. バックエンドだけを公開する（いちばん簡単。おすすめ）

バックエンドは `/` でフロント（index.html）も配信するので、これ 1 つで完結する。

1. このリポジトリを GitHub に push する（`.env` は含めない）
2. Render（https://render.com）に GitHub でサインアップ → "New → Blueprint" → このリポジトリを選ぶ（`render.yaml` を読み込んで作成される）
3. 作成時に聞かれる環境変数（`sync: false` のもの）に R2 の 5 つの値を入れる。`PUBLIC_MODE` などは `render.yaml` に書いてある。
   `DISCOGS_TOKEN` は入れない（公開版では Discogs を使わない）
4. デプロイが終わったら、できた URL（例 `https://trackmento.com`）を開く。`/health` で `"public": true, "storage": "r2"` なら設定完了
5. 以後は GitHub に push するたびに自動で再デプロイされる

Docker が動くホスト（Fly.io / Railway / Koyeb / Hugging Face Spaces など）でも `Dockerfile` でそのまま動く。
無料プランは一定時間アクセスが無いとスリープし、次のアクセスに 30〜60 秒かかる。

### B. フロントを GitHub Pages に、バックエンドを別ホストに置く

1. A の手順でバックエンドを公開し、環境変数に
   `CORS_ORIGINS=https://<user>.github.io` と `FRONTEND_URL=https://<user>.github.io/<repo>` を追加する
2. GitHub リポジトリの Settings → Pages → Source を **GitHub Actions** にする
3. Settings → Secrets and variables → Actions → **Variables** に `TRACKMENTO_API`（バックエンドの URL）を登録する
4. Actions タブから "Deploy frontend to GitHub Pages" を手動で実行する（`.github/workflows/pages.yml`。
   push で自動公開したいなら、その `push:` トリガーのコメントを外す）
   （手元で試すなら `python scripts/build_pages.py --api https://…` で `dist/` に出る）

### 共有画像を Cloudflare R2 に置く（共有 URL を長持ちさせる）

ホストのディスクは再デプロイで消えるので、共有（画像 + 並びの JSON）は R2 に置くとよい。
R2 の無料枠はストレージ 10GB / 月、書き込み 100 万回、読み出し 1,000 万回で、転送量は無料。
超えたぶんは 1GB あたり月 $0.015（共有画像は 1 件およそ 0.3〜0.5MB）。

1. Cloudflare ダッシュボード → R2 → **Create bucket**（例 `trackmento-shares`。ロケーションは Automatic でよい）
2. バケットの Settings → **Public access** で公開する。**独自ドメインを付ける**のがよい（本番は `https://img.trackmento.com`）。
   `R2.dev subdomain`（`https://pub-xxxx.r2.dev`）は開発用でレート制限があり、マスの多い共有画像を作るときに読み込みが詰まった。
   この公開 URL が `R2_PUBLIC_URL`
3. 古い共有は `scripts/r2_prune.py` で消す（GitHub Actions の `r2-prune.yml`。既定は 720 時間＝30 日。
   画像の控え `imgcache/` と検索結果の控え `searchcache/` は 7 日）。R2 のライフサイクル規則は使わない
   （規則はプレフィックスでしか対象を選べず、共有のファイル名はランダムなので絞れないため）。
   Actions の Secrets に `R2_ACCOUNT_ID` などを入れておく
4. R2 → **Manage R2 API Tokens** → Create API token → 権限 "Object Read & Write"、対象バケットをこのバケットに限定
   → 表示される Access Key ID / Secret Access Key と、R2 の概要ページにある Account ID を控える
5. バックエンドの環境変数に `R2_ACCOUNT_ID` `R2_ACCESS_KEY_ID` `R2_SECRET_ACCESS_KEY` `R2_BUCKET` `R2_PUBLIC_URL` を入れて再起動
   → 起動ログに `[storage] 共有の保存先: r2` と出れば有効

- 共有画像は `R2_PUBLIC_URL` から直接配信される。フォントの分割ファイルと、一度取得したジャケット画像の控え（2 回目からは R2 へ転送）も R2 から配る（Render の転送量を減らすため）
- 手元（ローカル）でも `.env` に同じ変数を書けば R2 を使う。無ければ従来どおり `shares/` に保存する
- **無料枠を超えないための上限**（環境変数で変更可）:
  `SHARE_BUDGET_GB`（既定 9.5。本番は 120）… 共有ファイルの合計が実バイト数でこれを超える保存は断る（バケットの使用量は裏で 10 分ごとに数え、保存のたびに加算）。
  `SHARE_LIMIT_PER_IP_DAY`（公開時の既定 100。本番は 50）/ `SHARE_LIMIT_PER_DAY`（公開時の既定 1500。本番は 0＝無制限）… 1 日の共有回数。0 で無制限。
  `MAX_SIDE`（公開時の既定 2400px）… 共有画像の最大辺。スマホなど指で触る端末とメモリの少ない端末は 2000px で描く。共有画像は JPEG（品質 0.78）で、
  リンクカード用の 1200×630 JPEG はサーバーが本体から作る
- 共有のほか、手入力用のアップロード画像と、検索結果の控え（`searchcache/`。VocaDB などサーバーで引いた結果をデプロイ後も使い回す。
  名前は HMAC で作り、中身に検索語を入れない）も R2 に置く

### 公開モード（PUBLIC_MODE=1）で変わること

- グリッドの保存名がブラウザごとのランダム ID になり、利用者同士で混ざらない（`/grids` の一覧も出さない）
- CORS を `CORS_ORIGINS` のオリジンに開く（未設定なら `*`）
- API に IP ごとのレートリミット（既定 120 回/分。`RATE_LIMIT` で変更）
- `shares/`（共有 PNG+JSON。R2 を使わないとき）と `uploads/` は新しい 2000 件だけ残し、`grids/` の 90 日更新の無いものは消す
- 共有ページの「TRACKMENTO で開く」は `FRONTEND_URL` に戻る

### 各サービスの利用条件（2026-09-20 に全サービスの公式ページと robots.txt を再確認。公開運用の前に必ず原文を読むこと）

| ソース | 取得方法 | 公式条件の要点 | 多人数公開でのリスク |
|---|---|---|---|
| iTunes Search API | 公式 API（キー不要） | 約 20 回/分。アートワークは iTunes/Apple Music への購入リンク（バッジ）と併せて表示する前提。「販促目的にのみ使う」 | **中**。コラージュ画像への利用は本来の用途（販促）から外れる。1 サーバーからの 20 回/分は複数人で共有するとすぐ足りなくなる |
| MusicBrainz / Cover Art Archive | 公式 API（キー不要） | 1 回/秒（IP ごと）、連絡先入りの User-Agent 必須。CAA の画像は権利者のもの（CC ではない）。CAA 自体にレート制限は無い | **低〜中**。1 回/秒はサーバー全体で共有。画像の権利は各作品の権利者 |
| Discogs | 公式 API（トークン必要） | 60 回/分。「Data provided by Discogs」と非提携の注意書きを表示する義務。Content は 6 時間より古いものを表示しない・必要以上に保持しない。**画像は Restricted Data**（第三者への譲渡・商用利用が不可） | **高**。生成 PNG に Discogs 画像を含めて配布することは Restricted Data の譲渡にあたる可能性。公開時は Discogs をオフにするか、Discogs 画像を PNG に含めない対応を検討 |
| Bandcamp | ページの og:image / JSON-LD を読む（非公式） | コンテンツの利用許諾は「個人的・非商用」。**Acceptable Use Policy が scraper を名指しで禁止**している一方、曲メタデータの公開 API が無く正規の口が無い | **高**（2026-09-20 に使い方を書いて問い合わせ中・返答待ち）。手元で使う分には実害が小さいが、公開サービスからの自動取得は想定外 |
| SoundCloud | 曲ごとの URL のみ oEmbed（公式・キー不要）。セットの一括読み込みは 2026-09-20 に廃止（内部 API が要り、API Terms §10 の scraping 禁止に触れるため） | アップローダーと SoundCloud のクレジット、元の音源へのリンク表示が必須。ユーザーコンテンツの永続保存・ダウンロード機能は不可 | **中**。アートワークを PNG に焼き込む行為は「永続保存」に近い |
| Spotify | 公式 Web API（Client Credentials）。鍵が無ければ公式 oEmbed（曲名とジャケット 300px のみ・アーティスト名は返らない） | Developer Terms IV.2.4 が robot / spider による取得を禁止し、robots.txt も `Disallow: /embed/`。メタデータ／カバーアートは Spotify へのリンクと帰属表示が必須、単独製品として提供不可。2026 年 2 月から開発者アプリの登録に Spotify Premium が要る | **低**（2026-09-20 に公式 API へ移した。本番は鍵なしなので oEmbed の経路で動く） |
| YouTube | 単体は oEmbed（公式）+ i.ytimg.com のサムネイル、再生リストは Data API v3（`playlistItems.list`。`YOUTUBE_API_KEY` が要る） | API Services 以外でのデータ取得禁止、保存は 30 日まで、YouTube ブランド表示と利用規約リンクが必須。1 日 10,000 ユニット | **中**（2026-09-20 に自動取得を Data API へ移した）。サムネイルを PNG に焼き込む用途は想定外 |
| ニコニコ動画 | getthumbinfo（公式・公開） | 規約に禁止条項は無いが、robots.txt の `Disallow: /api/` が getthumbinfo を覆う。Snapshot API は非営利限定で代わりにならない | **中**（2026-09-20 に現状維持と判断。人が貼ったときだけ 1 件・1 週間キャッシュ） |
| bilibili | **bilibili には問い合わせない**。動画の URL は otoDB（roxy）か VocaDB（byPv）に登録があるものだけ取る（2026-09-24。2026-09-20〜23 は対応をやめていた）。収藏夹と短縮 URL は不可 | 利用者規約 4.2.11 が自動プログラムによる取得に事前の書面許可を要求し、`api.bilibili.com` の robots.txt も全面 Disallow | **低**（bilibili へは通信しない。登録の無い動画は手入力＋リンク先の URL で並べられる） |
| otoDB / roxy | 公式 API（キー不要） | コミュニティ運営。roxy は MIT。データの利用条件は otoDB の運営に確認。問い合わせの頻度は運営から「問題ない」と返答済み（2026-09-13） | **低〜中** |
| VocaDB | 公式 API（キー不要） | データベースの内容は CC BY（商用も可。取り込んだら VocaDB へのリンクを付ける）。利用者が上げた画像（ジャケットなど）は対象外。API は応答のキャッシュと独自の User-Agent を勧め、**事前の許可なく 1 日数千件を超える問い合わせはサービス妨害とみなし、IP を締め出すことがある**（2026-09-20 に確認） | **低〜中**。2026-09-20 に運営へ問い合わせ、「この量なら問題ない・間隔を空けてほしい」と返答を得た。受けて同時 2 本・0.5 秒間隔に制限済み（CORS の許可は先方で検討中） |
| Apple Music | 単曲・アルバムは iTunes Lookup API（公式・キー不要）、プレイリストはページに埋まったデータを読む（非公式） | Lookup API は iTunes Search API と同じ条件（要確認） | 単曲・アルバムは **中**（iTunes と同じ）、プレイリストは **高**（規約外の可能性） |

このリポジトリでは Discogs の帰属表示（フッターと候補のバッジ）と 6 時間キャッシュ、YouTube サムネイルの 24 時間キャッシュ、
画面のフッターの「ソース」から各取得元（Apple Music・MusicBrainz・otoDB・VocaDB）へのリンクを実装済み
（2026-09-20。CC BY がリンクを求めている VocaDB を含む）。取得方法も 2026-09-20 に各サービスの規約へ合わせて見直した
（Spotify と YouTube は公式 API へ、SoundCloud のセットと bilibili は対応をやめた。bilibili は 2026-09-24 に otoDB・VocaDB 経由で戻した）。
それ以外（ブランド表示など）は公開者の判断で対応すること。
**個人が手元で使う範囲では問題になりづらいが、不特定多数向けの公開サービスとして各サービスの画像を集めて画像を配布する行為は、
多くのサービスの想定外**である。公開するなら「自分と友人向け」「iTunes / MusicBrainz / otoDB と手入力に絞る」などの線引きを勧める。

### 公開前に知っておくこと（セキュリティ・運用）

- Discogs のトークンはサーバー側にだけ置く（フロントには出ない）。MusicBrainz は `MB_USER_AGENT` に連絡先を入れる決まり
- 外部 URL の取得（画像プロキシ・描画・Bandcamp などのページ取得）は `backend/netguard.py` で私設アドレス宛てとそこへのリダイレクトを拒否する（SSRF 対策）
- アップロードと描画の画像は Pillow で開けるものだけ、2,400 万ピクセルまで（展開爆弾対策。約 4900×4900）。SVG は受け付けない
- 公開モードでは 1 枚あたり `MAX_CELLS`（既定 256。1 辺は 32 まで）マスまで、API は IP ごと `RATE_LIMIT` 回/分。プロキシの後ろでは `TRUST_PROXY=1`
- ホストのディスクは再デプロイで消える。`cache.sqlite3`（検索結果と画像の対応）は消えてよい前提で、残したいもの（共有・アップロード画像・画像と検索結果の控え）は R2 に置く
- 共有 ID とアップロード名はランダムなので推測しづらいが、URL を知っている人は誰でも見られる（公開範囲の概念は無い）
- 応答ヘッダ: CSP（スクリプトはサーバーが埋めた nonce 付きのものだけ、画像は同一オリジンと https と data:/blob:、接続は同一オリジンと検索 API（iTunes / MusicBrainz / Cover Art Archive / archive.org / mzstatic）と R2 だけ）、HSTS（公開モードの https）、nosniff、X-Frame-Options
- 入力の上限: JSON ボディ 1MB・アップロード 16MB（Content-Length 必須）、検索語 200 文字、URL 2048 文字、曲名など 300 文字、控え（stash）200 曲。公開モードでは `nocache` を無視し、`/render` を閉じる（`/share` を使う）
- Track の `image` は https?:// か /uploads/（とジャケット無しの /no-cover.png）だけ、`external_url` / `thumb` は https?:// だけ受け付ける（共有を読み込んだ他人のブラウザで `javascript:` が開かないように）
- グリッド JSON は 90 日更新の無いものに加えて件数（5,000）でも古い順に消す。Docker は非 root ユーザーで動かす。`PUBLIC_BASE_URL` を固定して Host ヘッダに依存しない
- SSRF 対策は DNS ピンニング付き: 名前解決で得た公開 IP にそのまま接続し、Host ヘッダと TLS の SNI に元のホスト名を渡す（証明書もそのホスト名で検証）。検査と接続の間に DNS の応答を変える rebinding は効かない。リダイレクトは 1 ホップごとに再検査・再ピン
- 依存パッケージは `requirements.txt` で固定し、Dependabot（`.github/dependabot.yml`）が毎週 pip / Docker ベースイメージ / Actions の更新 PR を出す。`audit.yml` が pip-audit（既知の脆弱性）と公開モードの起動テストを毎週と push / PR のたびに実行する。PR をマージすると Render が自動デプロイする

### サーバーの常時稼働と点検

- 本番は Render の有料インスタンス（Standard）で動かしていて、眠らない。無料プランは 15 分アクセスが無いと眠り、次の 1 回目に 30〜60 秒かかる
- `.github/workflows/keepalive.yml` は schedule を止めてある。GitHub の cron は大幅に間引かれ、10 分おきの指定でも実際は 2〜5 時間おきにしか動かず、
  起こしておく役に立たなかった。無料プランに戻すなら GitHub の外の監視サービス（UptimeRobot など）から `/health` を叩く
- `/health` は Render のヘルスチェック用。Web の接続確認は `/status`（同じ内容）を使う。広告ブロッカーの遮断リスト（EasyPrivacy）に
  旧アドレスの `||onrender.com/health` が載っていて、`/health` への fetch が遮断されていたため
- ディスクはデプロイ・再起動のたびに初期化される（`grids/`・`cache.sqlite3`・`uploads/` が消える）。起動後に R2 の `imgcache/`・`searchcache/`・`listed/` を
  一覧して索引を作り直すので、画像の転送と検索結果はデプロイ直後から控えを使える。それでも**小さな修正はまとめて push する**。
  `/health` の `started_at` で最後の初期化時刻が分かる
- `render.yaml` の `buildFilter` で、サーバーに関係するファイル（`backend/`・`frontend/`・`fonts/` など）が変わったときだけデプロイする
- 本番の点検: `.github/workflows/render-check.yml` が 2 時間おきに `scripts/render_check.py`（Render の API でログ・帯域・メモリを要約）を回し、
  異常なら Issue を立てる。手元なら `.venv/Scripts/python scripts/render_check.py --hours 2`（`RENDER_API_KEY` が要る）
- GitHub の cron は、リポジトリに 60 日間 push が無いと止まる。止まったら Actions タブから再有効化する

### 定期点検（/site-safety-check）

- Claude Code で `/site-safety-check` と打つと、`.claude/skills/site-safety-check/SKILL.md` の手順で点検する。自動部分は
  `.venv/Scripts/python scripts/safety_check.py https://trackmento.com`（引数無しでローカル）。応答ヘッダ・SSRF・入力上限・XSS・
  アップロードのメタデータ・共有 JSON・robots/sitemap を 36 項目見て、NG があれば終了コード 1
- 検査で共有 1 件と画像 1 枚を作り、R2 の資格情報があれば最後に消す。検査用グリッド `u-safetycheck0000` はサーバー側に残るが 90 日で消える

### 利用者のプライバシー（何を保存し、何を保存しないか）

- IP アドレスは保存しない。レートリミットと共有回数の集計はプロセス限りの乱数と混ぜたハッシュで数える。Docker（Render）では uvicorn のアクセスログ（IP と検索語入り URL）を出さない（`--no-access-log`）
- アップロード画像は再エンコードして保存する。EXIF（位置情報・撮影日時・機種）、ICC、コメント、PNG のテキストは残さない。長辺 2048px まで縮め、名前はランダム
- 共有 JSON にはブラウザごとのグリッド ID（`name`）と `savedAt` を入れない（同じ人の共有を突き合わせたり、そのグリッドを読み書きされたりしないため）
- 貼られた URL の `?si=…` などのクエリは外して保存する（SoundCloud / Bandcamp）。YouTube・ニコニコ・Spotify は正規 URL に直す
- 動画サムネイル・Bandcamp・SoundCloud・アップロード画像は `/image-proxy` 経由で配るので、利用者のブラウザが YouTube などに直接つながることはない。例外は iTunes と MusicBrainz で、**検索**はブラウザから iTunes Search API / MusicBrainz API / Cover Art Archive（archive.org）を直接叩き（サーバーの共有 IP が Apple に遮断され、MusicBrainz にレート制限されるため）、その**ジャケット画像**も配信元（mzstatic.com / archive.org）から直接読む（同じ相手先なので露出は増えず、サーバーの負荷を大きく減らせる）。検索語と利用者の IP が Apple・MetaBrainz・Internet Archive に渡る。共有 PNG は R2 の公開 URL から配る（Cloudflare が閲覧者の IP を見る）
- 検索キャッシュ（`cache.sqlite3`）には検索語と結果を保存するが、誰が検索したかは持たない。R2 に置く検索結果の控え（`searchcache/`）は、
  名前を秘密の鍵付きのハッシュ（HMAC）で作り、中身に検索語を入れない（R2 は公開ドメインから読めるので、素のハッシュだと「この語が検索されたか」を確かめられてしまう）
- 画面は、ブラウザ側で起きた失敗（共有の送信が止まった・描画に失敗した など）の**種類と回数だけ**を `/hiccup` に送る。曲名・検索語・URL は送らない

## 構成

```
backend/                FastAPI。検索 /search、URL /from-url・/from-playlist、画像 /image-proxy・/image-r2、並び /grids、
                        共有 /share・/share/upload・/s/<id>、探す /find、案内 /guide・/privacy・/about・/updates、/health
backend/sources/        iTunes / MusicBrainz / otoDB（音MAD） / VocaDB（ボカロ） / Discogs と、URL 貼付
                        （Bandcamp / SoundCloud / Spotify / Apple Music / YouTube / ニコニコ動画、プレイリスト）
backend/merge.py        出どころの違う結果を 1 つにまとめる（重複を消す）
backend/cache.py        SQLite キャッシュ（検索結果・画像）→ cache.sqlite3
backend/searchcache.py  検索結果の控えを R2 にも置く（デプロイで消えないように）
backend/storage.py      R2 の読み書き（設定が無ければローカルの shares/）
backend/grids.py        並びの検証と保存（grids/<名前>.json）
backend/render.py       サーバー側の描画（CLI と、ブラウザで描けない端末のため。ふだんは端末の Canvas で描いて /share/upload に送る）
backend/share.py        共有（画像 + 並びのスナップショット + 共有ページ）
backend/shareindex.py   「みんなのグリッド」の索引（共有するときに「載せる」を選んだものだけ）
backend/pages.py        使い方・プライバシーポリシー・運営者・更新情報のページ
backend/uploads.py      手入力用の画像アップロード
backend/netguard.py     外部 URL の取得の検査（SSRF 対策）
backend/main.py         経路・CSP・画像の中継・ログ・起動処理
cli.py                  add / pick / search / list / move / remove / share / render / clear / grids
frontend/index.html     画面（単一 HTML。CSS も JS も 1 枚）
fonts/                  同梱フォント（OFL）。Web 用の分割ファイルは fonts/split/
outputs/                CLI の PNG（/outputs/ で配信。OUTPUTS_KEEP 世代を保持）
grids/                  作業中の並び（CLI と Web で共有）
scripts/                点検・描画の突き合わせ・フォント生成・R2 の掃除
promo/                  紹介動画（Remotion + Playwright）
```

## 環境変数

`.env.example` を参照（全部の一覧と既定値は `docs/env.md`）。`DISCOGS_TOKEN` は任意（Discogs を使うなら必須）、`MB_USER_AGENT` は MusicBrainz を使うなら必須（連絡先を入れる）。
`PUBLIC_BASE_URL` は返す URL のベース。`auto` にすると LAN IP を自動検出する（スマホから開くならこれ）。公開するときは固定の URL にする。

### 検索エンジンに載せる（公開サイト）

- `/robots.txt`（トップだけ許可、API・画像・共有は除外）と `/sitemap.xml` を配る。共有ページ `/s/…` は 30 日で消えるので `noindex`
- Google に載せるには [Search Console](https://search.google.com/search-console) で URL プレフィックス型のプロパティ（`https://trackmento.com/`）を追加し、
  所有権の確認方法に「HTML タグ」を選ぶ。表示される `content="…"` の値を環境変数 `GOOGLE_SITE_VERIFICATION` に入れて再デプロイすると、
  トップページに確認タグが出る。確認後、「URL 検査」→「インデックス登録をリクエスト」でクロールを頼める（反映は数日〜数週間）
- 新しいサイトは、外部からリンクされるまで検索結果に出づらい。自分のサイト（tobokegao.github.io）や SNS のプロフィールからリンクを張ると早い
