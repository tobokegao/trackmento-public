"""作業中グリッド JSON（grids/<name>.json）の読み書き。Web の localStorage、CLI、/render で同じ形式を使う。

形式は仕様書「グリッド JSON の形式」のとおり。読み込み時はフロントの applyData と同じ規則で丸める。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.models import Track

ROOT = Path(__file__).resolve().parent.parent
GRIDS = ROOT / "grids"

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
# 1 辺の上限。frontend/index.html の MAX_SIDE_CELLS と同じ値にすること。
# 総数の上限（既定 256）は config.max_cells() が別に見る（main.py の _check_cells）。
# **ここを frontend より小さくしてはいけない**。GridDoc の検証は cols/rows を黙って丸めるので、
# 16x16 の並びを保存した瞬間に 12x12 へ潰れ、はみ出したマスが stash に移って並びが壊れる
MAX_COLS = 32
MAX_ROWS = 32
MAX_STASH = 200   # マスから溢れた曲の控え。無制限だと JSON が肥大する
Ratio = Literal["1:1", "16:9", "4:5", "9:16", "free"]
BG_KEYS = ("paper", "ink", "mustard", "cerulean", "lavender", "vermilion", "mint", "pink",
           "ivory", "charcoal", "lemon", "ultramarine", "coral", "sky", "leaf", "rose",
           "night", "chalk", "amber", "azure", "flare", "violet", "jade", "magenta", "custom")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class GridOptions(BaseModel):
    ratio: Ratio = "16:9"
    showTitle: bool = True
    sidebar: bool = True
    # 曲名リストをマスの上に重ねる（ジャケットの下に帯を敷いて曲名とアーティスト名を載せる）。
    # **重ねるときは sidebar を切って保存する**。この項目を知らない古いタブで開いても「曲名リストなし」になるだけで壊れない
    overlay: bool = False
    numbers: bool = False
    # マスの形。"1:1"（正方形）か "16:9"（横長。動画サイトのサムネイルに合う）。
    # **既定は正方形**（今ある並びと共有画像の見た目を変えないため）
    cellRatio: str = "1:1"
    # 正方形でないマスへの絵の入れ方。"crop"（中央で切る）か "blur"（切らずにぼかして埋める）。
    # マスごとに `Track.fit` で上書きできる（文字の入ったジャケットだけ埋めたいとき）
    cellFit: str = "crop"
    # 曲名とアーティスト名から蛇足（【東方Vocal】・「- Topic」など）を外して表示する（backend/names.py）。
    # **データは元のまま**で、表示のときだけ通す。この項目を知らない古いタブで開いても刈らないだけで壊れない
    trimNames: bool = True
    bg: str = "paper"
    bgCustom: Optional[str] = None
    # 背景の決め方（2026-09-25）。"pick"（色を選ぶ）/ "near"・"far"（ジャケットに近い色・反対の色）/ "none"（背景なし）。
    # **描くのは bg / bgCustom だけ**（ジャケットの色も背景なしの白い地もブラウザがカスタムカラーに入れて送る）。
    # これは画面で決め方を覚えておくためのもので、サーバーの描画は見ない
    bgMode: str = "pick"
    margin: int = 16
    # 外側の余白の下限の段。"normal"（内容の短い辺の 3.5%）/ "wide"（7%）/ "xwide"（12%）。render.py の PAD_FRAC。
    # **既定は normal**（今ある並びと共有画像の見た目を変えないため。2026-09-24 に「余白」のスライダーから替えた）
    pad: str = "normal"
    gap: int = 16       # マスとマスの間隔（出力 px）

    @field_validator("bg")
    @classmethod
    def _bg(cls, v: str) -> str:
        return v if v in BG_KEYS else "paper"

    @field_validator("bgMode")
    @classmethod
    def _bg_mode(cls, v: str) -> str:
        return v if v in ("pick", "near", "far", "none") else "pick"

    @field_validator("cellRatio")
    @classmethod
    def _cell_ratio(cls, v: str) -> str:
        return v if v in ("1:1", "16:9") else "1:1"

    @field_validator("cellFit")
    @classmethod
    def _cell_fit(cls, v: str) -> str:
        return v if v in ("crop", "blur") else "crop"

    @field_validator("pad")
    @classmethod
    def _pad(cls, v: str) -> str:
        return v if v in ("normal", "wide", "xwide") else "normal"

    @field_validator("margin", mode="before")
    @classmethod
    def _margin(cls, v) -> int:
        try:
            return max(0, min(160, int(round(float(v)))))
        except (TypeError, ValueError):
            return 16

    @field_validator("gap", mode="before")
    @classmethod
    def _gap(cls, v) -> int:
        try:
            return max(0, min(96, int(round(float(v)))))
        except (TypeError, ValueError):
            return 16

    @model_validator(mode="after")
    def _custom(self) -> "GridOptions":
        if self.bg == "custom" and not (self.bgCustom and _HEX_RE.match(self.bgCustom)):
            self.bg = "paper"
            self.bgCustom = None
        if self.overlay:
            self.sidebar = False   # 重ねるときは横の曲名リストを切って保存する（古いタブで開いても壊れない）
        return self


class GridDoc(BaseModel):
    app: str = "trackmento"
    version: int = 1
    name: str = "default"
    savedAt: Optional[str] = None
    title: str = ""
    cols: int = 3
    rows: int = 3
    cells: list[Optional[Track]] = Field(default_factory=list)
    stash: list[Track] = Field(default_factory=list)
    options: GridOptions = Field(default_factory=GridOptions)
    # **みんなの並びから探せるようにするか**（既定オフ）。共有は本来 URL を知っている人だけのものなので、
    # 索引（`backend/shareindex.py`）に載せるのは利用者が自分でチェックを入れたものだけにする
    listed: bool = False

    @field_validator("cols", "rows", mode="before")
    @classmethod
    def _dim(cls, v) -> int:
        try:
            return max(1, min(MAX_COLS, int(round(float(v)))))
        except (TypeError, ValueError):
            return 3

    @field_validator("title", mode="before")
    @classmethod
    def _title(cls, v) -> str:
        return " ".join((v if isinstance(v, str) else "").split())[:60]   # 改行は空白に

    @field_validator("cells", "stash", mode="before")
    @classmethod
    def _tracks(cls, v):
        # 壊れた要素は None（cells）／除外（stash）にして全体は生かす
        if not isinstance(v, list):
            return []
        out = []
        for t in v:
            try:
                out.append(Track.model_validate(t) if t is not None else None)
            except Exception:
                out.append(None)
        return out

    @model_validator(mode="after")
    def _fit(self) -> "GridDoc":
        n = self.cols * self.rows
        self.stash = [t for t in self.stash if t is not None][:MAX_STASH]
        if len(self.cells) > n:
            self.stash = [t for t in self.cells[n:] if t] + self.stash
            self.cells = self.cells[:n]
        while len(self.cells) < n:
            self.cells.append(self.stash.pop(0) if self.stash else None)
        return self

    # ---- 便利メソッド ----
    @property
    def size(self) -> int:
        return self.cols * self.rows

    def placed(self) -> list[tuple[int, Track]]:
        return [(i, t) for i, t in enumerate(self.cells) if t]

    def first_empty(self) -> int | None:
        for i, t in enumerate(self.cells):
            if t is None:
                return i
        return None

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        self._fit()

    def touch(self) -> None:
        self.savedAt = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise ValueError("グリッド名は英数字・ハイフン・アンダースコア 1〜40 文字にしてください")
    return name


def path_for(name: str) -> Path:
    return GRIDS / f"{validate_name(name)}.json"


def exists(name: str) -> bool:
    return path_for(name).exists()


def load(name: str = "default") -> GridDoc:
    """無ければ空の 3×3 を返す（ファイルは作らない）。"""
    p = path_for(name)
    if not p.exists():
        return GridDoc(name=name)
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{p.name} の形式が不正です")
    doc = GridDoc.model_validate(raw)
    doc.name = name
    return doc


def save(doc: GridDoc, name: str | None = None) -> Path:
    if name:
        doc.name = name
    p = path_for(doc.name)
    GRIDS.mkdir(exist_ok=True)
    if not doc.savedAt:
        doc.touch()
    p.write_text(json.dumps(doc.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def list_names() -> list[str]:
    if not GRIDS.exists():
        return []
    return sorted(p.stem for p in GRIDS.glob("*.json") if NAME_RE.match(p.stem))
