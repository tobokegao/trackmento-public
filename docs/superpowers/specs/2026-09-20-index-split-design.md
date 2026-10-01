# index.htmlのCSSとJSをR2から配る（Renderの帯域を減らす）

2026-09-20

## 何を直すか

Renderの帯域が出費の最大項。Hobbyプランの込みは**月5 GBだけ**で、2026-09-20時点で
143.33 GB使い **$20.85**（$0.15/GB）。9月の請求見込み $40.94のうち、いちばん大きい。

| 項目 | 月額 |
| --- | --- |
| 帯域143.33 GB | $20.85 |
| サービス（Standardインスタンス） | $6.62 |
| Workspace | $4.71 |
| R2 Class A | $3.5 |
| R2ストレージ | $0.31 |

帯域の内訳はHTTP応答108.3 GB、サービス発35.03 GB。

フォント・共有画像・ジャケットはすでにR2（`img.trackmento.com`）へ逃がしてある。
残っている大物が **`frontend/index.html` 本体**で、br圧縮後 **130 KB**。
`Cache-Control: no-cache` だがETagが効いているので再訪は304（0バイト）。
**初回訪問とデプロイ直後だけ130 KBがまるごと出ていく。**

2026-09-17のピーク（共有45,390件/日）の規模だと、これだけで5.9 GB/日。
HTTP応答108.3 GBの主因はここと見ている。

### 中身の内訳（実測）

| 部分 | 生のバイト数 |
| --- | --- |
| `<script>`（インライン1個） | 306,857 |
| `<style>`（1個） | 87,214 |
| HTML本体 | 30,626 |
| 合計 | 424,697 |

**93% がCSSとJS**。この2つはどの訪問者にも同じもので、内容ハッシュを付ければ1年キャッシュに乗る。

## 何をするか

`frontend/index.html` を**編集するときの正**として1枚のまま残し、**配るときだけ3つに割る**。
「単一HTML」は書き方の方針であって配り方の方針ではない、という切り分けにする。
フォントで `build_fonts.py` がやっていることと同じ形。

```
frontend/index.html（1枚。ここを編集する）
      │  scripts/build_app.py
      ▼
frontend/dist/index.html        … 殻（30 KB。サーバーが差し込む値もここ）
frontend/dist/app.<hash>.css    … 87 KB
frontend/dist/app.<hash>.js     … 307 KB
      │  scripts/upload_app_r2.py
      ▼
R2  app/app.<hash>.css / app.<hash>.js  （1年immutable）
```

### 1. `scripts/build_app.py`（新規）

`frontend/index.html` から `<style>` と `<script>`（インラインの1個）を抜き、
内容のsha256の頭8桁を付けて `frontend/dist/` に書く。殻には `<link>` と `<script>` を差し込む。

`build_fonts.py` と同じ作法にする（生成物は `dist/` に集め、ハッシュ名、`--check` で件数だけ出す）。

### 2. サーバーが差し込む値の置き場所を変える

6つのうち2つがCSS / JSの中にあるので、殻へ移す。

| 印 | 今どこ | どうする |
| --- | --- | --- |
| `__BASE__` | HTML | そのまま |
| `__PUBLIC__` | HTML | そのまま |
| `__RETENTION__` | HTML | そのまま |
| `<!--__FONT_LINK__-->` | HTML | そのまま |
| `__MIGRATE__` | `<script>` | 殻の `<meta name="trackmento-migrate" content="__MIGRATE__">` にし、JSは `<meta>` から読む |
| `__LOGO_FONT__` | `<style>` | その `@font-face` だけ殻の小さな `<style>` に移す |

`__PUBLIC__` がすでに `<meta name="trackmento-public">` でやっている形をそのまま踏襲する。

### 3. `backend/main.py` の `/` を差し替える

`frontend/dist/index.html` があり、かつR2に該当のハッシュのファイルが**両方とも載っている**ときだけ
殻を配る。どちらか欠けていれば今までどおり `frontend/index.html` をそのまま配る。

