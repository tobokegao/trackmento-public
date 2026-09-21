# マスの形を 16:9 にもできるようにする 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 並び全体でマスの形を「正方形」か「横長 16:9」から選べるようにし、動画サイトのサムネイルを切らずに並べられるようにする。

**Architecture:** `CELL_PX = 600`（正方形）を `CELL_W = 600` 固定 ＋ `cell_h`（600 か 338）に分ける。**幅を変えない**ので、幅基準の式はそのまま効く。16:9 のマスに正方形の絵が来たら、ぼかした引き伸ばしで左右を埋める。

**Tech Stack:** Python 3.14 / Pillow（サーバー）、単一 HTML の素の JS ＋ Canvas（ブラウザ）。

仕様: `docs/superpowers/specs/2026-09-21-cell-ratio-design.md`

## Global Constraints

- すべて `PYTHONUTF8=1 .venv/Scripts/python …` で実行する
- **二重実装**: `backend/render.py` と `frontend/index.html` の `renderShareCanvas` は同じ式。片方だけ直さない
- **画面側を直したら `scripts/build_app.py` → `scripts/upload_app_r2.py` → サーバーを立て直してから突き合わせる**
  （`docs/gotchas.md`。怠ると古い JS で比べて食い違いが出る）
- ブラウザで確かめるときは `PUBLIC_MODE=1` とポート 8000
- 突き合わせのサーバーは `PUBLIC_MODE=1 SHARE_BUDGET_GB=0 SHARE_LIMIT_PER_DAY=0 SHARE_LIMIT_PER_IP_DAY=0`
- 16:9 は **600 × 338**（600 × 337.5 の小数を避ける丸め。実比 16:9.01、誤差 0.15%）
- 既定は `"1:1"`。**今ある並びと共有画像の見た目を変えない**

## 寸法の基準（どの式がどちらを見るか）

| 場所 | 今 | これから | なぜ |
| --- | --- | --- | --- |
| `gw`（塊の幅） | `cols * CELL_PX + …` | `cols * CELL_W + …` | 幅 |
| `gh`（塊の高さ） | `rows * CELL_PX + …` | `rows * cell_h + …` | 高さ |
| `_mod_pad` の `step` | `(CELL_PX + gap) / MOD_PAD_DIV` | `(CELL_W + gap) / MOD_PAD_DIV` | 幅（余白は幅に合わせる） |
| `pitch`（曲名リストの段） | `CELL_PX + gap` | `cell_h + gap` | 高さ |
| `_snap_lead` の送り | `CELL_PX + gap` | `cell_h + gap` | 高さ |
| `overlay_ok` の字 | `CELL_PX * OVERLAY_TITLE` | `min(CELL_W, cell_h) * …` | **短辺**。16:9 で帯が潰れる |
| `WRAP_CELL_OK` の下限 | `CELL_PX * scale` | `min(CELL_W, cell_h) * scale` | **短辺** |
| 描くときのマス | `cell = sc(CELL_PX)` | `cw = sc(CELL_W)`, `ch = sc(cell_h)` | 両方 |

---

### Task 1: サーバー側の寸法を分ける

**Files:**
- Modify: `backend/grids.py`（`GridOptions`）
- Modify: `backend/render.py`

**Interfaces:**
- Produces: `render.CELL_W: int`、`render.cell_h(doc) -> int`、`GridOptions.cellRatio: str`

- [ ] **Step 1: `GridOptions` に `cellRatio` を足す**

```python
    # マスの形。"1:1"（正方形）か "16:9"（横長。動画サイトのサムネイルに合う）。
    # **既定は正方形**（今ある並びの見た目を変えないため）
    cellRatio: str = "1:1"

    @field_validator("cellRatio")
    @classmethod
    def _cell_ratio(cls, v: str) -> str:
        return v if v in ("1:1", "16:9") else "1:1"
```

