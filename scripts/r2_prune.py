"""共有ファイル（R2 またはローカル shares/）を古い順に削除して容量を空ける。

  python scripts/r2_prune.py --older-than-hours 168           # 対象を数えて表示するだけ（削除しない）
  python scripts/r2_prune.py --older-than-hours 168 --apply   # 削除する（取り消せない。該当の共有 URL は開けなくなる）

R2 のライフサイクル規則はプレフィックスでしか対象を指定できず、共有ファイルの名前は
ランダムな 12 桁なので絞り込めない。空のプレフィックス（＝バケット全体）で規則を作ると
fonts/ まで消えて本番のフォントが 404 になるため、削除はこのスクリプトで行う。

KEEP_PREFIXES に挙げたものは古くても消さない:
  - fonts/   … 分割フォント。消えると本番の表示が壊れる（scripts/upload_fonts_r2.py が上げる）

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

# 古くても消さないもの（前方一致）。共有の期限とは無関係に置いておく必要があるファイル
KEEP_PREFIXES = ("fonts/",)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--older-than-hours", type=float, required=True, help="これより古い（最終更新がこの時間数より前の）ファイルを対象にする")
    ap.add_argument("--apply", action="store_true", help="実際に削除する（無ければ数えるだけ）")
    a = ap.parse_args()

    st = storage.get_storage()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=a.older_than_hours)
    victims: list[str] = []
    vbytes = keep_n = keep_bytes = kept_n = kept_bytes = 0
    for key, size, modified in st.list_objects():
        if key.startswith(KEEP_PREFIXES):
            kept_n += 1
            kept_bytes += size
            continue
        if modified < cutoff:
            victims.append(key)
            vbytes += size
        else:
            keep_n += 1
            keep_bytes += size
    print(f"保存先: {st.name}  基準: {cutoff:%Y-%m-%d %H:%M} UTC より古いもの")
    print(f"削除対象: {len(victims)} 件 {vbytes / 1024**3:.2f} GB   残す: {keep_n} 件 {keep_bytes / 1024**3:.2f} GB")
    if kept_n:
        print(f"対象外（{', '.join(KEEP_PREFIXES)}）: {kept_n} 件 {kept_bytes / 1024**3:.2f} GB")
    if not a.apply:
        print("（数えただけ。削除するには --apply を付ける）")
        return 0
    deleted = st.delete_many(victims)
    print(f"削除: {deleted} 件")
    print(f"使用量: {storage.usage_bytes(refresh=True) / 1024**3:.2f} GB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
