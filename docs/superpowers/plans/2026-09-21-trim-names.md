# 曲名・アーティスト名の蛇足を外す 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 曲名とアーティスト名から確実に蛇足だと言える部分だけを外し、曲が多い並びでジャケットが文字に埋もれないようにする。

**Architecture:** 純関数 `trim(title, artist) -> (title, artist)` を 1 本作り、表示するところ（画面・ブラウザ描画・サーバー描画・共有ページ・CLI）が全部それを通る。マスに入っているデータは元のまま。オプション `trimNames`（既定 true）で切れる。

**Tech Stack:** Python 3.14 / FastAPI / Pillow（サーバー）、単一 HTML の素の JS（ブラウザ）。テストフレームワークは使っていない。検証は `scripts/` の突き合わせスクリプト。

仕様: `docs/superpowers/specs/2026-09-21-trim-names-design.md`

## Global Constraints

- すべて `PYTHONUTF8=1 .venv/Scripts/python …` で実行する（付けないと cp932 で落ちる）
- **二重実装**: `backend/names.py` と `frontend/index.html` の `trimName()` は**同じ規則**。片方だけ直さない
- ブラウザで確かめるときは `PUBLIC_MODE=1` とポート 8000（`grids/default.json` を壊さないため／R2 の CORS がこのポートだけ）
- `frontend/index.html` を変えたら `scripts/build_app.py` → `scripts/upload_app_r2.py`、殻（`frontend/dist/index.html`）もコミット
- 固定文字を足したら `scripts/build_fonts.py` → `scripts/upload_fonts_r2.py` と `scripts/check_i18n.py`
- 利用者に見える変化なので `backend/pages.py` の `CHANGES` に 1 行（同じコミットで）
- 文言は**やわらかい日本語**。「エクスポート」ではなく「並びを保存」の調子
- 正規化は `backend/merge.py` の `_n()` と frontend の `nkey()` と同じ規則

---

### Task 1: `backend/names.py`（刈り込みの規則）と検証スクリプト

**Files:**
- Create: `backend/names.py`
- Create: `scripts/check_trim.py`

**Interfaces:**
- Produces: `names.trim(title: str, artist: str) -> tuple[str, str]`、`names.trim_track(t) -> tuple[str, str]`（`.title` / `.artist` を持つものを受ける）

- [ ] **Step 1: `backend/names.py` を書く**