- [ ] **Step 2: `render.py` に `CELL_W` と `cell_h()` を入れる**

```python
CELL_W = 600                       # マスの幅（論理 px）。**形を変えても幅は変えない**
CELL_H_BY_RATIO = {"1:1": 600, "16:9": 338}   # 600×337.5 の小数を避けるための丸め（実比 16:9.01）
CELL_PX = CELL_W                   # 旧名（幅基準の式が読む）


def cell_h(doc: GridDoc) -> int:
    """マスの高さ（論理 px）。`cellRatio` から決まる"""
    return CELL_H_BY_RATIO.get(doc.options.cellRatio, CELL_W)
```

- [ ] **Step 3: 上の表のとおりに式を差し替える**

`layout()` と `render()`、`_slab_rows`、`_wrap_plan` の中。`doc` が手元にない関数には
高さを引数で渡す（`_snap_lead` の呼び出し側で計算する）。

- [ ] **Step 4: 正方形のときに何も変わらないことを確かめる**

```bash
PYTHONUTF8=1 .venv/Scripts/python scripts/compare_layout.py 200
```

Expected: `食い違い 0 / 200`（ブラウザ側はまだ直していないが、既定が `1:1` なので値は今までどおり）

- [ ] **Step 5: 16:9 で塊が横長になることを確かめる**

```bash
MAX_SIDE=2000 PYTHONUTF8=1 .venv/Scripts/python -c "
import sys; sys.path.insert(0,'.')
import httpx, json
from backend.grids import GridDoc
from backend import render as R
raw = httpx.get('https://img.trackmento.com/843a31ecb431.json', timeout=30).json()
for q in ('1:1', '16:9'):
    d = json.loads(json.dumps(raw)); d['options']['cellRatio'] = q
    L = R.layout(GridDoc.model_validate(d))
    print('%-5s 塊 %dx%d  出力 %dx%d' % (q, L.gw*L.scale, L.gh*L.scale, L.W*L.scale, L.H*L.scale))
"
```

Expected: `1:1` は塊が正方形、`16:9` は塊の高さが約 56% になる

- [ ] **Step 6: コミット**

```bash
git add backend/grids.py backend/render.py
git commit -m "feat(render): マスの幅と高さを分け、cellRatio で 16:9 を選べるようにする"
```

---

### Task 2: ぼかし埋め（サーバー）

**Files:**
- Modify: `backend/render.py`（`_cover_fit` の周り）

**Interfaces:**
- Produces: `render._cover_blur_pad(img, w, h) -> Image.Image`

- [ ] **Step 1: 書く**

```python
BLUR_RADIUS = 0.06        # 下地のぼかし半径（マスの高さに対する比。論理 px で決めて scale を掛ける）


def _cover_blur_pad(img: Image.Image, w: int, h: int) -> Image.Image:
    """**絵を切らずに**マスいっぱいに収める。余る側は、同じ絵を cover で広げてぼかした下地で埋める
    （YouTube の再生画面と同じやり方）。**frontend の coverBlurPad と対で直すこと**。

    16:9 のマスに正方形のジャケットが来たときに使う。中央で切ると、アルバムアートは
    中央に絵があるので損なう。
    """
    base = _cover_fit(img, w, h).filter(ImageFilter.GaussianBlur(max(1.0, h * BLUR_RADIUS)))
    f = min(w / img.width, h / img.height)          # contain
    fw, fh = max(1, round(img.width * f)), max(1, round(img.height * f))
    base.paste(img.resize((fw, fh), Image.LANCZOS), ((w - fw) // 2, (h - fh) // 2))
    return base
```

`from PIL import Image, ImageDraw, ImageFont` に `ImageFilter` を足す。

- [ ] **Step 2: `load_cover` を幅と高さで受けるようにする**

```python
def load_cover(t: Track, w: int = CELL_W, h: int | None = None) -> Image.Image | None:
```

