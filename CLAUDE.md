# TRACKMENTO — Claude Code向けメモ

## これは何か

**好きな曲のジャケットを格子状に並べて1枚の画像にする道具**。「私を構成する9曲」のような
画像を、音楽サブスクに入っていなくても、どのサイトの曲でも混ぜて作れるようにしたもの。

本番https://trackmento.com/ 。（2026-09-18にtrackmento.onrender.comから移転。古いURLは引っ越しの受け皿として生かしてある）手元では同じコードをローカルのuvicornで動かす。
`trackmento-spec.md` は2026-09-09時点の初期仕様の記録（今の仕様はこのファイルと `docs/` が正）。このファイルは**作業する人がまず読むもの**。

### 何が他と違うか

- **曲単位**で扱う。アルバム単位の似た道具は多いが、曲ごとのジャケットを並べられるものは少ない
- **出どころを混ぜられる**。iTunes・MusicBrainz・otoDB・VocaDB（Discogsはトークンがあるとき）の検索に加えて、
  Bandcamp / SoundCloud / YouTube / ニコニコ動画 / Spotify / Apple MusicのURLを貼っても入る（bilibiliはotoDB・VocaDBに登録のある動画だけ。bilibili本体には問い合わせない）。
  ジャケットが無い曲は画像URLを手で入れてもいい
- **プレイリストを丸ごと**入れられる（最大500曲）。マイリストや再生リストのURLを1本貼るだけ
- **消えた動画がよみがえる**。削除済みのニコニコ動画でも、otoDB（音MADデータベース）に
  登録があればタイトル・作者・サムネイルを引ける
- **登録なし・無料**。並びはブラウザとサーバーの両方に持ち、共有は30日で自然に消える

## 全体の仕組み

```
ブラウザ (frontend/index.html — 単一HTML)
  │  検索 / URLから取得 / 並べ替え
  │  共有画像は **ブラウザのCanvasで描いて** サーバーへ送る
  ▼
FastAPI (backend/)
  ├ sources/      … 各サイトから曲とジャケットを取る
  ├ merge.py      … 出どころの違う結果を1つにまとめる（重複を消す）
  ├ cache.py      … 検索結果と画像をSQLiteに覚える
  ├ grids.py      … 並びの検証と保存（grids/<名前>.json）
  ├ render.py     … **サーバー側の描画**（CLIと、Canvasが使えない端末のため）
  ├ share.py      … 共有ページ（/s/<id>）の組み立て
  ├ storage.py    … R2（Cloudflare）への読み書き
  └ main.py       … 経路・CSP・画像の中継・ログ
  ▼
Cloudflare R2 (img.trackmento.com)
   共有画像・並びの控え・アップロード画像・分割フォント・画像キャッシュ
```

**要点は「描画が2系統ある」こと。** ふだんはブラウザがCanvasで描いて `/share/upload` に送る
（サーバーのCPUを使わないため）。Canvasが使えない端末だけ `/share` でサーバーが描く。
この2つは**同じ絵にならなければいけない**ので、レイアウトの式・色・文字の省略規則を
両方に同じものを書いてある。片方だけ直すと、一部の端末でだけ見た目が変わる。

## なぜこの形なのか（設計の判断）

- **サーバーにお金をかけない**。Renderの転送量が課金対象なので、出せるものはR2から出す。
  R2は転送量が無料。フォント・共有画像・画像キャッシュを全部そちらに逃がしてある
- **画像は「小さい版を選ぶ」**。こちらで圧縮せず、配信元が用意している小さい版のURLに
  書き換えるだけ（`clamp_size`）。画質が落ちないうえ、転送量が減る
- **ブラウザに描かせる**。無料プランだった頃、サーバー描画が重なるとヘルスチェックに落ちて
  再起動していた。Canvasに逃がしてからその問題が消えた
- **状態をサーバーに持ちすぎない**。並びはブラウザのlocalStorageが主で、サーバーは控え。
  登録が要らないのはこのため

## デザインと言葉づかい

見た目は **Mac OS 9（プラチナ）風**に寄せてある。角丸を使わない、影は真っ黒を右下にずらす、
タイトルバーは縞模様、スクロールバーは溝とつまみの立体感まで作る。今どきのフラットな
Webツールとは逆を行く。**素っ気なさと厚みの同居**が持ち味なので、装飾を足すときは
「OS 9のダイアログに出てきそうか」を基準にする。

**足さない見た目**（「今どきのWebツールっぽさ」は曖昧なので、避けるものを名指しする。2026-09-23）:
角丸・ぼかした影・グラデーションの背景（タイトルバーの縞は別）・半透明のガラス風・
クリーム色やオフホワイトの地・ピル型のボタン・絵文字のアイコン・ホバーでふわっと浮く動き・
強調のための斜体。色の細かい決まり（画面に使う色の数など）は `docs/ui.md`

