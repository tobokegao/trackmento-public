"""「トラックを共有」。その時点の並びを PNG と JSON のスナップショットとして shares/<id>.{png,json} に保存し、
共有 URL（/s/<id>）で PNG・曲リスト・「TRACKMENTO で開く」（/?share=<id>）をまとめて見られるようにする。

- id は内容のハッシュ 6 桁 + 時刻 4 桁 + 乱数 2 桁（同じ並びでも押すたびに別 id。過去の共有は消えない）
- outputs/ と違って世代管理で消さない（共有 URL が死なないように）
"""
from __future__ import annotations

import hashlib
import html
import secrets
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import io

from PIL import Image

from backend import render, storage
from backend.config import public_mode
from backend.grids import GridDoc

ROOT = Path(__file__).resolve().parent.parent
SHARES = ROOT / "shares"
ID_RE = re.compile(r"^[a-z0-9]{6,16}$")


def _new_id(doc: GridDoc) -> str:
    body = json.dumps(doc.model_dump(exclude={"savedAt", "name"}), ensure_ascii=False, sort_keys=True)
    h = hashlib.sha1(body.encode("utf-8")).hexdigest()[:6]
    t = format(int(time.time()) % (36 ** 4), "x")[-4:].rjust(4, "0")
    r = secrets.token_hex(1)   # 同じ内容を同じ秒に共有しても別 ID になるように
    return f"{h}{t}{r}"


OG_W, OG_H = 1200, 630            # リンクカード（X の summary_large_image、Discord・LINE も同じ 1.91:1）
MAX_PNG_BYTES = 4_900_000         # X の画像添付は 5 MB まで。公開モードではこれに収まるまで縮小する


def _encode_png(im: Image.Image, limit: int) -> tuple[bytes, Image.Image]:
    """PNG に書き出す。limit > 0 で超えるときは、収まるまで（最大 4 回）縮小して書き直す。"""
    for _ in range(4):
        buf = io.BytesIO()
        im.save(buf, "PNG", compress_level=6)
        png = buf.getvalue()
        if not limit or len(png) <= limit:
            return png, im
        f = max(0.6, (limit / len(png)) ** 0.5 * 0.97)   # PNG の容量は概ね画素数に比例
        im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.LANCZOS)
    return png, im