`_load_cover_from` の中で、**絵の比とマスの比が違い、かつマスが正方形でないとき**だけ
`_cover_blur_pad` を使う。正方形のマスは今までどおり `_cover_fit`（中央で切る）。

```python
    ar_img, ar_cell = im.width / im.height, w / h
    fitted = (_cover_blur_pad(im, w, h) if w != h and abs(ar_img - ar_cell) > 0.01
              else _cover_fit(im, w, h))
```

- [ ] **Step 3: 絵で確かめる**

```bash
PYTHONUTF8=1 .venv/Scripts/python -c "
import sys; sys.path.insert(0,'.')
from PIL import Image
from backend.render import _cover_blur_pad, _cover_fit
im = Image.open('frontend/no-cover.png').convert('RGB')
_cover_blur_pad(im, 640, 360).save('outputs/_blur_test.png')
print('outputs/_blur_test.png を見る（左右がぼけた同じ絵で埋まっていること）')
"
```

- [ ] **Step 4: コミット**

```bash
git add backend/render.py
git commit -m "feat(render): 16:9 のマスに正方形の絵が来たらぼかして埋める"
```

---

### Task 3: ブラウザ側（寸法・ぼかし埋め・CSS・設定）

**Files:**
- Modify: `frontend/index.html`

- [ ] **Step 1: `CELL_PX` を `CELL_W` と `cellH()` に分ける**

```js
  const CELL_W = 600, CELL_H_BY_RATIO = { "1:1": 600, "16:9": 338 }, GAP_PX = 12, MAX_SIDE = 8000;
  const CELL_PX = CELL_W;   // 旧名（幅基準の式が読む）
  const cellH = () => CELL_H_BY_RATIO[state.cellRatio] || CELL_W;
```

サーバー側の表と**同じ基準**で 23 箇所を振り分ける。

- [ ] **Step 2: Canvas のぼかし埋め**

```js
  /* **backend/render.py の _cover_blur_pad と対で直すこと**。ぼかし半径は論理 px で決めて
     scale を掛ける（絶対 px で書くと出力サイズごとにぼけ方が変わり、サーバー描画とずれる） */
  function coverBlurPad(ctx, img, x, y, w, h) {
    ctx.save();
    ctx.beginPath(); ctx.rect(x, y, w, h); ctx.clip();
    ctx.filter = `blur(${Math.max(1, h * BLUR_RADIUS)}px)`;
    drawCover(ctx, img, x, y, w, h);          // cover でマスいっぱい（既存の切り抜きと同じ）
    ctx.filter = "none";
    const f = Math.min(w / img.width, h / img.height);
    const fw = Math.round(img.width * f), fh = Math.round(img.height * f);
    ctx.drawImage(img, x + Math.round((w - fw) / 2), y + Math.round((h - fh) / 2), fw, fh);
    ctx.restore();
  }
```

- [ ] **Step 3: 画面のマスの CSS**

グリッドのマスに `aspect-ratio` を当てる。`state.cellRatio` を `els.grid.dataset.cellRatio` に入れ、
CSS 側で切り替える（インラインスタイルを書かない。OS 9 風の見た目はトークン経由で保つ）。

```css
/* マスの形。16:9 は動画サイトのサムネイルに合わせたもの */
.grid .cell { aspect-ratio: 1 / 1; }
.grid[data-cell-ratio="16:9"] .cell { aspect-ratio: 16 / 9; }
```

- [ ] **Step 4: 設定を置く**

「比率」の下に**「マスの形」**。ラベルは **「正方形」** と **「横長 16:9」**。
既存の比率のセグメント（`ratioSeg`）と同じ作りにする。

- [ ] **Step 5: 短辺基準に変える**

- 番号バッジ・曲名の帯・× を出すかの判定（`DENSE_CELL_PX`・`SMALL_CELL_PX`・`overlayOk`）
- 「出力サイズ」の「マスの大きさ」表示は **`幅 × 高さ`**（`120 × 68 px`）にする

