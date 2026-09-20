"""VocaDB（ボーカロイド楽曲のデータベース）。

- 検索: https://vocadb.net/api/songs?query=…&fields=ThumbUrl,PVs,Artists&lang=Japanese
  作曲者と歌声を「ハチ feat. 初音ミク」の形に組むので（`artist_name`）、作者と歌声合成ソフトがまとめて手に入る。
  iTunes に配信の無いボカロ曲でも引ける
- **並べ替えを指定しないと原曲が上に来ない**。`sort=RatingScore` と `preferAccurateMatches=true` を
  付けると「メルト」で ryo の原曲が 1 位になる（付けないと歌ってみた・REMIX が先に並ぶ。実測）
- ジャケットは `thumbUrl` をそのまま使わない。YouTube のものは `default.jpg`（120x90・4.8KB）で、
  マス（600px）には粗すぎる。**`hqdefault.jpg`（480x360・39KB）へ URL を書き換える**
  （`clamp_size` と同じ考え方で、こちらで縮めたり拡大したりはしない）。
  ニコニコの CDN は素の URL が 130x100 しか無いので `.L`（360x270）を足す。ただし
  **古い動画には大きい版が無い**（実測で 17,000,000 番台までは 404、19,000,000 番台から 200）ので、
  番号で線を引く（`NICO_L_FROM`）

キーは要らない。データは CC ライセンスなので、画面のフッターに出典を出している。
"""
from __future__ import annotations

import asyncio
import re
import time
import unicodedata

import httpx

from backend import searchcache
from backend.models import Track

API = "https://vocadb.net/api/songs"

# ---- 外へ出すときの門（2026-09-20）----
# VocaDB から「1 分に 2 回くらいなら気にする量ではない。できれば**間隔を空けて、同時に多く送らない**でほしい」
# と返答をもらった（問い合わせへの回答）。数の上限ではなく**出し方**の要望なので、
# **VocaDB へのすべての要求**（検索・動画 ID・題からの検索）をこの門に通す。
#   - `_GATE` … 同時に出す本数。3 → 2
#   - `MIN_GAP` … 直前の要求からこれだけ空ける。まとめて貼られたときも階段状に出る
# マイリストの穴埋めは全体 10 秒で打ち切るので、間隔を空けたぶん埋まる数は減る（正しさより行儀を取る）
_GATE = asyncio.Semaphore(2)
_gap_lock = asyncio.Lock()
_last_call_at = 0.0
MIN_GAP = 0.5


