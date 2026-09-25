# はじめて動かすまで（セットアップ）

（`CLAUDE.md` から分けたもの。2026-09-25。毎回は要らないので核から外した。中身は当時のまま）

何も無い状態から手元で動かす手順。**Windows 前提**（パスは `.venv/Scripts/`。macOS / Linux なら `.venv/bin/`）。

1. **Python 3.14**（本番の Docker が `python:3.14-slim`。3.11 以上なら動くが、本番と揃えるほうが安全）

   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -r requirements.txt
   ```

2. **`.env` を作る**。無くても動く（検索は iTunes と MusicBrainz、保存はローカルの `shares/`）。
   入れると増えるものは `docs/env.md` の表。最低限の形:

   ```
   MB_USER_AGENT=trackmento/0.1 (https://github.com/あなた/…)    # MusicBrainz は連絡先入りの UA を要求する
   PUBLIC_BASE_URL=auto
   ```

3. **コミットの見張りを入れる**（クローンごとに 1 回）

   ```bash
   git config core.hooksPath .githooks
   ```

   `.githooks/pre-commit` が、鍵を含みそうなもの（`.env` とその控え・`*.pem`・値の入った
   `SECRET=` の形）をコミットの瞬間に止める。**2026-09-14 に `.env` の控えを公開リポジトリへ
   入れてしまった**ため（`docs/gotchas.md`）。GitHub の push protection は発行元の分かる形しか
   止められず、R2 の鍵のような「ただの英数字」はすり抜ける。

4. **起動**

   ```bash
   APP_FROM_R2=0 PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
   ```

   `PYTHONUTF8=1` は必須に近い。付けないと Windows の既定が cp932 で、日本語のタイトルを扱うときに落ちる。

5. **確認**。http://localhost:8000/ を開き、適当なアーティストで検索 → マスに入る →「トラックを共有」で
   画像ができれば一通り動いている。起動ログの `[public] PNG の URL は …` が、返ってくる URL のベース。

- **動画（`promo/`）を触るときだけ** Node と `npm install` が要る。Remotion（React で動画を書く）と
  Playwright（画面を録る）を使う。素材の作り方は `video-notes.md`
- **`scripts/` を動かすとき**も同じ venv を使う。`python` を直に叩くと `.env` が読まれず、
  R2 を見ているつもりでローカルの `shares/` を見ていることがある（`CLAUDE.md` の「覚え書き（核）」）
