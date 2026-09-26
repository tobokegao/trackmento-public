"""共有ファイル（R2 またはローカル shares/）を古い順に削除して容量を空ける。

  python scripts/r2_prune.py --older-than-hours 168           # 対象を数えて表示するだけ（削除しない）
  python scripts/r2_prune.py --older-than-hours 168 --apply   # 削除する（取り消せない。該当の共有 URL は開けなくなる）

R2 のライフサイクル規則はプレフィックスでしか対象を指定できず、共有ファイルの名前は
ランダムな 12 桁なので絞り込めない。空のプレフィックス（＝バケット全体）で規則を作ると
fonts/ まで消えて本番のフォントが 404 になるため、削除はこのスクリプトで行う。

KEEP_PREFIXES に挙げたものは古くても消さない:
  - fonts/   … 分割フォント。消えると本番の表示が壊れる（scripts/upload_fonts_r2.py が上げる）
  - howto/   … 使い方の動画（/howto）の動画。消えると動画が 404 になる（scripts/upload_howto_r2.py が上げる）

共有（既定 720 時間）より短い期限で消すものが 2 つあり、期限はそれぞれ違う:
  - imgcache/ … 画像キャッシュ。既定 336 時間（14 日）。SQLite 側の索引が 13 日
                （cache.R2_IMAGE_TTL）なので、それより長く置く。**索引 < 掃除**を必ず守る
                （逆にすると、消えた後もリダイレクトし続けて 404 になる）
  - searchcache/ … 検索結果の控え（backend/searchcache.py）。索引が 6 日なので 168 時間（7 日）

共有より**長く**置くものが 1 つある:
  - uploads/ … 端末から上げた画像（手入力のマス・背景の画像）。既定 2160 時間（90 日）。2026-09-25 までは共有と同じ 30 日で消えていた。
               共有は 30 日で消えるが、手元の並び（localStorage）はずっと残り、そこから画像を指しているので、共有より長く置く
               （利用者と決めた。1 か月で約 1GB 増えるので、90 日で約 3GB に頭打ちになり、R2 の無料の範囲に収まる）

残る量は種類ごとに数えて表示する。**この一覧に相乗りするので、数え直しに追加の Class A は要らない**。
`--append metrics/r2.jsonl` を付けると 1 行残り、運用ボードの「R2 の使用量」がそこから出る。
削除後に一覧を取り直してはいけない（21 万件ぶんの Class A をもう一度払うことになる）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import storage  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
from r2_count import bucket_of  # noqa: E402  種類分けはここだけに持つ（数え方が 2 つあるとずれる）


def write_line(path: Path, left_n, left_bytes, *, deleted: int, applied: bool, shares_by_day=None) -> None:
    """種類ごとの件数と容量を JSONL に 1 行足す。掃除の一覧に相乗りするので、追加の Class A は要らない。"""
    from datetime import datetime as _dt

    jst = _dt.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M")
    row = {
        "jst": jst,
        "applied": applied,
        "deleted": deleted,
        "total_n": sum(left_n.values()),
        "total_bytes": sum(left_bytes.values()),
        "kinds": {k: [left_n[k], left_bytes[k]] for k in sorted(left_n)},
    }
    if shares_by_day:
        # 残っている共有（並びの .json）を作られた日（UTC）ごとに。30 日ぶんが 1 行で揃うので、
        # 運用ボードの「1 日の共有数」はいちばん新しい行だけで描ける（2026-09-22）
        row["shares_by_day"] = dict(sorted(shares_by_day.items()))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[append] {path} に 1 行足した（{jst} JST）")

# 古くても消さないもの（前方一致）。共有の期限とは無関係に置いておく必要があるファイル
# app/ … 切り出した CSS と JS（scripts/upload_app_r2.py）。配布済みの殻がまだ古い名前を指しているので消さない
KEEP_PREFIXES = ("fonts/", "app/", "howto/")   # howto/ は使い方の動画の動画（scripts/upload_howto_r2.py）
# 共有（既定 720 時間）より短い期限で消すもの。**2 つは期限が違う**ので分けてある
IMAGE_PREFIXES = ("imgcache/",)      # 画像キャッシュ。索引は cache.R2_IMAGE_TTL（13 日）
SEARCH_PREFIXES = ("searchcache/",)  # 検索結果の控え（backend/searchcache.py。索引は 6 日）
SHORT_PREFIXES = IMAGE_PREFIXES + SEARCH_PREFIXES   # 表示用
UPLOAD_PREFIXES = ("uploads/",)     # 端末から上げた画像。共有より長く置く（--upload-hours、既定 90 日）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--older-than-hours", type=float, required=True, help="これより古い（最終更新がこの時間数より前の）ファイルを対象にする")
    ap.add_argument("--image-cache-hours", type=float, default=336.0,
                    help=f"{', '.join(IMAGE_PREFIXES)} を消すまでの時間数（既定 336 = 14 日）。"
                         "cache.R2_IMAGE_TTL（13 日）より長くしておく")
    ap.add_argument("--search-cache-hours", type=float, default=360.0,
                    help=f"{', '.join(SEARCH_PREFIXES)} を消すまでの時間数（既定 360 = 15 日）。索引の上限（14 日）より長くしておく")
    ap.add_argument("--upload-hours", type=float, default=2160.0,
                    help=f"{', '.join(UPLOAD_PREFIXES)} を消すまでの時間数（既定 2160 = 90 日）")
    ap.add_argument("--apply", action="store_true", help="実際に削除する（無ければ数えるだけ）")
    ap.add_argument("--append", type=Path,
                    help="種類ごとの件数と容量を JSONL に 1 行足す（既定 metrics/r2.jsonl。運用ボードの元）")
    a = ap.parse_args()

    st = storage.get_storage()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=a.older_than_hours)
    cutoff_img = now - timedelta(hours=a.image_cache_hours)
    cutoff_srch = now - timedelta(hours=a.search_cache_hours)
    cutoff_up = now - timedelta(hours=a.upload_hours)
    victims: list[str] = []
    vbytes = keep_n = keep_bytes = kept_n = kept_bytes = 0
    # 残るものを種類ごとに数える（この一覧に相乗りする。別に数えると Class A をもう一度払う）
    left_n: Counter[str] = Counter()
    left_bytes: Counter[str] = Counter()
    shares_by_day: Counter[str] = Counter()
    for key, size, modified in st.list_objects():
        if key.startswith(KEEP_PREFIXES):
            kept_n += 1
            kept_bytes += size
            left_n[bucket_of(key)] += 1
            left_bytes[bucket_of(key)] += size
            continue
        if key.startswith(IMAGE_PREFIXES):
            limit = cutoff_img
        elif key.startswith(SEARCH_PREFIXES):
            limit = cutoff_srch
        elif key.startswith(UPLOAD_PREFIXES):
            limit = cutoff_up
        else:
            limit = cutoff
        if modified < limit:
            victims.append(key)
            vbytes += size
        else:
            keep_n += 1
            keep_bytes += size
            left_n[bucket_of(key)] += 1
            left_bytes[bucket_of(key)] += size
            if bucket_of(key) == "共有（並び）":
                shares_by_day[modified.astimezone(timezone.utc).strftime("%Y-%m-%d")] += 1
    print(f"保存先: {st.name}  基準: {cutoff:%Y-%m-%d %H:%M} UTC より古いもの"
          f"（{', '.join(IMAGE_PREFIXES)} は {cutoff_img:%Y-%m-%d %H:%M} UTC、"
          f"{', '.join(SEARCH_PREFIXES)} は {cutoff_srch:%Y-%m-%d %H:%M} UTC、"
          f"{', '.join(UPLOAD_PREFIXES)} は {cutoff_up:%Y-%m-%d %H:%M} UTC）")
    print(f"削除対象: {len(victims)} 件 {vbytes / 1024**3:.2f} GB   残す: {keep_n} 件 {keep_bytes / 1024**3:.2f} GB")
    if kept_n:
        print(f"対象外（{', '.join(KEEP_PREFIXES)}）: {kept_n} 件 {kept_bytes / 1024**3:.2f} GB")
    for k in sorted(left_n, key=lambda x: -left_bytes[x]):
        print(f"  {k:<18} {left_n[k]:>8,} 件  {left_bytes[k] / 1024**3:7.3f} GB")

    if not a.apply:
        print("（数えただけ。削除するには --apply を付ける）")
        if a.append:
            write_line(a.append, left_n, left_bytes, deleted=0, applied=False, shares_by_day=shares_by_day)
        return 0
    deleted = st.delete_many(victims)
    print(f"削除: {deleted} 件")
    # **ここで一覧を取り直さない**。消した分は上の数えから引けば分かるので、取り直すと
    # 21 万件ぶんの Class A をもう一度払うことになる（2026-09-21 に気付いて直した）
    print(f"使用量: {sum(left_bytes.values()) / 1024**3:.2f} GB（消したあと。一覧は取り直さない）")
    if a.append:
        write_line(a.append, left_n, left_bytes, deleted=deleted, applied=True, shares_by_day=shares_by_day)
    return 0


if __name__ == "__main__":
    sys.exit(main())
