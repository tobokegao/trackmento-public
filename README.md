# TRACKMENTO (musicgrid-local)

「私を構成する9枚」「好きな曲9選」のようなジャケットグリッド画像を、
**曲単位・手動選択・複数ソース横断検索**で作るローカルツール。

iTunes に無い音源（Bandcamp 限定リリース等）も MusicBrainz / Discogs / Bandcamp・SoundCloud・Spotify・YouTube・ニコニコ動画・bilibili の URL から拾えます。
仕様の詳細は `musicgrid-local-spec.md` を参照。

## セットアップ

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
copy .env.example .env          # 必要なら API キーを記入
```

## 起動

```bash
.venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

ブラウザで http://localhost:8000 を開く。開発中は `--reload` を付けると便利。
フォントは `fonts/` に同梱（OFL）しているのでオフラインでも書き出し結果は変わらない。

## CLI（Claude Code / Remote Control から使う）

```bash
.venv/Scripts/python cli.py add --artist "Artist" --title "Song"   # 候補が複数なら番号付きで表示
.venv/Scripts/python cli.py pick --index 2                        # 番号で確定
.venv/Scripts/python cli.py add --url "https://xxx.bandcamp.com/track/..."      # Bandcamp / SoundCloud / Spotify / YouTube / ニコニコ動画 / bilibili
.venv/Scripts/python cli.py add --image "https://.../cover.jpg" --artist "A" --title "T"
.venv/Scripts/python cli.py list
.venv/Scripts/python cli.py move --from 1 --to 3
.venv/Scripts/python cli.py remove --index 2
.venv/Scripts/python cli.py share --ratio 16:9 --sidebar --title "私を構成する9曲"   # PNG + 共有ページ URL
.venv/Scripts/python cli.py render                                                  # PNG だけ
.venv/Scripts/python cli.py clear
```

`share` / `render` の最後の行は `URL: http://...` です。`share` は PNG と並びのスナップショットを `shares/` に保存し、共有ページ（`/s/<id>`）から PNG 保存や「TRACKMENTO で開く」ができます。
グリッドの状態は `grids/<name>.json` に保存され、Web UI と共有されます（Web 側は自動保存＋「サーバーから読み直す」）。
スマホからの運用手順は `CLAUDE.md` を参照。

## 公開する（誰でも使えるようにする）

このアプリは検索の中継・画像プロキシ・PNG 描画・共有をサーバー側（FastAPI）でやるので、
**静的ホスティング（GitHub Pages）だけでは動きません**。次のどちらかで公開します。

### A. バックエンドだけを公開する（いちばん簡単。おすすめ）

バックエンドは `/` でフロント（index.html）も配信するので、これ 1 つで完結します。

1. このリポジトリを GitHub に push する（`.env` は含めない）
2. Render（https://render.com）に GitHub でサインアップ → "New → Blueprint" → このリポジトリを選ぶ（`render.yaml` を読んで作成される）
3. 作成時に聞かれる環境変数（`sync: false` のもの）に R2 の 5 つの値を入れる。`PUBLIC_MODE` などは `render.yaml` に書いてある。
   `DISCOGS_TOKEN` は入れない（公開版では Discogs を使わない）
4. デプロイが終わったら、できた URL（例 `https://trackmento.onrender.com`）を開く。`/health` で `"public": true, "storage": "r2"` なら設定完了
5. 以後は GitHub に push するたびに自動で再デプロイされる

Docker が動くホスト（Fly.io / Railway / Koyeb / Hugging Face Spaces など）でも `Dockerfile` でそのまま動きます。
無料プランは一定時間アクセスが無いとスリープし、次のアクセスで 30〜60 秒かかります。

### B. フロントを GitHub Pages に、バックエンドを別ホストに置く

1. A の手順でバックエンドを公開し、環境変数に
   `CORS_ORIGINS=https://<user>.github.io` と `FRONTEND_URL=https://<user>.github.io/<repo>` を追加する
2. GitHub リポジトリの Settings → Pages → Source を **GitHub Actions** にする
3. Settings → Secrets and variables → Actions → **Variables** に `TRACKMENTO_API`（バックエンドの URL）を登録する
4. main / master に push すると `.github/workflows/pages.yml` がフロントを組み立てて公開する
   （手元で試すなら `python scripts/build_pages.py --api https://…` で `dist/` に出る）

### 共有 PNG を Cloudflare R2 に置く（無料枠で共有 URL を長持ちさせる）

無料ホストのディスクは再デプロイで消えるので、共有（PNG + 並びの JSON）は R2 に置くとよい。
R2 の無料枠はストレージ 10GB / 月、書き込み 100 万回、読み出し 1,000 万回、転送量無料（PNG 1 枚 1〜3MB なら数千件分）。