```python
"""曲名とアーティスト名から、確実に蛇足だと言える部分だけを外す。

**frontend/index.html の `trimName()` と対で直すこと**。片方だけ直すと、画面と書き出しで
曲名が違うものになる（`scripts/compare_trim.py` で突き合わせられる）。

規則は docs/superpowers/specs/2026-09-21-trim-names-design.md を参照。外すのは
「媒体の表記」「チャンネル名の尾」「分類のタグ」「アーティスト名の重複」だけで、
サークル名・原曲名・歌唱者は残す（消すと情報が落ちる）。
"""
from __future__ import annotations

import re

from backend.merge import _n

# 括弧は同じ種類どうしで対にする（「【初音ミク(とく)】」を「【初音ミク(とく」と読まない）
BRACKETS = (("【", "】"), ("［", "］"), ("[", "]"), ("〔", "〕"), ("《", "》"))

# R1 媒体・字幕の表記。括弧の中身がこれ「だけ」なら括弧ごと外す
MEDIA = (
    r"(?:Full\s*|Short\s*|Long\s*)?(?:M/?V|P/?V|Music\s*Video|Lyric\s*Video|Official\s*(?:Music\s*)?Video"
    r"|Official\s*Audio|Visualizer|Audio|Teaser|Trailer|Live\s*Video)"
    r"|(?:ENG\s*)?Sub(?:s|bed|title[ds]?)?|字幕(?:付き?)?|歌詞(?:付き?)?"
    r"|Full\s*ver\.?|Short\s*ver\.?|(?:公式|Official)\s*(?:MV|PV|Video)"
)
MEDIA_ONLY = re.compile(rf"^\s*(?:{MEDIA})\s*$", re.I)
MEDIA_TAIL = re.compile(rf"[\s　]*[/／|・-]?[\s　]*(?:{MEDIA})[\s　]*$", re.I)

# R3 分類・区分の語。括弧の中身にこれが含まれるなら括弧ごと外す。
# **「東方」単独は入れない**（【東方紅魔郷・東方花映塚】のような原作名まで消える）
GENRE = re.compile(
    r"Vocal|ボーカル|ヴォーカル|アレンジ|arrange|ニコカラ|カラオケ|歌ってみた|演奏してみた|踊ってみた"
    r"|公式|Official|M/?V|P/?V|Music\s*Video|Lyric\s*Video|Sub(?:s|bed)?|字幕|歌詞付|Full\s*ver"
    r"|初音ミク|MMD|音MAD|実況", re.I)

# R2 アーティスト名の末尾に付く、YouTube が作るチャンネル名の尾
CHANNEL_TAIL = re.compile(
    r"\s*(?:[-–—]\s*Topic|Official\s*(?:YouTube\s*)?Channel|公式\s*(?:YouTube\s*)?チャンネル"
    r"|(?<!\w)VEVO|Channel|チャンネル)\s*$", re.I)

# A2 宣伝の文句。アーティスト名の要素にこれが入っていたら、その要素は名前ではない
PROMO = re.compile(
    r"発売中|販売中|配信中|通販|予約|受付中|好評|新譜|NEW\s*(?:ALBUM|SINGLE|SONG)|最新|"
    r"公開中|投稿中|更新中|チャンネル登録|Subscribe|公式(?:サイト|ストア|通販)|Store|"
    r"毎週|毎月|毎日|活動中|始めました", re.I)

SEP = r"[/／,、，|｜]|\s+[-–—]\s+"          # アーティスト名の区切り
SEP_REPEAT = r"[_/／|｜・･]|\s+[-–—]\s+"    # A1 で使う区切り（`_` を含む）
STRIP = " 　/／|-–—,、"                     # 刈ったあとに端から落とす文字

# G3 題の後半から落とす、作品への言及
WORK_TAIL = re.compile(r"(?:テーマ曲?|主題歌|挿入歌|OP|ED|イメージソング|より|収録)\s*$")
WORK_BRACKET = re.compile(r"[『「【\[（(][^』」】\])）]*[』」】\])）]")


def _usable(s: str) -> bool:
    """刈った結果として使えるか（空・短すぎは不可）"""
    return len(_n(s)) >= 2


def _spans(s: str) -> list[tuple[int, int, str]]:
    """括弧の (開始, 終了, 中身) を左から。対応しない括弧は無視する"""
    out: list[tuple[int, int, str]] = []
    i = 0
    while i < len(s):
        for op, cl in BRACKETS:
            if s.startswith(op, i):
                j = s.find(cl, i + len(op))
                if j >= 0:
                    out.append((i, j + len(cl), s[i + len(op):j]))
                    i = j + len(cl)
                    break
        else:
            i += 1
            continue
    return out


def _graft(title: str, artist: str) -> str | None:
    """G: 題からアーティスト名を移植してよいか。よければ移植先の名前、だめなら None。

    **判定は刈る前の元の名前で行う**（先に「公式チャンネル」を刈ると G1 が立たなくなる）。
    """
    items = [p.strip() for p in re.split(SEP, artist) if p.strip()]
    if not any(PROMO.search(p) for p in items):
        return None                                    # G1 宣伝の文句が無い
    nt = _n(title)
    if any(_n(p) and _n(p) in nt for p in items):
        return None                                    # G2 題に出てくる＝名前として妥当
    bits = re.split(r"[/／]", title)
    if len(bits) != 2:
        return None                                    # G3 「/」がちょうど 1 つでない
    cand = WORK_BRACKET.sub("", bits[1])
    cand = WORK_TAIL.sub("", cand).strip(STRIP)
    cand = trim(cand, "")[0]
    if not _usable(cand) or _n(cand) == _n(artist):
        return None
    return cand


def _tidy_artist(a: str) -> str:
    """A1 同じ名前の繰り返しを 1 つに、A2 宣伝の文句を含む要素を落とす"""
    parts = [p for p in re.split(SEP_REPEAT, a) if p.strip()]
    if len(parts) >= 2 and len({_n(p) for p in parts}) == 1 and _usable(parts[0]):
        a = parts[0].strip()                           # A1 `ytr_ytr` → `ytr`
    items = [p.strip() for p in re.split(SEP, a) if p.strip()]
    if len(items) >= 2:
        keep = [p for p in items if not PROMO.search(p)]
        if keep and len(keep) < len(items):
            a = " / ".join(keep)                       # A2
    return a


def trim(title: str, artist: str) -> tuple[str, str]:
    """曲名とアーティスト名から蛇足を外す。**データは変えず、表示のときだけ通す**"""
    t, a = (title or "").strip(), (artist or "").strip()

    grafted = _graft(t, a)                             # G 題からの移植
    if grafted:
        a = grafted
    a = _tidy_artist(a)

    for _ in range(3):                                 # R2 チャンネル名の尾（重なることがある）
        n = CHANNEL_TAIL.sub("", a).strip(STRIP)
        if n == a or not _usable(n):
            break
        a = n

    names = {_n(p) for p in re.split(SEP, a) if _usable(p)}   # R4 で突き合わせる作者名

    kept, cut = "", 0                                  # R1/R3/R4 括弧のかたまり
    for st, en, inner in _spans(t):
        drop = MEDIA_ONLY.match(inner) or _n(inner) in names or GENRE.search(inner)
        if drop:
            kept += t[cut:st]
            cut = en
    nt = re.sub(r"\s{2,}", " ", (kept + t[cut:]).strip()).strip(STRIP)
    if _usable(nt):
        t = nt

    for _ in range(2):                                 # R1 括弧に入っていない末尾の媒体語
        n = MEDIA_TAIL.sub("", t).strip(STRIP)
        if n == t or not _usable(n):
            break
        t = n

    for _ in range(2):                                 # R4 末尾の「/ 作者名」「- 作者名」
        m = None
        for mm in re.finditer(r"[\s　]*(?:[/／|｜]|(?<=[\s　])[-–—](?=[\s　]))[\s　]*", t):
            m = mm
        if not m:
            break
        tail = t[m.end():].strip()
        if _n(tail) not in names and _n(tail) != _n(a):
            break
        n = t[:m.start()].strip(STRIP)
        if not _usable(n):
            break
        t = n
    return t, a
```