起動時に1回だけR2を確認し（`head_object` 2回。Class Bなので実質無料）、結果を覚える。
`APP_FROM_R2=0` で止められるようにする（`FONTS_FROM_R2` と同じ）。

**この確認があることで、資産を上げ忘れたままデプロイしても白い画面にならない。**
フォントのときは上げ忘れると本番で404になる作りで、CLAUDE.mdに注意書きが要った。同じ轍を踏まない。

### 4. CSP

- `script-src 'nonce-…'` … **変更不要**。nonceは外部 `src` の `<script>` にも効く
- `style-src 'self' 'unsafe-inline'` … R2のオリジンを足す。`_r2_origin()` から組んでいるので
  `font-src` / `connect-src` と同じ流儀で1行

### 5. 変更したら回すものに1行足す

`CLAUDE.md` の表に「`frontend/index.html` を変えたら `build_app.py` → `upload_app_r2.py`」を足す。
フォントの行のすぐ下。3の取りこぼし確認があるので忘れても壊れないが、忘れれば効果が出ない。

## 直したあとの見込み

| | 今 | 後 |
| --- | --- | --- |
| 初回訪問でRenderから出る量 | 130 KB | **約8 KB** |
| 再訪（内容に変更なし） | 0 KB（304） | 0 KB（304） |
| デプロイ直後の再訪 | 130 KB | 8 KB（CSS / JSが変わっていなければR2からも取り直さない） |
| R2から出る量 | 0 | 約122 KB（転送量は無料。1年immutable） |

**初回訪問あたり94% 減**。ピーク時（45,390件/日の規模）なら5.9 GB/日 → 0.4 GB/日。
今のペース（`/` が4,656件/日）でも、初回が半分として0.3 GB/日 → 0.02 GB/日、月 $1.3ほど。
効き目は訪問者数に比例するので、**次にバズったときに最も効く**。

CSSとJSを別々のハッシュにしてあるので、片方だけ直した回は片方しか取り直されない。

## 壊れ方と歯止め

- **資産をR2に上げ忘れた**: 起動時の確認で気付き、殻を使わず元の1枚を配る。今までどおり動く。
- **R2が落ちている**: CSS / JSが読めず画面が出ない。フォント・ジャケット・共有画像がすでに
  R2依存なので、R2が落ちれば元から実質使えない。依存の度合いは変わるが、種類は増えない。
- **殻と資産のハッシュがずれる**: 殻は毎回 `dist/` から読み、そこに書かれたハッシュを使う。
  起動時の確認は殻が指すハッシュそのものを見るので、ずれていれば落ちる方（元の1枚）に倒れる。
- **`build_app.py` の抜き出しが壊れる**: `<style>` と `<script>` が1個ずつという前提に依存する。
  2個以上見つかったら失敗させる（黙って一部だけ外に出すほうが危ない）。
- **`build_fonts.py` / `check_i18n.py`**: どちらも `frontend/index.html`（正のほう）を読むので影響なし。

## 確認のしかた

1. `PYTHONUTF8=1 .venv/Scripts/python scripts/build_app.py` で `dist/` に3つできることを見る。
2. 手元で `PUBLIC_MODE=1` で起動し、R2に未アップの状態で `/` が**元の1枚**を返すことを見る
   （`curl -s https://…/ | wc -c` が42万台）。
3. `upload_app_r2.py` を回してから再起動し、`/` が3万台に減り、`app.<hash>.js` が
   `img.trackmento.com` から読まれることをPlaywrightで見る。コンソールにエラーが無いこと。
4. 画面を一通り触る（検索 → マスに入る → 共有）。`__MIGRATE__` と `__LOGO_FONT__` を移したので、
   **引っ越しの案内とロゴの字形**を重点的に見る。
5. `scripts/check_consistency.py` と `scripts/check_i18n.py` を回す。
6. 本番へ出したあと `scripts/render_check.py --hours 2` で帯域が下がることを見る。