def _og_jpeg(im: Image.Image, bg: tuple[int, int, int]) -> bytes:
    """カード用の 1200×630 JPEG。全体を収め、余白は背景色（切り取らない）。"""
    canvas = Image.new("RGB", (OG_W, OG_H), bg)
    f = min(OG_W / im.width, OG_H / im.height)
    w, h = max(1, round(im.width * f)), max(1, round(im.height * f))
    canvas.paste(im.resize((w, h), Image.LANCZOS), ((OG_W - w) // 2, (OG_H - h) // 2))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=85, optimize=True, progressive=True)
    return buf.getvalue()


def og_url(sid: str) -> str:
    return storage.get_storage().public_url(f"{sid}-og.jpg") or f"/shares/{sid}-og.jpg"


def png_url(sid: str) -> str:
    """PNG の URL。R2 の公開 URL があればそれ（絶対 URL）、無ければバックエンドの /shares/<id>.png（相対）。"""
    return storage.get_storage().public_url(f"{sid}.png") or f"/shares/{sid}.png"


class BudgetExceeded(Exception):
    def __init__(self, used: int, budget: int, need: int):
        super().__init__(f"共有の保存容量が上限に達しています（使用 {used / 1024**3:.2f} GB / 上限 {budget / 1024**3:.2f} GB）。古い共有が期限切れで消えるまでお待ちください")
        self.used, self.budget, self.need = used, budget, need


def create(doc: GridDoc, budget: int = 0) -> dict:
    """PNG と JSON を保存（ローカルの shares/ か Cloudflare R2）して {id, png, json, width, height, bytes} を返す。
    png は公開 URL があれば絶対 URL、無ければ /shares/... の相対 URL。
    budget > 0 のときは、保存後の合計がそれを超えるなら保存せず BudgetExceeded を投げる（実バイト数で判定）。"""
    im = render.render(doc)
    o = doc.options
    bg = render._hex_to_rgb(o.bgCustom if o.bg == "custom" and o.bgCustom else render.TOKENS[o.bg])
    og = _og_jpeg(im, bg)
    png, im = _encode_png(im, MAX_PNG_BYTES if public_mode() else 0)
    return store(doc, png, og, im.width, im.height, budget)


def store(doc: GridDoc, png: bytes, og: bytes, width: int, height: int, budget: int = 0) -> dict:
    """描画済みの PNG（本体）とカード用 JPEG を保存する。ブラウザで描いたものもサーバーで描いたものもここを通る。"""
    st = storage.get_storage()
    sid = _new_id(doc)
    # name はブラウザごとの固有 ID（u-…）。公開 JSON に載せると同じ人の共有を突き合わせたり、そのグリッドを読み書きされたりするので外す
    snap = doc.model_dump(exclude={"name", "savedAt"})
    snap.update({"id": sid, "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                 "og": True})   # カード用 JPEG がある印（古い共有には無い）
    js = json.dumps(snap, ensure_ascii=False, indent=2).encode("utf-8")
    need = len(png) + len(js) + len(og)
    if budget > 0:
        used = storage.usage_bytes()
        if used + need > budget:
            used = storage.usage_bytes(refresh=True)   # キャッシュが古い可能性があるので取り直してから最終判断
            if used + need > budget:
                raise BudgetExceeded(used, budget, need)
    st.put(f"{sid}.png", png, "image/png")
    st.put(f"{sid}-og.jpg", og, "image/jpeg")
    st.put(f"{sid}.json", js, "application/json")
    storage.add_usage(need)
    return {"id": sid, "png": png_url(sid), "og": og_url(sid), "json": f"/shares/{sid}.json", "width": width, "height": height, "bytes": need}


MAX_UPLOAD_PNG = MAX_PNG_BYTES + 200_000   # ブラウザ側の縮小判定の誤差ぶんだけ許す
MAX_UPLOAD_OG = 600_000
MAX_UPLOAD_SIDE = 4096


def check_uploaded(png: bytes, og: bytes) -> tuple[int, int]:
    """ブラウザが描いた PNG / JPEG のヘッダだけ確かめる（デコードはしない。CPU を使わないのがこの経路の目的）。
    (幅, 高さ) を返す。不正なら ValueError。"""
    if not png or len(png) > MAX_UPLOAD_PNG:
        raise ValueError(f"PNG が空か大きすぎます（{len(png) / 1e6:.1f} MB）")
    if not og or len(og) > MAX_UPLOAD_OG:
        raise ValueError("カード用の JPEG が空か大きすぎます")
    try:
        with Image.open(io.BytesIO(png)) as im:
            if im.format != "PNG":
                raise ValueError("本体が PNG ではありません")
            w, h = im.size
        with Image.open(io.BytesIO(og)) as im2:
            if im2.format != "JPEG" or im2.size != (OG_W, OG_H):
                raise ValueError("カード用の画像が 1200×630 の JPEG ではありません")
    except Image.UnidentifiedImageError as e:
        raise ValueError("画像として読めません") from e
    if not (100 <= w <= MAX_UPLOAD_SIDE and 100 <= h <= MAX_UPLOAD_SIDE):
        raise ValueError(f"PNG の大きさが範囲外です（{w}×{h}）")
    return w, h


def get_png(sid: str) -> bytes | None:
    return storage.get_storage().get(f"{sid}.png") if valid_id(sid) else None


def valid_id(sid: str) -> bool:
    return bool(ID_RE.match(sid or ""))


def load(sid: str) -> dict | None:
    if not valid_id(sid):
        return None
    raw = storage.get_storage().get(f"{sid}.json")
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def page_html(snap: dict, base: str, app_url: str | None = None) -> str:
    """共有ページ。依存なしの単一 HTML（スマホのブラウザで開く前提）。"""
    sid = snap["id"]
    app_url = (app_url or base).rstrip("/")
    img_url = png_url(sid)   # R2 の公開 URL があればそこから直接（サーバーの転送量を節約）
    if img_url.startswith("/"):
        img_url = base + img_url
    # カード画像は 1200×630 の JPEG（X は 5 MB 超・2:1 以外を切り取るので PNG 本体は使わない）。古い共有は PNG のまま
    card_url = og_url(sid) if snap.get("og") else img_url
    if card_url.startswith("/"):
        card_url = base + card_url
    card_meta = ('<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:type" content="image/jpeg">'
                 if snap.get("og") else "")
    title = html.escape(snap.get("title") or "TRACKMENTO")
    rows = []
    for i, c in enumerate(snap.get("cells") or [], 1):
        if c:
            rows.append(f"<li><span class=n>{i:02d}</span><span class=t><b>{html.escape(c.get('title') or '')}</b> <span class=a>{html.escape(c.get('artist') or '')}</span></span></li>")
    n = len(rows)
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — TRACKMENTO</title>
<link rel="icon" href="/favicon.ico"><link rel="icon" type="image/png" href="/favicon.png" sizes="64x64"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="robots" content="noindex">
<meta property="og:title" content="{title}"><meta property="og:image" content="{card_url}">{card_meta}<meta name="twitter:image" content="{card_url}">
<meta property="og:description" content="トラック共有サイト #TRACKMENTO からシェア:「{html.escape(snap.get('title') or '無題')}」"><meta name="twitter:card" content="summary_large_image">
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
/* 曲名とアーティスト名は 1 つの流し込み。別々の flex 項目にすると狭い画面でアーティスト名だけ細長く折り返る */
.t {{ min-width: 0; overflow-wrap: anywhere; }}
.n {{ font-family: "Silkscreen", monospace; font-size: .7rem; color: #53595f; }}
.a {{ color: #53595f; }}
p.meta {{ margin: 0; color: #53595f; font-size: .85rem; overflow-wrap: anywhere; }}
p.meta a {{ color: #12171b; }}
</style></head>
<body>
<header><span class="mark">TRACKMENTO</span><small>share</small></header>
<main>
  <h1>{title}</h1>
  <img src="{img_url}" alt="{title}">
  <div class="btns">
    <a class="btn primary" href="/shares/{sid}.png" download="{html.escape((snap.get('title') or 'trackmento').replace('/', '_'))}.png">PNG を保存</a>
    <a class="btn" href="{app_url}/?share={sid}">TRACKMENTO で開く（この並びを読み込む）</a>
  </div>
  <ol>{''.join(rows)}</ol>
  <p class="meta">{n} 曲 · {snap.get('cols')}×{snap.get('rows')} · 共有 ID {sid} · {html.escape(snap.get('createdAt') or '')}</p>
  <p class="meta">この URL: {base}/s/{sid}</p>
  <p class="meta">連絡先: <a href="https://tobokegao.github.io/ja/about/" target="_blank" rel="noopener">Tobokegao</a></p>
</main>
</body></html>"""
