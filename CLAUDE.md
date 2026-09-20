# TRACKMENTO — Claude Code 向けメモ

## これは何か

**好きな曲のジャケットを格子状に並べて 1 枚の画像にする道具**。「私を構成する 9 曲」のような
画像を、音楽サブスクに入っていなくても、どのサイトの曲でも混ぜて作れるようにしたもの。

本番 https://trackmento.com/ 。（2026-09-18 に trackmento.onrender.com から移転。古い URL は引っ越しの受け皿として生かしてある）手元では同じコードをローカルの uvicorn で動かす。
`trackmento-spec.md` は 2026-09-09 時点の初期仕様の記録（今の仕様はこのファイルと `docs/` が正）。このファイルは**作業する人がまず読むもの**。

### 何が他と違うか

- **曲単位**で扱う。アルバム単位の似た道具は多いが、曲ごとのジャケットを並べられるものは少ない
- **出どころを混ぜられる**。iTunes・MusicBrainz・otoDB・VocaDB（Discogs はトークンがあるとき）の検索に加えて、
  Bandcamp / SoundCloud / YouTube / ニコニコ動画 / Spotify / Apple Music の URL を貼っても入る。
  ジャケットが無い曲は画像 URL を手で入れてもいい
- **プレイリストを丸ごと**入れられる（最大 500 曲）。マイリストや再生リストの URL を 1 本貼るだけ
- **消えた動画がよみがえる**。削除済みのニコニコ動画でも、otoDB（音MAD データベース）に
  登録があればタイトル・作者・サムネイルを引ける
- **登録なし・無料**。並びはブラウザとサーバーの両方に持ち、共有は 30 日で自然に消える

## 全体の仕組み

```
ブラウザ (frontend/index.html — 単一 HTML)
  │  検索 / URL から取得 / 並べ替え
  │  共有画像は **ブラウザの Canvas で描いて** サーバーへ送る
  ▼
FastAPI (backend/)
  ├ sources/      … 各サイトから曲とジャケットを取る
  ├ merge.py      … 出どころの違う結果を 1 つにまとめる（重複を消す）
  ├ cache.py      … 検索結果と画像を SQLite に覚える
  ├ grids.py      … 並びの検証と保存（grids/<名前>.json）
  ├ render.py     … **サーバー側の描画**（CLI と、Canvas が使えない端末のため）
  ├ share.py      … 共有ページ（/s/<id>）の組み立て
  ├ storage.py    … R2（Cloudflare）への読み書き
  └ main.py       … 経路・CSP・画像の中継・ログ
  ▼
Cloudflare R2 (img.trackmento.com)
   共有画像・並びの控え・アップロード画像・分割フォント・画像キャッシュ
```

**要点は「描画が 2 系統ある」こと。** ふだんはブラウザが Canvas で描いて `/share/upload` に送る
（サーバーの CPU を使わないため）。Canvas が使えない端末だけ `/share` でサーバーが描く。
この 2 つは**同じ絵にならなければいけない**ので、レイアウトの式・色・文字の省略規則を
両方に同じものを書いてある。片方だけ直すと、一部の端末でだけ見た目が変わる。

## なぜこの形なのか（設計の判断）

- **サーバーにお金をかけない**。Render の転送量が課金対象なので、出せるものは R2 から出す。
  R2 は転送量が無料。フォント・共有画像・画像キャッシュを全部そちらに逃がしてある
- **画像は「小さい版を選ぶ」**。こちらで圧縮せず、配信元が用意している小さい版の URL に
  書き換えるだけ（`clamp_size`）。画質が落ちないうえ、転送量が減る
- **ブラウザに描かせる**。無料プランだった頃、サーバー描画が重なるとヘルスチェックに落ちて
  再起動していた。Canvas に逃がしてからその問題が消えた
- **状態をサーバーに持ちすぎない**。並びはブラウザの localStorage が主で、サーバーは控え。
  登録が要らないのはこのため

## デザインと言葉づかい

見た目は **Mac OS 9（プラチナ）風**に寄せてある。角丸を使わない、影は真っ黒を右下にずらす、
タイトルバーは縞模様、スクロールバーは溝とつまみの立体感まで作る。今どきのフラットな
Web ツールとは逆を行く。**素っ気なさと厚みの同居**が持ち味なので、装飾を足すときは
「OS 9 のダイアログに出てきそうか」を基準にする。