- 色とフォントは **CSS変数のトークン経由**でしか使わない（`--color-ink` など）。
  直接 `#000` と書くと、後で一括で変えられなくなる
- 文字は3種類。本文はIBM Plex Sans JP、数字や記号はSilkscreen（ピクセル）、
  操作部品はJFドットM+ 12（12pxか24pxだけ。2026-09-24にDotGothic16から。PCだけ「TM Dot PC」の15px＝日本語Galmuri14・英数字 東雲14、`docs/ui.md`）。**ピクセルフォントは升目の大きさ以外だと字形が潰れる**ので、
  10pxまで落とすくらいなら消す（マスが小さいときの番号バッジがそれ）
- 言葉は**やわらかい日本語**にする。「エクスポート」ではなく「並びを保存」、
  「グリッドサイズ」ではなく「横 × 縦」。専門語を避けるほうが、音楽好きに届く
- 英語は**日本語の文面そのものを鍵**にして引く（`EN` 表）。原文がコードに残るので読みやすいが、
  **日本語を1文字直すと英語がそこだけ日本語に戻る**。`scripts/check_i18n.py` で必ず確かめる

## ファイルの役割（どこを見れば何があるか）

| ファイル | 役割 | 触るときの注意 |
| --- | --- | --- |
| `frontend/index.html` | 画面すべて。CSSもJSも1枚に入っている（**編集するのはここ**） | 固定文字を変えたら**フォントの作り直しとi18nの照合**が要る（下の表）。配るときだけ `build_app.py` が殻＋`app.<hash>.css` / `.js` に割り、CSSとJSはR2から出す |
| `backend/main.py` | 経路、CSP、`/image-proxy`、ログ、起動処理 | CSPは `R2_PUBLIC_URL` から自動で組む。手で書き足さない |
| `backend/render.py` | サーバー側の描画 | `renderShareCanvas` と**対で直す**。`rnd()` を使う（Pythonの `round()` は偶数丸め） |
| `backend/grids.py` | 並びの検証・保存 | マスの上限をここだけ小さくすると**並びが黙って潰れる** |
| `backend/cache.py` | 検索結果と画像のSQLiteキャッシュ | 画像の期限はR2の掃除（14日）より短い13日。逆にすると404が出続ける |
| `backend/storage.py` | R2の読み書き | `connect_timeout` は3秒のまま。長くすると利用者の待ち時間が跳ねる |
| `backend/sources/*` | 各サイトからの取得 | 取れるサイズをURLで選ぶ `clamp_size` を各自が持つ |
| `backend/merge.py` | 出どころ違いの結果をまとめる | 曲名の正規化はブラウザの `nkey()` と**同じ規則**にする |
| `cli.py` | スマホから使うための命令 | サーバーが動いていないと使えない |
| `scripts/` | 点検・突き合わせ・フォント生成・割り付けの総点検 | 下の「変更したら回すもの」に載っているものは必ず回す |
| `promo/` | 紹介動画（Remotion + Playwright）と、記事用のGIF・写真の撮影 | 詳しくは `video-notes.md`。**撮影は `capture.mjs`（1コマずつ・場面ごと）、書き出しは `render_cached.mjs`（変わった区切りだけ）、台本は譜割りエディタから `plan_gen.mjs`**（2026-09-20）。**使い捨ての調査スクリプトは置かない**（scratchpadで済ませる。2026-09-16と2026-09-20に19本ずつ消した。**docsかvideo-notes.mdから名指しされているものだけ残す**） |

### データはどこにあるか

- `grids/<名前>.json` … 並び。公開モードではブラウザごとに `u-<id>.json` に分かれる。**git管理外**
- `cache.sqlite3` … 検索結果と画像。**デプロイのたびに消える**（コンテナのディスクなので）
- R2 … 共有画像・並びの控え・アップロード画像・フォント断片・画像キャッシュ・検索結果の控え。共有は30日、画像キャッシュは14日、検索結果の控えは15日で消える（`scripts/r2_prune.py`）
  - 検索結果の控え（`searchcache/`）は **鍵をHMACにし、中身に検索語を入れない**（R2は公開ドメインから読める。仕組みと期限は `docs/ops.md`）
- `outputs/` … CLIで書き出したPNG

## どこに何が書いてあるか（まずここ）

このファイルは**毎回すべて読み込まれる**ので、核だけを置いてある（2026-09-20に11万字から分けた）。
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
| **スマホからの依頼**（曲を追加して・並びは？・入れ替えて・共有して）とCLI | `docs/cli.md` |
| はじめて動かすまで（venv・`.env`・コミットの見張り） | `docs/setup.md` |
| 更新情報（`/updates`）と、文章をGeminiに添削してもらう手順 | `docs/writing.md`、スキル `/updates` |