1. Cloudflare ダッシュボード → R2 → **Create bucket**（例 `trackmento-shares`。ロケーションは Automatic でよい）
2. バケットの Settings → **Public access** → 「R2.dev subdomain」を Allow にすると `https://pub-xxxx.r2.dev` が発行される
   （独自ドメインを付けてもよい）。これが `R2_PUBLIC_URL`
3. Settings → **Object lifecycle rules** → ルールを追加し「Delete uploaded objects after **30** days」にする（共有の有効期限）。
   見つからないときは、手順 4〜5 のあとに `python scripts/r2_setup.py` を実行すると API から同じルールを設定できる（`--days` で日数変更、`--check` で表示のみ）
4. R2 → **Manage R2 API Tokens** → Create API token → 権限 "Object Read & Write"、対象バケットをこのバケットに限定
   → 表示される Access Key ID / Secret Access Key と、R2 の概要ページにある Account ID を控える
5. バックエンドの環境変数に `R2_ACCOUNT_ID` `R2_ACCESS_KEY_ID` `R2_SECRET_ACCESS_KEY` `R2_BUCKET` `R2_PUBLIC_URL` を入れて再起動
   → 起動ログに `[storage] 共有の保存先: r2` と出れば有効

- PNG は `R2_PUBLIC_URL` から直接配信され、並びの JSON と「PNG を保存」はバックエンドが R2 から中継する
- 手元（ローカル）でも `.env` に同じ変数を書けば R2 を使う。無ければ従来どおり `shares/` に保存
- **無料枠を超えないための上限**（環境変数で変更可）:
  `SHARE_BUDGET_GB`（既定 9.5）… 共有ファイルの合計が実バイト数でこれを超える保存は断る（バケットの使用量を 10 分ごとに集計し、保存のたびに加算）。
  `SHARE_LIMIT_PER_IP_DAY`（既定 20）/ `SHARE_LIMIT_PER_DAY`（既定 200）… 1 日の共有回数。
  `MAX_SIDE`（公開時の既定 4000px）… PNG を軽くする。書き込み回数は 1 共有あたり 2 回なので、200 回/日でも月 1.2 万回（無料枠 100 万回）
- アップロード画像（手入力用）と検索キャッシュは R2 に置かない（消えてよいもの）

### 公開モード（PUBLIC_MODE=1）で変わること

- グリッドの保存名がブラウザごとのランダム ID になり、利用者同士で混ざらない（`/grids` の一覧も出さない）
- CORS を `CORS_ORIGINS` のオリジンに開く（未設定なら `*`）
- API に IP ごとのレートリミット（既定 120 回/分。`RATE_LIMIT` で変更）
- `shares/`（共有 PNG+JSON。R2 を使わないとき）と `uploads/` は新しい 2000 件だけ残し、`grids/` の 90 日更新の無いものは消す
- 共有ページの「TRACKMENTO で開く」は `FRONTEND_URL` に戻る

### 各サービスの利用条件（2026-09-09 に公式ページを確認。公開運用の前に必ず原文を読むこと）

