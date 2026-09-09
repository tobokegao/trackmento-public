# TRACKMENTO (musicgrid-local)

「私を構成する9枚」「好きな曲9選」のようなジャケットグリッド画像を、
**曲単位・手動選択・複数ソース横断検索**で作るローカルツール。

iTunes に無い音源（Bandcamp 限定リリース等）も Last.fm / MusicBrainz / Discogs / Bandcamp URL から拾えます。
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
.venv/Scripts/python cli.py add --bandcamp "https://xxx.bandcamp.com/track/..."
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

## 構成

```
backend/          FastAPI (/search, /bandcamp, /image-proxy, /render, /grids, /health)
backend/sources/  iTunes / Last.fm / MusicBrainz / Discogs / Bandcamp
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

`.env.example` を参照。`LASTFM_API_KEY` と `DISCOGS_TOKEN` は任意、`MB_USER_AGENT` は MusicBrainz を使うなら必須。
`PUBLIC_BASE_URL` は生成 PNG の URL のベース。`auto` にすると LAN IP を自動検出する（スマホから開くならこれ）。
