"""「トラックを共有」。その時点の並びを PNG と JSON のスナップショットとして shares/<id>.{png,json} に保存し、
共有 URL（/s/<id>）で PNG・曲リスト・「TRACKMENTO で開く」（/?share=<id>）をまとめて見られるようにする。

- id は内容のハッシュ 6 桁 + 時刻 4 桁（同じ並びでも押すたびに別 id。過去の共有は消えない）
- outputs/ と違って世代管理で消さない（共有 URL が死なないように）
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from backend import render
from backend.grids import GridDoc

ROOT = Path(__file__).resolve().parent.parent
SHARES = ROOT / "shares"
ID_RE = re.compile(r"^[a-z0-9]{6,16}$")


def _new_id(doc: GridDoc) -> str:
    body = json.dumps(doc.model_dump(exclude={"savedAt", "name"}), ensure_ascii=False, sort_keys=True)
    h = hashlib.sha1(body.encode("utf-8")).hexdigest()[:6]
    t = format(int(time.time()) % (36 ** 4), "x")[-4:].rjust(4, "0")
    return f"{h}{t}"


def create(doc: GridDoc) -> dict:
    """PNG と JSON を保存して {id, png, json, width, height} を返す（パスは /shares/... の相対 URL）。"""
    SHARES.mkdir(exist_ok=True)
    sid = _new_id(doc)
    im = render.render(doc)
    im.save(SHARES / f"{sid}.png", "PNG", optimize=True)
    snap = doc.model_dump()
    snap.update({"id": sid, "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")})
    (SHARES / f"{sid}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": sid, "png": f"/shares/{sid}.png", "json": f"/shares/{sid}.json", "width": im.width, "height": im.height}


def valid_id(sid: str) -> bool:
    return bool(ID_RE.match(sid or ""))


def load(sid: str) -> dict | None:
    if not valid_id(sid):
        return None
    p = SHARES / f"{sid}.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def page_html(snap: dict, base: str, app_url: str | None = None) -> str:
    """共有ページ。依存なしの単一 HTML（スマホのブラウザで開く前提）。"""
    sid = snap["id"]
    app_url = (app_url or base).rstrip("/")
    title = html.escape(snap.get("title") or "TRACKMENTO")
    rows = []
    for i, c in enumerate(snap.get("cells") or [], 1):
        if c:
            rows.append(f"<li><span class=n>{i:02d}</span><b>{html.escape(c.get('title') or '')}</b> <span class=a>{html.escape(c.get('artist') or '')}</span></li>")
    n = len(rows)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — TRACKMENTO</title>
<meta property="og:title" content="{title}"><meta property="og:image" content="{base}/shares/{sid}.png">
<style>
@font-face {{ font-family: "IBM Plex Sans JP"; font-weight: 400; src: url("{base}/fonts/IBMPlexSansJP-Regular.ttf") format("truetype"); }}
@font-face {{ font-family: "IBM Plex Sans JP"; font-weight: 700; src: url("{base}/fonts/IBMPlexSansJP-Bold.ttf") format("truetype"); }}
@font-face {{ font-family: "Silkscreen"; font-weight: 700; src: url("{base}/fonts/Silkscreen-Bold.ttf") format("truetype"); }}
@font-face {{ font-family: "DotGothic16"; src: url("{base}/fonts/DotGothic16-Regular.ttf") format("truetype"); }}
* {{ box-sizing: border-box; border-radius: 0; }}
body {{ margin: 0; background: #f6f5f3; color: #12171b; font-family: "IBM Plex Sans JP", sans-serif; line-height: 1.55; }}
header {{ display: flex; align-items: baseline; gap: 8px; padding: 10px 16px; border-bottom: 2px solid #12171b; }}
.mark {{ font-family: "Silkscreen", monospace; font-weight: 700; font-size: 20px; letter-spacing: .04em; padding-bottom: 10px;
  background: linear-gradient(to right, #e6b731 0 16.66%, #008bc7 0 33.33%, #e5462c 0 50%, #af9ee4 0 66.66%, #80e2b9 0 83.33%, #f594c3 0) bottom / 100% 5px no-repeat; }}
small {{ font-family: "DotGothic16", sans-serif; color: #53595f; }}
main {{ max-width: 56rem; margin: 0 auto; padding: 16px; display: grid; gap: 16px; }}
h1 {{ font-family: "DotGothic16", sans-serif; font-weight: 400; font-size: 1.25rem; margin: 0; }}
img {{ max-width: 100%; height: auto; display: block; border: 2px solid #12171b; }}
.btns {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.btn {{ display: inline-flex; align-items: center; min-height: 44px; padding: 4px 16px; border: 2px solid #12171b; background: #f6f5f3; color: #12171b;
  font-family: "DotGothic16", sans-serif; text-decoration: none; box-shadow: 2px 2px 0 #12171b; }}
.btn.primary {{ background: #12171b; color: #f6f5f3; }}
ol {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }}
li {{ display: flex; gap: 10px; align-items: baseline; }}
.n {{ font-family: "Silkscreen", monospace; font-size: .7rem; color: #53595f; }}
.a {{ color: #53595f; }}
p.meta {{ margin: 0; color: #53595f; font-size: .85rem; overflow-wrap: anywhere; }}
</style></head>
<body>
<header><span class="mark">TRACKMENTO</span><small>share</small></header>
<main>
  <h1>{title}</h1>
  <img src="/shares/{sid}.png" alt="{title}">
  <div class="btns">
    <a class="btn primary" href="/shares/{sid}.png" download="{html.escape((snap.get('title') or 'trackmento').replace('/', '_'))}.png">PNG を保存</a>
    <a class="btn" href="{app_url}/?share={sid}">TRACKMENTO で開く（この並びを読み込む）</a>
  </div>
  <ol>{''.join(rows)}</ol>
  <p class="meta">{n} 曲 · {snap.get('cols')}×{snap.get('rows')} · 共有 ID {sid} · {html.escape(snap.get('createdAt') or '')}</p>
  <p class="meta">この URL: {base}/s/{sid}</p>
</main>
</body></html>"""
