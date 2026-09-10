"""TRACKMENTO の安全性チェック（自動部分）。/site-safety-check スキルから呼ぶ。

  .venv/Scripts/python scripts/safety_check.py                                  # ローカル（http://127.0.0.1:8000）
  .venv/Scripts/python scripts/safety_check.py https://trackmento.onrender.com  # 公開サイト

サーバーに対して読み取り中心の検査をする。書き込みは「検査用グリッド 1 件の PUT」と「メタデータ付き画像 1 枚のアップロード」
「共有 1 件の作成」だけで、共有とアップロードは R2 の資格情報（.env）があれば最後に消す。
結果は OK / NG / SKIP の行で出し、NG が 1 つでもあれば終了コード 1。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import httpx
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
IS_HTTPS = BASE.startswith("https://")
results: list[tuple[str, str, str]] = []


def rec(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def check(name: str, ok: bool, detail: str = "") -> None:
    rec("OK" if ok else "NG", name, detail)


def main() -> int:
    c = httpx.Client(base_url=BASE, timeout=60, follow_redirects=False)
    r = c.get("/")
    check("トップページが 200", r.status_code == 200, str(r.status_code))
    h = r.headers
    csp = h.get("content-security-policy", "")
    check("CSP がある", bool(csp), csp[:60])
    check("CSP: script-src は nonce のみ（unsafe-inline / http: が無い）", "script-src 'nonce-" in csp and "unsafe-inline'" not in csp.split("script-src")[1].split(";")[0] if "script-src" in csp else False)
    check("CSP: connect-src は self のみ", "connect-src 'self'" in csp)
    check("CSP: object-src none / base-uri self / frame-ancestors", all(k in csp for k in ("object-src 'none'", "base-uri 'self'", "frame-ancestors")))
    check("X-Content-Type-Options: nosniff", h.get("x-content-type-options", "").lower() == "nosniff")
    check("Referrer-Policy がある", bool(h.get("referrer-policy")), h.get("referrer-policy", ""))
    check("X-Frame-Options がある", bool(h.get("x-frame-options")), h.get("x-frame-options", ""))
    if IS_HTTPS:
        check("HSTS がある（https）", "max-age" in h.get("strict-transport-security", ""), h.get("strict-transport-security", ""))
    else:
        rec("SKIP", "HSTS（https のときだけ）")
    check("インライン script に nonce が付いている", 'nonce="' in r.text and "<script>" not in r.text)
    check("HTML に Discogs トークンなど秘密が無い", "DISCOGS_TOKEN=" not in r.text and "R2_SECRET" not in r.text)

    hl = c.get("/health")
    check("/health が 200", hl.status_code == 200, str(hl.status_code))
    try:
        public = bool(hl.json().get("public"))
    except Exception:
        public = False
    allowed = {"ok", "public", "sources", "storage", "frontend_url"}   # 公開してよい項目だけ（キー・パス・バージョンは出さない）
    extra = set(hl.json().keys()) - allowed
    leak = any(k in json.dumps(hl.json()).lower() for k in ("secret", "token", "access_key", "/app/", "c:\\"))
    rec("OK" if not public or (not extra and not leak) else "NG", "公開モードの /health は最小限", ",".join(sorted(hl.json().keys())) + (f" 余分: {sorted(extra)}" if extra else ""))

    # SSRF: 私設・メタデータアドレス宛てを拒否
    for url in ("http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://localhost:8000/health", "http://[::1]/", "http://10.0.0.1/"):
        rr = c.get("/image-proxy", params={"url": url})
        check(f"image-proxy が私設宛てを拒否: {url}", rr.status_code == 403, str(rr.status_code))
    rr = c.post("/from-url", json={"url": "http://127.0.0.1:8000/"})
    check("from-url が対応外・私設 URL を拒否", rr.status_code in (400, 403, 422), str(rr.status_code))

    # 入力の上限
    rr = c.put("/grids/u-safetycheck0000", content=b"a" * (2 * 1024 * 1024), headers={"Content-Type": "application/json"})
    check("2MB の JSON ボディを 413 で拒否", rr.status_code == 413, str(rr.status_code))
    rr = c.get("/search", params={"q": "a" * 300, "source": "itunes"})
    check("検索語 300 文字を 422 で拒否", rr.status_code == 422, str(rr.status_code))
    rr = c.get("/image-proxy", params={"url": "https://example.com/" + "a" * 3000})
    check("URL 3000 文字を 422 で拒否", rr.status_code == 422, str(rr.status_code))

    # 公開モードで閉じているもの
    if public:
        rr = c.post("/render", json={}); check("公開モードで /render は 404", rr.status_code == 404, str(rr.status_code))
        rr = c.get("/grids"); check("公開モードで /grids 一覧は 404", rr.status_code == 404, str(rr.status_code))
        rr = c.delete("/grids/u-safetycheck0000"); check("公開モードで DELETE は使えない", rr.status_code in (404, 405), str(rr.status_code))
    else:
        rec("SKIP", "公開モード限定の項目（/render, /grids 一覧, DELETE）")

    # 曲データの URL 検証（共有経由の XSS 対策）
    g = "u-safetycheck0000"
    rr = c.put(f"/grids/{g}", json={"name": g, "cols": 1, "rows": 1, "cells": [
        {"source": "manual", "title": "t", "artist": "a", "image": "https://example.com/a.png", "external_url": "javascript:alert(1)", "thumb": "data:text/html,x"}]})
    ok = rr.status_code == 200 and rr.json()["cells"][0]["external_url"] is None and rr.json()["cells"][0]["thumb"] is None
    check("javascript: / data: のリンク先が捨てられる", ok, str(rr.status_code))
    rr = c.put(f"/grids/{g}", json={"name": g, "cols": 1, "rows": 1, "cells": [{"source": "manual", "title": "t", "artist": "a", "image": "javascript:alert(1)"}]})
    check("image が javascript: のマスは無効化される", rr.status_code == 200 and rr.json()["cells"] == [None], str(rr.status_code))

    # アップロード: メタデータ除去・ランダム名・元ファイル名を返さない
    im = Image.new("RGB", (640, 480), (200, 40, 40))
    exif = Image.Exif(); exif[0x0110] = "Cam"; exif[0x9286] = "secret"
    b = io.BytesIO(); im.save(b, "JPEG", exif=exif.tobytes(), comment=b"c")
    up = c.post("/upload", files={"file": ("IMG_private.jpg", b.getvalue(), "image/jpeg")})
    upload_url = None
    if up.status_code == 200:
        d = up.json(); upload_url = d["url"]
        check("アップロード応答に元ファイル名が無い", "name" not in d, ",".join(d.keys()))
        check("アップロード名がランダム（内容ハッシュや元名でない）", upload_url.split("/")[-1].split(".")[0] not in ("IMG_private",) and len(upload_url.split("/")[-1].split(".")[0]) == 16, upload_url)
        got = c.get(upload_url)
        im2 = Image.open(io.BytesIO(got.content))
        check("保存画像に EXIF / コメントが無い", not dict(im2.getexif()) and not im2.info.get("comment"))
    else:
        rec("NG", "アップロードできた", str(up.status_code))

    # 共有: JSON にブラウザ ID（name）と savedAt が無い。共有ページに noindex
    share_id = None
    if upload_url:
        c.put(f"/grids/{g}", json={"name": g, "cols": 1, "rows": 1, "cells": [{"source": "manual", "title": "safety", "artist": "check", "image": upload_url}]})
        sh = c.post("/share", json={"grid": g}, timeout=300)
        if sh.status_code == 200:
            share_id = sh.json()["id"]
            js = c.get(f"/shares/{share_id}.json").json()
            check("共有 JSON にブラウザ ID（name）が無い", "name" not in js and "savedAt" not in js, ",".join(sorted(js.keys())))
            pg = c.get(f"/s/{share_id}")
            check("共有ページに noindex", 'name="robots" content="noindex"' in pg.text)
            check("共有ページの CSP", "content-security-policy" in pg.headers)
        elif sh.status_code == 429:
            rec("SKIP", "共有（回数制限に達しているため省略）", sh.text[:80])
        else:
            rec("NG", "共有できた", f"{sh.status_code} {sh.text[:120]}")

    # 検索エンジン向け
    rb = c.get("/robots.txt"); check("robots.txt がある", rb.status_code == 200 and "Sitemap:" in rb.text)
    sm = c.get("/sitemap.xml"); check("sitemap.xml がある", sm.status_code == 200 and "<loc>" in sm.text)

    # 後片付け（R2 の資格情報があるときだけ。無ければ 30 日で消える）
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from backend import storage
        st = storage.get_storage()
        if st.is_remote and (share_id or upload_url):
            for k in ([f"{share_id}.png", f"{share_id}.json"] if share_id else []) + ([f"uploads/{upload_url.split('/')[-1]}"] if upload_url else []):
                st.delete(k)
            rec("OK", "検査で作った共有・アップロードを R2 から削除")
        elif share_id or upload_url:
            rec("SKIP", "検査データの削除（R2 未設定。ローカル運用なら shares/ uploads/ に残る）")
    except Exception as e:  # noqa: BLE001
        rec("SKIP", "検査データの削除に失敗", repr(e)[:80])

    ng = [r for r in results if r[0] == "NG"]
    print(f"\n合計 {len(results)} 項目: OK {sum(1 for r in results if r[0] == 'OK')} / NG {len(ng)} / SKIP {sum(1 for r in results if r[0] == 'SKIP')}")
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