| ソース | 取得方法 | 公式条件の要点 | 多人数公開でのリスク |
|---|---|---|---|
| iTunes Search API | 公式 API（キー不要） | 約 20 回/分。アートワークは iTunes/Apple Music への購入リンク（バッジ）と併せて表示する前提。「販促目的にのみ使う」 | **中**。コラージュ画像への利用は本来の用途（販促）から外れる。1 サーバーからの 20 回/分は複数人で共有するとすぐ足りない |
| MusicBrainz / Cover Art Archive | 公式 API（キー不要） | 1 回/秒（IP ごと）、連絡先入りの User-Agent 必須。CAA の画像は権利者のもの（CC ではない）。CAA 自体にレート制限は無い | **低〜中**。1 回/秒はサーバー全体で共有。画像の権利は各作品の権利者 |
| Discogs | 公式 API（トークン必要） | 60 回/分。「Data provided by Discogs」と非提携の注意書きを表示する義務。Content は 6 時間より古いものを表示しない・必要以上に保持しない。**画像は Restricted Data**（第三者への譲渡・商用利用が不可） | **高**。生成 PNG に Discogs 画像を含めて配布することは Restricted Data の譲渡にあたる可能性。公開時は Discogs をオフにするか、Discogs 画像を PNG に含めない対応を検討 |
| Bandcamp | ページの og:image / JSON-LD を読む（非公式） | コンテンツの利用許諾は「個人的・非商用」。自動アクセスを禁じる専用条項は見当たらないが Acceptable Use に従う必要 | **中**。手元で使う分には実害が小さいが、公開サービスからの自動取得は想定外 |
| SoundCloud | oEmbed（公式・キー不要） | アップローダーと SoundCloud のクレジット、元の音源へのリンク表示が必須。ユーザーコンテンツの永続保存・ダウンロード機能は不可 | **中**。アートワークを PNG に焼き込む行為は「永続保存」に近い |
| Spotify | ページの og タグ（非公式） | Developer Policy: コンテンツの分析禁止、メタデータ／カバーアートは Spotify へのリンクと帰属表示が必須、単独製品として提供不可 | **高**。API を通さない取得は規約外 |
| YouTube | oEmbed（公式）+ i.ytimg.com のサムネイル | API Services 以外でのデータ取得禁止、保存は 30 日まで、YouTube ブランド表示と利用規約リンクが必須 | **高**。サムネイルを PNG に焼き込む用途は想定外 |
| ニコニコ動画 | getthumbinfo（公式・公開） | 公開 API。利用ガイドラインは niconico の規約に従う | **中**（要確認） |
| bilibili | ページ内の JSON を読む（非公式） | 公式 API は Cookie 無しでは拒否される | **高**。スクレイピングは規約外の可能性が高い |
| otoDB / roxy | 公式 API（キー不要） | コミュニティ運営。roxy は MIT。データの利用条件は otoDB の運営に確認 | **低〜中** |

このリポジトリでは Discogs の帰属表示（フッターと候補のバッジ）と 6 時間キャッシュ、YouTube サムネイルの 24 時間キャッシュを実装済み。
それ以外（各サービスへのリンク表示、ブランド表示、取得方法の見直し）は公開者の判断で対応すること。
**個人が手元で使う範囲では問題になりにくいが、不特定多数向けの公開サービスとして各サービスの画像を集めて画像を配布する行為は、
多くのサービスの想定外**である。公開するなら「自分と友人向け」「iTunes / MusicBrainz / otoDB と手入力に絞る」などの線引きを勧める。

### 公開前に知っておくこと（セキュリティ・運用）

- Discogs のトークンはサーバー側にだけ置く（フロントには出ない）。MusicBrainz は `MB_USER_AGENT` に連絡先を入れる決まり
- 外部 URL の取得（画像プロキシ・描画・Bandcamp などのページ取得）は `backend/netguard.py` で私設アドレス宛てとそこへのリダイレクトを拒否する（SSRF 対策）
- アップロードと描画の画像は Pillow で開けるものだけ、4,000 万ピクセルまで（展開爆弾対策）。SVG は受け付けない
- 公開モードでは 1 枚あたり `MAX_CELLS`（既定 64）マスまで、API は IP ごと `RATE_LIMIT` 回/分。プロキシの後ろでは `TRUST_PROXY=1`
- 無料ホストのディスクは再デプロイで消える。検索キャッシュ・共有 PNG・アップロード画像が消えてよい前提。残すなら有料の永続ディスクか外部ストレージ
- 共有 ID とアップロード名はランダム／ハッシュなので推測しにくいが、URL を知っている人は誰でも見られる（公開範囲の概念は無い）

## 構成

```
backend/          FastAPI (/search, /bandcamp, /image-proxy, /render, /grids, /health)
backend/sources/  iTunes / MusicBrainz / Discogs / otoDB（音MAD） / URL 貼付（Bandcamp / SoundCloud / Spotify / YouTube / ニコニコ動画 / bilibili）
backend/cache.py  SQLite キャッシュ（検索結果・画像）→ cache.sqlite3
backend/grids.py  グリッド JSON の読み書き
backend/render.py Pillow による PNG 描画
backend/share.py  トラックを共有（PNG + 並びのスナップショット + 共有ページ）→ shares/
backend/uploads.py 手入力用の画像アップロード → uploads/
cli.py            add / pick / search / list / move / remove / share / render / clear / grids
frontend/         単一 HTML
fonts/            同梱フォント（OFL）。/fonts/ で配信
outputs/          生成 PNG（/outputs/ で静的配信。OUTPUTS_KEEP 世代を保持）
grids/            作業中グリッド JSON（CLI と Web で共有）
```

## 環境変数

`.env.example` を参照。`DISCOGS_TOKEN` は任意（Discogs を使うなら必須）、`MB_USER_AGENT` は MusicBrainz を使うなら必須。
`PUBLIC_BASE_URL` は生成 PNG の URL のベース。`auto` にすると LAN IP を自動検出する（スマホから開くならこれ）。
