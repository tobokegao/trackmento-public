"""「トラックを共有」。その時点の並びを画像（JPEG。古い共有は PNG）と JSON のスナップショットとして
shares/<id>.{jpg,json} に保存し、共有 URL（/s/<id>）で画像・曲リスト・「TRACKMENTO で開く」（/?share=<id>）をまとめて見られるようにする。

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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import io

from PIL import Image

from backend import names, render, shareindex, storage
from backend.config import public_mode, share_retention_days
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
MAX_IMAGE_BYTES = 4_900_000       # X の画像添付は 5 MB まで。公開モードではこれに収まるまで縮小する
MAX_PNG_BYTES = MAX_IMAGE_BYTES   # 旧名
IMAGE_EXT = "jpg"                 # 本体は JPEG（品質 90、色差は間引かない）。PNG の 1/6 程度で、X は投稿時に再圧縮するので見た目は変わらない
JPEG_QUALITY = 78   # ブラウザ側の encodeShare と同じ。90 → 82（-17%）→ 78（2026-09-19、送信の時間を縮めるため）


def _encode_image(im: Image.Image, limit: int) -> tuple[bytes, Image.Image]:
    """JPEG に書き出す。limit > 0 で超えるときは、収まるまで（最大 4 回）縮小して書き直す。"""
    for _ in range(4):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=JPEG_QUALITY, subsampling=0, optimize=True, progressive=True)
        data = buf.getvalue()
        if not limit or len(data) <= limit:
            return data, im
        f = max(0.6, (limit / len(data)) ** 0.5 * 0.97)   # 容量は概ね画素数に比例
        im = im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.LANCZOS)
    return data, im


OG_SAFE = 0.94   # カードの中で画像が占める割合。残りは余白（下の説明を参照）


def _bg_rgb(o) -> tuple[int, int, int]:
    """並びの背景色を (r, g, b) で返す。**サーバー描画とアップロードの両方から使う**ので 1 か所にまとめる。"""
    return render._hex_to_rgb(o.bgCustom if o.bg == "custom" and o.bgCustom else render.TOKENS[o.bg])


def _og_jpeg(im: Image.Image, bg: tuple[int, int, int]) -> bytes:
    """カード用の 1200×630 JPEG。全体を収め、余白は背景色（切り取らない）。

    **四辺に 3% ずつ安全代を残す**。1200×630 は X の summary_large_image に合わせた比率だが、
    受け取る側（X の表示位置、Discord、LINE、スマホの幅）で数 % 切られることがあり、
    いっぱいに収めると端のマスや曲名が欠ける。
    """
    canvas = Image.new("RGB", (OG_W, OG_H), bg)
    f = min(OG_W * OG_SAFE / im.width, OG_H * OG_SAFE / im.height)
    w, h = max(1, round(im.width * f)), max(1, round(im.height * f))
    canvas.paste(im.resize((w, h), Image.LANCZOS), ((OG_W - w) // 2, (OG_H - h) // 2))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=85, optimize=True, progressive=True)
    return buf.getvalue()


def og_url(sid: str) -> str:
    return storage.get_storage().public_url(f"{sid}-og.jpg") or f"/shares/{sid}-og.jpg"


def image_url(sid: str, ext: str = IMAGE_EXT) -> str:
    """本体画像の URL。R2 の公開 URL があればそれ（絶対 URL）、無ければバックエンドの /shares/<id>.<ext>（相対）。"""
    return storage.get_storage().public_url(f"{sid}.{ext}") or f"/shares/{sid}.{ext}"


def png_url(sid: str) -> str:
    return image_url(sid, "png")


class BudgetExceeded(Exception):
    def __init__(self, used: int, budget: int, need: int):
        super().__init__(f"共有の保存容量が上限に達しています（使用 {used / 1024**3:.2f} GB / 上限 {budget / 1024**3:.2f} GB）。古い共有が期限切れで消えるまでお待ちください")
        self.used, self.budget, self.need = used, budget, need


def create(doc: GridDoc, budget: int = 0) -> dict:
    """画像と JSON を保存（ローカルの shares/ か Cloudflare R2）して {id, image, json, width, height, bytes} を返す。
    image は公開 URL があれば絶対 URL、無ければ /shares/... の相対 URL。
    budget > 0 のときは、保存後の合計がそれを超えるなら保存せず BudgetExceeded を投げる（実バイト数で判定）。"""
    im = render.render(doc)
    o = doc.options
    og = _og_jpeg(im, _bg_rgb(o))
    data, im = _encode_image(im, MAX_IMAGE_BYTES if public_mode() else 0)
    return store(doc, data, og, im.width, im.height, budget, IMAGE_EXT)




def _check_budget(need: int, budget: int) -> None:
    """保存後の合計が budget を超えるなら BudgetExceeded。**覚えている使用量だけで判断し、一覧は回さない**
    （`storage.usage_cached`。数え直しは裏で 10 分ごと）。まだ一度も数えていない起動直後は通す
    （上限は保存容量の歯止めで、数分の遅れは問題にならない。待たせるほうが実害が大きい）"""
    used = storage.usage_cached()
    if used is None or used + need <= budget:
        return
    print(f"[share] budget: 使用 {used / 1024**3:.2f} GB / 上限 {budget / 1024**3:.2f} GB → 507")
    raise BudgetExceeded(used, budget, need)


def store(doc: GridDoc, image: bytes, og: bytes | None, width: int, height: int,
          budget: int = 0, ext: str = IMAGE_EXT) -> dict:
    """描画済みの本体画像（JPEG。古いブラウザのタブからは PNG）とカード用 JPEG を保存する。
    ブラウザで描いたものもサーバーで描いたものもここを通る。

    **`og` が `None` なら本体から作る**（実測 57ms）。ブラウザから送らせないぶん、
    上りが 2 割軽くなる。カードは 1200×630 に縮めるので、本体が一度 JPEG になっていても見分けはつかない。
    """
    if og is None:
        with Image.open(io.BytesIO(image)) as im:
            og = _og_jpeg(im.convert("RGB"), _bg_rgb(doc.options))
    st = storage.get_storage()
    sid = _new_id(doc)
    # name はブラウザごとの固有 ID（u-…）。公開 JSON に載せると同じ人の共有を突き合わせたり、そのグリッドを読み書きされたりするので外す
    snap = doc.model_dump(exclude={"name", "savedAt"})
    # **あとから自分で外す・消すための鍵**（2026-09-26、利用者の案）。鍵そのものは共有した端末にだけ返し、
    # 並びの JSON には SHA-256 だけを置く（JSON は誰でも読めるが、144 ビットの乱数のハッシュからは戻せない）
    owner_key = secrets.token_urlsafe(18)
    snap.update({"id": sid, "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                 "og": True,    # カード用 JPEG がある印（古い共有には無い）
                 "ext": ext,    # 本体画像の拡張子（無ければ png）
                 "ownerKeyHash": _key_hash(owner_key)})
    js = json.dumps(snap, ensure_ascii=False, indent=2).encode("utf-8")
    need = len(image) + len(js) + len(og)
    if budget > 0:
        _check_budget(need, budget)
    st.put(f"{sid}.{ext}", image, "image/jpeg" if ext == "jpg" else "image/png")
    st.put(f"{sid}-og.jpg", og, "image/jpeg")
    st.put(f"{sid}.json", js, "application/json;charset=utf-8")   # charset なしだと端末によっては文字化けして開かれる
    storage.add_usage(need)
    # **「みんなの並びから探せるようにする」に印が付いているときだけ**索引に載せる（既定はオフ）。
    # 印の無い共有は 1 件も載らない
    if getattr(doc, "listed", False):
        shareindex.add(snap)
    url = image_url(sid, ext)
    return {"id": sid, "image": url, "png": url, "ext": ext, "og": og_url(sid), "json": f"/shares/{sid}.json",
            "width": width, "height": height, "bytes": need,   # png は旧キー（古いタブ・CLI 互換）
            "ownerKey": owner_key, "listed": bool(getattr(doc, "listed", False))}


MAX_UPLOAD_IMAGE = MAX_IMAGE_BYTES + 200_000   # ブラウザ側の縮小判定の誤差ぶんだけ許す
MAX_UPLOAD_PNG = MAX_UPLOAD_IMAGE
MAX_UPLOAD_OG = 600_000
MAX_UPLOAD_SIDE = 4096


def check_uploaded(image: bytes, og: bytes | None = None) -> tuple[int, int, str]:
    """ブラウザが描いた本体（JPEG か PNG）のヘッダだけ確かめる。(幅, 高さ, 拡張子) を返す。不正なら ValueError。

    **カード用の JPEG は送られてこないのがふつう**（2026-09-16 から、本体だけ送って
    カードはサーバーで作る。送るバイトが 2 割減り、上りの細い端末の待ち時間が縮む）。
    ただし**開いたままの古いタブは今までどおり送ってくる**ので、来たときは確かめて使う。
    """
    if not image or len(image) > MAX_UPLOAD_IMAGE:
        raise ValueError(f"画像が空か大きすぎます（{len(image) / 1e6:.1f} MB）")
    if og is not None and (not og or len(og) > MAX_UPLOAD_OG):
        raise ValueError("カード用の JPEG が空か大きすぎます")
    try:
        with Image.open(io.BytesIO(image)) as im:
            if im.format not in ("JPEG", "PNG"):
                raise ValueError("本体が JPEG でも PNG でもありません")
            w, h = im.size
            ext = "jpg" if im.format == "JPEG" else "png"
        if og is not None:
            with Image.open(io.BytesIO(og)) as im2:
                if im2.format != "JPEG" or im2.size != (OG_W, OG_H):
                    raise ValueError("カード用の画像が 1200×630 の JPEG ではありません")
    except Image.UnidentifiedImageError as e:
        raise ValueError("画像として読めません") from e
    if not (100 <= w <= MAX_UPLOAD_SIDE and 100 <= h <= MAX_UPLOAD_SIDE):
        raise ValueError(f"画像の大きさが範囲外です（{w}×{h}）")
    return w, h, ext


def count_today() -> int:
    """今日（UTC）保存した共有の数。本体画像（.jpg / .png、カード用 -og.jpg を除く）を数える。
    起動時に 1 日の回数カウンタをここから復元する（プロセス内カウンタはデプロイ・再起動で 0 に戻るため）。

    **数えるのはバケットの直下（キーに `/` を含まないもの）だけ**（2026-09-17）。同じバケットには
    画像キャッシュ（`imgcache/`）とアップロード画像（`uploads/`）の .jpg / .png も入っていて、以前は
    それも数えていた。9/16（UTC）は共有 2,806 件に対して「42,410 件」と出ており、1 日の上限
    （`SHARE_LIMIT_PER_DAY`）を入れるとキャッシュの数で上限に当たって共有が止まる（9/15 の 3,788 件で 429 もこれ）"""
    today = datetime.now(timezone.utc).date()
    n = 0
    for key, _, modified in storage.get_storage().list_objects():
        if "/" in key:
            continue
        if modified.date() == today and (key.endswith(".jpg") or key.endswith(".png")) and not key.endswith("-og.jpg"):
            n += 1
    return n


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


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class NotOwner(Exception):
    """鍵が合わない・鍵の無い古い共有（2026-09-26 より前）。"""


def _owned(sid: str, key: str) -> dict:
    """共有を読み、鍵が合えばそのスナップショットを返す。共有が無ければ FileNotFoundError、鍵が合わなければ NotOwner。"""
    snap = load(sid)
    if snap is None:
        raise FileNotFoundError(sid)
    want = snap.get("ownerKeyHash")
    if not want or not isinstance(key, str) or not (8 <= len(key) <= 64) or not secrets.compare_digest(_key_hash(key), want):
        raise NotOwner(sid)
    return snap


def unlist(sid: str, key: str) -> None:
    """**みんなのグリッドから外す**（共有 URL はそのまま開ける）。索引の控え（listed/<id>.json）を消し、
    並びの JSON の listed も false に書き直す（共有ページの表示と揃えるため）。"""
    snap = _owned(sid, key)
    st = storage.get_storage()
    st.delete(f"{shareindex.PREFIX}{sid}.json")
    shareindex.forget(sid)
    if snap.get("listed"):
        snap["listed"] = False
        st.put(f"{sid}.json", json.dumps(snap, ensure_ascii=False, indent=2).encode("utf-8"), "application/json;charset=utf-8")


def delete(sid: str, key: str) -> None:
    """**共有ごと消す**（取り消せない）。消すものは scripts/delete_share.py と同じ: 本体画像・カード画像・並び・
    みんなのグリッドの控え。アップロード画像は同じ人の別の並びも使っていることがあるので残す。
    画像は img.trackmento.com（Cloudflare）のキャッシュにしばらく残ることがある。"""
    _owned(sid, key)
    storage.get_storage().delete_many([f"{sid}.jpg", f"{sid}.png", f"{sid}-og.jpg", f"{sid}.json", f"{shareindex.PREFIX}{sid}.json"])
    shareindex.forget(sid)


# 共有ページ・案内ページの文言。フロント（frontend/index.html の EN 表）と違い、こちらはサーバーで組み立てるので
# 開いた人の Accept-Language で選ぶ（共有ページは受け取った人が開くため、共有した人の設定ではなく開く人に合わせる）。
# お問い合わせは Google フォーム（2026-09-19。backend/pages.py の CONTACT_FORM と同じ URL）
CONTACT_FORM = "https://forms.gle/2ktpQAXMjJrkFJFz8"
# 連絡先は英語版のページが無いので URL は共通、ラベルだけ訳す。
TEXT = {
    "ja": {
        "expired_title": "この共有は見つかりません",
        "expired_og": "この共有は期限切れです。TRACKMENTO で作り直せます",
        "expired_note": "共有 URL は作成から {days} 日で消えます。この共有 URL は期限切れか、障害対応（保存容量の上限到達）で削除されたものです。"
                        "画像や並びのファイル（「並びを保存」で書き出す JSON）が手元に無い場合は、お手数ですが TRACKMENTO で作り直してください。",
        "make_btn": "TRACKMENTO で作る",
        "open_btn": "TRACKMENTO を開く",
        "contact": "連絡先",
        "contact_form": "お問い合わせフォーム",
        "report": "問題のある内容を報告する",
        "report_note": "（共有 ID {sid} を添えてください）",
        "about_url": "https://tobokegao.github.io/ja/about/",
        "nf_title": "ページが見つかりません",
        "nf_note": "URL が間違っているか、期限切れで消えたページです。共有 URL や画像は作成から {days} 日で消えます。",
        "busy_title": "アクセスが集中しています",
        "busy_note": "1 分ほど待ってからもう一度お試しください。",
        "err_title": "エラーが起きました",
        "err_note": "時間をおいてもう一度お試しください。直らない場合はお問い合わせフォームからお知らせください。",
        "save_img": "画像を保存",
        "open_in": "TRACKMENTO で開く（この並びを読み込む）",
        "tracks": "{n} トラック",
        "img_alt": "{cols}×{rows} に並べたサムネイル",
        "img_alt_more": "ほか {n} トラック",
        "share_id": "共有 ID",
        "this_url": "この URL",
        # **残し方は 2 つある**。画像だけでなく、TRACKMENTO で開いて「並びを保存」すれば
        # 並びそのものをファイルにでき、あとから読み込んで同じ状態に戻せる（期限切れの後でも）
        "keep": "画像を保存するか、「TRACKMENTO で開く」→「並びを保存」で並びのファイルにすれば手元に残ります",
        "expires_until": "有効期限: {until} まで（作成から {days} 日）",
        "expires_days": "有効期限: 作成から {days} 日",
        "og_share": "トラック共有サイト #TRACKMENTO からシェア:「{title}」",
        "untitled": "無題",
        "og_share_untitled": "トラック共有サイト #TRACKMENTO からシェア",
        "find_title": "みんなのグリッドを探す",
        "find_note": "トラック名やアーティスト名で、そのトラックが入っているグリッドを探せます。",
        "find_opt": "ここに出るのは、共有するときに「みんなのグリッドに載せる」にチェックを入れたものだけです（既定は入っていません）。ほかの共有は URL を知っている人だけが見られます。",
        "find_ph": "トラック名・アーティスト名",
        "find_btn": "探す",
        "find_none": "見つかりませんでした。別の言い方でも試してみてください。",
        "find_empty": "まだ 1 件も登録されていません。",
        "find_hits": "{n} 件見つかりました",
        "find_untitled": "無題のグリッド",
        "find_back": "TRACKMENTO を開く",
        # 自分の共有をあとから外す・消す（2026-09-26）。鍵を持っている端末にだけ出る
        "own_note": "この共有は、この端末から作りました。",
        "own_unlist": "みんなのグリッドから外す",
        "own_delete": "共有を消す",
        "own_confirm": "消すと、この URL も画像も見られなくなります（取り消せません）。",
        "own_yes": "消す",
        "own_cancel": "やめる",
        "own_unlisted": "みんなのグリッドから外しました。共有 URL はそのまま開けます。",
        "own_deleted": "共有を消しました。",
        "own_fail": "できませんでした",
        "find_own_done": "外しました",
        "dlg_title": "確認",
        "find_confirm": "「{{title}}」をみんなのグリッドから外します。共有 URL はそのまま開けます。",
        "find_yes": "外す",
        "find_varied": "いろんな切り口",
        "find_recent": "最近のグリッド",
    },
    "en": {
        "expired_title": "This share is gone",
        "expired_og": "This share has expired. Make a new one with TRACKMENTO",
        "expired_note": "Share URLs disappear {days} days after they are made. This one has either expired or been removed while freeing up storage. "
                        "If you do not have the image or the layout file (the JSON that \u201cSave layout\u201d writes) to hand, you will need to build it again in TRACKMENTO.",
        "make_btn": "Make one with TRACKMENTO",
        "open_btn": "Open TRACKMENTO",
        "contact": "Contact",
        "contact_form": "Contact form",
        "report": "Report inappropriate content",
        "report_note": " (please include the share ID {sid})",
        "about_url": "https://tobokegao.github.io/about/",
        "nf_title": "Page not found",
        "nf_note": "The URL is wrong, or the page has expired. Share URLs and images disappear {days} days after they are made.",
        "busy_title": "Too many requests right now",
        "busy_note": "Wait about a minute and try again.",
        "err_title": "Something went wrong",
        "err_note": "Try again in a little while. If it keeps happening, please let us know through the contact form below.",
        "save_img": "Save image",
        "open_in": "Open in TRACKMENTO (loads this layout)",
        "tracks": "{n} tracks",
        "img_alt": "Cover art in a {cols}×{rows} grid",
        "img_alt_more": "and {n} more",
        "share_id": "Share ID",
        "this_url": "This URL",
        "keep": "save the image, or open it in TRACKMENTO and use “Save layout” to keep the layout as a file",
        "expires_until": "Expires {until} ({days} days after it was made)",
        "expires_days": "Expires {days} days after it was made",
        "og_share": "Shared from #TRACKMENTO, the track-grid maker: \u201c{title}\u201d",
        "untitled": "Untitled",
        "og_share_untitled": "Shared from #TRACKMENTO, a track grid maker",
        "find_title": "Find shared grids",
        "find_note": "Search by track or artist name to find grids that contain it.",
        "find_opt": "Only grids whose maker ticked “Add to everyone's grids” when sharing appear here (it is off by default). Every other share stays visible only to people who have its URL.",
        "find_ph": "Track or artist",
        "find_btn": "Search",
        "find_none": "Nothing found. Try another spelling.",
        "find_empty": "Nothing has been listed yet.",
        "find_hits": "{n} found",
        "find_untitled": "Untitled grid",
        "find_back": "Open TRACKMENTO",
        "own_note": "You shared this from this device.",
        "own_unlist": "Remove from everyone's grids",
        "own_delete": "Delete this share",
        "own_confirm": "The URL and the image will stop working. This can't be undone.",
        "own_yes": "Delete",
        "own_cancel": "Cancel",
        "own_unlisted": "Removed from everyone's grids. The share URL still works.",
        "own_deleted": "The share was deleted.",
        "own_fail": "Couldn't do that",
        "find_own_done": "Removed",
        "dlg_title": "Confirm",
        "find_confirm": "Remove “{{title}}” from everyone's grids? The share URL still works.",
        "find_yes": "Remove",
        "find_varied": "Different themes",
        "find_recent": "Recent grids",
    },
}


def t(lang: str, key: str, **kw) -> str:
    """文言を引く。知らない言語は日本語にする。"""
    return TEXT.get(lang if lang in TEXT else "ja", TEXT["ja"])[key].format(**kw)


def _silkscreen_url() -> str:
    """ピクセルフォントの場所。R2 が使えるならそちら（転送量が無料。共有ページは閲覧が多い）。"""
    try:
        return storage.get_storage().public_url("fonts/Silkscreen-Bold.woff2") or "/fonts/Silkscreen-Bold.woff2"
    except Exception:
        return "/fonts/Silkscreen-Bold.woff2"


def logo_font_url() -> str:
    """ロゴ専用フォント（Silkscreen Bold の M だけ描き替えたもの。scripts/build_logo_font.py）の場所。
    **ファイル名は変えずに中身を作り直すことがある**ので、中身のハッシュを `?v=` に付けて古いキャッシュを踏まない
    （フォントは 1 年キャッシュする）。R2 が使えるならそちら、無ければこのサーバー"""
    import hashlib
    import pathlib
    f = pathlib.Path(__file__).resolve().parent.parent / "fonts" / "TrackmentoMark-Bold.woff2"
    try:
        v = hashlib.sha256(f.read_bytes()).hexdigest()[:8]
    except OSError:
        v = "0"
    try:
        url = storage.get_storage().public_url("fonts/TrackmentoMark-Bold.woff2") or "/fonts/TrackmentoMark-Bold.woff2"
    except Exception:
        url = "/fonts/TrackmentoMark-Bold.woff2"
    return f"{url}?v={v}"


def _page_css(base: str) -> str:
    # フォントはこのサーバー（共有ページを配っているのと同じオリジン）から相対パスで読む。base（LAN IP や公開 URL）と
    # ページのオリジンが違うとフォントは CORS で読めず、ワードマークが代替フォントになる
    silk = _silkscreen_url()
    logo = logo_font_url()
    return f"""