async def _pace() -> None:
    """直前の要求から MIN_GAP 秒は空ける（プロセス全体で 1 本の列）"""
    global _last_call_at
    async with _gap_lock:
        wait = MIN_GAP - (time.monotonic() - _last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_at = time.monotonic()
UA = "trackmento/0.1 (+https://trackmento.com)"
PAGE = 30            # 1 回に取る件数の上限（VocaDB 側は 50 まで受けるが、候補パネルに合わせる）
TIMEOUT = 20         # 実測で 1.6〜2.8 秒。iTunes より遅いので、選んだときだけ引く
# 元ページの URL を組み立てられる PV の種類（曲名リストのリンク先に使う）
_WATCH = {"NicoNicoDouga": "https://www.nicovideo.jp/watch/{}",
          "Youtube": "https://www.youtube.com/watch?v={}",
          "Bilibili": "https://www.bilibili.com/video/{}"}


# ニコニコの大きいサムネイル（`.L`）が存在する動画番号の下限。**実測で線を引いた**
# （17,000,000 番台までは 404、19,000,000 番台から 200）。古い動画は素の 130x100 のまま使う
NICO_L_FROM = 19_000_000
_NICO_THUMB = re.compile(r"^https://nicovideo\.cdn\.nimg\.jp/thumbnails/(\d+)/(\d+)$")


def clamp_size(url: str) -> str:
    """サムネイルを大きい版に差し替える。**URL の書き換えだけ**（再エンコードはしない）。

    - YouTube … VocaDB が返すのは `default.jpg`（120x90・4.8KB）で、マス（600px）には粗い。
      `hqdefault.jpg` は 480x360・39KB で、どの動画にも必ずある（`sddefault` は無いことがある）
    - ニコニコ … 素の URL は 130x100。`.L` を足すと 360x270 になる（`NICO_L_FROM` 以降の動画だけ）
    """
    if "i.ytimg.com/vi/" in url:
        return url.replace("/default.jpg", "/hqdefault.jpg")
    m = _NICO_THUMB.match(url)
    if m and m.group(1) == m.group(2) and int(m.group(1)) >= NICO_L_FROM:
        return url + ".L"
    return url


def _links(item: dict) -> str | None:
    """曲名リストのリンク先。PV があればその動画のページ、無ければ VocaDB の曲のページ。"""
    for pv in item.get("pvs") or []:
        tmpl, pv_id = _WATCH.get(pv.get("service") or ""), (pv.get("pvId") or "").strip()
        if tmpl and pv_id:
            return tmpl.format(pv_id)
    return f"https://vocadb.net/S/{item.get('id')}" if item.get("id") else None


# 役割がこれだけの参加者は、アーティスト名から外す（曲を作った人ではなく、出した会社・チャンネル）
_PUBLISHER_ROLES = {"Publisher", "Distributor"}


def artist_name(item: dict) -> str:
    """曲のアーティスト名。VocaDB の `artistString`（「ハチ feat. 初音ミク」）から**発行元だけの名前を外したもの**。
    `artistString` は発行元のサークルも並べるので、「Tell Your World」が「kz, Google feat. 初音ミク」、
    「崩壊歌姫」が「マチゲリータ, ProjectDIVAチャンネル feat. 初音ミク」になっていた（2026-09-19、利用者の指摘）。
    作曲者だけで組み直すと、「Omoi」のような作り手のユニット（サークル扱い）まで消えるので、外すのは
    役割が発行元・販売元だけのもの。`fields=Artists` が無いときは `artistString` のまま"""
    text = (item.get("artistString") or "").strip()
    drop = set()
    for a in item.get("artists") or []:
        roles = {r.strip() for r in (a.get("roles") or "").split(",") if r.strip()}
        if roles and roles <= _PUBLISHER_ROLES and "Producer" not in (a.get("categories") or ""):
            drop.add((a.get("name") or "").strip())
    if not drop:
        return text
    bits = re.split(r"(\s+feat\.?\s+)", text, maxsplit=1)
    makers = [m for m in (x.strip() for x in bits[0].split(",")) if m and m not in drop]
    if not makers:
        return text   # 全部外れるなら元のまま（名前が空になるよりよい）
    return ", ".join(makers) + "".join(bits[1:])


# ---- 外へ聞いた回数を数える（2026-09-20）----
# VocaDB は有志の運営で、問い合わせが多すぎると止められうる。`[srch]` は「検索」しか数えないので、
# 種類（検索・動画 ID・題）ごとに「外へ聞いた」「覚えていた（メモリ / R2）」を数えて 60 秒ごとに出す。
# **語そのものは数えない**（`[src]` や `[ua]` と同じ方針）
CALLS: dict[str, int] = {}


def note_call(kind: str) -> None:
    CALLS[kind] = CALLS.get(kind, 0) + 1


def take_calls() -> dict[str, int]:
    """数えた分を返して空にする（`main.py` のログの 60 秒ごとの出力から呼ぶ）"""
    got = dict(CALLS)
    CALLS.clear()
    return got


def query_key(q: str, artist: str = "") -> str:
    """VocaDB に送る語。**曲名だけ**（無ければアーティスト名）を、表記の揺れをそろえてから使う（2026-09-20）。

    VocaDB は有志の運営で「1 日数千件の問い合わせには事前の許可が要る」としているので、外へ聞く回数を
    減らす。同じ曲を別のアーティスト名で引いた検索（「メルト ryo」と「メルト supercell」）も、
    表記が違うだけの検索（「ｼｬﾙﾙ」「シャルル」「Tell Your World」「tell  your world 」）も、
    **VocaDB へは 1 回**にまとまる。アーティストでの絞り込みは手元で行う（`narrow`）。

    そろえ方は `merge._n` と同じ NFKC ＋ casefold（半角カナ・全角英数・単独の濁点を吸収）に、
    続く空白を 1 つにまとめたもの。**記号は落とさない**（`_n` は落とすが、VocaDB に送る語が
    変わると結果まで変わりかねない。そろえるのは、同じ語だとはっきり言える揺れだけ）"""
    text = (q.strip() or artist.strip()).replace("゛", "゙").replace("゜", "゚")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).casefold()).strip()


def narrow(tracks: list[Track], q: str, artist: str) -> list[Track]:
    """曲名だけで引いた結果を、手元でアーティスト名で絞る。1 件も残らなければ絞らずに返す
    （表記が違うだけのことがある）。**外へ聞き直さない**ので、控えは曲名だけで共有できる"""
    if not (q.strip() and artist.strip()):
        return tracks
    from backend.merge import _n
    key = _n(artist)
    return [t for t in tracks if key and key in _n(t.artist)] or tracks


