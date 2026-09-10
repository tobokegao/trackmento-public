---
name: site-safety-check
description: TRACKMENTO（公開サイト／ローカル）の安全性を定期点検する。応答ヘッダ・SSRF・入力上限・XSS・アップロードのメタデータ・共有 JSON・依存関係・Render の状態を、自動スクリプトと手動確認で見て、NG があれば直す。
---

# サイト安全性チェック

TRACKMENTO を公開したまま安全に保つための点検手順。月 1 回、または大きな変更を入れたあとに実行する。
観点は IPA「安全なウェブサイトの作り方」と OWASP Top 10 / Cheat Sheet に沿う。

## 0. 前提

- Python は必ず `.venv/Scripts/python`。ローカルを点検するときは uvicorn を先に起動する（CLAUDE.md の起動手順）
- 検査は読み取り中心。書き込みは検査用グリッド 1 件・画像 1 枚・共有 1 件だけで、R2 の資格情報（.env）があれば最後に消す
- 秘密（.env の値、R2 のキー、トークン）を出力や報告に含めない。マスクする
- 引数が無ければ公開サイト `https://trackmento.onrender.com` を対象にする。「ローカル」と言われたら `http://127.0.0.1:8000`

## 1. 自動チェックを走らせる

```bash
.venv/Scripts/python scripts/safety_check.py https://trackmento.onrender.com
```

`[NG]` の行が対処対象。項目の意味と直し方の当たりは次のとおり。

| 項目 | 見ている場所 | NG のときに見るファイル |
|---|---|---|
| CSP / HSTS / nosniff / Referrer-Policy / X-Frame-Options | 応答ヘッダ | `backend/main.py` の `rate_limit` ミドルウェア |
| インライン script の nonce | `/` の HTML | `backend/main.py` の `index()`、`frontend/index.html` の `<script>` |
| image-proxy / from-url の私設宛て拒否（SSRF） | 403 になるか | `backend/netguard.py`（DNS ピンニング、`_ip_public`） |
| ボディ 1MB・検索語 200 字・URL 2048 字の上限 | 413 / 422 | `backend/main.py` の `_BODY_LIMIT_*`、`Query(max_length=)` |
| 公開モードで `/render`・`/grids` 一覧・DELETE が閉じている | 404 / 405 | `backend/main.py` の `public_mode()` 分岐 |
| `javascript:` / `data:` のリンク先が捨てられる（XSS） | PUT /grids の応答 | `backend/models.py` の `_opt_url` / `_image_url` |
| アップロードの EXIF / コメント除去、ランダム名、元名を返さない | /upload と保存画像 | `backend/uploads.py` の `_reencode`、`backend/main.py` の `upload_image` |
| 共有 JSON に `name`（ブラウザ ID）・`savedAt` が無い | /shares/<id>.json | `backend/share.py` の `create`（`exclude=`） |
| 共有ページの noindex と CSP | /s/<id> | `backend/share.py` の `page_html` |
| robots.txt / sitemap.xml | 200 か | `backend/main.py` の `robots()` / `sitemap()` |

## 2. 手動で見る項目（スクリプトでは判定できないもの）

1. **依存関係**: `gh pr list --repo tobokegao/trackmento-public` で Dependabot の PR を確認し、`gh run list --repo tobokegao/trackmento-public --workflow audit.yml --limit 3` で監査（pip-audit ＋ 起動テスト）が成功しているか見る。
   失敗していれば原因の PR を報告する。マージは利用者の判断（マージすると Render が自動デプロイする）
2. **Render の状態**: メモリ超過の再起動メールが来ていないか利用者に聞く。来ていたら `backend/render.py` の描画（`load_cover` の縮小、`render()` の直接描画）が壊れていないかと、
   ローカルで `scratchpad` 相当の計測（64 マス・3000px・16:9 でピーク 150MB 未満）を再現する
3. **ログの中身**: `[error]` / `[share] failed` の print にクエリ文字列や IP が混ざる変更が入っていないか `git log -p --since=<前回> -- backend/main.py` で見る。
   Docker の起動コマンドに `--no-access-log` が残っているか `Dockerfile` を見る
4. **秘密の混入**: `git ls-files | grep -i "\.env$\|secret\|key"` が `.env.example` 以外を返さないこと。`git log -p -S"R2_SECRET_ACCESS_KEY=" --all` が空であること
5. **利用条件の変化**: README「各サービスの利用条件」の日付が 6 か月以上前なら、iTunes / MusicBrainz / YouTube oEmbed / niconico / bilibili / Spotify / otoDB の規約ページを見直すよう提案する（変更の確認は利用者が原文を読む）
6. **外部の採点**: 利用者に https://securityheaders.com と https://observatory.mozilla.org に `https://trackmento.onrender.com` を入れてもらい、A 未満の項目があれば理由を調べる

## 3. 報告のしかた

- 先頭に結論（NG の数、直したもの、残ったもの）。次に NG ごとに「何が」「どこで」「どう直したか」を 1〜2 文
- 直したものはコミットして push し、Render の再デプロイ後にスクリプトを再実行して OK を確認する
- 直さないと決めたものは理由を書く（例: 利用者の判断が要る、外部サービス側の仕様）
- 検査で作ったデータ（共有・アップロード・検査用グリッド）が残っていないか最後に述べる

## 4. やってはいけないこと

- 本番の R2 バケットや `shares/` `uploads/` を検査データ以外まとめて消さない
- レートリミットや共有回数の上限を超える連打（1 回の点検で共有は 1 件まで）
- 実在の第三者のサイトや IP に対する攻撃的なリクエスト（検査対象は自分のサーバーだけ。私設アドレス宛ての拒否確認はサーバー側で止まる）
