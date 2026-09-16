"""送信中の窓に出す「作者の曲」の一覧を Bandcamp から作り直す。

    PYTHONUTF8=1 .venv/Scripts/python scripts/build_own_tracks.py [--dry]

`https://tbkgao.bandcamp.com/music` を 1 回だけ読み、**Tobokegao 名義の作品だけ**を拾って
`frontend/index.html` の `OWN_TRACKS` を書き換える。あのアカウントには別名義（MLTEK・
Giant Chess Men・Various Artists など）の作品も置いてあるので、名義で絞る。

**実行時に取りに行かない**のは、画面の CSP が Bandcamp への接続を許していないのと、
送信中に外部へ問い合わせて待たせたくないため。ここで一覧を焼き込んでおく。

新しい作品を出したら、これを回して `scripts/build_fonts.py` → `scripts/check_i18n.py` の順に。
"""
from __future__ import annotations

import html as H
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PAGE = "https://tbkgao.bandcamp.com/music"
BASE = "https://tbkgao.bandcamp.com"
# この名前で始まる名義だけ載せる（大文字小文字は無視）。"Tobokegao & JAWZZ" のような共作も入る
KEEP = "tobokegao"
BEGIN = "  const OWN_TRACKS = ["
END = "  ];"


def _items(text: str) -> list[dict]:
    """/music の一覧（最初のぶんは HTML、続きは data-client-items の JSON）をまとめて返す。"""
    out: list[dict] = []
    m = re.search(r'data-client-items="(.*?)"', text, re.S)
    if m:
        for d in json.loads(H.unescape(m.group(1))):
            out.append({"url": d.get("page_url", ""), "title": d.get("title", ""), "artist": d.get("artist", "")})
    i = text.find("music-grid")
    for li in re.findall(r'<li[^>]*data-item-id="[^"]*"[^>]*>(.*?)</li>', text[i:i + 60000], re.S):
        href = re.search(r'href="([^"]+)"', li)
        ti = re.search(r'<p class="title">(.*?)</p>', li, re.S)
        if not (href and ti):
            continue
        parts = [H.unescape(re.sub(r"<[^>]+>", "", p)).strip()
                 for p in re.split(r"<br>|<span[^>]*>|</span>", ti.group(1))]
        parts = [p for p in parts if p]
        if not parts:
            continue
        out.append({"url": href.group(1).split("?")[0], "title": parts[0],
                    "artist": parts[1] if len(parts) > 1 else ""})
    return out


def main() -> int:
    r = httpx.get(PAGE, timeout=30, follow_redirects=True,
                  headers={"User-Agent": "trackmento own-tracks builder (https://trackmento.onrender.com/)"})
    r.raise_for_status()
    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    for it in _items(r.text):
        url, title, artist = it["url"], " ".join(it["title"].split()), " ".join(it["artist"].split())
        if not url.startswith("/") or not title or url in seen:
            continue
        if not artist.lower().startswith(KEEP):
            continue
        seen.add(url)
        # 共作は名義も出す（「Wedding Bell（Tobokegao & JAWZZ）」）。単独名義なら題だけ
        label = title if artist.lower() == KEEP else f"{title}（{artist}）"
        rows.append((label, BASE + url))
    rows.sort(key=lambda x: x[0].lower())
    if not rows:
        print("1 件も取れませんでした（ページの作りが変わった可能性）")
        return 1
    body = "\n".join(f'    [{json.dumps(t, ensure_ascii=False)}, {json.dumps(u)}],' for t, u in rows)
    print(f"{len(rows)} 件")
    for t, u in rows:
        print(f"  {t}  {u}")
    if "--dry" in sys.argv:
        return 0
    p = ROOT / "frontend" / "index.html"
    s = p.read_text(encoding="utf-8", newline="")
    nl = "\r\n" if "\r\n" in s else "\n"
    a = s.index(BEGIN.replace("\n", nl))
    b = s.index(END.replace("\n", nl), a)
    new = (BEGIN + nl + body.replace("\n", nl) + nl + END)
    s = s[:a] + new + s[b + len(END):]
    p.write_text(s, encoding="utf-8", newline="")
    print("frontend/index.html を書き換えました（フォントの作り直しを忘れずに）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