async def search(q: str, artist: str = "", *, limit: int = PAGE,
                 client: httpx.AsyncClient | None = None) -> list[Track]:
    """VocaDB を検索する。原曲が上に来るように評価の高い順で引く。

    **`main.py` からは曲名だけの語（`query_key`）で呼ばれ、アーティストでの絞り込みは呼び出し側
    （`narrow`）で行う**。ここに artist を渡しても同じ結果になるが、控えの鍵が分かれる"""
    # **query は曲名だけ**（無ければアーティスト名）。「シャルル バルーン」のように 2 つをつなぐと
    # VocaDB は曲名にその全文が含まれるものを探して 0 件になる（artistName パラメータは無視される。実測）。
    # 半角の濁点（ﾊﾞ）や単独の濁点（ハ゛）は merge._n / query_key が吸収する
    query = query_key(q, artist)
    if not query:
        return []
    note_call("search")
    own = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        async with _GATE:
            await _pace()
            r = await client.get(API, params={
                "query": query, "maxResults": max(1, min(limit, PAGE)),
                "nameMatchMode": "Auto", "sort": "RatingScore", "preferAccurateMatches": "true",
                "fields": "ThumbUrl,PVs,Artists", "lang": "Japanese",
            }, headers={"User-Agent": UA})
        r.raise_for_status()
        items = (r.json() or {}).get("items") or []
    finally:
        if own:
            await client.aclose()

    out: list[Track] = []
    for it in items:
        title = (it.get("name") or "").strip()
        image = clamp_size((it.get("thumbUrl") or "").strip())
        if not (title and image):
            continue
        out.append(Track(
            source="vocadb",
            title=title,
            # 「ハチ feat. 初音ミク」。feat. の前が作者なので、そのまま出すと曲の並びで読みやすい
            artist=artist_name(it),
            album=None,
            image=image,
            thumb=image,
            external_url=_links(it),
        ))
    return narrow(out, q, artist)


# ---- 投稿者名が取れない動画のアーティスト名を補う ----
# ニコニコの API は、投稿者が退会したか情報を非公開にした動画だと投稿者名を返さない（`getthumbinfo` に
# user_nickname も ch_name も無い）。VocaDB は動画 ID から曲を引けるので、登録があれば作者名で埋める
# （2026-09-19。利用者の共有「私を構成するボカロ曲25選」で 25 曲中 2 曲のアーティスト名が空だった）。
# VocaDB は有志の運営なので、同時に 3 本まで・結果は見つからなかった分も 1 日覚える
BY_PV = "https://vocadb.net/api/songs/byPv"
PV_TIMEOUT = 8
PV_TTL = 86400
PV_CACHE_MAX = 5000
_pv_cache: dict[tuple[str, str], tuple[float, str]] = {}   # (サービス, 動画 ID) → (時刻, アーティスト名。無ければ "")

# 作者名の控えを R2 にも置く（2026-09-20）。メモリの控えは 1 日もつが、**デプロイのたびにプロセスごと消える**。
# ほぼ毎日デプロイしているので、同じマイリストを貼り直すたびに VocaDB へ聞き直していた。
# 検索結果と同じ仕組み（`searchcache`。鍵は HMAC で、中身に動画 ID や題は入らない）に、
# 擬似ソース `vocadb-pv` / `vocadb-title` として置く。**見つからなかった分（空文字）も覚える**
# （転載や未登録の動画のほうが多く、そちらこそ聞き直さない意味がある）
R2_TTL = 6 * 24 * 3600


async def _remembered(kind: str, key: str) -> str | None:
    """R2 の控え。アーティスト名（見つからなかったなら空文字）。控えが無いときだけ None"""
    try:
        rows = await asyncio.to_thread(searchcache.get, f"vocadb-{kind}", key, "", R2_TTL)
    except Exception:
        return None
    if rows and isinstance(rows[0], dict) and "artist" in rows[0]:
        note_call(f"{kind}_r2")
        return str(rows[0].get("artist") or "")
    return None


def _remember(kind: str, key: str, name: str) -> None:
    searchcache.put_bg(f"vocadb-{kind}", key, "", [{"artist": name}])


