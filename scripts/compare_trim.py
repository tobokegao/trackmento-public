"""刈り込みの二重実装（`backend/names.py` と frontend の `trimName`）を突き合わせる。

曲名が 1 字でも違えば折り返しが変わり、そこから割り付けが丸ごとずれる。**全件一致が条件**。

正規表現の写し間違いのほかに、`_n()` と `nkey()` の食い違い（ß の畳み方・単独の濁点・
`\\w` と `\\p{L}` の差）でもずれる。落ちたら**ブラウザ側を Python に合わせる**。

    # サーバーを公開モードで立てたうえで
    PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_trim.py
    PYTHONUTF8=1 .venv/Scripts/python scripts/compare_trim.py --n 400   # 集める題の数（既定 200）
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from backend.names import trim  # noqa: E402
from scripts.check_trim import CASES  # noqa: E402

FIND = "https://trackmento.com/find.json"
SNAP = "https://img.trackmento.com/{}.json"


def collect(limit: int) -> list[tuple[str, str]]:
    """みんなの並びから題と作者名を集める。**本物の題で試す**のが肝心で、
    作った文字列では括弧の入れ子やチャンネル名の癖が出ない"""
    pairs: list[tuple[str, str]] = [(t, a) for t, a, _, _ in CASES]   # 既知の例も必ず入れる
    seen = {(t, a) for t, a in pairs}
    with httpx.Client(timeout=30) as c:
        ids = [r["id"] for r in c.get(FIND, params={"limit": 40}).json()["results"]]
        for i in ids:
            if len(pairs) >= limit:
                break
            try:
                doc = c.get(SNAP.format(i)).json()
            except Exception:
                continue
            for cell in doc.get("cells") or []:
                if not cell:
                    continue
                pair = ((cell.get("title") or "").strip(), (cell.get("artist") or "").strip())
                if pair[0] and pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)
    return pairs[:limit]


def main() -> int:
    n = 200
    if "--n" in sys.argv:
        n = int(sys.argv[sys.argv.index("--n") + 1])
    pairs = collect(n)
    print(f"{len(pairs)} 件の題で比べます")

    with tempfile.TemporaryDirectory() as td:
        tmp = pathlib.Path(td)
        (tmp / "in.json").write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run(["node", str(ROOT / "promo" / "dump_trim.mjs"),
                            str(tmp / "out.json"), str(tmp / "in.json")],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            print(r.stdout)
            print(r.stderr)
            return 2
        js = json.loads((tmp / "out.json").read_text(encoding="utf-8"))

    bad = 0
    for (title, artist), got_js in zip(pairs, js):
        got_py = list(trim(title, artist))
        if got_py != got_js:
            bad += 1
            print(f"[ずれ] {title} / {artist}")
            print(f"   Python: {got_py[0]!r} / {got_py[1]!r}")
            print(f"   JS    : {got_js[0]!r} / {got_js[1]!r}")
    print(f"{len(pairs) - bad} / {len(pairs)} 件一致")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
