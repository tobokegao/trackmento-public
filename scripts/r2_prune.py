"""共有ファイル（R2 またはローカル shares/）を古い順に削除して容量を空ける。緊急時用。通常はライフサイクル規則に任せる。

  python scripts/r2_prune.py --older-than-hours 12           # 対象を数えて表示するだけ（削除しない）
  python scripts/r2_prune.py --older-than-hours 12 --apply   # 削除する（取り消せない。該当の共有 URL は開けなくなる）

削除後に使用量を取り直して表示する。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import storage  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--older-than-hours", type=float, required=True, help="これより古い（最終更新がこの時間数より前の）ファイルを対象にする")
    ap.add_argument("--apply", action="store_true", help="実際に削除する（無ければ数えるだけ）")
    a = ap.parse_args()

    st = storage.get_storage()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=a.older_than_hours)
    victims: list[str] = []
    vbytes = keep_n = keep_bytes = 0
    for key, size, modified in st.list_objects():
        if modified < cutoff:
            victims.append(key)
            vbytes += size
        else:
            keep_n += 1
            keep_bytes += size
    print(f"保存先: {st.name}  基準: {cutoff:%Y-%m-%d %H:%M} UTC より古いもの")
    print(f"削除対象: {len(victims)} 件 {vbytes / 1024**3:.2f} GB   残す: {keep_n} 件 {keep_bytes / 1024**3:.2f} GB")
    if not a.apply:
        print("（数えただけ。削除するには --apply を付ける）")
        return 0
    deleted = st.delete_many(victims)
    print(f"削除: {deleted} 件")
    print(f"使用量: {storage.usage_bytes(refresh=True) / 1024**3:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