async def artist_by_pv(pv_id: str, *, service: str = "NicoNicoDouga",
                       client: httpx.AsyncClient | None = None) -> str:
    """動画 ID から VocaDB の作者と歌声（「マチゲリータ feat. 初音ミク」の形、`artist_name`）。無い・失敗なら空文字"""
    key = (service, pv_id)
    now = time.monotonic()
    hit = _pv_cache.get(key)
    if hit and now - hit[0] < PV_TTL:
        note_call("pv_mem")
        return hit[1]
    kept = await _remembered("pv", f"{service}/{pv_id}")
    if kept is not None:
        _pv_cache[key] = (now, kept)
        return kept
    note_call("pv")
    own = client is None
    client = client or httpx.AsyncClient(timeout=PV_TIMEOUT)
    name = ""
    try:
        async with _GATE:
            await _pace()
            r = await client.get(BY_PV, params={"pvService": service, "pvId": pv_id, "fields": "Artists", "lang": "Japanese"},
                                 headers={"User-Agent": UA}, timeout=PV_TIMEOUT)
        if r.status_code == 200 and r.content.strip() not in (b"", b"null"):
            name = artist_name(r.json() or {})
    except (httpx.HTTPError, ValueError):
        return ""   # 失敗は覚えない（一時的な不調で空が 1 日固定されないように）
    finally:
        if own:
            await client.aclose()
    if len(_pv_cache) >= PV_CACHE_MAX:
        _pv_cache.clear()
    _pv_cache[key] = (now, name)
    _remember("pv", f"{service}/{pv_id}", name)
    return name


# ---- 転載の動画は、題から曲を探して作者を補う ----
# 転載（再投稿）の動画は VocaDB に動画 ID の登録が無いので `artist_by_pv` では埋まらない。
# 題には「livetune feat. 初音ミク【Tell Your World】Music Video」のように曲名が入っているので、
# 括弧の中などから曲名の候補を取り出して VocaDB で探す（2026-09-19、利用者の提案）。
# **間違った作者名は空欄より悪い**ので、次をすべて満たすものだけ採る:
#   - VocaDB の曲名（別名を含む）が題に含まれる
#   - 原曲（songType が Original）。歌ってみた・リミックスを除く（同じ題のリミックスが先に来ることがある）
#   - 題に歌声合成ソフトの名前（初音ミク など）があるなら、その曲の歌声にも同じ名前がある（同名の別の曲を除く）
#   - 題に作者名が入っている候補があればそれを優先する。無ければ、当てはまる原曲が 1 つのときだけ
#   - 「歌ってみた」「MAD」「実況」などは曲名の候補にしない（その語を題に持つ別の曲を拾っていた）
# 利用者の「私を構成するボカロ曲25選」で試して、作者が取れていた 23 曲のうち 21 曲で正しい作者、
# 残りは空欄（誤りは 0）。絞る前はリミックスの作者と同名の別の曲の作者を 1 件ずつ拾っていた
_TITLE_NOISE = re.compile(
    # 英字の語は前後が英字でないときだけ（「paranoia」の IA を消さない。\b は「曲PV」の境目を拾えない）
    r"Long version|LONG ver\.?|Full ?ver\.?|fullver\.?|Music ?Video|"
    r"(?<![A-Za-z])(?:PV|MV|feat\.?|vo\.|KAITO|MEIKO|GUMI|IA)(?![A-Za-z])|"
    r"(?:ミク)?オリジナル(?:曲|MV|PV)?|付き|応募曲|修正版|第\d+回[^\s】」』]*|"
    r"(?:歌|踊|弾|演奏し|叩)(?:っ|い)てみた|音?MAD|ゆっくり実況|実況|"
    r"初音ミク|鏡音リン|鏡音レン|巡音ルカ|重音テト", re.I)
# 括弧は同じ種類どうしで対にする（「【初音ミク(とく)】」を「【初音ミク(とく」と読まない）
_TITLE_BR = re.compile(r"「([^」]+)」|『([^』]+)』|【([^】]+)】|\[([^\]]+)\]|〔([^〕]+)〕|\(([^)]+)\)|（([^）]+)）|“([^”]+)”|\"([^\"]+)\"")
# 題に出ていたら「その歌声の曲か」を確かめる名前。VocaDB の artistString の feat. の後ろと突き合わせる
VOICES = ("初音ミク", "鏡音リン", "鏡音レン", "巡音ルカ", "KAITO", "MEIKO", "GUMI", "重音テト", "IA", "結月ゆかり",
          "可不", "flower", "音街ウナ", "ONE", "紲星あかり", "裏命", "星界", "歌愛ユキ", "がくっぽいど", "神威がくぽ")
WEAK_LEAD = 5.0
_title_cache: dict[str, tuple[float, str]] = {}


