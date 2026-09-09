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

1. Render（https://render.com）で "New → Blueprint" → このリポジトリを選ぶ（`render.yaml` を読んで作成される）
2. 環境変数を入れる: `PUBLIC_MODE=1`、`MB_USER_AGENT`（連絡先入り）、`DISCOGS_TOKEN`（任意）
   `CORS_ORIGINS` と `FRONTEND_URL` は同一オリジンなら不要
3. できた URL（例 `https://trackmento.onrender.com`）を開く

Docker が動くホスト（Fly.io / Railway / Koyeb / Hugging Face Spaces など）でも `Dockerfile` でそのまま動きます。
無料プランは一定時間アクセスが無いとスリープし、次のアクセスで 30〜60 秒かかります。

### B. フロントを GitHub Pages に、バックエンドを別ホストに置く

1. A の手順でバックエンドを公開し、環境変数に
   `CORS_ORIGINS=https://<user>.github.io` と `FRONTEND_URL=https://<user>.github.io/<repo>` を追加する
2. GitHub リポジトリの Settings → Pages → Source を **GitHub Actions** にする
3. Settings → Secrets and variables → Actions → **Variables** に `TRACKMENTO_API`（バックエンドの URL）を登録する
4. main / master に push すると `.github/workflows/pages.yml` がフロントを組み立てて公開する
   （手元で試すなら `python scripts/build_pages.py --api https://…` で `dist/` に出る）

### 公開モード（PUBLIC_MODE=1）で変わること

- グリッドの保存名がブラウザごとのランダム ID になり、利用者同士で混ざらない（`/grids` の一覧も出さない）
- CORS を `CORS_ORIGINS` のオリジンに開く（未設定なら `*`）
- API に IP ごとのレートリミット（既定 120 回/分。`RATE_LIMIT` で変更）
- `shares/`（共有 PNG+JSON）と `uploads/` は新しい 2000 件だけ残し、`grids/` の 90 日更新の無いものは消す
- 共有ページの「TRACKMENTO で開く」は `FRONTEND_URL` に戻る

### 公開前に知っておくこと

- Discogs のトークンはサーバー側にだけ置く（フロントには出ない）。MusicBrainz は `MB_USER_AGENT` に連絡先を入れる決まり
- 画像プロキシは外部の画像を中継する。私設アドレス宛ては拒否しているが、帯域は使う
- 無料ホストのディスクは再デプロイで消える。検索キャッシュ・共有 PNG・アップロード画像が消えてよい前提。残すなら有料の永続ディスク
- 利用規約上、各サービスの取得は「個人が手元で使う」範囲を想定している。多人数の公開運用では各 API の利用条件を確認すること

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
