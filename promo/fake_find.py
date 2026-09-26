"""X 向けの短い動画（f-find）で使う、架空の「みんなのグリッドを探す」ページを出す。

    PYTHONUTF8=1 .venv/Scripts/python promo/fake_find.py '{"q": "", "own": {"id": "…", "title": "…"}}'

**本番の探すページには利用者の本物の題（実在の曲名・アーティスト名）が並ぶ**ので、撮影では使わない（2026-09-26）。
並びの題も曲名もすべて架空のものを入れて、サイトと同じ `share.find_html` で組み、HTML を標準出力に書く。
撮影側（x_catalog_flow.mjs）が /find への問い合わせをこれで差し替える。own を渡すと、その並びを「最近のグリッド」の先頭に置く
（撮影でいま共有した並び。端末に鍵があるので × が出る）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import share  # noqa: E402

VARIED = [("夏の終わりに聴きたい9曲", 3, 3), ("作業用 BGM", 4, 4), ("今年のベスト 16", 4, 4), ("ドライブで流す曲", 3, 3),
          ("人生を変えた音MAD", 3, 3), ("雨の日のプレイリスト", 4, 3), ("深夜のボカロ", 3, 3), ("はじめて買った CD", 2, 2)]
RECENT = [("私を構成する9曲", 3, 3), ("私を構成する9曲", 3, 3), ("好きな歌ってみた", 4, 4), ("私を構成する9曲", 3, 3)]
# 探したときに当たる曲（架空。promo/fake_covers.py の曲名と同じ世界）
HITS = {"夜明けのシグナル": ["夜明けのシグナル — ミナトリ"], "シグナル": ["夜明けのシグナル — ミナトリ"]}


def main() -> None:
    arg = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    q, own = (arg.get("q") or "").strip(), arg.get("own")
    row = lambda i, t, c, r: {"id": f"fa4e{i:08x}", "title": t, "n": c * r, "cols": c, "rows": r, "createdAt": "", "hits": []}
    varied = [row(i, *v) for i, v in enumerate(VARIED)]
    recent = [row(100 + i, *v) for i, v in enumerate(RECENT)]
    if own:
        recent.insert(0, {"id": own["id"], "title": own.get("title") or "", "n": own.get("n", 9), "cols": own.get("cols", 3),
                          "rows": own.get("rows", 3), "createdAt": "", "hits": []})
    if q:
        hits = HITS.get(q, [])
        results = [{**r, "hits": hits} for r in ([recent[0]] + varied[:3] if hits else [])]
        html = share.find_html(q, results, "http://127.0.0.1:8000", "http://127.0.0.1:8000", "ja", 240, None, nonce="clip")
    else:
        html = share.find_html("", recent, "http://127.0.0.1:8000", "http://127.0.0.1:8000", "ja", 240, varied, nonce="clip")
    sys.stdout.write(html)


if __name__ == "__main__":
    main()