def _title_queries(title: str) -> list[str]:
    """題から曲名の候補を取り出す（括弧の中身 → 括弧の外）。最大 3 つ"""
    from backend.merge import _n
    out: list[str] = []
    for groups in _TITLE_BR.findall(title):
        m = next(g for g in groups if g)
        c = re.sub(r"[()（）]", " ", _TITLE_NOISE.sub("", m)).strip(" -・/.")
        if len(_n(c)) >= 2 and c not in out:
            out.append(c)
    rest = _TITLE_NOISE.sub("", _TITLE_BR.sub(" ", title)).strip(" -・/.")
    if len(_n(rest)) >= 2 and rest not in out:
        out.append(rest)
    return out[:3]


def _parts(artist_string: str) -> tuple[list[str], list[str]]:
    """「kz, Google feat. 初音ミク Append (Dark)」→ (作者, 歌声の最初の語)"""
    bits = re.split(r"\s+feat\.?\s+", artist_string, maxsplit=1)
    head, tail = bits[0], bits[1] if len(bits) > 1 else ""
    makers = [p.strip() for p in re.split(r"[,、，/]", head) if p.strip()]
    voices = [re.split(r"[\s(]", v.strip())[0] for v in re.split(r"[,、]", tail) if v.strip()]
    return makers, voices


async def artist_by_title(title: str, *, client: httpx.AsyncClient | None = None) -> str:
    """動画の題から VocaDB の曲を探し、確かなときだけ作者と歌声（`artist_name`）を返す。無い・失敗なら空文字"""
    from backend.merge import _n
    now = time.monotonic()
    hit = _title_cache.get(title)
    if hit and now - hit[0] < PV_TTL:
        note_call("title_mem")
        return hit[1]
    kept = await _remembered("title", title)
    if kept is not None:
        _title_cache[title] = (now, kept)
        return kept
    nt = _n(title)
    voiced = [v for v in VOICES if _n(v) in nt]
    own = client is None
    client = client or httpx.AsyncClient(timeout=PV_TIMEOUT)
    name = ""
    try:
        for q in _title_queries(title):
            note_call("title")
            async with _GATE:
                await _pace()
                r = await client.get(API, params={
                    "query": q, "maxResults": 10, "nameMatchMode": "Auto", "sort": "RatingScore",
                    "preferAccurateMatches": "true", "fields": "Names,Artists", "lang": "Japanese",
                }, headers={"User-Agent": UA}, timeout=PV_TIMEOUT)
            r.raise_for_status()
            strong = ""
            weak: dict[str, float] = {}   # アーティスト名 → 評価（同じ作者の別名義の曲は大きいほう）
            for it in (r.json() or {}).get("items") or []:
                if it.get("songType") != "Original":
                    continue
                names = [it.get("name") or ""] + [n.get("value") or "" for n in it.get("names") or []]
                if not any(len(_n(n)) >= 2 and _n(n) in nt for n in names):
                    continue
                artist = artist_name(it)
                makers, voices = _parts(artist)
                if voiced and not any(len(_n(v)) >= 2 and _n(v) in nt for v in voices):
                    continue
                if any(len(_n(m)) >= 2 and _n(m) in nt for m in makers):
                    strong = strong or artist
                weak[artist] = max(weak.get(artist, 0.0), float(it.get("ratingScore") or 0))
            # 題に作者名が無いときは、当てはまる原曲が 1 つに絞れるか、評価が 2 番目の `WEAK_LEAD` 倍以上
            # 離れているときだけ採る（「ハロー」のように同じ名前の原曲がいくつもあると、上位が正しいとは限らない）
            ranked = sorted(weak.items(), key=lambda kv: -kv[1])
            if not strong and ranked and (len(ranked) == 1 or ranked[0][1] >= max(1.0, ranked[1][1]) * WEAK_LEAD):
                name = ranked[0][0]
            else:
                name = strong
            if name:
                break
    except (httpx.HTTPError, ValueError):
        return ""   # 失敗は覚えない
    finally:
        if own:
            await client.aclose()
    if len(_title_cache) >= PV_CACHE_MAX:
        _title_cache.clear()
    _title_cache[title] = (now, name)
    _remember("title", title, name)
    return name


async def artist_for_video(pv_id: str, title: str, *, client: httpx.AsyncClient | None = None) -> str:
    """投稿者名が取れない動画の作者名。動画 ID で引き、無ければ（転載など）題から探す"""
    return await artist_by_pv(pv_id, client=client) or await artist_by_title(title, client=client)