- 色とフォントは **CSS 変数のトークン経由**でしか使わない（`--color-ink` など）。
  直接 `#000` と書くと、後で一括で変えられなくなる
- 文字は 3 種類。本文は IBM Plex Sans JP、数字や記号は Silkscreen（ピクセル）、
  補助は DotGothic16。**ピクセルフォントは小さくすると字形が潰れる**ので、
  10px まで落とすくらいなら消す（マスが小さいときの番号バッジがそれ）
- 言葉は**やわらかい日本語**にする。「エクスポート」ではなく「並びを保存」、
  「グリッドサイズ」ではなく「横 × 縦」。専門語を避けるほうが、音楽好きに届く
- 英語は**日本語の文面そのものを鍵**にして引く（`EN` 表）。原文がコードに残るので読みやすいが、
  **日本語を 1 文字直すと英語がそこだけ日本語に戻る**。`scripts/check_i18n.py` で必ず確かめる

## ファイルの役割（どこを見れば何があるか）

| ファイル | 役割 | 触るときの注意 |
| --- | --- | --- |
| `frontend/index.html` | 画面すべて。CSS も JS も 1 枚に入っている | 固定文字を変えたら**フォントの作り直しと i18n の照合**が要る（下の表） |
| `backend/main.py` | 経路、CSP、`/image-proxy`、ログ、起動処理 | CSP は `R2_PUBLIC_URL` から自動で組む。手で書き足さない |
| `backend/render.py` | サーバー側の描画 | `renderShareCanvas` と**対で直す**。`rnd()` を使う（Python の `round()` は偶数丸め） |
| `backend/grids.py` | 並びの検証・保存 | マスの上限をここだけ小さくすると**並びが黙って潰れる** |
| `backend/cache.py` | 検索結果と画像の SQLite キャッシュ | 画像の期限は R2 の掃除（7 日）より短い 6 日。逆にすると 404 が出続ける |
| `backend/storage.py` | R2 の読み書き | `connect_timeout` は 3 秒のまま。長くすると利用者の待ち時間が跳ねる |
| `backend/sources/*` | 各サイトからの取得 | 取れるサイズを URL で選ぶ `clamp_size` を各自が持つ |
| `backend/merge.py` | 出どころ違いの結果をまとめる | 曲名の正規化はブラウザの `nkey()` と**同じ規則**にする |
| `cli.py` | スマホから使うための命令 | サーバーが動いていないと使えない |
| `scripts/` | 点検・突き合わせ・フォント生成・割り付けの総点検 | 下の「変更したら回すもの」に載っているものは必ず回す |
| `promo/` | 紹介動画（Remotion + Playwright）と、記事用の GIF・写真の撮影 | 詳しくは `video-notes.md`。**撮影は `capture.mjs`（1 コマずつ・場面ごと）、書き出しは `render_cached.mjs`（変わった区切りだけ）、台本は譜割りエディタから `plan_gen.mjs`**（2026-09-20）。**使い捨ての調査スクリプトは置かない**（scratchpad で済ませる。2026-09-16 と 2026-09-20 に 19 本ずつ消した。**docs か video-notes.md から名指しされているものだけ残す**） |

### データはどこにあるか

- `grids/<名前>.json` … 並び。公開モードではブラウザごとに `u-<id>.json` に分かれる。**git 管理外**
- `cache.sqlite3` … 検索結果と画像。**デプロイのたびに消える**（コンテナのディスクなので）
- R2 … 共有画像・並びの控え・アップロード画像・フォント断片・画像キャッシュ・検索結果の控え。共有は 30 日、画像キャッシュと検索結果の控えは 7 日で消える（`scripts/r2_prune.py`）
  - **検索結果の控え（`searchcache/`、`backend/searchcache.py`、2026-09-19）**。`cache.sqlite3` はデプロイで消えるので、
    サーバーで引いた検索結果（VocaDB・otoDB・Discogs・MusicBrainz の引き直し）を R2 にも置く。起動後に一覧して索引を作り
    （`imgcache/` と同じ）、索引に無い語は R2 を見に行かない。R2 から読むのは 0.15 秒（VocaDB は数秒〜25 秒）。
    **鍵は HMAC（秘密鍵は R2 の鍵、`SEARCHCACHE_SECRET` で上書き可）、中身に検索語を入れない**（R2 は公開ドメインから読めるので、
    素のハッシュだと「この語が検索されたか」を確かめられる。プライバシーポリシーの「検索キーワードは恒常的に記録しない」と両立させる）。
    期限は 6 日、`r2_prune.py` が 7 日で消す（`SHORT_PREFIXES`）。**iTunes と MusicBrainz はブラウザから直接引くので対象外**
