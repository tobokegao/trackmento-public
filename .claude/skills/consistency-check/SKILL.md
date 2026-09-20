---
name: consistency-check
description: TRACKMENTO の文書と画面の記述が、コードの実態とずれていないか点検して直す。README・CLAUDE.md・docs/・サイト内のページ（使い方・プライバシーポリシー・更新情報）・画面の固定文言・運用ボードを、自動スクリプトと手動確認で突き合わせる。コミットやプッシュの前に回す。
---

# 文書とコードの整合性チェック

**書いてあることが、今のコードの動きと合っているか**を見る点検。
機能を足したり外したりしたあと、コミット・プッシュの前に回す。

安全性の点検は別（`/site-safety-check`）。こちらは「嘘が残っていないか」だけを見る。

## 0. 前提

- Python は必ず `PYTHONUTF8=1 .venv/Scripts/python`（cp932 で落ちる）
- 直すのは**文書と文言だけ**。コードの動きを変えたくなったら、それは別の作業として切り出して相談する
- 「利用者に見える文章」（サイト内のページ・画面の固定文言）と「作業する人向けの文書」（README・CLAUDE.md・docs/）は
  **別のコミットに分ける**。前者は `fix:`、後者は `docs:`

## 1. 自動チェックを走らせる

```bash
PYTHONUTF8=1 .venv/Scripts/python scripts/check_consistency.py
```

見ているもの（詳しくはスクリプトの冒頭）:

| 項目 | 何を見るか | NG のとき |
| --- | --- | --- |
| 参照先の実在 | 文書の中の `backend/render.py` のようなパス | 参照先が消えたか、名前が変わった。文書側を直す |
| マスの上限（4 か所） | `index.html` / `grids.py` / `config.py` | **並びが黙って潰れる**。4 か所そろえる |
| 文書とコードの数字 | プレイリストの上限・JPEG の品質・画像の画素数 | コードが正。文書と画面を直す |
| サイト内ページの最終更新 | `pages.py` の `UPDATED` と `CHANGES` の先頭 | `UPDATED` を更新の日付に合わせる |
| 移転前の URL | `trackmento.onrender.com` | 本番は `trackmento.com`。移転の記録として書いた行は除外済み |
| 参照の無いスクリプト | `promo/` と `scripts/` | 使い捨てなら消す。残すなら文書から名指しする |

**スクリプトが OK でも、下の手動の点検はやる。** 機械で言えるのは数字とパスだけで、
「対応をやめたサービスが案内に残っている」類は拾えない。

## 2. 手動で突き合わせる（機械では拾えないもの）

まず**コードから実態を取る**。そのうえで、下の 4 か所を読んで食い違いを挙げる。

```bash
# 単体 URL の対応（resolve の分岐）と、プレイリストの対応（_FETCHERS と、例外を投げるもの）
sed -n '1,70p' backend/sources/fromurl.py
grep -n "raise ValueError\|_FETCHERS" backend/sources/playlist.py
# 検索元（トークンの有無で増減する）
grep -n "SOURCES\[" backend/main.py
```

見る場所:

1. **サイト内のページ** … `backend/pages.py` の `_guide` / `_privacy` / `_about`
   （対応サービスの一覧・外部へ送る先・保持日数。日本語と英語の両方）
2. **画面の固定文言** … `frontend/index.html` の URL 貼り付け欄の案内、ソース説明のモーダル、エラーメッセージ。
   **文書が「」で引用しているボタン名が、画面の表記と一致しているか**も見る
3. **README の「各サービスの利用条件」の表** … 取得方法・リスクの欄が、今の実装と `docs/services-terms.md` に合っているか。
   **`docs/services-terms.md` がいちばん新しい**ことが多いので、そこに寄せる
4. **運用ボード**（https://claude.ai/artifact/F3TPV7qzZJKN4kpwFT6KSA）… 外部サービスの表・待っていること

### よく残る食い違い

- **対応をやめたサービスの名前**が案内に残る（更新情報の履歴と、保存済みの並びに使うラベルは**残すのが正しい**）
- **同じことを 2 か所に書いた数字**の片方だけが古い（`CLAUDE.md` の「二重実装の一覧」が手がかり）
- **分割・改名で切れた参照**（「下の覚え書き」「このファイルの◯◯」のような、位置に頼った書き方）
- **当時の記録**と**今の仕様**の混同（`trackmento-spec.md`・`video-notes.md`・`docs/history.md` は記録。
  今の仕様は `CLAUDE.md` と `docs/`）

## 3. 直したあとに回すもの

- `frontend/index.html` の固定文字を変えた → `scripts/build_fonts.py` → 断片に差分が出たときだけ
  `scripts/upload_fonts_r2.py`（忘れると**本番でフォントが 404**）
- 同上 → `scripts/check_i18n.py`（日本語を 1 文字変えると英訳の鍵がずれる）
- 最後にもう一度 `scripts/check_consistency.py`

## 4. 報告のしかた

直した箇所を「どこが・何と食い違っていて・何に直したか」の形で並べる。
**判断が要るもの（方針と実態のどちらに寄せるか、消すかどうか）は勝手に決めず、一覧を見せて聞く。**
利用者に見える機能の変化があったときだけ、`backend/pages.py` の `CHANGES` に 1 行足す
（案内文の誤りを直しただけなら書かない）。