**今の状況（点検の数字・待っていること）は運用ボード**: https://claude.ai/artifact/F3TPV7qzZJKN4kpwFT6KSA

### 書き足すときの決まり（核を太らせない）

- **核（このファイル）に足してよいのは「毎回必要なこと」だけ**。危ない操作・二重実装・手順の表・索引
- 直した理由や実測、細かい規則は**該当する `docs/*.md` の側**に足す。日付と「なぜ」を必ず書く（これまでどおり）
- 利用者に見える変化は `backend/pages.py` の `CHANGES` に1行（同じコミットで）。**手順は `/updates`**
- 今の状況（待っていること・点検の数字）は**このファイルに書かない**。メモリと運用ボードが持つ

### 最低限これだけは

- **手元でブラウザ確認するときは `PUBLIC_MODE=1` とポート8000**（下の「覚え書き（核）」）
- **同じ知識が2か所以上にある所**（下の一覧）。片方だけ直すと壊れる
- **変更したら回すもの**（下の表）。忘れると本番が壊れるか、気付けない
- すべて `PYTHONUTF8=1 .venv/Scripts/python …` で実行する（cp932で落ちる）
- **スマホからの依頼は `docs/cli.md` の手順どおり**。候補が複数なら番号を付けて見せ、**勝手に選ばない**。`URL:` 行は省略せずに返す

### 進め方（どこで止まるか）

中身はメモリ `commit-push-without-asking` と同じ（2026-09-23）。

- 利用者の返事が要らない手順は**止まらずに続ける**。途中の報告は次の操作と同じメッセージに書く。
  実装したらコミットとpushまで進めてよい
- **止まって聞くのは**: 利用者なしでは進めないとき、**本番の動き・課金・データ削除・force pushの前**、
  説明のつかない理由でテストや点検が落ちたとき
- 頼まれた作業は「**何ができたら終わりか**」を先に決めてから始める（例: 点検がOK・突き合わせが基準内・
  `CHANGES` に1行・push済み）
- 報告は**先頭に「利用者にしてほしいこと」**（無ければ無いと書く）。調べたが**確かめられなかったこと**
  （外部サービスの画面・届いたメールなど）は、確かめたことと分けて書く
- 大きな点検はサブエージェントに分けてよい。**戻ってきた指摘は、該当行を自分で開いて確かめてから**直す

## 環境変数（核だけ。一覧は `docs/env.md`）

- `PUBLIC_MODE` … 1で公開モード。**手元のブラウザ確認でも必ず付ける**（付けないと利用者の `grids/default.json` を上書きする）
- `MAX_CELLS` / `MAX_SIDE` … マスの総数とPNGの最大辺。**変えるなら4か所すべて**（下の表）
- R2の4つ（`R2_ACCOUNT_ID` ほか。`R2_PUBLIC_URL` と `R2_ENDPOINT` は任意）… 揃っていないと `get_storage()` が黙ってローカルの `shares/` に落ちる
- 鍵は**リポジトリに書かない**。本番はRenderのダッシュボード、手元は `.env`、点検はGitHub Secrets

## 変更したら回すもの（忘れると本番が壊れる／気付けない）

**機械で言える分は `scripts/check.py` が門になっている**（2026-09-27）。コミット前に変えたファイルに応じて回り、push前にR2の上げ忘れを見て、push後にCI（`check.yml`）がもう一度見る。落ちたら表の「回すもの」を回す。**作業の終わりの条件は「`check.py --all` が通る」**。`compare_render.py` と `compare_trim.py` はサーバーとブラウザが要るので門では回らない（該当ファイルを変えると回すよう表示される）。

| 何を変えたか | 回すもの | 忘れるとどうなるか |
| --- | --- | --- |
| `frontend/index.html`（中身を何か変えたら） | `scripts/build_app.py` → `scripts/upload_app_r2.py` → 殻（`frontend/dist/index.html`）もコミット | 古いCSS / JSが配られ続ける（R2に新しい名前が無ければ1枚配信に倒れるので壊れはしない） |
| `frontend/index.html` の固定文字 | `scripts/build_fonts.py` → `scripts/upload_fonts_r2.py` | **本番でフォントが404**（断片名にハッシュが入るため） |
| 同上 | `scripts/check_i18n.py` | 英語表示でそこだけ日本語のまま残る（警告は出ない） |
| 描画（`render.py` か `renderShareCanvas`） | `scripts/compare_render.py` | サーバー描画とブラウザ描画がずれる（描けない端末だけ見た目が変わる） |
| 曲名の刈り込み（`names.py` か `trimName`） | `scripts/check_trim.py` → `scripts/compare_trim.py` | 画面と書き出しで曲名が変わり、折り返しから割り付けが丸ごとずれる |
| マスの上限 | 4か所すべて（下記） | 並びが黙って潰れる |
| 機能を足した・やめた | `scripts/check_consistency.py`（手順は `/consistency-check`） | 文書と画面に古い案内が残る |