- `outputs/` … CLI で書き出した PNG

## はじめて動かすまで（セットアップ）

何も無い状態から手元で動かす手順。**Windows 前提**（パスは `.venv/Scripts/`。macOS / Linux なら `.venv/bin/`）。

1. **Python 3.14**（本番の Docker が `python:3.14-slim`。3.11 以上なら動くが、本番と揃えるほうが安全）

   ```bash
   python -m venv .venv
   .venv/Scripts/python -m pip install -r requirements.txt
   ```

2. **`.env` を作る**。無くても動く（検索は iTunes と MusicBrainz、保存はローカルの `shares/`）。
   入れると増えるものは次の節の表。最低限の形:

   ```
   MB_USER_AGENT=trackmento/0.1 (https://github.com/あなた/…)    # MusicBrainz は連絡先入りの UA を要求する
   PUBLIC_BASE_URL=auto
   ```

3. **起動**

   ```bash
   PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

   `PYTHONUTF8=1` は必須に近い。付けないと Windows の既定が cp932 で、日本語のタイトルを扱うときに落ちる。

4. **確認**。http://localhost:8000/ を開き、適当なアーティストで検索 → マスに入る →「トラックを共有」で
   画像ができれば一通り動いている。起動ログの `[public] PNG の URL は …` が、返ってくる URL のベース。

- **動画（`promo/`）を触るときだけ** Node と `npm install` が要る。Remotion（React で動画を書く）と
  Playwright（画面を録る）を使う。素材の作り方は `video-notes.md`
- **`scripts/` を動かすとき**も同じ venv を使う。`python` を直に叩くと `.env` が読まれず、
  R2 を見ているつもりでローカルの `shares/` を見ていることがある（下の覚え書き参照）


## どこに何が書いてあるか（まずここ）

このファイルは**毎回すべて読み込まれる**ので、核だけを置いてある（2026-09-20 に 11 万字から分けた）。
詳しいことは下のファイルにある。**作業を始める前に、その作業の行のファイルを読む**。

| これから触るもの | 読むファイル |
| --- | --- |
| 書き出し画像の割り付け（`render.py` / `renderShareCanvas`・曲名リスト・回り込み・柱と帯） | `docs/layout.md` |
| 画面の見た目と操作（スライダー・スクロールバー・パレット・大きく見る・日本語と英語） | `docs/ui.md` |
| 取得元（iTunes・MusicBrainz・VocaDB・otoDB・Bandcamp・画像の大きさ） | `docs/sources.md` |
| 共有（送信・保存・プレビュー・リンクカード・みんなのグリッド） | `docs/share.md` |
| 本番の運用（Render・R2・画像の中継・点検・引っ越し・過去の数字） | `docs/ops.md` |
| 環境変数 | `docs/env.md` |
| 紹介動画と記事の素材 | `docs/promo.md`、`video-notes.md` |
| 「前にも同じ所でつまずいた気がする」とき | `docs/gotchas.md` |
| 「なぜこうなっているのか」「次に何をする予定だったか」 | `docs/history.md`、メモリの `project-status-tasks-done` |
| 外部サービスの規約と上限・問い合わせの記録（VocaDB・Bandcamp・otoDB） | `docs/services-terms.md` |

**今の状況（点検の数字・待っていること）は運用ボード**: https://claude.ai/artifact/F3TPV7qzZJKN4kpwFT6KSA

### 書き足すときの決まり（核を太らせない）

- **核（このファイル）に足してよいのは「毎回必要なこと」だけ**。危ない操作・二重実装・手順の表・索引
- 直した理由や実測、細かい規則は**該当する `docs/*.md` の側**に足す。日付と「なぜ」を必ず書く（これまでどおり）
- 利用者に見える変化は `backend/pages.py` の `CHANGES` に 1 行（同じコミットで）
- 今の状況（待っていること・点検の数字）は**このファイルに書かない**。メモリと運用ボードが持つ

### 最低限これだけは

- **手元でブラウザ確認するときは `PUBLIC_MODE=1` とポート 8000**（下の「覚え書き（核）」）
- **同じ知識が 2 か所以上にある所**（下の一覧）。片方だけ直すと壊れる
- **変更したら回すもの**（下の表）。忘れると本番が壊れるか、気付けない
- すべて `PYTHONUTF8=1 .venv/Scripts/python …` で実行する（cp932 で落ちる）

## 環境変数（核だけ。一覧は `docs/env.md`）

- `PUBLIC_MODE` … 1 で公開モード。**手元のブラウザ確認でも必ず付ける**（付けないと利用者の `grids/default.json` を上書きする）
- `MAX_CELLS` / `MAX_SIDE` … マスの総数と PNG の最大辺。**変えるなら 4 か所すべて**（下の表）
- R2 の 4 つ（`R2_ACCOUNT_ID` ほか。`R2_PUBLIC_URL` と `R2_ENDPOINT` は任意）… 揃っていないと `get_storage()` が黙ってローカルの `shares/` に落ちる
- 鍵は**リポジトリに書かない**。本番は Render のダッシュボード、手元は `.env`、点検は GitHub Secrets

## 起動（PC 側、毎回）

```bash
cd trackmento-public   # 手元のフォルダ（名前は環境による）
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
.venv/Scripts/python cli.py add    --url "https://xxx.bandcamp.com/track/..." [--grid NAME]     # Bandcamp / SoundCloud / Spotify / Apple Music / YouTube / ニコニコ動画の URL
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
- `share` は画像（JPEG 品質 78）と並びスナップショットを `shares/<id>.{jpg,json}` 保存、共有ページ `http://…/s/<id>` の URL 出力。
  共有ページ内容: 画像・曲リスト・「TRACKMENTO で開く」（`/?share=<id>` でその並びを Web 読込）
- `share` / `render` 最終行は必ず `URL: http://...`
- 検索結果・画像は `cache.sqlite3` にキャッシュ。再取得は Web の `/search?...&nocache=true`

## スマホからの依頼への対応手順

### 「○○の『△△』を追加して」
1. `cli.py add --artist "○○" --title "△△"` 実行
2. 曲名＋アーティスト一致候補あれば自動で次の空きマスへ。出力「NN 番に追加: …」をそのまま伝達
   （検索順 iTunes → MusicBrainz → Discogs（--source mb,discogs 等で絞込可）。iTunes は曲名・アーティスト名にクエリ含むもののみ返却、完全一致先頭）
3. **候補複数時は必ず番号付き提示、ユーザーの番号返答後** `cli.py pick --index N` で確定。勝手に選ばない
4. 未発見時の順: `--source discogs` / `--source mb`（音MAD は `--source otodb`）→ Bandcamp / SoundCloud / Spotify / Apple Music / YouTube / ニコニコ動画なら URL 受取→ `--url URL` → 画像 URL 受取→ `--image URL --artist --title`
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

## お問い合わせ（Google フォーム）

https://forms.gle/2ktpQAXMjJrkFJFz8 （2026-09-19。新しい回答は to6okegao@gmail.com にメールで届く設定）。
リンクは運営者ページ・更新情報の「うまくいかないとき」・共有に失敗したときのメッセージの 3 か所
（`backend/pages.py` の `CONTACT_FORM` と frontend の `CONTACT_FORM`。**URL を変えるときは両方**）。
自前のフォームにしなかったのは、メール配信の仕組み・迷惑投稿の対策・なりすまし対策（`v=spf1 -all`）の見直しが要るため

## 更新情報のページ（`/updates`）

`backend/pages.py` の `CHANGES` に、**利用者に見える変化だけ**を日付と 1〜2 行（日本語・英語）で先頭に足す（2026-09-19 に作った）。
内部の直し（点検・ログ・リファクタ）は書かない。**「検討中」は書かない**（一人で運営しているので、約束に見えるものを増やさない）。
「分かっている不具合」「うまくいかないとき」は `_updates` の本文にある。直したら消す。**コミットと同じ回に 1 行足す**

**まとまった文章は Gemini に添削してもらってから利用者に渡す**（2026-09-19、利用者の依頼。以前は利用者が手で Gemini に聞いていた）。
`PYTHONUTF8=1 .venv/Scripts/python scripts/proofread.py <下書き.txt> --out <添削.txt>`（鍵は `.env` の `GEMINI_API_KEY`、モデルは `gemini-3.8-flash`）。
**README など作業する人向けの文書は `--doc` を付ける**（告知文用の指示は「です・ます」にそろえるので、常体の文書が文体ごと書き換わる。2026-09-20）。
**`gemini-3.8-flash` が使えないとき（無料枠は 1 日 20 回）は回さない**。別のモデルで代用せず、下書きを利用者に渡す
（利用者が手で 3.8 flash にかけて返す。2026-09-20 の指定）。
**Gemini の直しをそのまま採らない**: 事実（言い切りすぎ）・画面の表記（「」の中）・書き方の好み（「しづらく」）を突き合わせて取捨し、
利用者には txt で「仕上がり」と「採った直し・採らなかった直しと理由」を渡す。書き方の好みはスクリプトの `STYLE`

## 変更したら回すもの（忘れると本番が壊れる／気付けない）

| 何を変えたか | 回すもの | 忘れるとどうなるか |
| --- | --- | --- |
| `frontend/index.html` の固定文字 | `scripts/build_fonts.py` → `scripts/upload_fonts_r2.py` | **本番でフォントが 404**（断片名にハッシュが入るため） |
| 同上 | `scripts/check_i18n.py` | 英語表示でそこだけ日本語のまま残る（警告は出ない） |
| 描画（`render.py` か `renderShareCanvas`） | `scripts/compare_render.py` | サーバー描画とブラウザ描画がずれる（描けない端末だけ見た目が変わる） |
| マスの上限 | 4 か所すべて（下記） | 並びが黙って潰れる |
| 機能を足した・やめた | `scripts/check_consistency.py`（手順は `/consistency-check`） | 文書と画面に古い案内が残る |

上限の 4 か所: `frontend/index.html` の `MAX_SIDE_CELLS`（1 辺 32）と `MAX_CELLS`（総数 256）、
`backend/grids.py` の `MAX_COLS` / `MAX_ROWS`（1 辺）、`backend/config.py` の `max_cells()`（総数）。

すべて `PYTHONUTF8=1 .venv/Scripts/python …` で実行する（cp932 で落ちる）。


## 開発メモ（核）

- 構成: `backend/`（FastAPI、sources/、cache.py、grids.py、render.py、share.py、uploads.py、config.py）、`frontend/index.html`（単一 HTML）、`cli.py`、`fonts/`（OFL 同梱）
- 動作確認は各ステップごとブラウザで（`claude-in-chrome` または手動）。サーバー `--reload` なし起動時、コード変更後再起動必要


## 二重実装の一覧（片方だけ直すと壊れる）

- **同じ知識が 2 か所以上にある所の一覧**（今回のバグはすべてここから出た）。片方だけ直すと壊れる:
  - 描画: `backend/render.py` と `frontend/index.html` の `renderShareCanvas`（定数・レイアウト式・文字の省略規則）
    → `scripts/compare_render.py` で突き合わせられる。丸めは `render.py` の `rnd()` が JS の `Math.round` に
    合わせてある（**Python の `round()` は偶数丸めなので使ってはいけない**）
  - 曲名リストの組み方（1 曲 1 行ではないほう）: `render.py` の `_row_plan` / `_plan_rows` / `_split_title` /
    `_sidebar` と frontend の `rowPlan` / `planRows` / `splitTitle` / `sidebar`。2026-09-15 に他サービスを
    参考にして作り直した。**曲名とアーティスト名は上下 2 行**（横に並べると長い曲名でアーティストが押し出される）、
    **文字が小さくなるなら列を増やす**（25 曲で 2 列。出力で何 px になるかで決める。上限 3 列）
    - **サイドバーの幅は文字を測って決めない**。比率があるときは比率から決まる残り幅、無いときはグリッドと同じ幅。
      文字の幅は PIL と Canvas で数 px 違い、幅を実測で決めると**中央寄せのグリッドまで 1〜2px ずれる**
      （突き合わせでグリッド側に 6% の差が出て、原因を探して行き着いた）。16px 刻みに丸める案は、
      境目をまたぐと逆に 16px ずれるので却下
    - 列の間隔は `LIST_COL_GAP`（マスの間隔の 5 倍）。マスと同じ間隔だと隣の列の曲名と近すぎて、
      どちらの列か迷う
    - 曲名が 1 行に入らないときだけ 2 行に折る。**折る位置は「行の真ん中にいちばん近い切れ目」**
      （2 行の長さがそろうように）。「(feat. …)」の手前は少し優遇していて、ちょうどよい位置なら選ばれる。
      2 行目がわずかにはみ出すだけなら**縮めて収める**（0.92 → 0.86 → 0.8）。「…」で切るのは最後
  - 曲名リストの回り込み（正方形以下の比率で曲が多いとき）: `render.py` の `_wrap_plan` / `WRAP_*` と
    frontend の `wrapPlan` / `WRAP_*`。下の「曲名の回り込み」を参照
  - 柱・帯（塊を枠の辺に付ける組み方）: `render.py` の `_slab_plan` / `_slab_frame` / `SLAB_*` と
    frontend の `slabPlan` / `slabFrame` / `SLAB_*`
  - 曲名リストの流し込み: `render.py` の `_flow_rows` / `FLOW_*` と frontend の `flowRows` / `FLOW_*`。
    **折り返しは字の単位。ただし両端をそろえること**がずれを抑える鍵。
    字で折ると PIL と Canvas のわずかな計測差で折り返す位置が変わるが、行ごとに右端でそろえていれば
    そこで吸収され、次の行へ積み上がらない（`compare_render.py` のぼかし後の差: 両端そろえ無し 3.19% →
    **両端そろえ有り 0.71%**。基準は 1%）。曲の単位で折れば 0.05% まで下がるが、
    行の頭がいつも番号になって規則的に見えるので採らなかった
    - **語の尻尾だけが次の行へこぼれるなら、語ごと次の行へ送る**（`FLOW_TAIL` = 2 字・`FLOW_WORD_MAX` = 12 字、`tail_back` / `tailBack`、
      2026-09-20、利用者の 11x11・16:9・121 曲で「ビリー・アイリッシ／ュ」「La／ur」）。語の区切りは空白と記号（`FLOW_WORD_SEP`）。
      送った行の末尾の空白は外す。**曲名の最初の語は送らない**（番号だけが行末に取り残される）。こぼれるのが 3 字以上なら今までどおり字の途中で折る
    - 余りの配分は**空白 1 つぶんまで**。上限を付けないと、1 行の曲数が少ないときに切れ目が間延びする
    - **曲の切れ目（全角空白 1 つぶん）は必ず描く**。幅だけ取って描かないでいると、余りの無い行で
      曲と曲がくっつく（利用者の画像で「Chevon06 例え話」のように番号が前の曲名に貼り付いていた。
      2026-09-14 に直した）。行末に来た切れ目は数に入れない（使っていない送りを幅に含めると余りの配分がずれる）
    - **折り返しの判定は字幅を 1px に丸めてから行う**。PIL と Canvas の字幅は 1px 未満だけ違い、
      生の値で足すと境目の字で折る・折らないが入れ替わって、そこから先の行が全部ずれる
      （丸める前 2.28% → 丸めた後 0.66%）。描くときは実寸のまま
    - **ブラウザ側の字幅の控え（`CHAR_W`）は、Web フォントが効く前の値を持ち越してはいけない**。
      読み込み直後の `layout()` はまだ代替フォントで測るので、そのまま残すと**折り返しが
      サーバーとずれる**（16x16・16:9 の突き合わせで 0.26% → 3.69% になっていた。
      `renderShareCanvas` の先頭で捨て、`document.fonts` の `loadingdone` でも捨てる）
    - **行の中身は 1 本のベースラインに乗せる**（`BASELINE` = 0.38。字の大きさに対する比）。
      PIL の `anchor="lm"` と Canvas の `textBaseline="middle"` は基準が違い、**文字が大きいほど
      食い違う**（出力 64px で 10px ずれた）。**字面を実測して決めてはいけない**:
      PIL の `getbbox` と Canvas の `actualBoundingBox` も数 px 違うので、固定比のほうが揃う
    - **1px に丸める前に 1/64 px にそろえる**（frontend の `snapW`）。PIL は字幅を 1/64 px の固定小数で返すので、
      実寸がちょうど .5 px になる字（IBM Plex の `e` / `r` / `-`）だけ Canvas の実数と丸めの向きが食い違い、
      その 1 字から先の折り返しが全部ずれる。**190 字中 3 字の差で、回り込みの突き合わせが
      6px のぼかしで 0.94% → 0.07% まで変わった**
  - 検索の絞り込み: `backend/sources/itunes.py` と frontend の `itunesSearch`（ブラウザから直接 iTunes を叩くため）
  - 描く前の文字の掃除: `render.py` の `_drawable`（フォントの cmap に無い字を落とす）と frontend の `oneLine`
    （`STRIP_RE` = 絵文字・私用領域・補助面を落とす）。**Chromium の `\p{Extended_Pictographic}` は ★ ♪ ♡ ♥ も
    絵文字扱い**なので、フォントにあるものは `KEEP_PICTO`（31 字）で残す（2026-09-16。落としていたときは
    「ブラック★ロックシューター」の幅がずれて 12x20 の回り込みが別物になり、`compare_layout.py --tracks` で
    25/200 食い違った）。フォントを替えたら一覧を作り直す（Chromium で測る。Node の判定は ★ を含まない）
    - **既知の食い違い**（2026-09-17、未対応）: フォントに無い BMP の字（「◈」U+25C8、タミル文字「ஐ」など）は
      PIL 側（`_drawable`）が落とすが、Chromium は代替フォントで測るので幅がずれ、`compare_layout.py --tracks` で
      36 曲の組 13/200・25 曲の組 18/200 食い違う。ブラウザ描画どうしは一貫しているので実害は小さい。
      直すなら JS にもフォントの cmap（`fonts/split/` の unicode-range）を持たせて同じ字を落とす
  - 曲名の正規化: `backend/merge.py` の `_n()` と frontend の `nkey()`。
    **Python の `casefold()` は ß を ss に畳むが JS の `toLowerCase()` は畳まない**ので手で合わせてある。
    **単独の濁点・半濁点（゛゜）は結合文字に置き換えてから NFKC**（「ハ゛」→「バ」。NFKC だけでは合成されない）
  - マスの上限: 4 か所（上の表）
  - 文言: 日本語の原文と `EN` 表 → `scripts/check_i18n.py`
  - 色・比率・`CELL_PX` / `GAP_PX` / `MAX_SIDE`: `render.py` と `index.html`（2026-09-14 時点で一致を確認済み）

## 覚え書き（核）

- **マスの上限は 4 か所にあり、ずれると並びが黙って壊れる**。`frontend/index.html` の `MAX_SIDE_CELLS`（1 辺）と
  `MAX_CELLS`（総数）、`backend/grids.py` の `MAX_COLS` / `MAX_ROWS`（1 辺）、`backend/config.py` の `max_cells()`（総数）。
  **`grids.py` の側を小さくしてはいけない**。`GridDoc` の検証は cols/rows を黙って丸め、はみ出したマスを stash に移すので、
  16x16 の並びを保存した瞬間に 12x12 へ潰れる（2026-09-14 に実際に起きていた。上限を 256 に上げたとき
  `grids.py` と `applyData` の 12 を直し忘れていた）
- **ブラウザで動作を確かめるときは `PUBLIC_MODE=1` を付けて起動する**。付けないとグリッド名が `default` になり、
  **`grids/default.json`（利用者の並び）をテストで上書きしてしまう**（2026-09-14 に実際にやった。
  幸い `grids/default.json.bak-*` が残っていたので復元できた）。公開モードならブラウザごとの `u-….json` に分かれる
  ```bash
  PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
  ```
  R2 の CORS は `localhost:8000` / `127.0.0.1:8000` だけ許可しているので**ポートは 8000 固定**
- **`grids/` と `shares/` は `.gitignore`**。並びを壊しても git では戻せない。ただし `shares/<id>.json` は共有したときの並びのスナップショットなので、**そこから失われたマスを復元できる**（実例: 1 マス目だけ消えたグリッドを、同じ並びの共有 JSON から戻した）