- [ ] **Step 6: ブラウザで見る**

```bash
PYTHONUTF8=1 .venv/Scripts/python scripts/build_app.py
PYTHONUTF8=1 .venv/Scripts/python scripts/build_fonts.py
PYTHONUTF8=1 .venv/Scripts/python scripts/check_i18n.py
PYTHONUTF8=1 .venv/Scripts/python scripts/upload_app_r2.py
PYTHONUTF8=1 .venv/Scripts/python scripts/upload_fonts_r2.py
# サーバーを立て直してから開く
```

「マスの形」を切り替えて、格子が横長になること・ジャケットの左右が切れないことを見る。

- [ ] **Step 7: コミット**

```bash
git add frontend/index.html frontend/dist/index.html fonts/
git commit -m "feat(ui): マスの形（正方形 / 横長 16:9）を選べるようにする"
```

---

### Task 4: 突き合わせ

**Files:**
- Modify: `scripts/compare_layout.py`、`promo/dump_layouts.mjs`
- Modify: `scripts/compare_render.py`

- [ ] **Step 1: `compare_layout` に形を足す**

組み合わせを `(cols, rows, ratio)` から `(cols, rows, ratio, cellRatio)` にする。
`dump_layouts.mjs` の `opt` にも `cellRatio` を渡す。

- [ ] **Step 2: 回す**

Run: `PYTHONUTF8=1 .venv/Scripts/python scripts/compare_layout.py 200`
Expected: `食い違い 0 / 200`

- [ ] **Step 3: 絵で比べる**（16:9 のマス、正方形の絵が混ざる並び）

```bash
PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py make 6 6 16:9 fill
# ブラウザで開き「マスの形」を横長にして「トラックを共有」
PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py diff <サーバー> <ブラウザ>
PYTHONUTF8=1 .venv/Scripts/python scripts/compare_render.py clean <ID> <ID>
```

Expected: **6px のぼかしで 0.3% 未満**。

**ぼかし埋めの下地は PIL と Canvas で完全には一致しない**。超えるときは、どれだけ超えるかを
記録したうえで、下地を平均色で塗る逃げ道（`COMPARE_FLAT_PAD=1`）を用意する。

- [ ] **Step 4: コミット**

```bash
git add scripts/ promo/
git commit -m "test(cell-ratio): 突き合わせにマスの形を足す"
```

---

### Task 5: 文書と更新情報

**Files:**
- Modify: `docs/layout.md`、`docs/ui.md`、`CLAUDE.md`、`backend/pages.py`
- Modify: `cli.py`（`--cell 1:1|16:9`）

- [ ] **Step 1: `cli.py` に `--cell`**

```python
    sp.add_argument("--cell", dest="cell_ratio", choices=["1:1", "16:9"], help="マスの形（既定は正方形）")
```

`updates` に `"cellRatio": a.cell_ratio` を足す。

- [ ] **Step 2: 文書**

- `docs/layout.md`: 寸法の表（どの式が幅・高さ・短辺を見るか）とぼかし埋め、突き合わせの実測
- `docs/ui.md`: 「マスの形」の場所と、短辺基準に変えた判定
- `CLAUDE.md` の二重実装の一覧: 「色・比率・`CELL_PX` / `GAP_PX` / `MAX_SIDE`」の行を
  `CELL_W` / `CELL_H_BY_RATIO` に直し、ぼかし埋めを足す

- [ ] **Step 3: 更新情報**（手順はスキル `/updates`）

```
2026-09-21 マスの形に「横長 16:9」を選べるようにしました。YouTube やニコニコ動画の
           サムネイルが左右を切られずに並びます。
```

- [ ] **Step 4: 点検**

```bash
PYTHONUTF8=1 .venv/Scripts/python scripts/check_consistency.py
```

- [ ] **Step 5: コミット して push**
