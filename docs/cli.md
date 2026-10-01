# CLIとスマホからの依頼

（`CLAUDE.md` から分けたもの。2026-09-25。毎回は要らないので核から外した。中身は当時のまま）

スマホのClaudeアプリ（Remote Control）から曲の追加・並べ替え・共有を頼まれたときの手順。

## 起動（PC側、毎回）

```bash
cd trackmento-public   # 手元のフォルダ（名前は環境による）
.venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000   # API + 画像配信
claude --remote-control TRACKMENTO                                             # スマホのClaudeアプリから接続
```

- Web UI: http://localhost:8000/ 。生成PNGは `outputs/` から `/outputs/<file>.png` で配信
- `.env` の `PUBLIC_BASE_URL` が `auto` ならLAN IP（例 `http://192.168.3.14:8000`）でURL返却。
  スマホで開く場合 `localhost` でなくLAN IPかTailscale URL必須
- 実際のベースURLはサーバー起動ログ `[public] PNGのURLは ...` で確認

## CLI（Bashから呼ぶ。Pythonは必ず `.venv/Scripts/python`）

```bash
.venv/Scripts/python cli.py add    --artist "A" --title "T" [--grid NAME] [--source itunes|mb|discogs|otodb] [--first]
.venv/Scripts/python cli.py add    --url "https://xxx.bandcamp.com/track/..." [--grid NAME]     # Bandcamp / SoundCloud / Spotify / Apple Music / YouTube / ニコニコ動画のURL
.venv/Scripts/python cli.py add    --image "https://.../cover.jpg" --artist "A" --title "T" [--grid NAME]   # 手入力
.venv/Scripts/python cli.py pick   --index N [--grid NAME]     # 直前の候補から選ぶ
.venv/Scripts/python cli.py search --artist "A" --title "T"    # 候補を見るだけ（pickで選べる）
.venv/Scripts/python cli.py list   [--grid NAME]
.venv/Scripts/python cli.py move   --from N --to M [--grid NAME]
.venv/Scripts/python cli.py remove --index N [--grid NAME]
.venv/Scripts/python cli.py share  [--grid NAME] [--size 3x3] [--ratio 1:1|4:5|16:9|9:16|free] [--sidebar|--no-sidebar]   # PNG + 共有ページURL
.venv/Scripts/python cli.py render [--grid NAME] ...                                                          # PNGだけ（オプションはshareと同じ）
                                   [--title "…"] [--no-title] [--numbers|--no-numbers] [--bg paper|ink|mustard|cerulean|lavender|vermilion|mint|pink]
                                   [--bg-custom "#rrggbb"] [--pad normal|wide|xwide] [--margin 48] [--gap 12]
.venv/Scripts/python cli.py clear  [--grid NAME]
.venv/Scripts/python cli.py grids
```

- 番号Nは画面番号バッジ同一、**1始まり**
- 既定グリッド `default`。状態は `grids/<NAME>.json` 保存、Web UIと共有
  （Webは起動時localStorageとサーバーの新しい方を読込。開いたままのWebには「サーバーから読み直す」ボタン）
- `share` / `render` は指定オプションをグリッドJSONにも保存。次回以降省略可
- `share` は画像（JPEG品質78）と並びスナップショットを `shares/<id>.{jpg,json}` 保存、共有ページ `http://…/s/<id>` のURL出力。
  共有ページ内容: 画像・曲リスト・「TRACKMENTOで開く」（`/?share=<id>` でその並びをWeb読込）
- `share` / `render` 最終行は必ず `URL: http://...`
- 検索結果・画像は `cache.sqlite3` にキャッシュ。再取得はWebの `/search?...&nocache=true`

## スマホからの依頼への対応手順

### 「○○の『△△』を追加して」
1. `cli.py add --artist "○○" --title "△△"` 実行
2. 曲名＋アーティスト一致候補あれば自動で次の空きマスへ。出力「NN番に追加: …」をそのまま伝達
   （検索順iTunes → MusicBrainz → Discogs（--source mb,discogs等で絞込可）。iTunesは曲名・アーティスト名にクエリ含むもののみ返却、完全一致先頭）
3. **候補複数時は必ず番号付き提示、ユーザーの番号返答後** `cli.py pick --index N` で確定。勝手に選ばない
4. 未発見時の順: `--source discogs` / `--source mb`（音MADは `--source otodb`）→ Bandcamp / SoundCloud / Spotify / Apple Music / YouTube / ニコニコ動画ならURL受取→ `--url URL` → 画像URL受取→ `--image URL --artist --title`
5. 空きマスなしの場合、`remove --index N` で除外か `render --size 4x6` 等で拡張かをユーザーに確認

### 「今の並びは？」
`cli.py list` 出力をそのまま返却（番号・曲名・アーティスト・ソース）。

### 「N番とM番を入れ替えて」「N番を消して」
`cli.py move --from N --to M` / `cli.py remove --index N`。結果の並びをそのまま返却。

### 「画像にして」「共有して」「16:9で曲名リスト付きにして」
1. 指定あれば `cli.py share --ratio 16:9 --sidebar --title "…"`。なければ `cli.py share`
2. 出力の並び一覧と **`URL:` 行を省略せずそのまま返却**。スマホ側はそのURL（共有ページ）でPNG保存や
   「TRACKMENTOで開く」で並び読込可。画像のみ要望時は `画像:` 行も添付
3. `注意: サーバーが応答しません` 出力時、uvicorn起動後にURL伝達

### 「全部消して」
`cli.py clear` 実行前に一度確認（取消不可）。
