"""画像の中継（`/image-proxy`）と、R2に寄せた画像の索引（`imgcache/`）。

起動時にR2を1周して索引と使用量を作る `_seed_r2_index` と、使用量を数え直す `_usage_loop` もここ。
2026-10-12に `main.py` から分けた（名前はそのまま）。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field

from backend import imgtools, netguard, storage, uploads
from backend.cache import R2_IMAGE_TTL, cache
from backend.sources import bandcamp, itunes, musicbrainz, otodb, soundcloud, video

ROOT = Path(__file__).resolve().parent.parent
router = APIRouter()

# /image-proxyが取得を許可するホスト（末尾一致）
IMAGE_HOST_ALLOWLIST = (
    "mzstatic.com",            # iTunes
    "sndcdn.com",              # SoundCloud
    "ytimg.com",               # YouTubeサムネイル
    "nimg.jp",                 # ニコニコ動画サムネイル（nicovideo.cdn.nimg.jp）
    "nicovideo.jp",
    "hdslb.com",               # bilibiliカバー画像
    "scdn.co",                 # Spotifyジャケット
    "spotifycdn.com",
    "otodb.net",               # otoDBサムネイル（cdn.otodb.net）
    "coverartarchive.org",     # MusicBrainz CAA
    "archive.org",
    "discogs.com",             # Discogs
    "bcbits.com",              # Bandcamp
    "bandcamp.com",
)
IMAGE_MAX_BYTES = 15 * 1024 * 1024
# 画像取得のタイムアウト。共有クライアントapp.state.httpの既定（30秒 / connect 10秒）は
# MusicBrainzやroxyに合わせたもので、画像には長すぎる。遅い配信元が1本で _PROXY_SEMの枠を
# 30秒占有すると16枠が飽和し、後続が20秒待たされて503になる（実測で最大24秒）。
# サーバー側描画（render.pyのsafe_get_sync）も12秒なので、そちらに揃える。
IMAGE_FETCH_TIMEOUT = httpx.Timeout(float(os.getenv("IMAGE_FETCH_TIMEOUT", "12")), connect=5)


def _known_image_host(url: str) -> bool:
    """うちが扱いを知っている配信元（IMAGE_HOST_ALLOWLIST）か。**知らないホスト＝手で貼られたURL**。"""
    from urllib.parse import urlsplit
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in IMAGE_HOST_ALLOWLIST)


def _host_allowed(url: str) -> bool:
    """許可ホスト（末尾一致）か公開アドレスだけ。私設・ループバック宛て（SSRF）は拒否。リダイレクト先もnetguardが検査する。"""
    return netguard.url_ok(url, IMAGE_HOST_ALLOWLIST)


IMAGE_R2_PREFIX = "imgcache/"
# 画像をR2へ寄せるか（既定は有効）。R2が無い・公開URLが無い環境では自動で無効になる
IMAGE_TO_R2 = os.getenv("IMAGE_TO_R2", "1") not in ("0", "false", "no")
_IMG_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def _image_r2_key(url: str, ctype: str) -> str:
    """取得元URLからR2のキーを作る。同じ画像は同じキーになる。"""
    return f"{IMAGE_R2_PREFIX}{_image_hash(url)}.{_IMG_EXT.get(ctype, 'bin')}"


def _image_hash(url: str) -> str:
    """R2のキーのうち拡張子より前の部分。索引（_IMG_INDEX）の鍵でもある。"""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


# imgcache/ にあるキーの索引。sha1の頭20桁 → (R2のキー, 最終更新のepoch秒)。起動時に一覧して作る。
#
# cache.sqlite3はコンテナのディスクにあるのでデプロイのたびに消えるが、R2の中身は残っている。
# 索引が無いと、既にR2にある画像を配信元から取り直して上げ直すことになり、入れ替えのたびに
# Renderの転送量（課金対象）が跳ねる（本体68KB × 件数。302なら数百バイト）。
# 一覧は1000件ごとに1回のClass A（実測5,609件で6回）。1件ずつHeadObjectを引くより安く、
# 取得前には分からない拡張子（jpg/png/webp/gif）を知らなくても引ける。
_IMG_INDEX: dict[str, tuple[str, float]] = {}
# 1件あたり150B程度。40万件で60MB（本番のRSSは211MB、割当は2048MB）。
# 2026-09-20に20万から上げた。imgcache/ が132,371件で上限の66% まで来ていたため。
# 超えたぶんは索引に載らず、SQLiteも忘れていればデプロイ直後に配信元から取り直すことになる
_IMG_INDEX_MAX = int(os.getenv("IMAGE_INDEX_MAX", "400000"))

# imgcacheの当たり外れ（60秒ごとに `[img]` で出す）。語やURLは数えない
#   hit   … R2へ302で返せた
#   miss  … 返せず本体を取りに行った
#   put   … R2に置けた
#   stale … putのうち、索引に同じ鍵があったが期限切れだったもの（新しい画像ではなく取り直し）
_img_stats: dict[str, int] = {}


def _note_img(kind: str) -> None:
    _img_stats[kind] = _img_stats.get(kind, 0) + 1


def _image_index_get(url: str) -> str | None:
    """索引に載っていて、まだR2のライフサイクルで消えていなければR2のキー。

    期限はR2_IMAGE_TTL（13日）で切る。R2側の掃除は14日なので、こちらを短くしておかないと
    消えた後もリダイレクトし続けて404になる（cache.get_image_r2keyと同じ理由）。
    """
    ent = _IMG_INDEX.get(_image_hash(url))
    if not ent:
        return None
    key, mtime = ent
    if time.time() - mtime > R2_IMAGE_TTL:
        _IMG_INDEX.pop(_image_hash(url), None)
        _img_stale.add(_image_hash(url))   # 次にputされたら「新しい画像」ではなく「取り直し」と数える
        return None
    return key


# 期限切れで索引から外した鍵。次に同じものがputされたらstaleとして数える（`[img]`）。
# 取り直しがどれだけあるかが分かれば、R2の掃除と索引の期限を延ばす効果を測れる。
# 増え続けないよう、数えたら消す・多すぎれば捨てる
_img_stale: set[str] = set()


def _image_index_put(url: str, key: str) -> None:
    if len(_IMG_INDEX) < _IMG_INDEX_MAX:
        _IMG_INDEX[_image_hash(url)] = (key, time.time())


def _usage_from_metrics() -> int | None:
    """前回の掃除が数えた合計バイト数（`metrics/r2.jsonl` の最後の行）。無ければNone。

    掃除（`scripts/r2_prune.py --append`）はどのみちバケットを1周するので、その数えを持ち越せば
    起動時に全件を一覧しなくて済む（`imgcache/` だけに絞れてClass A 214 → 134回）。

    **多めにずれる側に倒れる**: 最後の掃除より後に消えたものは引かれていない。増えたぶんは
    `storage.add_usage()` が共有の保存ごとに足す。歯止めの用途なので、多めに見えるのは安全な向き。
    ファイルはイメージに焼かれた時点のもの（`metrics/` はbuildFilterに無いのでデプロイは走らない）で、
    古くても数日ぶん。読めなければNoneを返し、呼び出し側が今までどおり全件を数える。
    """
    path = ROOT / "metrics" / "r2.jsonl"
    try:
        last = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last = line
        if not last:
            return None
        n = json.loads(last).get("total_bytes")
        return int(n) if n else None
    except Exception:
        return None


def _load_r2_index(prefix: str = "") -> tuple[dict[str, tuple[str, float]], int]:
    """バケットを1周して (imgcacheの索引, 数えたぶんの合計バイト数) を返す。

    `prefix` を渡すとその接頭辞だけを一覧する（`imgcache/` に絞るとClass A 214 → 134回）。
    **そのとき合計バイト数は絞ったぶんだけ**になるので、全体の使用量として使ってはいけない。
    prefix無しで呼ぶと今までどおり全件で、索引づくりと使用量の集計を1周で兼ねる（2026-09-20）。
    """
    st = storage.get_storage()
    out: dict[str, tuple[str, float]] = {}
    total = 0

    def walk(pfx: str) -> list[tuple[str, int, object]]:
        return list(st.list_objects(pfx))

    # **imgcache/ だけのときは、鍵の頭の16進1文字ごとに16本並べて一覧する**（2026-09-25）。
    # 1本で順に一覧すると14万件で143秒かかり（1000件ごとの呼び出しが順番待ちになる）、その間は
    # R2に控えがあっても見つけられずに配信元から取り直していた（デプロイ直後にニコニコのサムネ49枚が
    # 遅いと利用者から）。呼び出しの回数（Class A）は同じ。鍵は _image_hashの16進なので16通りで漏れない。
    # **同時に走らせるのは4本まで**（2026-09-27）。16本同時だと応答のXMLの読み取りがGILを取り合い、
    # 1 vCPUの本番ではデプロイのたびにイベントループが2〜5秒止まった（点検の [loop] lag）。
    # 手元を1コアに絞って測ると、16本は14秒・遅れ最大0.87秒、4本は35秒・0.14秒、1本は100秒・0.08秒
    if prefix == IMAGE_R2_PREFIX:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            parts = list(ex.map(walk, [f"{IMAGE_R2_PREFIX}{h}" for h in "0123456789abcdef"]))
        rows = [r for part in parts for r in part]   # 索引が拾うのは16進20桁の鍵だけなので、ほかの形の鍵は要らない
    else:
        rows = walk(prefix)
    for key, size, modified in rows:
        total += size
        if not key.startswith(IMAGE_R2_PREFIX):
            continue
        name = key[len(IMAGE_R2_PREFIX):].rsplit(".", 1)[0]
        if len(name) == 20 and len(out) < _IMG_INDEX_MAX:   # _image_hashが作るsha1の頭20桁だけを拾う
            out[name] = (key, modified.timestamp())
    return out, total


async def _seed_r2_index() -> None:
    """起動後にR2を1周して、imgcacheの索引と使用量をまとめて作る。

    失敗しても、画像は取り直すだけ・使用量は `_usage_loop` が次の回で拾い直すだけなので握りつぶす。
    """
    st = storage.get_storage()
    if not st.is_remote:
        return
    want_index = IMAGE_TO_R2 and bool(st.public_url(""))
    # 使用量を掃除の記録から持ち越せたら、一覧はimgcache/ だけで済む（Class A 214 → 134回）。
    # 持ち越せなければ今までどおり全件を1周して、索引と使用量をまとめて作る
    carried = _usage_from_metrics()
    try:
        got, total = await asyncio.to_thread(_load_r2_index, IMAGE_R2_PREFIX if carried else "")
    except Exception as e:
        print(f"[error] R2の一覧を取れませんでした: {type(e).__name__}: {e}")
        return
    if carried:
        storage.set_usage(carried)
        print(f"[storage] 使用量{carried / 1024**3:.1f} GB（前回の掃除の数えから。一覧はimgcache/ だけ）")
    else:
        storage.set_usage(total)
        print(f"[storage] 使用量{total / 1024**3:.1f} GB（起動時の一覧から）")
    if want_index:
        _IMG_INDEX.update(got)
        print(f"[storage] imgcacheの索引: {len(_IMG_INDEX)}件（デプロイ後の取り直しを防ぐ）")


async def _usage_loop() -> None:
    """R2の使用量を裏で数え直す（共有の容量の上限に使う。`storage.usage_cached`）。

    全件の一覧に2分ほどかかるので、共有の保存の途中では数えない（2026-09-19）。
    **起動直後の1回は `_seed_r2_index()` が済ませているので、先に眠ってから数える**（2026-09-20）。
    同じ一覧を2回回さないため。`_seed_r2_index()` が落ちた場合はここが次の回で拾い直す
    （それまで `usage_cached()` はNoneを返し、上限判定は通す。歯止めなので許容する）。
    """
    while True:
        await asyncio.sleep(storage.USAGE_CACHE_SEC)
        try:
            t0 = time.monotonic()
            n = await asyncio.to_thread(storage.usage_bytes, True)
            print(f"[storage] 使用量{n / 1024**3:.1f} GB（数えるのに{time.monotonic() - t0:.0f}秒）")
        except Exception as e:
            print(f"[error] R2の使用量を数えられませんでした: {type(e).__name__}: {e}")


async def _image_r2_redirect(url: str) -> Response | None:
    """R2に寄せ済みならそこへ302。まだならNone（呼び出し元が本体を返す）。

    画像1枚77KBに対してリダイレクトの応答は数百バイトなので、Renderの転送量（課金対象）が
    ほぼ無くなる。ブラウザはfetch + createImageBitmapで読むため、R2側のCORSと
    CSPのconnect-src（_r2_origin）が要る。どちらもフォントをR2に移したときに整えてある。
    """
    if not IMAGE_TO_R2:
        return None
    # SQLiteが忘れていても（デプロイでコンテナのディスクごと消える）、R2に現物が残っていれば索引で引ける
    key = await asyncio.to_thread(cache.get_image_r2key, url) or _image_index_get(url)
    if not key:
        _note_img("miss")
        return None
    public = storage.get_storage().public_url(key)
    if not public:
        _note_img("miss")
        return None
    _note_img("hit")
    return RedirectResponse(public, status_code=302, headers={"Cache-Control": "public, max-age=86400"})


async def _image_to_r2(url: str, ctype: str, data: bytes) -> None:
    """画像をR2に置き、次からは302で返せるようにする。失敗しても本体は返せるので握りつぶす。"""
    st = storage.get_storage()
    if not IMAGE_TO_R2 or not st.is_remote or not st.public_url(""):
        return
    key = _image_r2_key(url, ctype)
    try:
        await asyncio.to_thread(st.put, key, data, ctype)
        await asyncio.to_thread(cache.mark_image_r2, url, key)
        _image_index_put(url, key)   # SQLiteの行が掃除されても索引だけで302を返せるように
        _note_img("put")
        if _image_hash(url) in _img_stale:
            _img_stale.discard(_image_hash(url))
            _note_img("stale")   # 新しい画像ではなく、期限切れによる取り直し
    except Exception as e:
        print(f"[error] 画像をR2に置けませんでした: {type(e).__name__}: {e}")


_R2_TASKS: set[asyncio.Task] = set()
_R2_TASKS_MAX = int(os.getenv("IMAGE_R2_TASKS_MAX", "64"))


def _image_to_r2_bg(url: str, ctype: str, data: bytes) -> None:
    """R2への書き込みを応答の後ろに回す（待たない）。

    putはconnect_timeout 3秒 × リトライ3回＋バックオフで10秒を超えることがあり、awaitすると
    その分そのまま利用者の待ち時間になる（/s/* を14.3秒 → 1.0秒にしたのと同じ話）。
    次回以降302で返すためのキャッシュなので、落としても応答は正しい。
    R2が不調なときに溜め込まないよう、走っている本数が _R2_TASKS_MAXを超えたら諦める。
    """
    if len(_R2_TASKS) >= _R2_TASKS_MAX:
        return
    t = asyncio.create_task(_image_to_r2(url, ctype, data))
    _R2_TASKS.add(t)
    t.add_done_callback(_R2_TASKS.discard)


class ImageWant(BaseModel):
    u: str = Field(max_length=2048)
    px: int = Field(0, ge=0, le=2000)


class ImageWantList(BaseModel):
    items: list[ImageWant] = Field(default_factory=list, max_length=300)


@router.post("/image-r2")
async def image_r2(body: ImageWantList) -> dict:
    """それぞれの画像がR2のどこにあるかを、まとめて答える（取得はしない）。

    **ブラウザが共有画像を描くときは、302を挟まずにR2を直接読む**ためのもの。
    `/image-proxy` の302を追わせると、ブラウザは別オリジンへのリダイレクトとして
    `Origin: null` で取りに行くことになり、まとめて読むと総崩れになることがある
    （2026-09-15に実測: R2直読み240/240成功、302経由は120/120失敗）。
    R2に無いものはnullを返し、呼ぶ側は今までどおり `/image-proxy` に取りに行く。
    """
    out: list[str | None] = []
    for it in body.items:
        url = it.u
        if not url or uploads.is_upload_url(url) or not await asyncio.to_thread(_host_allowed, url):
            out.append(None)
            continue
        want = max(100, min(600, it.px or 600))
        for _src in (itunes, bandcamp, video, soundcloud, musicbrainz):
            url = _src.clamp_size(url, want)
        shrink_px = min(600, -(-want // 200) * 200) if (otodb.is_otodb_image(url) or not _known_image_host(url)) else 0
        ckey = f"{url}#px={shrink_px}" if shrink_px else url
        key = await asyncio.to_thread(cache.get_image_r2key, ckey) or _image_index_get(ckey)
        out.append((storage.get_storage().public_url(key) if key else None) or None)
    return {"urls": out}


@router.get("/image-proxy")
async def image_proxy(request: Request, url: str = Query(..., description="取得する画像URL", max_length=2048),
                      px: int = Query(0, ge=0, le=2000, description="欲しい実寸（マスが小さいときだけ指定する）"),
                      direct: int = Query(0, ge=0, le=1, description="1ならR2へ302せず本体を返す")) -> Response:
    """外部画像を同一オリジンで返す（CanvasのCORS/tainted回避）。取得結果はSQLiteにキャッシュ。

    二度目以降は本体を返さずR2へ302で送る（_image_r2_redirect）。IMAGE_TO_R2=0で止められる。

    direct=1は302を挟まず本体を返す。共有画像を描くブラウザは1枚ずつfetchするが、
    R2の公開URL（r2.dev）はまとまった数を続けて読むと落ちることがあり、256マスだと
    ジャケットがごっそり抜けた画像ができていた。ブラウザ側はR2で失敗したらこれで取り直す。
    """
    if uploads.is_upload_url(url):
        got = await run_in_threadpool(uploads.read_bytes, url)
        if got is None:
            raise HTTPException(404, "アップロード画像が見つかりません（期限切れの可能性）")
        return Response(content=got[0], media_type=got[1], headers={"Cache-Control": "public, max-age=86400"})
    if not await asyncio.to_thread(_host_allowed, url):   # 許可ホスト以外は名前解決（同期）を伴うのでスレッドで
        raise HTTPException(403, "このホストの画像は取得できません（私設アドレスや解決できないホスト）")
    # 保存済みのグリッドが持つ大きすぎるURL（iTunesの1000x1000、Bandcampとbilibiliの原寸）を
    # 欲しい実寸に合わせて取り直す。ホストは変わらないので検査の後でよい。
    # pxはマスが小さいとき（8x8以上）にブラウザが指定する。既定は書き出しのマスと同じ600
    want = max(100, min(600, px or 600))
    url = _nico_legacy_thumb(url)
    orig = url
    for _src in (itunes, bandcamp, video, soundcloud, musicbrainz):
        url = _src.clamp_size(url, want)
    # otoDBだけはURLに大きさを指定できないので、取ったあとにこちらで縮める。
    # 大きさごとに別のキャッシュになるので、刻みを200px単位にして種類を3つ（200/400/600）に抑える
    # 小さい版を選べない画像は、こちらで縮めてから返す。対象は2つ:
    #   ・otoDB … URLに大きさを指定する仕組みが無い
    #   ・**利用者が手で貼ったURL** … どこのサイトか分からないのでclamp_sizeが効かない。
    #     原寸のまま通すと、マス（600px）には過剰な画素をブラウザが毎回読むことになる
    #     （実測: 3000x3000がそのまま出ていた）
    shrink_px = min(600, -(-want // 200) * 200) if (otodb.is_otodb_image(url) or not _known_image_host(url)) else 0
    ckey = f"{url}#px={shrink_px}" if shrink_px else url   # キャッシュとR2のキー。取得元はurlのまま
    if not direct and (redirect := await _image_r2_redirect(ckey)) is not None:
        return redirect
    hit = await asyncio.to_thread(cache.get_image, ckey)
    if hit:
        ctype, data = hit
        _image_to_r2_bg(ckey, ctype, data)   # 既にキャッシュ済みの分も、一度返すついでにR2へ寄せる
    elif (_miss := _IMG_MISSING.get(ckey)) and _miss[0] > time.time():
        # **配信元に無かった画像はIMG_MISSING_TTLのあいだ取りに行かない**（2026-09-17）。消えた画像が
        # 人気の共有に1枚入っているだけで、見られるたびに配信元へ取りに行き、2時間で1,000件の404になっていた。
        # つながらなかった画像（502）もIMG_UNREACHABLE_TTLのあいだ同じ扱い（2026-09-18）。
        # 応答が遅くて読み取りが時間切れになった画像（502）はIMG_SLOW_TTLのあいだ（2026-09-25）
        if _miss[1] == 404:
            raise HTTPException(404, "配信元に画像が無い（しばらく前に確かめた）")
        raise HTTPException(502, "配信元につながらない（しばらく前に確かめた）")
    else:
        # 配信元からの取得の同時本数をIMAGE_PROXY_CONCURRENCYで絞る（既定16）。
        # 取りこぼすと503になるので、CPUの割当を変えたらこちらも見直す（0.1 vCPUの頃は8本だった）
        try:
            await asyncio.wait_for(_PROXY_SEM.acquire(), timeout=20)
        except asyncio.TimeoutError:
            raise HTTPException(503, "画像の取得が混み合っています", headers={"Retry-After": "5"})
        try:
            shrink_to = shrink_px
            try:
                ctype, data = await fetch_image(url, request.app.state.http)
            except HTTPException as e:
                if e.status_code != 404:
                    if (ttl := _retry_after(e)):
                        _remember_missing(ckey, 502, ttl)
                    raise
                # **配信元に無ければ、別の版を順に取りに行く**（2026-09-17）: 縮小版のURLを書き換える前の原寸、
                # YouTubeのhqdefault → mqdefault → default、ニコニコの .L → 無印。どれも無ければ404を覚える
                got = None
                for alt in _image_fallbacks(url, orig):
                    try:
                        got = await fetch_image(alt, request.app.state.http)
                        break
                    except HTTPException as e2:
                        if e2.status_code != 404:
                            raise
                if got is None:
                    _remember_missing(ckey)
                    raise
                ctype, data = got
                shrink_to = shrink_px or want   # 原寸は大きいことがあるので、こちらで縮める
            if imgtools.is_video_thumb(url):
                # 動画サムネイルの黒帯（レターボックス）を落とす。プレビューと書き出しで同じ見た目になる
                data, ctype = await asyncio.to_thread(imgtools.trim_letterbox_bytes, data, ctype)
            if shrink_to:
                data, ctype = await asyncio.to_thread(imgtools.shrink_bytes, data, ctype, shrink_to)
            await asyncio.to_thread(cache.set_image, ckey, ctype, data)
        finally:
            _PROXY_SEM.release()
        _image_to_r2_bg(ckey, ctype, data)
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})


_PROXY_SEM = asyncio.Semaphore(max(1, int(os.getenv("IMAGE_PROXY_CONCURRENCY", "16"))))
IMG_MISSING_TTL = int(os.getenv("IMG_MISSING_TTL", "3600"))   # 配信元に無かった画像を覚えておく秒数
IMG_UNREACHABLE_TTL = int(os.getenv("IMG_UNREACHABLE_TTL", "600"))   # 配信元につながらなかった画像を覚えておく秒数
# 応答が遅く、読み取りが時間切れになった画像を覚えておく秒数（2026-09-25）。遅いだけで次は取れることもあるので
# つながらなかったときより短くする。覚えないと、開き直すたびにIMAGE_FETCH_TIMEOUT（12秒）待たせて502を返し、
# _PROXY_SEMの枠も12秒ふさぐ（9/25の点検でp1.music.126.netのReadTimeoutが2時間に4件。手で入れたURL）
IMG_SLOW_TTL = int(os.getenv("IMG_SLOW_TTL", "300"))
_IMG_MISSING: dict[str, tuple[float, int]] = {}                 # キャッシュのキー → (期限（time.time()）, 返す状態)

# ニコニコの古いサムネイルのドメイン（`tn.smilevideo.jp/smile?i=N`）。**ドメインごと応答しない**
# （2026-09-18の点検で接続の時間切れが2時間に66件。1件ごとにIMAGE_FETCH_TIMEOUTだけ待たせていた）。
# 同じ画像は今のCDNの `nicovideo.cdn.nimg.jp/thumbnails/N/N` にある（sm9で確認）
_NICO_LEGACY = re.compile(r"^https?://tn(?:-skr\d+)?\.smilevideo\.jp/smile\?i=(\d+)(?:\.L)?$")


def _nico_legacy_thumb(url: str) -> str:
    """古いドメインのニコニコのサムネイルを、今のCDNのURLに書き換える。"""
    m = _NICO_LEGACY.match(url)
    return f"https://nicovideo.cdn.nimg.jp/thumbnails/{m.group(1)}/{m.group(1)}" if m else url


def _retry_after(e: HTTPException) -> int:
    """取り直すまで待つ秒数。つながらなかった（接続の時間切れ・拒否）ならIMG_UNREACHABLE_TTL、
    応答が遅かった（読み取り・書き込みの時間切れ）ならIMG_SLOW_TTL、それ以外（配信元の5xxなど）は0＝覚えない。"""
    if isinstance(e.__cause__, (httpx.ConnectTimeout, httpx.ConnectError)):
        return IMG_UNREACHABLE_TTL
    if isinstance(e.__cause__, (httpx.ReadTimeout, httpx.WriteTimeout)):   # PoolTimeoutはこちらの混雑なので覚えない
        return IMG_SLOW_TTL
    return 0


def _image_fallbacks(url: str, orig: str) -> list[str]:
    """配信元に無かったときに試す別の版。順に試す（重複は除く）。"""
    out: list[str] = []
    for u in (url, orig):
        if "i.ytimg.com/vi/" in u:
            for a, b in (("/hqdefault.jpg", "/mqdefault.jpg"), ("/hqdefault.jpg", "/default.jpg"), ("/mqdefault.jpg", "/default.jpg")):
                if a in u:
                    out.append(u.replace(a, b))
        if u.endswith(".L") and "nimg.jp" in u:
            out.append(u[:-2])
    if orig != url:
        out.insert(0, orig)
    seen: set[str] = set()
    return [u for u in out if u != url and not (u in seen or seen.add(u))]


def _remember_missing(ckey: str, status: int = 404, ttl: int = 0) -> None:
    """配信元に無かった（404）・つながらなかった／遅すぎた（502）画像を覚える。膨らみすぎたら丸ごと忘れる（取り直すだけで壊れない）。
    ttlを省くと、404はIMG_MISSING_TTL、502はIMG_UNREACHABLE_TTL。"""
    if len(_IMG_MISSING) >= 5000:
        _IMG_MISSING.clear()
    ttl = ttl or (IMG_MISSING_TTL if status == 404 else IMG_UNREACHABLE_TTL)
    _IMG_MISSING[ckey] = (time.time() + ttl, status)


def _host_of(url: str) -> str:
    """ログに添えるホスト名（URL全体は利用者のデータなので出さない）。"""
    try:
        return (urllib.parse.urlsplit(url).hostname or "?")[:60]
    except Exception:
        return "?"


def _s3_missing(r: httpx.Response) -> bool:
    """S3をそのまま公開している配信元の「無い」か。

    一覧の権限を与えていないバケットは、**存在しないキーに404ではなく403 AccessDeniedを返す**
    （cdn.piapro.jpで確かめた。2026-09-25）。502のまま数えると点検の5xxに紛れ、
    別の版の取り直しや「しばらく覚えて取りに行かない」も効かないので、404と同じに扱う。
    """
    if r.status_code != 403 or "xml" not in r.headers.get("content-type", ""):
        return False
    return b"<Code>AccessDenied</Code>" in r.content[:512]


async def fetch_image(url: str, client: httpx.AsyncClient) -> tuple[str, bytes]:
    """画像を取得して (content-type, bytes) を返す。失敗はHTTPException。clientは共有のもの（`app.state.http`）"""
    try:
        # 画像CDNの中には汎用UAを弾くものがある（Wikimedia等）ためブラウザ風にする。リダイレクトは1ホップずつ宛先を検査
        r = await netguard.safe_get(client, url, allowlist=IMAGE_HOST_ALLOWLIST, timeout=IMAGE_FETCH_TIMEOUT,
                                    headers={"User-Agent": "Mozilla/5.0 (compatible; trackmento/0.1)", "Accept": "image/*,*/*;q=0.8"})
    except netguard.BlockedURL as e:
        raise HTTPException(403, str(e)) from e
    except httpx.HTTPError as e:
        # **配信元のホスト名だけ理由に添える**（2026-09-17）。点検で「404が1,039件」と出ても、どの配信元かが
        # 分からず手が打てなかった。URL全体は利用者のデータなので出さない（ホストは出どころの種類にすぎない）
        raise HTTPException(502, f"取得失敗 ({_host_of(url)}): {type(e).__name__} {e}"[:120]) from e
    if r.status_code == 404 or _s3_missing(r):
        # **配信元に無いものは404で返す**（2026-09-17）。こちらの障害ではないのに502で数えていたので、
        # 点検の「5xx」に消えた画像（削除された動画のサムネイルなど）が混ざり、本当の障害が埋もれていた
        raise HTTPException(404, f"配信元に画像が無い ({_host_of(url)})")
    if r.status_code != 200:
        raise HTTPException(502, f"画像サーバーが{r.status_code}を返しました ({_host_of(url)})")
    ctype = r.headers.get("content-type", "").split(";")[0].strip()
    if not ctype.startswith("image/"):
        # Content-Typeを付けずに返す配信元がある（otoDBのCDNが実際にそう。
        # 200で中身も画像なのにヘッダが無く、ヘッダだけ見ていると全部415で弾いてしまう）。
        # 中身の先頭を見て画像だと分かるなら、その型として通す
        ctype = imgtools.sniff_image_type(r.content) or ""
        if not ctype:
            raise HTTPException(415, f"画像ではありません: {r.headers.get('content-type', '(型なし)')}")
    if len(r.content) > IMAGE_MAX_BYTES:
        raise HTTPException(413, "画像が大きすぎます")
    return ctype, r.content
