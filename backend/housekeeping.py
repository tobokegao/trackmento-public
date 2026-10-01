"""公開モード用のディスク掃除。shares/ とuploads/ は新しい順に一定数だけ残し、grids/ は古いものを消す。"""
from __future__ import annotations

import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARES = ROOT / "shares"
UPLOADS = ROOT / "uploads"
GRIDS = ROOT / "grids"

KEEP_SHARES = 2000      # PNG + カードJPEG + JSONの組数
KEEP_UPLOADS = 2000
GRID_MAX_AGE_DAYS = 90
KEEP_GRIDS = 5000       # ブラウザごとのグリッドJSONの上限件数（古い順に消す）


def _prune_newest(dir_: Path, patterns: tuple[str, ...], keep: int) -> int:
    if not dir_.exists():
        return 0
    files = sorted((p for pat in patterns for p in dir_.glob(pat) if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for p in files[keep:]:
        try:
            p.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def prune_shares(keep: int = KEEP_SHARES) -> int:
    # PNG・カードJPEG・JSONは1組なので合計はkeep*3
    return _prune_newest(SHARES, ("*.png", "*.jpg", "*.json"), keep * 3)


def prune_uploads(keep: int = KEEP_UPLOADS) -> int:
    return _prune_newest(UPLOADS, ("*.jpg", "*.png", "*.webp", "*.gif"), keep)


def prune_grids_count(keep: int = KEEP_GRIDS) -> int:
    """u-… のグリッドを新しい順にkeep件だけ残す（defaultは数えない）"""
    return _prune_newest(GRIDS, ("u-*.json",), keep)


def prune_grids(max_age_days: int = GRID_MAX_AGE_DAYS) -> int:
    """ブラウザごとのグリッド（u-… で始まるもの）で、長く更新されていないものを消す。defaultは消さない。"""
    if not GRIDS.exists():
        return 0
    limit = time.time() - max_age_days * 86400
    removed = 0
    for p in GRIDS.glob("u-*.json"):
        try:
            if p.stat().st_mtime < limit:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def run_all() -> dict[str, int]:
    return {"shares": prune_shares(), "uploads": prune_uploads(), "grids": prune_grids()}
