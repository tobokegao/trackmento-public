# MusicGrid Local — 曲単位ジャケットグリッド作成ツール 仕様書

Claude Code で開発を再開するための引き継ぎドキュメント。
まずこのファイルを読み、「実装タスク」の順に進めてください。

---

## 1. 目的

X などで流行している「私を構成する9枚」「好きな曲9選」のようなグリッド画像を、
**曲単位**で手動選択して作成するツールをローカルで動かす。

参考サイト: https://musicgrid-nine.vercel.app/
（アルバム／曲を検索してグリッドに配置 → 画像保存。アートワークは iTunes Search API のみ）

### 既存ツールでは足りない点
- MusicGrid: 曲単位で選べるが iTunes にない音源（Bandcamp限定リリース等）が拾えない
- charty (https://github.com/iyra/charty): Last.fm + Discogs 対応だがアルバム単位
- SongStitch / Riffology: Last.fm の再生履歴から自動生成。手動選択ではない

→ 「曲単位・手動選択・複数ソース横断検索」を満たすものが無いので自作する。

### 想定ジャンル
パンク／ハードコア、ノイズ／実験音楽、日本のインディー。
iTunes 未配信が多いので Last.fm / MusicBrainz / Bandcamp からの取得が重要。

---

## 2. 要件

### 必須
- 曲名（＋アーティスト名）で検索し、候補をジャケット付きで表示
- 検索ソースを切替可能: iTunes / Last.fm / MusicBrainz(Cover Art Archive) / Discogs / Bandcamp(URL貼付)
- 候補をタップ／クリックで次の空きマスに追加、ドラッグで入れ替え、×で削除
- 検索で見つからない場合は **画像URL＋曲名＋アーティスト名を手入力**で追加できる
- グリッドサイズ: 3×3 (9) / 4×6 (24) / 3×8 (24) / 5×5 (25) / 任意 W×H
- 出力比率プリセット: X横長 16:9 / インスタ投稿 4:5 / 正方形 1:1 / ストーリーズ 9:16
- タイトル表示 ON/OFF、曲名・アーティスト名のサイドバー表示 ON/OFF、背景色、余白
- PNG 書き出し（高解像度、少なくともマス目 500px 以上）
- 作成中のグリッドをブラウザ (localStorage) と JSON エクスポート／インポートで保存
- **CLI からも操作できること**（Claude Code Remote Control でスマホから使うため。詳細は「9. Remote Control 運用」）
- **生成した PNG を簡易 HTTP サーバーで配信し、URL で受け取れること**

### あると良い
- 取得済みアートワークのキャッシュ（SQLite or JSON）で API 制限回避
- 複数チャートの保存・切替
- 番号バッジ表示
- 日本語フォント同梱（曲名が化けないように）

### やらないこと
- ユーザー登録・公開ページ・ランキング等の SNS 機能
- Last.fm 再生履歴からの自動生成（必要なら後で）

---

## 3. 構成

```
musicgrid-local/
├── backend/
│   ├── main.py          # FastAPI: /search, /bandcamp, /image-proxy
│   ├── sources/
│   │   ├── itunes.py
│   │   ├── lastfm.py
│   │   ├── musicbrainz.py
│   │   ├── discogs.py
│   │   └── bandcamp.py
│   ├── cache.py         # SQLite キャッシュ
│   ├── models.py        # 共通レスポンス型
│   └── render.py        # サーバー側 PNG 描画（Pillow）。CLI からも Web からも使う
├── cli.py               # Claude Code から叩く CLI（add / list / render / clear）
├── frontend/
│   └── index.html       # 単一HTML（CSS/JS内包）
├── outputs/             # 生成 PNG の保存先。FastAPI が /outputs/ で静的配信
├── grids/               # 作業中グリッドの JSON（CLI と Web で共有）
├── .env.example
├── requirements.txt
└── README.md
```

### 技術選定
- バックエンド: Python 3.11+ / FastAPI / httpx
  - 役割: API キーの秘匿、CORS 回避、レスポンス形式の統一、キャッシュ
- フロント: 素の HTML + JS（フレームワーク不要）。画像書き出しは Canvas API
  - 外部画像を Canvas に描くと tainted になるため、必ず `/image-proxy` 経由で読み込む
- 起動: `uvicorn backend.main:app --reload` → http://localhost:8000 で index.html を配信

### 共通レスポンス型（全ソースをこれに正規化）
```json
{
  "source": "itunes | lastfm | musicbrainz | discogs | bandcamp | manual",
  "title": "曲名",
  "artist": "アーティスト名",
  "album": "アルバム名（任意）",
  "image": "ジャケット画像URL（高解像度）",
  "thumb": "サムネイルURL（任意）",
  "external_url": "元ページURL（任意）"
}
```

---

## 4. 各ソースの取得仕様

| ソース | エンドポイント | 認証 | 制限 | 備考 |
|---|---|---|---|---|
| iTunes | `https://itunes.apple.com/search?term={q}&entity=song&country=JP&limit=25` | 不要 | 緩い | `artworkUrl100` の `100x100` を `1000x1000` に置換で高解像度 |
| Last.fm | `track.search` → `track.getInfo` | APIキー(無料) | 緩い | `track.search` は画像が空のことが多いので `getInfo` の `album.image[extralarge]` を使う |
| MusicBrainz + CAA | `https://musicbrainz.org/ws/2/recording?query=...&fmt=json` → `https://coverartarchive.org/release/{release-mbid}/front-500` | 不要 | **1 req/秒・User-Agent 必須** | recording の `releases[]` から release MBID を取り CAA を叩く。404 は「画像なし」 |
| Discogs | `https://api.discogs.com/database/search?track={q}&artist={a}&type=release&token=...` | トークン必須 | 60 req/分 | `cover_image` を使う。未設定時はソース選択肢から非表示 |
| Bandcamp | 公式APIなし。トラック／アルバムページURLを受け取り `og:image` を抽出 | 不要 | スクレイピング | ユーザーがURLを貼る運用。曲名・アーティストも `og:title` / `meta[name=title]` から拾う |

### 環境変数 (.env)
```
LASTFM_API_KEY=
DISCOGS_TOKEN=
MB_USER_AGENT=musicgrid-local/0.1 (your-email@example.com)
```

---

## 5. API 設計（バックエンド）

- `GET /search?q=&artist=&source=`
  - `source` 省略時は iTunes + Last.fm + MusicBrainz を並列で叩き、
    `title+artist` の正規化キーで重複マージ（µsic tools と同じ発想）
- `POST /bandcamp` body: `{ "url": "..." }` → 共通レスポンス型を返す
- `GET /image-proxy?url=` → 画像をそのまま返す（Canvas の CORS 対策）。許可ドメインをホワイトリスト化
- `GET /` → frontend/index.html
- `GET /grids/{name}` / `PUT /grids/{name}` → 作業中グリッド JSON の読み書き（CLI と Web で同じファイルを共有）
- `POST /render` body: `{ "grid": "<name>", "ratio": "16:9", "sidebar": true }`
  → `backend/render.py` で PNG を生成し `outputs/` に保存、`{ "url": "http://<host>:8000/outputs/<name>-<timestamp>.png" }` を返す
- `GET /outputs/{file}` → 生成 PNG の静的配信（FastAPI `StaticFiles`）

### 簡易 HTTP 配信の方針
- 追加の Web サーバーは立てず、FastAPI の `StaticFiles` で `outputs/` をマウントする
- レスポンスの URL は **LAN 内の IP**（例 `http://192.168.x.x:8000/outputs/...`）で返す。
  `uvicorn --host 0.0.0.0` で起動し、ホスト名は `.env` の `PUBLIC_BASE_URL` で指定
- 外出先から見たい場合は Tailscale か Cloudflare Tunnel で `PUBLIC_BASE_URL` を差し替える（後回しで可）
- `outputs/` は世代管理: 直近 50 件を残し古いものは起動時に削除

---

## 6. フロント UI 要素

1. 上部: 検索欄（曲名 / アーティスト）、ソース切替タブ、Bandcamp URL 入力
2. 左: 検索結果リスト（サムネ＋曲名＋アーティスト＋ソースバッジ）
3. 中央: グリッド（サイズ選択、比率選択、タイトル入力）
4. 右 or 下: オプション（タイトル表示、サイドバー表示、番号、背景色、余白）
5. ボタン: 画像を作る / PNG保存 / JSON書き出し / JSON読み込み / 全部クリア
6. 手入力追加フォーム: 画像URL・曲名・アーティスト

---

## 7. 実装タスク（この順で）

- [x] 1. リポジトリ雛形作成、requirements.txt、.env.example、README
- [x] 2. `sources/itunes.py`（キー不要なので最初に動作確認）
- [x] 3. `main.py` に `/search` と `/image-proxy` と静的配信
- [x] 4. `frontend/index.html`: 検索→3×3グリッドに追加→PNG保存の最小動作
- [x] 5. `sources/musicbrainz.py`（1秒スリープ、User-Agent）
- [x] 6. `sources/lastfm.py`（2026-09-09 に廃止。代わりに `sources/soundcloud.py`（oEmbed、URL 貼付）を追加）
- [x] 7. `sources/bandcamp.py` + `/bandcamp`
- [x] 8. 横断検索の重複マージ
- [x] 9. グリッドサイズ／比率プリセット／サイドバー／番号／背景色
- [x] 10. localStorage 保存、JSON 入出力、手入力追加
- [x] 11. SQLite キャッシュ
- [x] 12. `sources/discogs.py`（トークンありのときだけ有効）
- [x] 13. 日本語フォント同梱と PNG 書き出し時のフォント適用確認
- [x] 14. `backend/render.py`（Pillow でサーバー側描画）と `POST /render`、`outputs/` 静的配信
- [x] 15. `cli.py`（add / list / render / clear）。Claude Code が Bash から呼ぶ想定
- [x] 16. `CLAUDE.md` に CLI の使い方と定型ワークフローを記載し、Remote Control でスマホから動作確認

各ステップごとにブラウザで動作確認してから次へ進む。

### 実装メモ（2026-09-09 タスク11〜16 完了時）
- キャッシュ: `cache.sqlite3` に検索結果（7日）と画像（30日・300MB 上限）。`/search?nocache=true` で取り直し
- ALL（source 省略時）は MusicBrainz → Discogs（トークンがあるとき）→ iTunes の順。重複は先のソースを残す。iTunes は曲名・アーティストの部分一致（含む）のみ、完全一致が先頭
- フォントは `fonts/` に IBM Plex Sans JP / Silkscreen / DotGothic16（OFL）を同梱し `/fonts/` で配信。Google Fonts 依存を外した
- グリッド JSON: Web は localStorage とサーバー `grids/default.json` の両方に保存し、起動時に savedAt が新しい方を採用。
  `/render` と CLI の `render` は指定オプションをグリッド JSON に保存する
- `backend/render.py` の layout はフロントの layout() と同じ式（丸めは JS の Math.round 相当）。寸法は一致する
- Remote Control の起動コマンドは現行の Claude Code では `claude --remote-control <name>`（フラグ形式）
- `PUBLIC_BASE_URL=auto` で LAN IP を自動検出。タスク16 のスマホ実機確認は未実施（手順は CLAUDE.md）
- Last.fm は画像が iTunes と重なるため廃止。SoundCloud（oEmbed）・YouTube（oEmbed + i.ytimg.com）・ニコニコ動画（getthumbinfo）・bilibili（動画ページの __INITIAL_STATE__）・Spotify（クローラ UA での og タグ、無ければ embed の JSON）は URL 貼付で対応（キー不要）
- otoDB（音MAD データベース）: /api/work/search を検索ソース「otoDB」として追加（ALL には含めない）。作者はタグの Creator 区分。
  動画 URL の直接取得に失敗したときは roxy（roxy.otodb.net/xml）にフォールバックし、削除済み動画でも otoDB 登録分は取れる
- 「トラックを共有」: PNG と並びのスナップショットを shares/ に保存し、共有ページ /s/<id> と /?share=<id> で読み込み。JSON 入出力は廃止

---

## 8. 未決事項（着手時に決める）

- Canvas 書き出しにするか、html2canvas 等のライブラリを使うか（まず Canvas API で試す）
- 日本語フォントは何を同梱するか（Noto Sans JP など）
- 将来 REAPER × TouchDesigner 環境と連携するなら JSON 出力形式を先に固めておくか

---

### UI デザイン方針（決定）
- Anti-AI-slop 系スキル **Hallmark**（https://github.com/nutlope/hallmark, MIT, Star 28k）を `~/.claude/skills/hallmark` に導入済み
- タスク4以降の `frontend/index.html` は Hallmark の Design flow に従って作る
  - 3質問ゲート（Audience / Use case / Tone）→ ジャンル → マクロ構造 → テーマ → トークン固定 → slop-test
  - 色・フォントは必ず CSS 変数トークン経由。紫グラデ、Inter 単独、3カラム均等カード、ガラス風、全画面中央ヒーローは禁止
  - 見出しはイタリック禁止、320/375/414/768px で横スクロールなし
- ツール系 UI なので macrostructure は Workbench 系を第一候補にする（ランディングページ用の hero/footer 類型は使わない）

#### デザインブリーフ（2026-09-09 決定・Hallmark 3質問ゲートの回答）
- **サイト名（画面表示）**: 「TRACKMENTO」（track + memento）。リポジトリ名は musicgrid-local のまま
- **Audience**: 自分用。日本の J-POP リスナー
- **Use case**: 曲を検索してマスに置き、PNG を書き出す。1画面で完結するツール
- **Tone**: utilitarian。リソグラフ風フラット、レトロ GUI／ドット絵を意識。角丸なし（`border-radius: 0`）
- **色**: 地はクリーム（2026-09-09 に黄みを半分以下へ: paper の彩度 0.015 → 0.006）＋黒インク。アクセントはマスタード／セルリアンブルー／ラベンダー／朱赤／ミント／ピンクの6色。
  全体は暖色に寄せない（主アクセントはセルリアン、暖色3色はバッジ等に限定）。ソース6種（iTunes / Last.fm / MusicBrainz / Discogs / Bandcamp / 手入力）にこの6色を1対1で割り当てる
- **テーマルート**: Hallmark custom（tuned）。macrostructure は Workbench
- **ワードマーク**: Silkscreen 700 の大文字。版ズレは二重に見えて読みづらいため不採用、文字の下にセルリアンの太線（5px）。日本語ドット表示は粗さが出せず不採用
- **横断検索のマージ鍵**: 曲名＋アーティスト＋アルバム名（「- Single」「- EP」接尾辞は無視）。同じ曲の別ジャケットを残すため

### グリッド JSON の形式（タスク10で決定。localStorage / JSON 書き出し / grids/<name>.json で共通）
```json
{ "app": "trackmento", "version": 1, "name": "default", "savedAt": "ISO8601",
  "title": "…", "cols": 3, "rows": 3,
  "cells": [ <共通レスポンス型 Track> | null, ... ],   // cols*rows 個
  "stash": [ <Track>, ... ],                            // 縮小時に退避した曲
  "options": { "ratio": "1:1|16:9|9:16|free", "showTitle": true, "sidebar": true,
               "numbers": false, "bg": "paper|ink|mustard|cerulean|lavender|vermilion|mint|pink|custom",
               "bgCustom": "#rrggbb|null", "margin": 16, "gap": 16 } }
```
- `/image-proxy` はホワイトリスト外でも公開ホストなら通す（私設IP・ループバック・解決不能は 403）。手入力の画像URL対応のため

## 9. Remote Control 運用（スマホから曲を追加して画像を受け取る）

### 前提
- Claude Code の Remote Control（`claude remote-control`）を使う。セッションは PC 上で動き、
  スマホの Claude アプリ（Code タブ）はその窓になる。ファイル・ツール・MCP は PC 側のものがそのまま使える
- Pro / Max / Team / Enterprise のいずれかで claude.ai ログインが必要（API キー不可）
- PC のプロセスを止めるとオフラインになる。長時間動かすなら tmux / screen 内で起動する

### 起動手順（PC側、毎回）
```bash
cd musicgrid-local
.venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &   # API + 画像配信
claude --remote-control TRACKMENTO                                               # QR をスマホで読む
```
スマホの Claude アプリで QR を読むか、Code タブから "MusicGrid" を選ぶ。

### スマホからの流れ
1. スマホで「○○（アーティスト）の『△△』を追加して」と送る
2. PC 側の Claude Code が `python cli.py add --artist "○○" --title "△△"` を実行
   - CLI は iTunes → Last.fm → MusicBrainz の順に検索し、最初にジャケットが取れたものを採用
   - 複数候補で迷う場合は候補を番号付きで返し、スマホから番号で選ぶ
   - Bandcamp 限定なら URL を送ってもらい `cli.py add --bandcamp <url>`
3. 「画像にして」で `python cli.py render --ratio 16:9 --sidebar`
   → PNG を `outputs/` に保存し、配信 URL とリストを標準出力に出す
4. Claude Code はその出力をそのまま返す。スマホ側には
   - 曲名／アーティスト／ソースの一覧（テキスト）
   - `http://<PC の LAN IP>:8000/outputs/xxxx.png` の URL
   が表示されるので、URL をタップして画像を開く／保存する

### 画像を URL で返す理由
- スマホ→PC の画像添付は公式対応しているが、PC で生成した画像がセッション内に表示されるかは
  公式ドキュメントに明記がない。テキストは確実に同期されるので、URL で渡すのが最も確実
- 同期フォルダ方式は採らない。FastAPI の静的配信で完結させる

### CLI 仕様（cli.py）
```
cli.py add    --artist A --title T [--grid NAME] [--source itunes|lastfm|mb|discogs]
cli.py add    --bandcamp URL [--grid NAME]
cli.py add    --image URL --artist A --title T [--grid NAME]   # 手入力
cli.py pick   --index N                                         # 直前の候補から選択
cli.py list   [--grid NAME]                                     # 現在の並びを表示
cli.py move   --from N --to M                                   # 入れ替え
cli.py remove --index N
cli.py render [--grid NAME] [--size 3x3] [--ratio 16:9] [--sidebar] [--title "..."]
cli.py clear  [--grid NAME]
```
- 既定グリッド名は `default`。状態は `grids/<NAME>.json` に保存し Web 側と共有
- 出力は人間が読めるテキスト。`render` の最後の行は必ず `URL: http://...` にする
  （Claude Code がそのまま転記できるように）

### CLAUDE.md に書くこと
- 上記 CLI の使い方
- 「曲を追加して」「画像にして」「今の並びは？」への対応手順
- 候補が複数あるときは必ず番号付きで提示してから確定すること
- render 後は URL を省略せずそのまま返すこと
