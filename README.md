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
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

ブラウザで http://localhost:8000 を開く。

## CLI（Claude Code / Remote Control から使う）

```bash
python cli.py add --artist "Artist" --title "Song"
python cli.py list
python cli.py render --ratio 16:9 --sidebar
```

`render` の最後の行は `URL: http://...` で、生成 PNG は `outputs/` から配信されます。

## 構成

```
backend/          FastAPI (/search, /bandcamp, /image-proxy, /render, /grids)
backend/sources/  iTunes / Last.fm / MusicBrainz / Discogs / Bandcamp
backend/render.py Pillow による PNG 描画
cli.py            add / list / render / clear など
frontend/         単一 HTML
outputs/          生成 PNG（/outputs/ で静的配信）
grids/            作業中グリッド JSON（CLI と Web で共有）
```

## 環境変数

`.env.example` を参照。`LASTFM_API_KEY` と `DISCOGS_TOKEN` は任意、`MB_USER_AGENT` は MusicBrainz を使うなら必須。