上限の4か所: `frontend/index.html` の `MAX_SIDE_CELLS`（1辺32）と `MAX_CELLS`（総数256）、
`backend/grids.py` の `MAX_COLS` / `MAX_ROWS`（1辺）、`backend/config.py` の `max_cells()`（総数）。

すべて `PYTHONUTF8=1 .venv/Scripts/python …` で実行する（cp932で落ちる）。


## 二重実装の一覧（片方だけ直すと壊れる）

同じ知識が2か所以上にある所。細則と経緯は `docs/layout.md` の末尾「二重実装の細則」ほか。

- 描画: `backend/render.py` と `frontend/index.html` の `renderShareCanvas`（定数・レイアウト式・文字の省略規則）
  → `scripts/compare_render.py`。丸めは `render.py` の `rnd()` がJSの `Math.round` に合わせてある
  （**Pythonの `round()` は偶数丸めなので使ってはいけない**）
- 曲名リストの組み方（1曲1行ではないほう）: `render.py` の `_row_plan` / `_plan_rows` / `_split_title` / `_sidebar` と
  frontendの `rowPlan` / `planRows` / `splitTitle` / `sidebar`。**サイドバーの幅は文字を測って決めない**（PILとCanvasの差でグリッドまでずれる）
- 曲名リストの回り込み: `_wrap_plan` / `WRAP_*` ↔ `wrapPlan` / `WRAP_*`
- 柱・帯: `_slab_plan` / `_slab_frame` / `SLAB_*` ↔ `slabPlan` / `slabFrame` / `SLAB_*`
- 曲名リストの流し込み: `_flow_rows` / `FLOW_*` ↔ `flowRows` / `FLOW_*`（細則は `docs/layout.md` の「曲名リストの流し込み」）
- 曲名の刈り込み: `backend/names.py` ↔ `trimName`。**割り付けを決める前に通す**。**割り付けは刈り込み後のセル（`viewCells()`）で測る**
  → `scripts/check_trim.py` と `scripts/compare_trim.py`
- 検索の絞り込み: `backend/sources/itunes.py` ↔ `itunesSearch`（ブラウザから直接iTunesを叩くため）
- 描く前の文字の掃除: `render.py` の `_drawable` ↔ `oneLine`（`drawable`）。**両方ともIBM Plex Sans JPのcmapで決める**。
  JSのcmap（`PLEX_CMAP_BLOCKS` / `PLEX_CMAP_BITS`）は **`scripts/build_fonts.py` が書き込む**（手で直さない）
- 曲名の正規化: `backend/merge.py` の `_n()` ↔ `nkey()`。ß と単独の濁点（゛゜）の扱いを手で合わせてある（`docs/sources.md`）
- マスの上限: 4か所（上の表）
- 文言: 日本語の原文と `EN` 表 → `scripts/check_i18n.py`
- 色・比率・`CELL_W` / `CELL_H_BY_RATIO` / `GAP_PX` / `MAX_SIDE`: `render.py` と `index.html`
- 背景の画像: `render.py` の `_paint_bg_image` ↔ `renderShareCanvas` の頭（切り抜き・`bgImageAlpha` の濃さ）
- マスへの絵の入れ方: `_cover_blur_pad` / `blur_margin` ↔ `coverBlurPad` / `blurMargin`（**下地はマスより広く作ってから切り取る**）
- お問い合わせのフォームのURL: `backend/pages.py` の `CONTACT_FORM` ↔ frontendの `CONTACT_FORM`（`docs/ops.md`）

## 覚え書き（核）

- **マスの上限は4か所にあり、ずれると並びが黙って壊れる**（上の表）。**`grids.py` の側を小さくしてはいけない**
  （保存した瞬間に並びが潰れる。経緯は `docs/gotchas.md`）
- **ブラウザで動作を確かめるときは次の形で起動する**。`PUBLIC_MODE=1` が無いと **`grids/default.json`（利用者の並び）を上書きする**。
  `APP_FROM_R2=0` が無いとR2の古いCSS / JSが配られ、編集中の `index.html` が画面に出ない。
  R2のCORSの都合で**ポートは8000固定**
  ```bash
  APP_FROM_R2=0 PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
  ```
- `--reload` なしで起動しているときは、コードを変えたら再起動する
- **`grids/` と `shares/` は `.gitignore`**。並びを壊してもgitでは戻せない（`shares/<id>.json` から復元できることはある）