- [ ] **Step 2: `scripts/check_trim.py` を書く**（期待値の表で確かめる）

```python
"""backend/names.py の刈り込みを、既知の入力と期待値で確かめる。

規則を直したらこれを回す。**期待値は実際の共有から取った本物の題**なので、
落ちたときは「規則が変わってよいのか」を必ず考えること（黙って期待値を書き換えない）。

    PYTHONUTF8=1 .venv/Scripts/python scripts/check_trim.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.names import trim   # noqa: E402

# (題, 作者, 期待する題, 期待する作者)
CASES = [
    # R3 分類のタグ
    ("【東方Vocal／Traditional Rock】「心綺楼」「凋叶棕」【ENG Subs】", "Kappashiro",
     "「心綺楼」「凋叶棕」", "Kappashiro"),
    # R2 チャンネル名の尾
    ("リバースイデオロギー", "KISIDA KYODAN & THE AKEBOSI ROCKETS - Topic",
     "リバースイデオロギー", "KISIDA KYODAN & THE AKEBOSI ROCKETS"),
    ("psychology / Adust Rain【ハルトマンの妖怪少女】", "Adust Rain Official YouTube Channel",
     "psychology【ハルトマンの妖怪少女】", "Adust Rain"),
    # R4 括弧の中身が作者名
    ("【東方MV】ラクト・ガール【ビートまりお】", "ビートまりお / COOL&CREATE",
     "ラクト・ガール", "ビートまりお / COOL&CREATE"),
    # A1 名前の繰り返し
    ("【東方】物凄いヴァイブスで魔理沙が物凄いラップ【ｙｔｒ】", "ytr_ytr",
     "【東方】物凄いヴァイブスで魔理沙が物凄いラップ【ｙｔｒ】", "ytr"),
    # G 題からの移植
    ("「幻想に咲いた花」MV FULL ver./岸田教団&THE明星ロケッツ×草野華余子『東方ダンマクカグラ』テーマ曲",
     "アンノウンX公式チャンネル / 東方ダンマクカグラ発売中",
     "「幻想に咲いた花」MV FULL ver.", "岸田教団&THE明星ロケッツ×草野華余子"),
    # 残すもの（サークル名・原曲名・歌唱者・原作名）
    ("流星ドライヴ 【魂音泉】", "ディレイド", "流星ドライヴ 【魂音泉】", "ディレイド"),
    ("AbsoЯute Zero / いざ宵裂く矢となれ【東方紅魔郷・東方花映塚】", "AbsoЯute Zero Channel",
     "いざ宵裂く矢となれ【東方紅魔郷・東方花映塚】", "AbsoЯute Zero"),
    ("【東方ヴォーカルMV】インスタントブルー（Vo:あよ）【森羅万象公式】", "森羅万象/Shinra-Bansho",
     "インスタントブルー（Vo:あよ）", "森羅万象/Shinra-Bansho"),
    # 名前を壊さない（要素が違えば A1 は効かない）
    ("Rock 'n' Rock 'n' Beat", "qfeuille3_v2 🥐⚓", "Rock 'n' Rock 'n' Beat", "qfeuille3_v2 🥐⚓"),
    # 空・短すぎは刈らない
    ("【MV】", "", "【MV】", ""),
]


def main() -> int:
    bad = 0
    for title, artist, want_t, want_a in CASES:
        got_t, got_a = trim(title, artist)
        if (got_t, got_a) != (want_t, want_a):
            bad += 1
            print(f"[違う] {title} / {artist}")
            print(f"   期待: {want_t!r} / {want_a!r}")
            print(f"   実際: {got_t!r} / {got_a!r}")
    print(f"{len(CASES) - bad} / {len(CASES)} 件そろいました")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: 回して落ちることを確かめる**

まだ `names.py` の中身が期待どおりとは限らない。回して差分を見る。

Run: `PYTHONUTF8=1 .venv/Scripts/python scripts/check_trim.py`
Expected: `11 / 11 件そろいました`（違う行が出たら、規則と期待値のどちらが正しいか考えて直す）

- [ ] **Step 4: 実際の共有 100 曲で効果を測る**

```bash
PYTHONUTF8=1 .venv/Scripts/python -c "
import httpx, json
from backend.names import trim
d = httpx.get('https://img.trackmento.com/843a31ecb431.json', timeout=20).json()
cs = [c for c in d['cells'] if c]
n0 = sum(len((c.get('title') or '') + (c.get('artist') or '')) for c in cs)
n1 = sum(len(''.join(trim(c.get('title') or '', c.get('artist') or ''))) for c in cs)
print('%d 曲  %d 字 → %d 字 (%.0f%%)' % (len(cs), n0, n1, n1 / n0 * 100))
"
```

Expected: `100 曲  5421 字 → 3859 字 (71%)`（±1% なら可。大きく違えば規則がずれている）

- [ ] **Step 5: コミット**

```bash
git add backend/names.py scripts/check_trim.py
git commit -m "feat(names): 曲名とアーティスト名から蛇足を外す規則を足す"
```

---

### Task 2: サーバー描画に通す（`grids.py` の `trimNames` と `render.py`）

**Files:**
- Modify: `backend/grids.py`（`GridOptions`）
- Modify: `backend/render.py`（`layout()` の入口）

**Interfaces:**
- Consumes: `names.trim(title, artist)`
- Produces: `GridOptions.trimNames: bool = True`、`render._trimmed(doc) -> GridDoc`（刈った題を入れた写し）

- [ ] **Step 1: `GridOptions` に `trimNames` を足す**

`backend/grids.py` の `GridOptions` に、ほかの真偽値オプション（`showTitle` など）と同じ並びで足す。

```python
    trimNames: bool = True       # 曲名・アーティスト名から蛇足を外して表示する（backend/names.py）