/* 日本語フォントは読まない（IBM Plex Sans JP 1.1MB ＋ DotGothic16 0.5MB が 1 閲覧ごとに転送されていた。共有ページは X からの
   閲覧が多く、帯域の主因になっていた）。ワードマークと番号の Silkscreen（9KB）だけ読み、本文は端末のフォント */
@font-face {{ font-family: "Silkscreen"; font-weight: 700; font-display: swap; src: url("{silk}") format("woff2"), url("/fonts/Silkscreen-Bold.ttf") format("truetype"); }}
@font-face {{ font-family: "TrackmentoMark"; font-weight: 700; font-display: swap; src: url("{logo}") format("woff2"), url("/fonts/TrackmentoMark-Bold.ttf") format("truetype"); }}
* {{ box-sizing: border-box; border-radius: 0; }}
body {{ margin: 0; background: #f6f5f3; color: #12171b; font-family: "Hiragino Sans", "Noto Sans JP", "Yu Gothic UI", "Meiryo", sans-serif; line-height: 1.55; }}
header {{ display: flex; align-items: baseline; gap: 8px; padding: 10px 16px; border-bottom: 2px solid #12171b; }}
/* ワードマークは本体（frontend/index.html の .wordmark .mark）と同じ規則: Silkscreen 25px、行送り 16px（大文字のインク高）、
   インクの 3px 下にリソ 6 色の太線（5px）、線の頭に離して 5px 角の四角。色も本体の oklch トークンと同値。
   押すと編集画面（トップ）へ戻る。リンクだが色と下線は付けない（ロゴの見た目を変えない） */
.mark {{ font-family: "TrackmentoMark", "Silkscreen", "JF Dot MPlus12", monospace; font-weight: 700; font-size: 1.5625rem; letter-spacing: .04em; white-space: nowrap;
  color: inherit; text-decoration: none;
  display: inline-block; line-height: 16px; margin-top: -2px; padding-bottom: 10px;
  margin-left: -10px; padding-left: 10px; margin-right: -3px; padding-right: 3px;
  background:
    linear-gradient(oklch(80% 0.150 88), oklch(80% 0.150 88)) left bottom / 5px 5px no-repeat,
    linear-gradient(to right,
    oklch(80% 0.150 88)  0 calc(100% / 6),
    oklch(60% 0.140 235) 0 calc(200% / 6),
    oklch(62% 0.200 32)  0 50%,
    oklch(74% 0.100 295) 0 calc(400% / 6),
    oklch(84% 0.110 165) 0 calc(500% / 6),
    oklch(78% 0.130 350) 0) right bottom / calc(100% - 7px) 5px no-repeat; }}
small {{ color: #53595f; }}
main {{ max-width: 56rem; margin: 0 auto; padding: 16px; display: grid; gap: 16px; }}
h1 {{ font-weight: 700; font-size: 1.25rem; margin: 0; }}
img {{ max-width: 100%; height: auto; display: block; border: 2px solid #12171b; }}
.btns {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.btn {{ display: inline-flex; align-items: center; min-height: 44px; padding: 4px 16px; border: 2px solid #12171b; background: #f6f5f3; color: #12171b;
  font-weight: 700; text-decoration: none; box-shadow: 2px 2px 0 #12171b; }}
.btn.primary {{ background: #12171b; color: #f6f5f3; }}
/* 自分の共有を外す・消す（2026-09-26）。鍵を持つ端末にだけ出る。button は a と同じ見た目に */
button.btn {{ font: inherit; font-weight: 700; cursor: pointer; }}
button.btn:disabled {{ opacity: .5; cursor: default; }}
.btn.danger {{ background: oklch(62% 0.200 32); color: #f6f5f3; }}
.own {{ display: grid; gap: 8px; padding: 12px; border: 2px dashed #12171b; }}
.own[hidden] {{ display: none; }}
.own .note {{ margin: 0; padding: 0; border: 0; background: none; }}   /* 破線の枠の中なので、ふだんの .note の枠は付けない */
.own .own-msg:empty {{ display: none; }}
/* 探すページの「外す」は **Mac OS 8 のクローズボックス**（題名バーの左端の、中が空の小さな立体の四角。× は描かない。
   HIG の Window Guidelines の図 HIG_W-007）。× を四角で囲んだ形は一覧の中で目立ちすぎた（2026-09-26、利用者の指摘）。
   押せる広さは 24px 四方で、見た目の箱は真ん中の 13px。押すと凹む。何のボタンかは title と読み上げで伝える */
.own-rm {{ position: relative; display: inline-block; width: 24px; height: 24px; padding: 0; vertical-align: middle;
  background: none; border: 0; cursor: pointer; }}
.own-rm::before {{ content: ""; position: absolute; left: 5px; top: 5px; width: 13px; height: 13px; box-sizing: border-box;
  border: 1px solid #12171b; background: #dddcd8; box-shadow: inset 1px 1px 0 #fff, inset -1px -1px 0 #8b8f93; }}
.own-rm:hover::before {{ background: #cfcdc8; }}
.own-rm:active::before {{ background: #8b8f93; box-shadow: inset 1px 1px 0 #53595f, inset -1px -1px 0 #c2c4c6; }}
/* 箱の中の ×（2026-09-26、利用者の案）。斜めの 2 本の線で描く（字だと書体で太さと位置が変わる） */
.own-rm::after {{ content: ""; position: absolute; left: 8px; top: 8px; width: 7px; height: 7px;
  background: linear-gradient(45deg, transparent 43%, #12171b 43% 57%, transparent 57%),
              linear-gradient(-45deg, transparent 43%, #12171b 43% 57%, transparent 57%); }}
/* 確認の窓。画面（frontend/index.html）の #confirm-modal と同じ作り */
.odlg {{ position: fixed; inset: 0; z-index: 10; display: grid; place-items: center; padding: 16px; }}
.odlg-bg {{ position: absolute; inset: 0; background: color-mix(in oklab, #12171b 45%, transparent); }}
.odlg-panel {{ position: relative; width: min(100%, 26rem); border: 2px solid #12171b; background: #f6f5f3; box-shadow: 4px 4px 0 #12171b; }}
.odlg-head {{ padding: 8px 12px; background: #12171b; }}
.odlg-head h2 {{ margin: 0; font-size: 1rem; font-weight: 700; letter-spacing: .04em; color: #f6f5f3; }}
.odlg-body {{ display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: 16px; align-items: start; padding: 12px; }}
.odlg-body p {{ margin: 0; }}
.odlg-body .caution {{ width: 32px; height: 32px; }}
.odlg-body .caution .c-fill {{ fill: oklch(80% 0.150 88); }}
.odlg-body .caution .c-edge, .odlg-body .caution .c-mark {{ fill: #12171b; }}
.odlg-btns {{ grid-column: 1 / -1; display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-top: 12px; }}
/* 既定のボタン（やめる）は二重の枠（HIG の決まり） */
.odlg-default {{ box-shadow: 0 0 0 2px #f6f5f3, 0 0 0 5px #12171b; margin: 4px; }}
.own-rm:disabled {{ opacity: .5; cursor: default; }}
li.own-gone .t a {{ text-decoration: line-through; opacity: .5; }}
/* 外したあとの印は、曲名リストから離した黒地の小さな札（灰色の字のままだと曲名リストと見分けにくかった。2026-09-26、利用者の指摘） */
.own-done {{ display: inline-block; margin-left: 10px; padding: 0 6px; font-size: .8rem; font-weight: 700; line-height: 1.6;
  background: #12171b; color: #f6f5f3; vertical-align: 1px; }}
.own-err {{ margin-left: 10px; font-size: .85rem; color: oklch(55% 0.200 32); }}
ol {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }}
li {{ display: flex; gap: 10px; align-items: baseline; }}
/* 曲名とアーティスト名は 1 つの流し込み。別々の flex 項目にすると狭い画面でアーティスト名だけ細長く折り返る */
.t {{ min-width: 0; overflow-wrap: anywhere; }}
.n {{ font-family: "Silkscreen", monospace; font-size: .7rem; color: #53595f; }}
.a {{ color: #53595f; }}
/* 曲ごとのメモ。曲名の下に、左の縦線で「この曲への書き込み」と分かるようにする */
.memo {{ display: block; margin: 2px 0 6px; padding-left: 8px; border-left: 2px solid #12171b; font-size: .9rem; white-space: pre-line; }}
/* 曲名から元のページへ。**リンクだと一目で分かるようにする**（触れるまで分からないと気付かれない）。
   色は変えず、曲名に点線の下線と外部リンクの印を付ける。リンクの無い曲と並んでも一覧が騒がしくならない */
.t a {{ color: inherit; text-decoration: none; }}
.t a b {{ text-decoration: underline; text-decoration-style: dotted; text-decoration-thickness: 1px; text-underline-offset: 3px; }}
.t a::after {{ content: "↗"; margin-left: .3em; font-size: .8em; color: #53595f; }}
.t a:hover b, .t a:focus-visible b {{ text-decoration-style: solid; }}
.t a:hover::after, .t a:focus-visible::after {{ color: #12171b; }}
p.meta {{ margin: 0; color: #53595f; font-size: .85rem; overflow-wrap: anywhere; }}
p.meta a {{ color: #12171b; }}
p.note {{ margin: 0; padding: 12px 16px; border: 2px solid #12171b; background: #fff; overflow-wrap: anywhere; }}
"""


def _expires_text(created_at: str | None, lang: str = "ja") -> str:
    """「有効期限: 2026-09-18 まで（作成から 7 日）」。createdAt が読めなければ日数だけ。"""
    days = share_retention_days()
    try:
        created = datetime.fromisoformat((created_at or "").replace("Z", "+00:00"))
        until = (created + timedelta(days=days)).astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
        return t(lang, "expires_until", until=until, days=days)
    except ValueError:
        return t(lang, "expires_days", days=days)


def expired_html(sid: str, base: str, app_url: str | None = None, lang: str = "ja") -> str:
    """共有が見つからないときの案内ページ（404）。JSON を返すと X から開いた人に何が起きたか伝わらない。
    リンクカードはサイト既定の画像にして、再共有されても壊れた表示にならないようにする。"""
    app_url = (app_url or base).rstrip("/")
    days = share_retention_days()
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t(lang, "expired_title")} — TRACKMENTO</title>
<link rel="icon" href="/favicon.ico"><link rel="icon" type="image/png" href="/favicon.png" sizes="64x64"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="robots" content="noindex">
<meta property="og:title" content="TRACKMENTO"><meta property="og:image" content="{base}/og.png"><meta name="twitter:image" content="{base}/og.png">
<meta property="og:description" content="{t(lang, "expired_og")}"><meta name="twitter:card" content="summary_large_image">
<style>{_page_css(base)}</style></head>
<body>
<header><a class="mark" href="{app_url}/">TRACKMENTO</a></header>
<main>
  <h1>{t(lang, "expired_title")}</h1>
  <p class="note">{t(lang, "expired_note", days=days)}</p>
  <div class="btns">
    <a class="btn primary" href="{app_url}/">{t(lang, "make_btn")}</a>
  </div>
  <p class="meta"><a href="{CONTACT_FORM}" target="_blank" rel="noopener noreferrer">{t(lang, "contact_form")}</a></p>
</main>
</body></html>"""


def notice_html(status: int, base: str, app_url: str | None = None, detail: str = "", lang: str = "ja") -> str:
    """ブラウザで直接開いた URL がエラーになったときの案内ページ（404・405・429・5xx）。
    JSON の {"detail": …} をそのまま見せない。見た目は共有ページと同じ。"""
    app_url = (app_url or base).rstrip("/")
    days = share_retention_days()
    if status in (404, 405):
        title, note = t(lang, "nf_title"), t(lang, "nf_note", days=days)
    elif status == 429:
        title, note = t(lang, "busy_title"), t(lang, "busy_note")
    else:
        title, note = t(lang, "err_title"), t(lang, "err_note")
    extra = f'<p class="note">{html.escape(detail)}</p>' if detail and status not in (404, 405) else ""
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — TRACKMENTO</title>
<link rel="icon" href="/favicon.ico"><link rel="icon" type="image/png" href="/favicon.png" sizes="64x64"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="robots" content="noindex">
<style>{_page_css(base)}</style></head>
<body>
<header><a class="mark" href="{app_url}/">TRACKMENTO</a></header>
<main>
  <h1>{title}</h1>
  <p class="note">{note}</p>{extra}
  <div class="btns">
    <a class="btn primary" href="{app_url}/">{t(lang, "open_btn")}</a>
  </div>
  <p class="meta"><a href="{CONTACT_FORM}" target="_blank" rel="noopener noreferrer">{t(lang, "contact_form")}</a></p>
</main>
</body></html>"""


ALT_TRACKS = 10   # 画像の代替テキストに入れる曲の数


# 端末に覚えた「自分の共有の鍵」（frontend/index.html の SHARE_KEYS と同じ名前・同じ形 {id: {k, at, l}}）
OWNER_STORE = "trackmento:shareKeys"

# 確認の窓の「注意」の絵（OS 9 の Caution alert にならう 32x32 のドット絵）。frontend/index.html の #confirm-modal と同じもの
CAUTION_SVG = '<svg class="caution" viewBox="0 0 32 32" width="32" height="32" aria-hidden="true" shape-rendering="crispEdges"><path class="c-fill" d="M15 1h2v1H15zM15 2h2v1H15zM14 3h4v1H14zM14 4h4v1H14zM13 5h6v1H13zM13 6h6v1H13zM12 7h8v1H12zM12 8h8v1H12zM11 9h10v1H11zM11 10h10v1H11zM10 11h12v1H10zM10 12h12v1H10zM9 13h14v1H9zM9 14h14v1H9zM8 15h16v1H8zM8 16h16v1H8zM7 17h18v1H7zM7 18h18v1H7zM6 19h20v1H6zM6 20h20v1H6zM5 21h22v1H5zM5 22h22v1H5zM4 23h24v1H4zM4 24h24v1H4zM3 25h26v1H3zM3 26h26v1H3zM2 27h28v1H2zM2 28h28v1H2zM1 29h30v1H1zM1 30h30v1H1z"/><path class="c-edge" d="M15 1h2v1H15zM15 2h2v1H15zM14 3h1v1H14zM17 3h1v1H17zM14 4h1v1H14zM17 4h1v1H17zM13 5h1v1H13zM18 5h1v1H18zM13 6h1v1H13zM18 6h1v1H18zM12 7h1v1H12zM19 7h1v1H19zM12 8h1v1H12zM19 8h1v1H19zM11 9h1v1H11zM20 9h1v1H20zM11 10h1v1H11zM20 10h1v1H20zM10 11h1v1H10zM21 11h1v1H21zM10 12h1v1H10zM21 12h1v1H21zM9 13h1v1H9zM22 13h1v1H22zM9 14h1v1H9zM22 14h1v1H22zM8 15h1v1H8zM23 15h1v1H23zM8 16h1v1H8zM23 16h1v1H23zM7 17h1v1H7zM24 17h1v1H24zM7 18h1v1H7zM24 18h1v1H24zM6 19h1v1H6zM25 19h1v1H25zM6 20h1v1H6zM25 20h1v1H25zM5 21h1v1H5zM26 21h1v1H26zM5 22h1v1H5zM26 22h1v1H26zM4 23h1v1H4zM27 23h1v1H27zM4 24h1v1H4zM27 24h1v1H27zM3 25h1v1H3zM28 25h1v1H28zM3 26h1v1H3zM28 26h1v1H28zM2 27h1v1H2zM29 27h1v1H29zM2 28h1v1H2zM29 28h1v1H29zM1 29h1v1H1zM30 29h1v1H30zM1 30h30v1H1z"/><path class="c-mark" d="M15 10h2v1H15zM15 11h2v1H15zM15 12h2v1H15zM15 13h2v1H15zM15 14h2v1H15zM15 15h2v1H15zM15 16h2v1H15zM15 17h2v1H15zM15 18h2v1H15zM15 19h2v1H15zM15 20h2v1H15zM15 21h2v1H15zM15 24h2v1H15zM15 25h2v1H15zM15 26h2v1H15z"/></svg>'

# 鍵を持っている端末にだけ「外す」「消す」を出すスクリプト。__T__ / __MODE__ / __STORE__ を差し替えて使う
_OWNER_JS = """
(() => {
  const T = __T__, MODE = "__MODE__", STORE = "__STORE__";
  let keys = {};
  try { keys = JSON.parse(localStorage.getItem(STORE) || "{}") || {}; } catch { return; }
  const save = () => { try { localStorage.setItem(STORE, JSON.stringify(keys)); } catch {} };
  const ask = async (sid, action) => {
    const r = await fetch(`/s/${sid}/${action}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key: keys[sid].k }) });
    let d = {}; try { d = await r.json(); } catch {}
    if (r.status === 404) { delete keys[sid]; save(); }
    if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
    if (action === "delete") delete keys[sid]; else keys[sid].l = false;
    save();
  };
  const btn = (text, cls) => { const b = document.createElement("button"); b.type = "button"; b.className = "btn" + (cls ? " " + cls : ""); b.textContent = text; return b; };
  // **確認の窓**（画面の #confirm-modal と同じ作り: 暗い幕・黒い帯の題・注意の絵・既定は「やめる」で二重の枠。2026-09-26、利用者の案）。
  // 開いたら「やめる」に焦点を置く（Return で取り消せる）。Esc と幕を押しても取り消し。閉じたら押したボタンへ焦点を戻す
  const confirmBox = (msg, yesText, opener) => new Promise((done) => {
    const wrap = document.createElement("div");
    wrap.className = "odlg"; wrap.setAttribute("role", "dialog"); wrap.setAttribute("aria-modal", "true"); wrap.setAttribute("aria-labelledby", "odlg-t");
    wrap.innerHTML = `<div class="odlg-bg"></div><div class="odlg-panel"><div class="odlg-head"><h2 id="odlg-t"></h2></div>
      <div class="odlg-body">${__CAUTION__}<p></p><div class="odlg-btns"></div></div></div>`;
    wrap.querySelector("h2").textContent = T.dlg_title;
    wrap.querySelector("p").textContent = msg;
    const no = btn(T.own_cancel, "odlg-default"), yes = btn(yesText);
    wrap.querySelector(".odlg-btns").append(no, yes);
    const close = (ok) => { document.removeEventListener("keydown", onKey, true); wrap.remove(); if (opener && opener.isConnected) opener.focus(); done(ok); };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(false); }
      else if (e.key === "Tab") { e.preventDefault(); (document.activeElement === no ? yes : no).focus(); }   // 焦点は 2 つのボタンの間だけ
    };
    no.addEventListener("click", () => close(false));
    yes.addEventListener("click", () => close(true));
    wrap.querySelector(".odlg-bg").addEventListener("click", () => close(false));
    document.addEventListener("keydown", onKey, true);
    document.body.append(wrap);
    no.focus();
  });
  if (MODE === "find") {
    for (const a of document.querySelectorAll('main li a[href^="/s/"]')) {
      const sid = a.getAttribute("href").slice(3);
      if (!keys[sid]) continue;
      // Mac OS 8 のクローズボックスの形に × を入れたもの（2026-09-26、利用者の選択）。何のボタンかは title と読み上げで伝える。
      // 押すと確認の窓を出す（うっかり押しても外れない）
      const b = document.createElement("button");
      b.type = "button"; b.className = "own-rm";
      b.title = T.own_unlist; b.setAttribute("aria-label", T.own_unlist);
      const note = document.createElement("span");
      b.addEventListener("click", async () => {
        if (!(await confirmBox(T.find_confirm.replace("{title}", a.textContent.trim()), T.find_yes, b))) return;
        b.disabled = true;
        try { await ask(sid, "unlist"); a.closest("li").classList.add("own-gone"); note.className = "own-done"; note.textContent = T.find_own_done; b.replaceWith(note); }
        catch (e) { b.disabled = false; note.className = "own-err"; note.textContent = `${T.own_fail}（${e.message}）`; b.after(note); }
      });
      a.closest("li").querySelector(".t").append(" ", b);
    }
    return;
  }
  const box = document.getElementById("own"), sid = box && box.dataset.sid;
  if (!box || !keys[sid]) return;
  const msg = box.querySelector(".own-msg"), row = box.querySelector(".btns");
  const say = (text) => { msg.textContent = text; };
  const unlist = btn(T.own_unlist), del = btn(T.own_delete);
  const reset = () => { row.replaceChildren(); if (box.dataset.listed === "1") row.append(unlist); row.append(del); };
  unlist.addEventListener("click", async () => {
    unlist.disabled = true;
    try { await ask(sid, "unlist"); box.dataset.listed = ""; unlist.remove(); say(T.own_unlisted); }
    catch (e) { unlist.disabled = false; say(`${T.own_fail}（${e.message}）`); }
  });
  // 消すのは取り消せないので、確認の窓を挟む（ブラウザの confirm は使わない）
  del.addEventListener("click", async () => {
    if (!(await confirmBox(T.own_confirm, T.own_yes, del))) return;
    del.disabled = unlist.disabled = true;
    try { await ask(sid, "delete"); row.replaceChildren(); say(T.own_deleted); setTimeout(() => location.reload(), 1200); }
    catch (e) { del.disabled = unlist.disabled = false; say(`${T.own_fail}（${e.message}）`); }
  });
  reset();
  box.hidden = false;
})();
"""


def _owner_script(nonce: str, lang: str, mode: str) -> str:
    """鍵を持っている端末にだけ「外す」「消す」を出す（2026-09-26）。**鍵の無い端末では何も出ない**。
    mode: "page"（共有ページ）/ "find"（探すページ）。文言はサーバーで入れる。CSP の nonce を付ける"""
    tx = {k: t(lang, k) for k in ("own_note", "own_unlist", "own_delete", "own_confirm", "own_yes", "own_cancel",
                                   "own_unlisted", "own_deleted", "own_fail", "find_own_done",
                                   "dlg_title", "find_confirm", "find_yes")}
    js = (_OWNER_JS.replace("__T__", json.dumps(tx, ensure_ascii=False).replace("</", "<\\/"))
          .replace("__MODE__", mode).replace("__STORE__", OWNER_STORE).replace("__CAUTION__", json.dumps(CAUTION_SVG)))
    return f'<script nonce="{html.escape(nonce, quote=True)}">{js}</script>'


def page_html(snap: dict, base: str, app_url: str | None = None, lang: str = "ja", nonce: str = "") -> str:
    """共有ページ。依存なしの単一 HTML（スマホのブラウザで開く前提）。"""
    sid = snap["id"]
    app_url = (app_url or base).rstrip("/")
    ext = snap.get("ext") or "png"   # 古い共有は PNG
    img_url = image_url(sid, ext)   # R2 の公開 URL があればそこから直接（サーバーの転送量を節約）
    if img_url.startswith("/"):
        img_url = base + img_url
    # カード画像は 1200×630 の JPEG（X は 5 MB 超・2:1 以外を切り取るので PNG 本体は使わない）。古い共有は PNG のまま
    card_url = og_url(sid) if snap.get("og") else img_url
    if card_url.startswith("/"):
        card_url = base + card_url
    card_meta = ('<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta property="og:image:type" content="image/jpeg">'
                 if snap.get("og") else "")
    # **タイトルを付けずに共有したときは、見出しを出さない**（「無題」と書くより素直。
    # X のカードに "Untitled" と出るのも避ける）。ページの題と og:title はサイト名にする
    raw_title = (snap.get("title") or "").strip()
    title = html.escape(raw_title)
    page_title = f"{title} — TRACKMENTO" if title else "TRACKMENTO"
    og_title = title or "TRACKMENTO"
    og_desc = t(lang, "og_share", title=title) if title else t(lang, "og_share_untitled")
    heading = f"<h1>{title}</h1>" if title else ""
    # **画像と同じ題を出す**。共有したときの `trimNames`（無い古い共有は入り）に従う
    trim_names = ((snap.get("options") or {}).get("trimNames")) is not False
    rows = []
    alt_items = []
    # 番号は**曲の入ったマスの序数**（空きマスは飛ばして詰める。書き出し画像の番号と同じ。2026-09-25）
    for i, c in enumerate((c for c in snap.get("cells") or [] if c), 1):
        c_title, c_artist = (c.get("title") or ""), (c.get("artist") or "")
        if trim_names:
            c_title, c_artist = names.trim(c_title, c_artist)
        alt_items.append(f"{c_title}（{c_artist}）" if lang == "ja" and c_artist
                         else f"{c_title} – {c_artist}" if c_artist else c_title)
        inner = f"<b>{html.escape(c_title)}</b> <span class=a>{html.escape(c_artist)}</span>"
        # 元のページ（YouTube・ニコニコ・Bandcamp など）へ飛べるようにする。
        # **URL は利用者のデータなので、http(s) だけを通す**（javascript: などを弾く）。
        # 外部へ出すリンクには noopener / noreferrer / nofollow を付ける
        url = (c.get("external_url") or "").strip()
        if url[:7].lower() == "http://" or url[:8].lower() == "https://":
            inner = (f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                     f'rel="noopener noreferrer nofollow">{inner}</a>')
        # 作った人のメモ（選んだ理由など）。改行は CSS の pre-line で残す。リンクの外に置く（押せる範囲を広げない）
        note = (c.get("note") or "").strip()
        if note:
            inner += f"<span class=memo>{html.escape(note)}</span>"
        rows.append(f"<li><span class=n>{i:02d}</span><span class=t>{inner}</span></li>")
    n = len(rows)
    # 画像の代替テキスト。読み上げや画像が読めないときにも何の並びか分かるよう、題・大きさ・曲名を入れる。
    # **曲名は先頭 ALT_TRACKS 曲まで**（全曲は直後の一覧にあり、読み上げで同じものを 2 度聞かせない）
    alt = t(lang, "img_alt", cols=snap.get("cols"), rows=snap.get("rows"))
    if raw_title:
        alt = (f"「{raw_title}」、" if lang == "ja" else f"“{raw_title}”: ") + alt
    if alt_items:
        shown = alt_items[:ALT_TRACKS]
        rest = len(alt_items) - len(shown)
        alt += ("。" if lang == "ja" else ". ") + ("、" if lang == "ja" else "; ").join(shown)
        if rest:
            alt += ("、" if lang == "ja" else "; ") + t(lang, "img_alt_more", n=rest)
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title>
<link rel="icon" href="/favicon.ico"><link rel="icon" type="image/png" href="/favicon.png" sizes="64x64"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="robots" content="noindex">
<meta property="og:title" content="{og_title}"><meta property="og:image" content="{card_url}">{card_meta}<meta name="twitter:image" content="{card_url}">
<meta property="og:description" content="{og_desc}"><meta name="twitter:card" content="summary_large_image">
<style>{_page_css(base)}</style></head>
<body>
<header><a class="mark" href="{app_url}/">TRACKMENTO</a></header>
<main>
  {heading}
  <img src="{img_url}" alt="{html.escape(alt, quote=True)}">
  <div class="btns">
    <a class="btn primary" href="/shares/{sid}.{ext}" download="{html.escape((snap.get('title') or 'trackmento').replace('/', '_'))}.{ext}">{t(lang, "save_img")}</a>
    <a class="btn" href="{app_url}/?share={sid}">{t(lang, "open_in")}</a>
  </div>
  <ol>{''.join(rows)}</ol>
  <p class="meta">{t(lang, 'tracks', n=n)} · {snap.get('cols')}×{snap.get('rows')} · {t(lang, 'share_id')} {sid} · {html.escape(snap.get('createdAt') or '')}</p>
  <p class="meta">{t(lang, 'this_url')}: {base}/s/{sid} · {_expires_text(snap.get('createdAt'), lang)} · {t(lang, 'keep')}</p>
  <p class="meta"><a href="{CONTACT_FORM}" target="_blank" rel="noopener noreferrer">{t(lang, "contact_form")}</a>
    · <a href="{CONTACT_FORM}" target="_blank" rel="noopener noreferrer">{t(lang, "report")}</a>{t(lang, "report_note", sid=sid)}</p>
  <section class="own" id="own" data-sid="{sid}" data-listed="{'1' if snap.get('listed') else ''}" hidden>
    <p class="note">{t(lang, "own_note")}</p><div class="btns"></div><p class="note own-msg" role="status" aria-live="polite"></p>
  </section>
</main>
{_owner_script(nonce, lang, "page") if nonce else ""}
</body></html>"""


def find_html(q: str, results: list[dict], base: str, app_url: str | None = None,
              lang: str = "ja", listed_total: int = 0, varied: list[dict] | None = None, nonce: str = "") -> str:
    """「みんなの並びを探す」ページ。**ここに出るのは opt-in の共有だけ**（`backend/shareindex.py`）。

    探すのはフォームの GET だけ。スクリプトは、自分の共有の横に「外す」を出す小さなもの 1 つだけ（2026-09-26。
    鍵を持っている端末にだけ出る。`_owner_script`）。共有ページと同じ見た目・同じ CSS。
    検索避けは付けたまま（`noindex`）: 載せた人が同意したのは「このサイトの中で探せること」で、
    外部の検索結果に出ることまでは同意していない。
    """
    app_url = (app_url or base).rstrip("/")
    qs = html.escape(q or "", quote=True)
    def items(rs: list[dict]) -> str:
        out = []
        for r in rs:
            title = html.escape(r["title"]) or t(lang, "find_untitled")
            hits = "".join(f"<span class=a>{html.escape(h)}</span>" for h in r.get("hits") or [])
            out.append(f'<li><span class=n>{r["n"]:02d}</span><span class=t>'
                       f'<a href="/s/{r["id"]}"><b>{title}</b></a> '
                       f'<span class=a>{r["cols"]}×{r["rows"]}</span> {hits}</span></li>')
        return "".join(out)
    if q and not results:
        body = f'<p class="note">{t(lang, "find_none")}</p>'
    elif q:
        body = f'<p class="meta">{t(lang, "find_hits", n=len(results))}</p><ol>{items(results)}</ol>'
    elif results or varied:
        # 探す前: 「私を構成する 9 曲」ばかりにならないよう、ほかのテーマを先に出す（open-use ⑤）
        body = "".join(f'<section><h2>{t(lang, key)}</h2><ol>{items(rs)}</ol></section>'
                       for key, rs in (("find_varied", varied or []), ("find_recent", results)) if rs)
    elif listed_total:
        body = ""
    else:
        body = f'<p class="note">{t(lang, "find_empty")}</p>'
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t(lang, "find_title")} — TRACKMENTO</title>
<link rel="icon" href="/favicon.ico"><link rel="icon" type="image/png" href="/favicon.png" sizes="64x64"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="robots" content="noindex">
<style>{_page_css(base)}
form.find {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }}
form.find input {{ flex: 1 1 14rem; min-width: 0; font: inherit; padding: 10px 12px;
  border: 2px solid var(--ink); background: var(--paper); color: var(--ink); }}
section {{ display: grid; gap: 8px; }}
h2 {{ font-weight: 700; font-size: 1rem; margin: 0; }}
</style></head>
<body>
<header><a class="mark" href="{app_url}/">TRACKMENTO</a></header>
<main>
  <h1>{t(lang, "find_title")}</h1>
  <p class="note">{t(lang, "find_note")}</p>
  <form class="find" method="get" action="/find">
    <input type="search" name="q" value="{qs}" placeholder="{t(lang, 'find_ph')}" autofocus>
    <button class="btn primary" type="submit">{t(lang, "find_btn")}</button>
  </form>
  {body}
  <p class="note">{t(lang, "find_opt")}</p>
  <div class="btns"><a class="btn" href="{app_url}/">{t(lang, "find_back")}</a></div>
  <p class="meta"><a href="{CONTACT_FORM}" target="_blank" rel="noopener noreferrer">{t(lang, "contact_form")}</a></p>
</main>
{_owner_script(nonce, lang, "find") if nonce else ""}
</body></html>"""
