---
name: site-safety-check
description: TRACKMENTO（公開サイト／ローカル）の安全性を定期点検する。応答ヘッダ・SSRF・入力上限・XSS・アップロードのメタデータ・共有JSON・依存関係・Renderの状態を、自動スクリプトと手動確認で見て、NGがあれば直す。
---

# サイト安全性チェック

TRACKMENTOを公開したまま安全に保つための点検手順。月1回、または大きな変更を入れたあとに実行する。
観点はIPA「安全なウェブサイトの作り方」とOWASP Top 10 / Cheat Sheetに沿う。

## 0. 前提

- Pythonは必ず `PYTHONUTF8=1 .venv/Scripts/python`（cp932で落ちるため）。ローカルを点検するときはuvicornを先に起動する（CLAUDE.mdの起動手順）
- 検査は読み取り中心。書き込みは検査用グリッド1件・画像1枚・共有1件だけで、R2の資格情報（.env）があれば最後に消す
- 秘密（.envの値、R2のキー、トークン）を出力や報告に含めない。マスクする
- 引数が無ければ公開サイト `https://trackmento.com` を対象にする。「ローカル」と言われたら `http://127.0.0.1:8000`

## 1. 自動チェックを走らせる

```bash
PYTHONUTF8=1 .venv/Scripts/python scripts/safety_check.py https://trackmento.com
```

`[NG]` の行が対処対象。項目の意味と直し方の当たりは次のとおり。

| 項目 | 見ている場所 | NGのときに見るファイル |
|---|---|---|
| CSP / HSTS / nosniff / Referrer-Policy / X-Frame-Options | 応答ヘッダ | `backend/main.py` の `rate_limit` ミドルウェア |
| インラインscriptのnonce | `/` のHTML | `backend/main.py` の `index()`、`frontend/index.html` の `<script>` |
| image-proxy / from-urlの私設宛て拒否（SSRF） | 403になるか | `backend/netguard.py`（DNSピンニング、`_ip_public`） |
| ボディ1MB・検索語200字・URL 2048字の上限 | 413 / 422 | `backend/main.py` の `_BODY_LIMIT_*`、`Query(max_length=)` |
| 公開モードで `/render`・`/grids` 一覧・DELETEが閉じている | 404 / 405 | `backend/main.py` の `public_mode()` 分岐 |
| `javascript:` / `data:` のリンク先が捨てられる（XSS） | PUT /gridsの応答 | `backend/models.py` の `_opt_url` / `_image_url` |
| アップロードのEXIF / コメント除去、ランダム名、元名を返さない | /uploadと保存画像 | `backend/uploads.py` の `_reencode`、`backend/main.py` の `upload_image` |
| 共有JSONに `name`（ブラウザID）・`savedAt` が無い | /shares/<id>.json | `backend/share.py` の `create`（`exclude=`） |
| 共有ページのnoindexとCSP | /s/<id> | `backend/share.py` の `page_html` |
| robots.txt / sitemap.xml | 200か | `backend/main.py` の `robots()` / `sitemap()` |

## 2. 手動で見る項目（スクリプトでは判定できないもの）

1. **依存関係**: `gh pr list --repo tobokegao/trackmento-public` でDependabotのPRを確認し、`gh run list --repo tobokegao/trackmento-public --workflow audit.yml --limit 3` で監査（pip-audit＋ 起動テスト）が成功しているか見る。
   失敗していれば原因のPRを報告する。マージは利用者の判断（マージするとRenderが自動デプロイする）
2. **Renderの状態**: メモリ超過の再起動メールが来ていないか利用者に聞く。来ていたら `backend/render.py` の描画（`load_cover` の縮小、`render()` の直接描画）が壊れていないかと、
   ローカルで `scratchpad` 相当の計測（64マス・3000px・16:9でピーク150MB未満）を再現する
3. **ログの中身**: `[error]` / `[share] failed` のprintにクエリ文字列やIPが混ざる変更が入っていないか `git log -p --since=<前回> -- backend/main.py` で見る。
   Dockerの起動コマンドに `--no-access-log` が残っているか `Dockerfile` を見る