```

- [ ] **Step 2: `render.py` で割り付けの前に刈る**

`layout()` の先頭で、刈った題を入れた写しを作る。**割り付けを決める前に刈らないと枠が縮まない**。

```python
def _trimmed(doc: GridDoc) -> GridDoc:
    """曲名・アーティスト名から蛇足を外した写しを返す（`trimNames` が偽ならそのまま）。
    **割り付けを決める前に通すこと**。刈ったあとの文字で行数と字の大きさを決めないと枠が縮まない"""
    if not doc.options.trimNames:
        return doc
    out = doc.model_copy(deep=True)
    for cell in out.cells:
        if cell is not None:
            cell.title, cell.artist = names.trim(cell.title or "", cell.artist or "")
    return out
```

`layout()` と `render()` の先頭で `doc = _trimmed(doc)` を呼ぶ。`import` に `from backend import names` を足す。

- [ ] **Step 3: 刈り前・刈り後で塊の大きさが変わることを確かめる**

```bash
PYTHONUTF8=1 MAX_SIDE=2000 .venv/Scripts/python -c "
import httpx, json
from backend.grids import GridDoc
from backend import render as R
raw = httpx.get('https://img.trackmento.com/843a31ecb431.json', timeout=20).json()
for trim in (False, True):
    d = json.loads(json.dumps(raw)); d['options']['trimNames'] = trim
    L = R.layout(GridDoc.model_validate(d))
    print('%s 1 マス %.0fpx 塊 %.1f%%' % ('刈り後' if trim else '刈り前',
          L.gw / d['cols'] * L.scale, L.gw * L.gh / (L.W * L.H) * 100))
