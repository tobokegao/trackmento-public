"""共有ファイル（R2 またはローカル shares/）を古い順に削除して容量を空ける。

  python scripts/r2_prune.py --older-than-hours 168           # 対象を数えて表示するだけ（削除しない）
  python scripts/r2_prune.py --older-than-hours 168 --apply   # 削除する（取り消せない。該当の共有 URL は開けなくなる）

R2 のライフサイクル規則はプレフィックスでしか対象を指定できず、共有ファイルの名前は
ランダムな 12 桁なので絞り込めない。空のプレフィックス（＝バケット全体）で規則を作ると
fonts/ まで消えて本番のフォントが 404 になるため、削除はこのスクリプトで行う。

KEEP_PREFIXES に挙げたものは古くても消さない:
  - fonts/   … 分割フォント。消えると本番の表示が壊れる（scripts/upload_fonts_r2.py が上げる）

共有（既定 720 時間）より短い期限で消すものが 2 つあり、期限はそれぞれ違う:
  - imgcache/ … 画像キャッシュ。既定 336 時間（14 日）。SQLite 側の索引が 13 日
                （cache.R2_IMAGE_TTL）なので、それより長く置く。**索引 < 掃除**を必ず守る
                （逆にすると、消えた後もリダイレクトし続けて 404 になる）
  - searchcache/ … 検索結果の控え（backend/searchcache.py）。索引が 6 日なので 168 時間（7 日）

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
# app/ … 切り出した CSS と JS（scripts/upload_app_r2.py）。配布済みの殻がまだ古い名前を指しているので消さない
KEEP_PREFIXES = ("fonts/", "app/")
# 共有（既定 720 時間）より短い期限で消すもの。**2 つは期限が違う**ので分けてある
IMAGE_PREFIXES = ("imgcache/",)      # 画像キャッシュ。索引は cache.R2_IMAGE_TTL（13 日）
SEARCH_PREFIXES = ("searchcache/",)  # 検索結果の控え（backend/searchcache.py。索引は 6 日）
SHORT_PREFIXES = IMAGE_PREFIXES + SEARCH_PREFIXES   # 表示用


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--older-than-hours", type=float, required=True, help="これより古い（最終更新がこの時間数より前の）ファイルを対象にする")
    ap.add_argument("--image-cache-hours", type=float, default=336.0,
                    help=f"{', '.join(IMAGE_PREFIXES)} を消すまでの時間数（既定 336 = 14 日）。"
                         "cache.R2_IMAGE_TTL（13 日）より長くしておく")
    ap.add_argument("--search-cache-hours", type=float, default=168.0,
                    help=f"{', '.join(SEARCH_PREFIXES)} を消すまでの時間数（既定 168 = 7 日）。索引の 6 日より長くしておく")
    ap.add_argument("--apply", action="store_true", help="実際に削除する（無ければ数えるだけ）")
    a = ap.parse_args()

    st = storage.get_storage()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=a.older_than_hours)
    cutoff_img = now - timedelta(hours=a.image_cache_hours)
    cutoff_srch = now - timedelta(hours=a.search_cache_hours)
    victims: list[str] = []
    vbytes = keep_n = keep_bytes = kept_n = kept_bytes = 0
    for key, size, modified in st.list_objects():
        if key.startswith(KEEP_PREFIXES):
            kept_n += 1
            kept_bytes += size
            continue
        if key.startswith(IMAGE_PREFIXES):
            limit = cutoff_img
        elif key.startswith(SEARCH_PREFIXES):
            limit = cutoff_srch
        else:
            limit = cutoff
        if modified < limit:
            victims.append(key)
            vbytes += size
        else:
            keep_n += 1
            keep_bytes += size
    print(f"保存先: {st.name}  基準: {cutoff:%Y-%m-%d %H:%M} UTC より古いもの"
          f"（{', '.join(IMAGE_PREFIXES)} は {cutoff_img:%Y-%m-%d %H:%M} UTC、"
          f"{', '.join(SEARCH_PREFIXES)} は {cutoff_srch:%Y-%m-%d %H:%M} UTC）")
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
