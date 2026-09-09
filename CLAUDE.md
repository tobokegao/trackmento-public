# TRACKMENTO (musicgrid-local) — Claude Code 向けメモ

曲単位のジャケットグリッド画像を作るローカルツール。仕様と経緯は `musicgrid-local-spec.md`。
このファイルは主に **Remote Control（スマホから）で曲を追加して画像 URL を受け取る** ときの手順を書く。

## 起動（PC 側、毎回）

```bash
cd musicgrid-local
.venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000   # API + 画像配信
claude --remote-control TRACKMENTO                                             # スマホの Claude アプリから接続
```

- Web UI: http://localhost:8000/ 。生成 PNG は `outputs/` から `/outputs/<file>.png` で配信
- `.env` の `PUBLIC_BASE_URL` が `auto` なら LAN IP（例 `http://192.168.3.14:8000`）で URL を返す。
  スマホで開くなら `localhost` ではなく LAN IP か Tailscale の URL にすること
- サーバー起動ログの `[public] PNG の URL は ...` で実際のベース URL を確認できる

## CLI（Bash から呼ぶ。Python は必ず `.venv/Scripts/python`）

```bash
.venv/Scripts/python cli.py add    --artist "A" --title "T" [--grid NAME] [--source itunes|lastfm|mb|discogs] [--first]
.venv/Scripts/python cli.py add    --bandcamp "https://xxx.bandcamp.com/track/..." [--grid NAME]
.venv/Scripts/python cli.py add    --image "https://.../cover.jpg" --artist "A" --title "T" [--grid NAME]   # 手入力
.venv/Scripts/python cli.py pick   --index N [--grid NAME]     # 直前の候補から選ぶ
.venv/Scripts/python cli.py search --artist "A" --title "T"    # 候補を見るだけ（pick で選べる）
.venv/Scripts/python cli.py list   [--grid NAME]
.venv/Scripts/python cli.py move   --from N --to M [--grid NAME]
.venv/Scripts/python cli.py remove --index N [--grid NAME]
.venv/Scripts/python cli.py render [--grid NAME] [--size 3x3] [--ratio 1:1|16:9|9:16|free] [--sidebar|--no-sidebar]
                                   [--title "…"] [--no-title] [--numbers|--no-numbers] [--bg paper|ink|mustard|cerulean|lavender|vermilion|mint|pink]
                                   [--bg-custom "#rrggbb"] [--margin 48] [--gap 12]
.venv/Scripts/python cli.py clear  [--grid NAME]
.venv/Scripts/python cli.py grids
```

- 番号 N は画面の番号バッジと同じ **1 始まり**
- 既定グリッドは `default`。状態は `grids/<NAME>.json` に保存され、Web UI と共有される
  （Web は起動時に localStorage とサーバーの新しい方を読む。開きっぱなしの Web には「サーバーから読み直す」ボタンがある）
- `render` は指定したオプションをグリッド JSON にも保存する。次回以降は省略してよい
- `render` の最後の行は必ず `URL: http://...`
- 検索結果と画像は `cache.sqlite3` にキャッシュされる。取り直したいときは Web の `/search?...&nocache=true`

## スマホからの依頼への対応手順

### 「○○の『△△』を追加して」
1. `cli.py add --artist "○○" --title "△△"` を実行する
2. 曲名＋アーティストが一致する候補があれば自動で次の空きマスに入る。出力の「NN 番に追加: …」をそのまま伝える
3. **候補が複数出た場合は必ず番号付きで提示し、ユーザーが番号を返してから** `cli.py pick --index N` で確定する。勝手に選ばない
4. 見つからない場合の順に: `--source mb`（MusicBrainz）→ Bandcamp なら URL をもらって `--bandcamp URL` → 画像 URL をもらって `--image URL --artist --title`
5. 空きマスがないと言われたら、`remove --index N` で外すか `render --size 4x6` などで広げるかをユーザーに聞く

### 「今の並びは？」
`cli.py list` の出力をそのまま返す（番号・曲名・アーティスト・ソース）。

### 「N 番と M 番を入れ替えて」「N 番を消して」
`cli.py move --from N --to M` / `cli.py remove --index N`。結果の並びをそのまま返す。

### 「画像にして」「16:9 で曲名リスト付きにして」
1. 指定があればオプションを付けて `cli.py render --ratio 16:9 --sidebar --title "…"`。無ければ `cli.py render`
2. 出力の並び一覧と **`URL:` の行を省略せずそのまま返す**。スマホ側はその URL をタップして画像を開く・保存する
3. `注意: サーバーが応答しません` が出たら uvicorn を起動してから URL を伝える

### 「全部消して」
`cli.py clear` を実行する前に一度確認する（取り消せないため）。

## 開発メモ

- 構成: `backend/`（FastAPI、sources/、cache.py、grids.py、render.py、config.py）、`frontend/index.html`（単一 HTML）、`cli.py`、`fonts/`（OFL 同梱）
- サーバー側描画（`backend/render.py`）はフロントの Canvas 描画 `layout()` と同じ式。片方を変えたらもう片方も変える
- UI デザインは Hallmark の方針（仕様書「UI デザイン方針」）。色・フォントは CSS 変数トークン経由、角丸なし
- 動作確認は各ステップごとにブラウザで（`claude-in-chrome` または手動）。サーバーは `--reload` なしで起動しているとコード変更後に再起動が必要