"
```

Expected:
```
刈り前 1 マス 64px 塊 18.5%
刈り後 1 マス 88px 塊 34.3%
```

- [ ] **Step 4: コミット**

```bash
git add backend/grids.py backend/render.py
git commit -m "feat(render): 割り付けの前に曲名の蛇足を外す"
```

---

### Task 3: ブラウザ側の `trimName()` と画面表示

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Produces: JS の `trimName(title, artist) -> [title, artist]`

- [ ] **Step 1: `trimName()` を書く**

`nkey()` の近くに置く。`backend/names.py` と**同じ規則**を JS で書く。
正規表現は Python 版をそのまま写し、`re.I` → `i` フラグ、`(?<=…)` `(?<!…)` は Chromium が対応しているのでそのまま使う。

冒頭に必ずこのコメントを入れる:

```js
/* 曲名とアーティスト名から蛇足を外す。**backend/names.py と対で直すこと**。
   片方だけ直すと画面と書き出しで曲名が変わる（scripts/compare_trim.py で突き合わせられる）。
   規則は docs/superpowers/specs/2026-09-21-trim-names-design.md */
```

- [ ] **Step 2: 表示するところを通す**

マスの帯・拡大表示・曲名リストのプレビュー・`renderShareCanvas` の曲名。
**データ（`state.cells`）は書き換えない**。表示の直前だけ通す。
`opt.trimNames`（既定 true）が偽なら素通し。

- [ ] **Step 3: 書き出し設定に「曲名の蛇足を外す」を足す**

ほかのチェック（「番号を出す」など）と同じ作りで 1 つ。ラベルは
**「曲名の蛇足を外す」**、説明は **「【東方Vocal】や「- Topic」のような、曲名でない部分を外します」**。

- [ ] **Step 4: ブラウザで見る**

```bash
PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

