# TRACKMENTO (musicgrid-local) — Claude Code 向けメモ

曲単位ジャケットグリッド画像生成ローカルツール。仕様・経緯は `musicgrid-local-spec.md`。
本ファイルは主に **Remote Control（スマホ）で曲追加→画像 URL 受取** 手順。

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

## 開発メモ

- 構成: `backend/`（FastAPI、sources/、cache.py、grids.py、render.py、share.py、uploads.py、config.py）、`frontend/index.html`（単一 HTML）、`cli.py`、`fonts/`（OFL 同梱）
- 描画は 2 系統: Web は端末の Canvas で描いて `/share/upload` に送る（`frontend/index.html` の `renderShareCanvas`）。サーバー描画（`backend/render.py`）は CLI と、描けない端末のフォールバック（`/share`）。レイアウト・色・文字の省略規則は両方同じ式。**片方変更時は他方も変更**し、Playwright でブラウザ描画とサーバー描画の画素差を比較する（差は輪郭のみが正常）
- フォント: Web は `fonts/split/`（`scripts/build_fonts.py` が IBM Plex Sans JP / DotGothic16 を unicode-range で分割した WOFF2 ＋ `fonts.<hash>.css`）を `<!--__FONT_LINK__-->` 経由で読む。**`frontend/index.html` の固定文字（ラベル・説明文）を変えたら `python scripts/build_fonts.py` で再生成**（先頭断片に UI の全文字を入れる設計。忘れると初回表示で断片を大量に読む）。共有画像の描画前は `loadShareFonts` が描く文字を渡して必要断片だけ読む。サーバー描画は `fonts/*.ttf` のまま。共有ページはシステムフォント（Silkscreen のみ読む）
- UI デザインは Hallmark 方針（仕様書「UI デザイン方針」）。色・フォントは CSS 変数トークン経由、角丸なし
- 本番の点検: `PYTHONUTF8=1 .venv/Scripts/python scripts/render_check.py --hours 2`（Render API でログ・イベント・帯域・メモリを要約。`.env` の `RENDER_API_KEY`）。GitHub Actions `render-check.yml` が 2 時間おきに同じ点検を回し、異常時は Issue（ラベル render-check）に書く
- 動作確認は各ステップごとブラウザで（`claude-in-chrome` または手動）。サーバー `--reload` なし起動時、コード変更後再起動必要
