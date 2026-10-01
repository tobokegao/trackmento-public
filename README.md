# TRACKMENTO

「私を構成する9枚」「好きな曲9選」のようなジャケットグリッド画像を、
**曲単位・手動選択・複数の出どころの横断検索**で作るWebツール。
https://trackmento.com/ で公開している（登録不要・無料）。同じコードを手元のuvicornでも動かせる。

検索対象はiTunes・MusicBrainz・otoDB（音MAD）・VocaDB（ボカロ）。iTunesに無い音源も、
Bandcamp・SoundCloud・Spotify・Apple Music・YouTube・ニコニコ動画のURLを貼れば拾える
（ニコニコのマイリスト・Bandcampのプレイリスト・YouTubeの再生リスト・Apple Musicのプレイリストは最大500曲まとめて読める）。
Discogsはトークンを置いたときだけ使える（公開版では使っていない）。
仕様と経緯は `trackmento-spec.md`、作業する人向けのメモは `CLAUDE.md`（詳しい話は `docs/` に分けてある）を参照。
不具合の報告・要望は[お問い合わせフォーム](https://forms.gle/2ktpQAXMjJrkFJFz8)へ。

## セットアップ

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
copy .env.example .env          # Windows（macOS / Linuxはcp）。必要ならAPIキーを記入
```

## 起動

```bash
PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

ブラウザでhttp://localhost:8000を開く。開発中は `--reload` を付けると便利。
Windowsでは `PYTHONUTF8=1` が要る（既定のcp932だと日本語のタイトルを扱うときに落ちる）。
ブラウザで動作を確かめるときは `PUBLIC_MODE=1` も付ける（付けないと自分の `grids/default.json` を上書きする）。
フォントは `fonts/` に同梱（OFL）しているため、オフラインでも書き出し結果は変わらない。

## CLI（Claude Code / Remote Controlから使う）

```bash
.venv/Scripts/python cli.py add --artist "Artist" --title "Song"   # 候補が複数なら番号付きで表示
.venv/Scripts/python cli.py pick --index 2                        # 番号で確定
.venv/Scripts/python cli.py add --url "https://xxx.bandcamp.com/track/..."      # Bandcamp / SoundCloud / Spotify / Apple Music / YouTube / ニコニコ動画
.venv/Scripts/python cli.py add --image "https://.../cover.jpg" --artist "A" --title "T"
.venv/Scripts/python cli.py list
.venv/Scripts/python cli.py move --from 1 --to 3
.venv/Scripts/python cli.py remove --index 2
.venv/Scripts/python cli.py share --ratio 16:9 --sidebar --title "私を構成する9曲"   # 画像 + 共有ページURL
.venv/Scripts/python cli.py render                                                  # PNGだけ
.venv/Scripts/python cli.py clear
```

`share` / `render` の最後の行は `URL: http://...` となる。`share` は画像（JPEG）と並びのスナップショットを保存し（R2を設定していなければ `shares/`）、共有ページ（`/s/<id>`）から画像の保存や「TRACKMENTOで開く」ができる。`render` はPNGを `outputs/` に書き出す。
グリッドの状態は `grids/<name>.json` に保存され、Web UIと共有される（Web側は自動保存＋「サーバーから読み直す」）。
スマホからの運用手順は `docs/cli.md` を参照。

## 公開する（誰でも使えるようにする）

このアプリは検索の中継・画像プロキシ・共有の保存をサーバー側（FastAPI）で行うため、
**静的ホスティング（GitHub Pages）だけでは動かない**。次のどちらかで公開する。

### A. バックエンドだけを公開する（いちばん簡単。おすすめ）

バックエンドは `/` でフロント（index.html）も配信するので、これ1つで完結する。

1. このリポジトリをGitHubにpushする（`.env` は含めない）
2. Render（https://render.com）にGitHubでサインアップ → "New → Blueprint" → このリポジトリを選ぶ（`render.yaml` を読み込んで作成される）
3. 作成時に聞かれる環境変数（`sync: false` のもの）にR2の5つの値を入れる。`PUBLIC_MODE` などは `render.yaml` に書いてある。
   `DISCOGS_TOKEN` は入れない（公開版ではDiscogsを使わない）
4. デプロイが終わったら、できたURL（例 `https://trackmento.com`）を開く。`/health` で `"public": true, "storage": "r2"` なら設定完了
5. 以後はGitHubにpushするたびに自動で再デプロイされる

Dockerが動くホスト（Fly.io / Railway / Koyeb / Hugging Face Spacesなど）でも `Dockerfile` でそのまま動く。
無料プランは一定時間アクセスが無いとスリープし、次のアクセスに30〜60秒かかる。

### B. フロントをGitHub Pagesに、バックエンドを別ホストに置く

1. Aの手順でバックエンドを公開し、環境変数に
   `CORS_ORIGINS=https://<user>.github.io` と `FRONTEND_URL=https://<user>.github.io/<repo>` を追加する
2. GitHubリポジトリのSettings → Pages → Sourceを **GitHub Actions** にする
3. Settings → Secrets and variables → Actions → **Variables** に `TRACKMENTO_API`（バックエンドのURL）を登録する
4. Actionsタブから "Deploy frontend to GitHub Pages" を手動で実行する（`.github/workflows/pages.yml`。
   pushで自動公開したいなら、その `push:` トリガーのコメントを外す）
   （手元で試すなら `python scripts/build_pages.py --api https://…` で `dist/` に出る）

### 共有画像をCloudflare R2に置く（共有URLを長持ちさせる）

ホストのディスクは再デプロイで消えるので、共有（画像 + 並びのJSON）はR2に置くとよい。
R2の無料枠はストレージ10GB / 月、書き込み100万回、読み出し1,000万回で、転送量は無料。
超えたぶんは1GBあたり月 $0.015（共有画像は1件およそ0.3〜0.5MB）。

1. Cloudflareダッシュボード → R2 → **Create bucket**（例 `trackmento-shares`。ロケーションはAutomaticでよい）
2. バケットのSettings → **Public access** で公開する。**独自ドメインを付ける**のがよい（本番は `https://img.trackmento.com`）。
   `R2.dev subdomain`（`https://pub-xxxx.r2.dev`）は開発用でレート制限があり、マスの多い共有画像を作るときに読み込みが詰まった。
   この公開URLが `R2_PUBLIC_URL`
3. 古い共有は `scripts/r2_prune.py` で消す（GitHub Actionsの `r2-prune.yml`。既定は720時間＝30日。
   画像の控え `imgcache/` と検索結果の控え `searchcache/` は7日）。R2のライフサイクル規則は使わない
   （規則はプレフィックスでしか対象を選べず、共有のファイル名はランダムなので絞れないため）。
   ActionsのSecretsに `R2_ACCOUNT_ID` などを入れておく
4. R2 → **Manage R2 API Tokens** → Create API token → 権限 "Object Read & Write"、対象バケットをこのバケットに限定
   → 表示されるAccess Key ID / Secret Access Keyと、R2の概要ページにあるAccount IDを控える
5. バックエンドの環境変数に `R2_ACCOUNT_ID` `R2_ACCESS_KEY_ID` `R2_SECRET_ACCESS_KEY` `R2_BUCKET` `R2_PUBLIC_URL` を入れて再起動
   → 起動ログに `[storage] 共有の保存先: r2` と出れば有効

- 共有画像は `R2_PUBLIC_URL` から直接配信される。フォントの分割ファイルと、一度取得したジャケット画像の控え（2回目からはR2へ転送）もR2から配る（Renderの転送量を減らすため）
- 手元（ローカル）でも `.env` に同じ変数を書けばR2を使う。無ければ従来どおり `shares/` に保存する
- **無料枠を超えないための上限**（環境変数で変更可）:
  `SHARE_BUDGET_GB`（既定9.5。本番は120）… 共有ファイルの合計が実バイト数でこれを超える保存は断る（バケットの使用量は裏で10分ごとに数え、保存のたびに加算）。
  `SHARE_LIMIT_PER_IP_DAY`（公開時の既定100。本番は50）/ `SHARE_LIMIT_PER_DAY`（公開時の既定1500。本番は0＝無制限）… 1日の共有回数。0で無制限。
  `MAX_SIDE`（公開時の既定2400px）… 共有画像の最大辺。スマホなど指で触る端末とメモリの少ない端末は2000pxで描く。共有画像はJPEG（品質0.78）で、
  リンクカード用の1200×630 JPEGはサーバーが本体から作る
- 共有のほか、手入力用のアップロード画像と、検索結果の控え（`searchcache/`。VocaDBなどサーバーで引いた結果をデプロイ後も使い回す。
  名前はHMACで作り、中身に検索語を入れない）もR2に置く

### 公開モード（PUBLIC_MODE=1）で変わること

- グリッドの保存名がブラウザごとのランダムIDになり、利用者同士で混ざらない（`/grids` の一覧も出さない）
- CORSを `CORS_ORIGINS` のオリジンに開く（未設定なら `*`）
- APIにIPごとのレートリミット（既定120回/分。`RATE_LIMIT` で変更）
- `shares/`（共有PNG+JSON。R2を使わないとき）と `uploads/` は新しい2000件だけ残し、`grids/` の90日更新の無いものは消す
- 共有ページの「TRACKMENTOで開く」は `FRONTEND_URL` に戻る

### 各サービスの利用条件（2026-09-20に全サービスの公式ページとrobots.txtを再確認。公開運用の前に必ず原文を読むこと）

| ソース | 取得方法 | 公式条件の要点 | 多人数公開でのリスク |
|---|---|---|---|
| iTunes Search API | 公式API（キー不要） | 約20回/分。アートワークはiTunes/Apple Musicへの購入リンク（バッジ）と併せて表示する前提。「販促目的にのみ使う」 | **中**。コラージュ画像への利用は本来の用途（販促）から外れる。1サーバーからの20回/分は複数人で共有するとすぐ足りなくなる |
| MusicBrainz / Cover Art Archive | 公式API（キー不要） | 1回/秒（IPごと）、連絡先入りのUser-Agent必須。CAAの画像は権利者のもの（CCではない）。CAA自体にレート制限は無い | **低〜中**。1回/秒はサーバー全体で共有。画像の権利は各作品の権利者 |
| Discogs | 公式API（トークン必要） | 60回/分。「Data provided by Discogs」と非提携の注意書きを表示する義務。Contentは6時間より古いものを表示しない・必要以上に保持しない。**画像はRestricted Data**（第三者への譲渡・商用利用が不可） | **高**。生成PNGにDiscogs画像を含めて配布することはRestricted Dataの譲渡にあたる可能性。公開時はDiscogsをオフにするか、Discogs画像をPNGに含めない対応を検討 |
| Bandcamp | ページのog:image / JSON-LDを読む（非公式） | コンテンツの利用許諾は「個人的・非商用」。**Acceptable Use Policyがscraperを名指しで禁止**している一方、曲メタデータの公開APIが無く正規の口が無い | **高**（2026-09-20に使い方を書いて問い合わせ中・返答待ち）。手元で使う分には実害が小さいが、公開サービスからの自動取得は想定外 |
| SoundCloud | 曲ごとのURLのみoEmbed（公式・キー不要）。セットの一括読み込みは2026-09-20に廃止（内部APIが要り、API Terms §10のscraping禁止に触れるため） | アップローダーとSoundCloudのクレジット、元の音源へのリンク表示が必須。ユーザーコンテンツの永続保存・ダウンロード機能は不可 | **中**。アートワークをPNGに焼き込む行為は「永続保存」に近い |
| Spotify | 公式Web API（Client Credentials）。鍵が無ければ公式oEmbed（曲名とジャケット300pxのみ・アーティスト名は返らない） | Developer Terms IV.2.4がrobot / spiderによる取得を禁止し、robots.txtも `Disallow: /embed/`。メタデータ／カバーアートはSpotifyへのリンクと帰属表示が必須、単独製品として提供不可。2026年2月から開発者アプリの登録にSpotify Premiumが要る | **低**（2026-09-20に公式APIへ移した。本番は鍵なしなのでoEmbedの経路で動く） |
| YouTube | 単体はoEmbed（公式）+ i.ytimg.comのサムネイル、再生リストはData API v3（`playlistItems.list`。`YOUTUBE_API_KEY` が要る） | API Services以外でのデータ取得禁止、保存は30日まで、YouTubeブランド表示と利用規約リンクが必須。1日10,000ユニット | **中**（2026-09-20に自動取得をData APIへ移した）。サムネイルをPNGに焼き込む用途は想定外 |
| ニコニコ動画 | getthumbinfo（公式・公開） | 規約に禁止条項は無いが、robots.txtの `Disallow: /api/` がgetthumbinfoを覆う。Snapshot APIは非営利限定で代わりにならない | **中**（2026-09-20に現状維持と判断。人が貼ったときだけ1件・1週間キャッシュ） |
| bilibili | **bilibiliには問い合わせない**。動画のURLはotoDB（roxy）かVocaDB（byPv）に登録があるものだけ取る（2026-09-24。2026-09-20〜23は対応をやめていた）。収藏夹と短縮URLは不可 | 利用者規約4.2.11が自動プログラムによる取得に事前の書面許可を要求し、`api.bilibili.com` のrobots.txtも全面Disallow | **低**（bilibiliへは通信しない。登録の無い動画は手入力＋リンク先のURLで並べられる） |
| otoDB / roxy | 公式API（キー不要） | コミュニティ運営。roxyはMIT。データの利用条件はotoDBの運営に確認。問い合わせの頻度は運営から「問題ない」と返答済み（2026-09-13） | **低〜中** |
| VocaDB | 公式API（キー不要） | データベースの内容はCC BY（商用も可。取り込んだらVocaDBへのリンクを付ける）。利用者が上げた画像（ジャケットなど）は対象外。APIは応答のキャッシュと独自のUser-Agentを勧め、**事前の許可なく1日数千件を超える問い合わせはサービス妨害とみなし、IPを締め出すことがある**（2026-09-20に確認） | **低〜中**。2026-09-20に運営へ問い合わせ、「この量なら問題ない・間隔を空けてほしい」と返答を得た。受けて同時2本・0.5秒間隔に制限済み（CORSの許可は先方で検討中） |
| Apple Music | 単曲・アルバムはiTunes Lookup API（公式・キー不要）、プレイリストはページに埋まったデータを読む（非公式） | Lookup APIはiTunes Search APIと同じ条件（要確認） | 単曲・アルバムは **中**（iTunesと同じ）、プレイリストは **高**（規約外の可能性） |

このリポジトリではDiscogsの帰属表示（フッターと候補のバッジ）と6時間キャッシュ、YouTubeサムネイルの24時間キャッシュ、
画面のフッターの「ソース」から各取得元（Apple Music・MusicBrainz・otoDB・VocaDB）へのリンクを実装済み
（2026-09-20。CC BYがリンクを求めているVocaDBを含む）。取得方法も2026-09-20に各サービスの規約へ合わせて見直した
（SpotifyとYouTubeは公式APIへ、SoundCloudのセットとbilibiliは対応をやめた。bilibiliは2026-09-24にotoDB・VocaDB経由で戻した）。
それ以外（ブランド表示など）は公開者の判断で対応すること。
**個人が手元で使う範囲では問題になりづらいが、不特定多数向けの公開サービスとして各サービスの画像を集めて画像を配布する行為は、
多くのサービスの想定外**である。公開するなら「自分と友人向け」「iTunes / MusicBrainz / otoDBと手入力に絞る」などの線引きを勧める。

### 公開前に知っておくこと（セキュリティ・運用）

- Discogsのトークンはサーバー側にだけ置く（フロントには出ない）。MusicBrainzは `MB_USER_AGENT` に連絡先を入れる決まり
- 外部URLの取得（画像プロキシ・描画・Bandcampなどのページ取得）は `backend/netguard.py` で私設アドレス宛てとそこへのリダイレクトを拒否する（SSRF対策）
- アップロードと描画の画像はPillowで開けるものだけ、2,400万ピクセルまで（展開爆弾対策。約4900×4900）。SVGは受け付けない
- 公開モードでは1枚あたり `MAX_CELLS`（既定256。1辺は32まで）マスまで、APIはIPごと `RATE_LIMIT` 回/分。プロキシの後ろでは `TRUST_PROXY=1`
- ホストのディスクは再デプロイで消える。`cache.sqlite3`（検索結果と画像の対応）は消えてよい前提で、残したいもの（共有・アップロード画像・画像と検索結果の控え）はR2に置く
- 共有IDとアップロード名はランダムなので推測しづらいが、URLを知っている人は誰でも見られる（公開範囲の概念は無い）
- 応答ヘッダ: CSP（スクリプトはサーバーが埋めたnonce付きのものだけ、画像は同一オリジンとhttpsとdata:/blob:、接続は同一オリジンと検索API（iTunes / MusicBrainz / Cover Art Archive / archive.org / mzstatic）とR2だけ）、HSTS（公開モードのhttps）、nosniff、X-Frame-Options
- 入力の上限: JSONボディ1MB・アップロード16MB（Content-Length必須）、検索語200文字、URL 2048文字、曲名など300文字、控え（stash）200曲。公開モードでは `nocache` を無視し、`/render` を閉じる（`/share` を使う）
- Trackの `image` はhttps?:// か /uploads/（とジャケット無しの /no-cover.png）だけ、`external_url` / `thumb` はhttps?:// だけ受け付ける（共有を読み込んだ他人のブラウザで `javascript:` が開かないように）
- グリッドJSONは90日更新の無いものに加えて件数（5,000）でも古い順に消す。Dockerは非rootユーザーで動かす。`PUBLIC_BASE_URL` を固定してHostヘッダに依存しない
- SSRF対策はDNSピンニング付き: 名前解決で得た公開IPにそのまま接続し、HostヘッダとTLSのSNIに元のホスト名を渡す（証明書もそのホスト名で検証）。検査と接続の間にDNSの応答を変えるrebindingは効かない。リダイレクトは1ホップごとに再検査・再ピン
- 依存パッケージは `requirements.txt` で固定し、Dependabot（`.github/dependabot.yml`）が毎週pip / Dockerベースイメージ / Actionsの更新PRを出す。`audit.yml` がpip-audit（既知の脆弱性）と公開モードの起動テストを毎週とpush / PRのたびに実行する。PRをマージするとRenderが自動デプロイする

### サーバーの常時稼働と点検

- 本番はRenderの有料インスタンス（Standard）で動かしていて、眠らない。無料プランは15分アクセスが無いと眠り、次の1回目に30〜60秒かかる
- `.github/workflows/keepalive.yml` はscheduleを止めてある。GitHubのcronは大幅に間引かれ、10分おきの指定でも実際は2〜5時間おきにしか動かず、
  起こしておく役に立たなかった。無料プランに戻すならGitHubの外の監視サービス（UptimeRobotなど）から `/health` を叩く
- `/health` はRenderのヘルスチェック用。Webの接続確認は `/status`（同じ内容）を使う。広告ブロッカーの遮断リスト（EasyPrivacy）に
  旧アドレスの `||onrender.com/health` が載っていて、`/health` へのfetchが遮断されていたため
- ディスクはデプロイ・再起動のたびに初期化される（`grids/`・`cache.sqlite3`・`uploads/` が消える）。起動後にR2の `imgcache/`・`searchcache/`・`listed/` を
  一覧して索引を作り直すので、画像の転送と検索結果はデプロイ直後から控えを使える。それでも**小さな修正はまとめてpushする**。
  `/health` の `started_at` で最後の初期化時刻が分かる
- `render.yaml` の `buildFilter` で、サーバーに関係するファイル（`backend/`・`frontend/`・`fonts/` など）が変わったときだけデプロイする
- 本番の点検: `.github/workflows/render-check.yml` が2時間おきに `scripts/render_check.py`（RenderのAPIでログ・帯域・メモリを要約）を回し、
  異常ならIssueを立てる。手元なら `.venv/Scripts/python scripts/render_check.py --hours 2`（`RENDER_API_KEY` が要る）
- GitHubのcronは、リポジトリに60日間pushが無いと止まる。止まったらActionsタブから再有効化する

### 定期点検（/site-safety-check）

- Claude Codeで `/site-safety-check` と打つと、`.claude/skills/site-safety-check/SKILL.md` の手順で点検する。自動部分は
  `.venv/Scripts/python scripts/safety_check.py https://trackmento.com`（引数無しでローカル）。応答ヘッダ・SSRF・入力上限・XSS・
  アップロードのメタデータ・共有JSON・robots/sitemapを36項目見て、NGがあれば終了コード1
- 検査で共有1件と画像1枚を作り、R2の資格情報があれば最後に消す。検査用グリッド `u-safetycheck0000` はサーバー側に残るが90日で消える

### 利用者のプライバシー（何を保存し、何を保存しないか）

- IPアドレスは保存しない。レートリミットと共有回数の集計はプロセス限りの乱数と混ぜたハッシュで数える。Docker（Render）ではuvicornのアクセスログ（IPと検索語入りURL）を出さない（`--no-access-log`）
- アップロード画像は再エンコードして保存する。EXIF（位置情報・撮影日時・機種）、ICC、コメント、PNGのテキストは残さない。長辺2048pxまで縮め、名前はランダム
- 共有JSONにはブラウザごとのグリッドID（`name`）と `savedAt` を入れない（同じ人の共有を突き合わせたり、そのグリッドを読み書きされたりしないため）
- 貼られたURLの `?si=…` などのクエリは外して保存する（SoundCloud / Bandcamp）。YouTube・ニコニコ・Spotifyは正規URLに直す
- 動画サムネイル・Bandcamp・SoundCloud・アップロード画像は `/image-proxy` 経由で配るので、利用者のブラウザがYouTubeなどに直接つながることはない。例外はiTunesとMusicBrainzで、**検索**はブラウザからiTunes Search API / MusicBrainz API / Cover Art Archive（archive.org）を直接叩き（サーバーの共有IPがAppleに遮断され、MusicBrainzにレート制限されるため）、その**ジャケット画像**も配信元（mzstatic.com / archive.org）から直接読む（同じ相手先なので露出は増えず、サーバーの負荷を大きく減らせる）。検索語と利用者のIPがApple・MetaBrainz・Internet Archiveに渡る。共有PNGはR2の公開URLから配る（Cloudflareが閲覧者のIPを見る）
- 検索キャッシュ（`cache.sqlite3`）には検索語と結果を保存するが、誰が検索したかは持たない。R2に置く検索結果の控え（`searchcache/`）は、
  名前を秘密の鍵付きのハッシュ（HMAC）で作り、中身に検索語を入れない（R2は公開ドメインから読めるので、素のハッシュだと「この語が検索されたか」を確かめられてしまう）
- 画面は、ブラウザ側で起きた失敗（共有の送信が止まった・描画に失敗した など）の**種類と回数だけ**を `/hiccup` に送る。曲名・検索語・URLは送らない

## 構成

```
backend/                FastAPI。検索 /search、URL /from-url・/from-playlist、画像 /image-proxy・/image-r2、並び /grids、
                        共有 /share・/share/upload・/s/<id>、探す /find、案内 /guide・/howto・/articles・/privacy・/terms・/about・/updates、/health
backend/sources/        iTunes / MusicBrainz / otoDB（音MAD） / VocaDB（ボカロ） / Discogsと、URL貼付
                        （Bandcamp / SoundCloud / Spotify / Apple Music / YouTube / ニコニコ動画、プレイリスト）
backend/merge.py        出どころの違う結果を1つにまとめる（重複を消す）
backend/cache.py        SQLiteキャッシュ（検索結果・画像）→ cache.sqlite3
backend/searchcache.py  検索結果の控えをR2にも置く（デプロイで消えないように）
backend/storage.py      R2の読み書き（設定が無ければローカルのshares/）
backend/grids.py        並びの検証と保存（grids/<名前>.json）
backend/render.py       サーバー側の描画（CLIと、ブラウザで描けない端末のため。ふだんは端末のCanvasで描いて /share/uploadに送る）
backend/share.py        共有（画像 + 並びのスナップショット + 共有ページ）
backend/shareindex.py   「みんなのグリッド」の索引（共有するときに「載せる」を選んだものだけ）
backend/pages.py        使い方・プライバシーポリシー・運営者・更新情報のページ
backend/uploads.py      手入力用の画像アップロード
backend/netguard.py     外部URLの取得の検査（SSRF対策）
backend/main.py         経路・CSP・画像の中継・ログ・起動処理
cli.py                  add / pick / search / list / move / remove / share / render / clear / grids
frontend/index.html     画面（単一HTML。CSSもJSも1枚）
fonts/                  同梱フォント（OFL）。Web用の分割ファイルはfonts/split/
outputs/                CLIのPNG（/outputs/ で配信。OUTPUTS_KEEP世代を保持）
grids/                  作業中の並び（CLIとWebで共有）
scripts/                点検・描画の突き合わせ・フォント生成・R2の掃除
promo/                  紹介動画（Remotion + Playwright）
```

## 環境変数

`.env.example` を参照（全部の一覧と既定値は `docs/env.md`）。`DISCOGS_TOKEN` は任意（Discogsを使うなら必須）、`MB_USER_AGENT` はMusicBrainzを使うなら必須（連絡先を入れる）。
`PUBLIC_BASE_URL` は返すURLのベース。`auto` にするとLAN IPを自動検出する（スマホから開くならこれ）。公開するときは固定のURLにする。

### 検索エンジンに載せる（公開サイト）

- `/robots.txt`（トップだけ許可、API・画像・共有は除外）と `/sitemap.xml` を配る。共有ページ `/s/…` は30日で消えるので `noindex`
- Googleに載せるには [Search Console](https://search.google.com/search-console) でURLプレフィックス型のプロパティ（`https://trackmento.com/`）を追加し、
  所有権の確認方法に「HTMLタグ」を選ぶ。表示される `content="…"` の値を環境変数 `GOOGLE_SITE_VERIFICATION` に入れて再デプロイすると、
  トップページに確認タグが出る。確認後、「URL検査」→「インデックス登録をリクエスト」でクロールを頼める（反映は数日〜数週間）
- 新しいサイトは、外部からリンクされるまで検索結果に出づらい。自分のサイト（tobokegao.github.io）やSNSのプロフィールからリンクを張ると早い