http://localhost:8000/ を開き、`/?share=843a31ecb431` でその並びを読み込む。
チェックの入り切りでマスの帯と曲名リストの文字が変わることを見る。

- [ ] **Step 5: 配る形を作ってコミット**

```bash
PYTHONUTF8=1 .venv/Scripts/python scripts/build_app.py
PYTHONUTF8=1 .venv/Scripts/python scripts/build_fonts.py
PYTHONUTF8=1 .venv/Scripts/python scripts/check_i18n.py
git add frontend/index.html frontend/dist/index.html fonts/
git commit -m "feat(ui): 曲名の蛇足を外す設定を足す"
```

`check_i18n.py` が「英語が無い」と言ったら `EN` 表に足してから commit する。

---

### Task 4: Python と JS の一致を見る `scripts/compare_trim.py`

**Files:**
- Create: `scripts/compare_trim.py`

**Interfaces:**
- Consumes: `names.trim`、frontend の `trimName`

- [ ] **Step 1: 書く**

`scripts/compare_layout.py` が Chromium を動かしている作りに合わせる（同じ起動の仕方を写す）。
みんなの並びから題を集め、Python と JS の出力が**全件一致する**ことを見る。1 件でも違えば失敗。

```
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_trim.py
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_trim.py --n 200   # 集める題の数
```

出力は `200 / 200 件一致` か、違った行の `題 / 作者 → Python の結果 ≠ JS の結果`。

- [ ] **Step 2: 回す**

Run: `PYTHONUTF8=1 .venv/Scripts/python scripts/compare_trim.py`
Expected: `200 / 200 件一致`

違いが出たら、たいてい正規表現の書き写しか、`_n()` と `nkey()` の食い違い
（`ß` の畳み方・単独の濁点）。**JS 側を Python に合わせる**。

- [ ] **Step 3: コミット**

```bash
git add scripts/compare_trim.py
git commit -m "test(trim): Python と JS の刈り込みを突き合わせる"
```

---

### Task 5: 共有ページ・OG 画像・CLI

**Files:**
- Modify: `backend/share.py`
- Modify: `backend/pages.py`（共有ページの曲リスト）
- Modify: `cli.py`

- [ ] **Step 1: 共有ページの曲リストを通す**

共有ページ（`/s/<id>`）の曲リストと OG 画像が使う題に `names.trim` を通す。
**共有 JSON に入っている `options.trimNames` に従う**（共有したときの見た目を再現するため）。

- [ ] **Step 2: CLI に `--trim` / `--no-trim`**

`render` と `share` に足す。既定は `trimNames`（真）。ほかのオプションと同じくグリッド JSON に保存する。
`cli.py list` の表示も通す。

- [ ] **Step 3: 確かめる**

```bash
PYTHONUTF8=1 .venv/Scripts/python cli.py list --grid <適当な並び>
PYTHONUTF8=1 .venv/Scripts/python cli.py render --grid <適当な並び> --no-trim
```

- [ ] **Step 4: コミット**

```bash
git add backend/share.py backend/pages.py cli.py
git commit -m "feat(share): 共有ページと CLI にも刈り込みを通す"
```

---

### Task 6: 「すべての曲名を短くする」（データに焼く）

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: ボタンを置く**

並べ替えの下。ラベルは **「すべての曲名を短くする」**。

- [ ] **Step 2: 押したときの確認**

