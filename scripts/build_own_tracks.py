"""送信中の窓に出す「作者の曲」の一覧を Bandcamp から作り直す。

    PYTHONUTF8=1 .venv/Scripts/python scripts/build_own_tracks.py [--dry]

`https://tbkgao.bandcamp.com/music` を読んで **Tobokegao 名義の作品**を拾い、
さらに 1 作品ずつページを開いて**曲単位**にばらし、`frontend/index.html` の
`OWN_TRACKS` を書き換える。あのアカウントには別名義（MLTEK・Giant Chess Men・
Various Artists など）の作品も置いてあるので、名義で絞る。

**題は日本語で出す**:

- Bandcamp の題が「ピクニック (Picnic)」のように併記なら、**日本語のほうだけ**にする
- ローマ字だけの題（Okane Ga Tarinai Toki No Uta）は自動では戻せないので、下の `JA` に
  読み替えを書く。**ここに無いものはローマ字のまま出る**ので、増えたら足す

**実行時に取りに行かない**のは、画面の CSP が Bandcamp への接続を許していないのと、
送信中に外部へ問い合わせて待たせたくないため。ここで一覧を焼き込んでおく。

新しい作品を出したら、これを回して `scripts/build_fonts.py` →
`scripts/upload_fonts_r2.py` → `scripts/check_i18n.py` の順に。
"""
from __future__ import annotations

import html as H
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PAGE = "https://tbkgao.bandcamp.com/music"
BASE = "https://tbkgao.bandcamp.com"
# この名前で始まる名義だけ載せる（大文字小文字は無視）。"Tobokegao & JAWZZ" のような共作も入る
KEEP = "tobokegao"
BEGIN = "  const OWN_TRACKS = ["
END = "  ];"
WAIT = 0.6   # Bandcamp へ続けて投げない（作品の数だけ開くので）

# ローマ字だけの題の読み替え。**左は Bandcamp の題そのまま**
JA = {
    "Okane Ga Tarinai Toki No Uta": "おかねがたりないときのうた",
    "Okane Ga Tarinai Toki No Uta (Tsukuyomi Ai Version)": "おかねがたりないときのうた（つくよみちゃん版）",
    "Yaruki ga Denai Toki no Uta": "やるきがでないときのうた",
    "Yomi De Ashibumi": "よみであしぶみ",
    "Yomi De Ashibumi (Vocal Version)": "よみであしぶみ（歌入り版）",
    "Sonna Hi Mo Aru Yone": "そんな日もあるよね",
    "Kodoku Na Fruits": "孤独なフルーツ",
    "Kodoku Na Fruits (Vocal Version)": "孤独なフルーツ（歌入り版）",
    "Tanashii Mainichi": "たなしい毎日",
    "Being Rusty (Tanashii Mainichi)": "たなしい毎日",
}

_JA_RE = re.compile(r"[ぁ-んァ-ヶ一-龥ー－]")


def _has_ja(s: str) -> bool:
    return bool(_JA_RE.search(s))


def _title(raw: str) -> str:
    """出す題を決める。併記なら日本語のほうだけ、ローマ字だけなら読み替え表を見る。"""
    t = " ".join(raw.split())
    if t in JA:
        return JA[t]
    # 「日本語 (English)」 … 後ろの括弧を落とす。括弧の中に日本語があるなら触らない
    m = re.match(r"^(.*?)\s*\(([^()]*)\)$", t)
    if m and _has_ja(m.group(1)) and not _has_ja(m.group(2)):
        return m.group(1).strip()
    return t


def _releases(text: str) -> list[dict]:
    """/music の一覧（最初のぶんは HTML、続きは data-client-items の JSON）をまとめて返す。"""
    out: list[dict] = []
    m = re.search(r'data-client-items="(.*?)"', text, re.S)
    if m:
        for d in json.loads(H.unescape(m.group(1))):
            out.append({"url": d.get("page_url", ""), "artist": d.get("artist", "")})
    i = text.find("music-grid")
    for li in re.findall(r'<li[^>]*data-item-id="[^"]*"[^>]*>(.*?)</li>', text[i:i + 60000], re.S):
        href = re.search(r'href="([^"]+)"', li)
        ti = re.search(r'<p class="title">(.*?)</p>', li, re.S)
        if not (href and ti):
            continue
        parts = [H.unescape(re.sub(r"<[^>]+>", "", p)).strip()
                 for p in re.split(r"<br>|<span[^>]*>|</span>", ti.group(1))]
        parts = [p for p in parts if p]
        out.append({"url": href.group(1).split("?")[0], "artist": parts[1] if len(parts) > 1 else ""})
    return out


def _tracks(client: httpx.Client, url: str) -> list[tuple[str, str]]:
    """作品のページから (題, 曲の URL) を並び順に返す。"""
    r = client.get(BASE + url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    m = re.search(r'data-tralbum="(.*?)"', r.text, re.S)
    if not m:
        return []
    d = json.loads(H.unescape(m.group(1)))
    out = []
    for t in d.get("trackinfo") or []:
        link = t.get("title_link") or ""
        if not link.startswith("/"):
            continue
        out.append((_title(t.get("title") or ""), BASE + link))
    return out


def main() -> int:
    dry = "--dry" in sys.argv
    head = {"User-Agent": "trackmento own-tracks builder (https://trackmento.onrender.com/)"}
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    with httpx.Client(headers=head) as c:
        r = c.get(PAGE, timeout=30, follow_redirects=True)
        r.raise_for_status()
        rel = [x for x in _releases(r.text)
               if x["url"].startswith("/") and x["artist"].lower().startswith(KEEP)]
        # 同じ作品が一覧に 2 度出ることがある（静的なぶんと data-client-items）
        rel = list({x["url"]: x for x in rel}.values())
        print(f"作品 {len(rel)} 件")
        for i, x in enumerate(rel, 1):
            try:
                got = _tracks(c, x["url"])
            except Exception as e:
                print(f"  ! {x['url']}: {type(e).__name__}")
                continue
            new = 0
            for title, url in got:
                if not title or url in seen:
                    continue
                seen.add(url)
                rows.append((title, url))
                new += 1
            print(f"  {i:2d}/{len(rel)} {x['url']}  {len(got)} 曲（新しく {new}）")
            time.sleep(WAIT)
    if not rows:
        print("1 曲も取れませんでした（ページの作りが変わった可能性）")
        return 1
    rows.sort(key=lambda x: x[0])
    left = [t for t, _ in rows if not _has_ja(t) and t not in JA.values()]
    print(f"\n合計 {len(rows)} 曲。日本語でないもの {len(left)} 件（読み替えを足すならこれ）:")
    for t in left:
        print(f"  {t}")
    if dry:
        return 0
    body = "\n".join(f'    [{json.dumps(t, ensure_ascii=False)}, {json.dumps(u)}],' for t, u in rows)
    p = ROOT / "frontend" / "index.html"
    s = p.read_text(encoding="utf-8", newline="")
    nl = "\r\n" if "\r\n" in s else "\n"
    a = s.index(BEGIN.replace("\n", nl))
    b = s.index(END.replace("\n", nl), a)
    s = s[:a] + BEGIN + nl + body.replace("\n", nl) + nl + END + s[b + len(END):]
    p.write_text(s, encoding="utf-8", newline="")
    print("frontend/index.html を書き換えました（フォントの作り直しを忘れずに）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
