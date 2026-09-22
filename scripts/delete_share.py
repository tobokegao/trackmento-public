"""荒らし・問い合わせを受けて、共有を期限（30 日）より前に消す。

  python scripts/delete_share.py abcd1234efgh                         # 消える対象を表示するだけ（削除しない）
  python scripts/delete_share.py https://trackmento.com/s/abcd1234efgh --apply            # 削除する（取り消せない）
  python scripts/delete_share.py abcd1234efgh --apply --with-uploads  # その並びが使っているアップロード画像も消す

消すもの: 本体画像（`<id>.jpg` / 古い共有は `.png`）・カード画像（`<id>-og.jpg`）・並び（`<id>.json`）・
「みんなのグリッド」の控え（`listed/<id>.json`）。`--with-uploads` を付けると、並びのマスが指している
アップロード画像（`uploads/<name>`）も消す。**アップロード画像は同じ人の別の並び・別の共有も使っていることがある**ので、
画像そのものに問題があるときだけ付ける。

- 共有ページ（`/s/<id>`）は開くたびに R2 から並びを読むので、**消した時点でメモも曲名も出なくなる**（410 の案内ページになる）
- 動いているサーバーの「みんなのグリッド」の索引からは、次にその共有ページが開かれたときに外れる
  （`shareindex.forget`。再起動でも外れる）
- **画像は img.trackmento.com（Cloudflare）のキャッシュに残ることがある**。最後に出る URL を
  Cloudflare のダッシュボードの「Caching → Configuration → Custom Purge」に貼って消す
  （`.env` の `CLOUDFLARE_API_TOKEN` は Analytics の読み取り権限しか無いので、ここからは消せない）
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import share, shareindex, storage  # noqa: E402

UPLOAD_RE = re.compile(r"^/uploads/([A-Za-z0-9._-]+)$")


def share_id(arg: str) -> str | None:
    """ID そのものか、共有ページの URL（…/s/<id>、…/?share=<id>）から ID を取り出す。"""
    m = re.search(r"(?:/s/|[?&]share=)([a-z0-9]+)", arg)
    sid = m.group(1) if m else arg.strip()
    return sid if share.valid_id(sid) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("shares", nargs="+", help="共有 ID か共有ページの URL（複数可）")
    ap.add_argument("--apply", action="store_true", help="実際に消す（付けなければ対象を表示するだけ）")
    ap.add_argument("--with-uploads", action="store_true", help="並びが使っているアップロード画像も消す")
    a = ap.parse_args()

    st = storage.get_storage()
    print(f"保存先: {'R2（' + st.bucket + '）' if st.is_remote else 'ローカルの shares/'}")
    keys: list[str] = []
    for arg in a.shares:
        sid = share_id(arg)
        if not sid:
            print(f"[skip] 共有 ID として読めません: {arg}")
            continue
        snap = share.load(sid)
        if snap:
            print(f"[{sid}] 「{snap.get('title') or '（題なし）'}」 {snap.get('createdAt') or ''}")
            for i, c in enumerate(snap.get("cells") or [], 1):
                if c and c.get("note"):
                    print(f"    {i:02d} メモ: {c['note']!r}")
        else:
            print(f"[{sid}] 並び（.json）はありません（期限切れか、もう消したもの）")
        found = [k for k in (f"{sid}.jpg", f"{sid}.png", f"{sid}-og.jpg", f"{sid}.json", shareindex.PREFIX + f"{sid}.json")
                 if st.exists(k)]
        if a.with_uploads and snap:
            for c in snap.get("cells") or []:
                m = UPLOAD_RE.match((c or {}).get("image") or "")
                if m and st.exists(f"uploads/{m.group(1)}"):
                    found.append(f"uploads/{m.group(1)}")
        for k in found:
            print(f"    {k}")
        keys += found

    keys = list(dict.fromkeys(keys))
    if not keys:
        print("消すものはありません")
        return 0
    if not a.apply:
        print(f"\n{len(keys)} 件が対象です。消すときは --apply を付けてもう一度（取り消せません）")
        return 0
    done = st.delete_many(keys)
    print(f"\n{done} / {len(keys)} 件を消しました")
    # 並びの .json も公開ドメインから読めてメモが入っているので、画像と一緒に消す。listed/ は画面から読まない
    urls = [u for u in (st.public_url(k) for k in keys if not k.startswith(shareindex.PREFIX)) if u]
    if urls:
        print("Cloudflare のキャッシュに残っている場合は、次の URL を Custom Purge に貼る:")
        for u in urls:
            print(f"  {u}")
    return 0 if done == len(keys) else 1


if __name__ == "__main__":
    sys.exit(main())