刈って変わるマスを数え、
**「84 マスの曲名・52 マスのアーティスト名を短くします。よろしいですか？」**
と出す（数は実際の件数）。`confirm()` は使わず、既存のダイアログの作りに合わせる。
変わるマスが 0 件なら **「短くできる曲名はありませんでした」** と出して終わる。

- [ ] **Step 3: 書き戻し**

`state.cells` の `title` / `artist` を刈った結果で置き換え、既存の取り消しの仕組みに 1 回ぶん積む。
書き戻したあとはサーバーにも保存する（ほかの編集と同じ経路）。

- [ ] **Step 4: ブラウザで確かめる**

`PUBLIC_MODE=1` で立てて `/?share=843a31ecb431` を読み、押して件数が出ること・
編集パネルの曲名が短い形になっていること・取り消せることを見る。

- [ ] **Step 5: 配る形を作ってコミット**

```bash
PYTHONUTF8=1 .venv/Scripts/python scripts/build_app.py
PYTHONUTF8=1 .venv/Scripts/python scripts/build_fonts.py
PYTHONUTF8=1 .venv/Scripts/python scripts/check_i18n.py
git add frontend/index.html frontend/dist/index.html fonts/
git commit -m "feat(ui): すべての曲名を短くするボタンを足す"
```

---

### Task 7: 突き合わせ・文書・更新情報

**Files:**
- Modify: `scripts/compare_render.py`（刈り込みを入れた組を 1 つ）
- Modify: `docs/layout.md`、`docs/ui.md`、`CLAUDE.md`
- Modify: `backend/pages.py`（`CHANGES`）

- [ ] **Step 1: サーバー描画とブラウザ描画を突き合わせる**

100 曲の並びで、刈り込みを入れた状態のサーバー描画とブラウザ描画を比べる。

```bash
PUBLIC_MODE=1 SHARE_BUDGET_GB=0 SHARE_LIMIT_PER_DAY=0 SHARE_LIMIT_PER_IP_DAY=0 \
  PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py make 10 10 16:9 fill
# 出た URL をブラウザで開いて「トラックを共有」
PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py diff <サーバーのID> <ブラウザのID>
PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py clean <ID> <ID>
```

Expected: **6px のぼかしで 0.3% 未満**（`compare_render.py` の見方のとおり）

- [ ] **Step 2: 文書を直す**

- `docs/layout.md`: 「刈り込みは割り付けの前に通す」と、その理由（あとで刈っても枠が縮まない）
- `docs/ui.md`: 「曲名の蛇足を外す」の場所と、「すべての曲名を短くする」の動き
- `CLAUDE.md` の「二重実装の一覧」に `backend/names.py` ↔ frontend の `trimName()` を 1 行
- `CLAUDE.md` の「変更したら回すもの」に `scripts/check_trim.py` と `scripts/compare_trim.py` を 1 行

- [ ] **Step 3: 更新情報に 1 行**

`backend/pages.py` の `CHANGES` の先頭に、日本語と英語で。手順はスキル `/updates`。

```
2026-09-21 曲名から「【東方Vocal】」「- Topic」のような、曲名でない部分を外すようにしました。
           曲が多い並びでジャケットが大きく出ます（書き出し設定で切れます）。
```

- [ ] **Step 4: 文書の点検**

Run: `PYTHONUTF8=1 .venv/Scripts/python scripts/check_consistency.py`
Expected: 新しい指摘が出ないこと（出たら直す）

- [ ] **Step 5: R2 へ配ってコミット**

```bash
PYTHONUTF8=1 .venv/Scripts/python scripts/upload_app_r2.py
PYTHONUTF8=1 .venv/Scripts/python scripts/upload_fonts_r2.py
git add scripts/compare_render.py docs/ CLAUDE.md backend/pages.py
git commit -m "docs(trim): 刈り込みの決まりと更新情報を書く"
git push
```