4. **秘密の混入**: 2段で見る。**値は報告に出さない**（変数名と、漏れたか／入れ替えたかだけ書く）

   **(a) いまのリポジトリ（ここは必ず空であること）**
   ```bash
   sh scripts/scan_secrets.sh tree
   ```
   **判定はこのスクリプトにだけ置いてある**（`.githooks/pre-commit` と
   `.github/workflows/secrets.yml` が同じものを呼ぶ）。見るもの: `.env` とその控え・`*.pem`・
   SSHの秘密鍵といったファイル名と、発行元の分かる鍵の形・値の入った `SECRET=` の形。
   誤検知だったら、スクリプトの `allow` に足す。**値は出力しない**（行番号と変数名だけ）

   **(b) 履歴（既知の1件を除いて、新しいものが無いこと）**
   ```bash
   git log --all --oneline --diff-filter=A --name-only \
     -- '.env' '.env.*' '*.env' ':(exclude).env.example' ':(exclude)*/.env.example'
   ```
   **2026-09-14の `412582f` で入り2026-09-19の `3eec4d2` で消した `.env.bak-before-customdomain` は既知**
   （`docs/gotchas.md` に記録。R2のキーとDiscogsのトークンは失効・再発行済みで、古い鍵はUnauthorizedを確認済み）。
   **これ以外が出たら新しい漏洩**なので、**まずその鍵を失効させる**。
   **履歴を書き換えて消そうとしない**（force-pushはcloneを壊し、GitHubはGC前のblobを残す。
   鍵を失効させるほうが確実で早い）。`-S"R2_SECRET_ACCESS_KEY="` での検索は、この既知の1件のせいで
   **必ず4件返る**ので判定に使わない。`.env.example` を除かないと、雛形を作った回を毎回拾う。
   この検査は `.github/workflows/secrets.yml` がpushのたびに自動で回しているので、
   ここでは**そのrunが緑かどうか**を見れば足りる:
   ```bash
   gh run list --workflow secrets.yml --limit 3
   ```

   **(c) GitHub側の守り**
   ```bash
   gh api repos/tobokegao/trackmento-public -q '.security_and_analysis | to_entries[] | "\(.key): \(.value.status)"'
   gh api repos/tobokegao/trackmento-public/secret-scanning/alerts
   ```
   `secret_scanning` と `secret_scanning_push_protection` が `enabled`、アラートが空であること。
   - **`secret_scanning_non_provider_patterns` は `disabled` のままでよい**（2026-09-21に一次資料で確認）。
     汎用パターンの検知は「Organization-owned repositories on GitHub Team with GitHub Secret Protection enabled」
     だけが対象で、**個人アカウントのpublicリポジトリには購入経路が無い**（Organization＋Team $4/user/月 ＋
     Secret Protection $19/active committer/月）。**APIのPATCHが200を返しても反映されないのは仕様どおりで、
     設定ミスではない。直そうとしない**
   - その穴は `scripts/scan_secrets.sh`（コミット時のフックとpush時のCI）で自前に埋めてある。
     **publicをprivateにすると、無料のsecret scanningごと消える**ので、そのときは見直す
5. **利用条件の変化**: README「各サービスの利用条件」の日付が6か月以上前なら、iTunes / MusicBrainz / YouTube（oEmbedとData API）/ niconico / Spotify Web API / otoDB / VocaDB / Bandcamp / Apple Musicの規約ページを見直すよう提案する（変更の確認は利用者が原文を読む）
6. **外部の採点**: 利用者にhttps://securityheaders.comとhttps://observatory.mozilla.orgに `https://trackmento.com` を入れてもらい、A未満の項目があれば理由を調べる

## 3. 報告のしかた

- いちばん先に**利用者にしてほしいこと**（Renderのメールの有無・外部の採点・Dependabotのマージ判断など。無ければ「なし」）
- 次に結論（NGの数、直したもの、残ったもの）。続けてNGごとに「何が」「どこで」「どう直したか」を1〜2文
- **確かめられなかった項目**（利用者の手元にしか無いもの、外部サイトの結果）はOKと混ぜず、別に並べる
- 直したものはコミットしてpushし、Renderの再デプロイ後にスクリプトを再実行してOKを確認する
- 直さないと決めたものは理由を書く（例: 利用者の判断が要る、外部サービス側の仕様）
- 検査で作ったデータ（共有・アップロード・検査用グリッド）が残っていないか最後に述べる

## 4. やってはいけないこと

- 本番のR2バケットや `shares/` `uploads/` を検査データ以外まとめて消さない
- レートリミットや共有回数の上限を超える連打（1回の点検で共有は1件まで）
- 実在の第三者のサイトやIPに対する攻撃的なリクエスト（検査対象は自分のサーバーだけ。私設アドレス宛ての拒否確認はサーバー側で止まる）
