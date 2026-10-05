"""FastAPIエントリポイント。起動: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import asyncio
import functools
import gzip as gziplib
import hashlib
import json
import os
import re
import secrets
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
import time
from datetime import datetime, timezone
from collections import Counter, defaultdict, deque

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from starlette.datastructures import Headers, MutableHeaders, UploadFile as StarletteUploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import articles, grids, housekeeping, imgtools, netguard, pages, render, searchcache, share, shareindex, storage, support, uploads
from backend.cache import R2_IMAGE_TTL, _search_ttl, cache
from backend.logutil import brief
from backend.config import (app_url_for, base_url_for, cors_origins, frontend_url, max_cells, migrate_to, public_base_url, public_mode,
                            rate_limit_per_minute, share_budget_bytes, share_limits, share_retention_days, trust_proxy)
from backend.grids import GridDoc, GridOptions
from backend.merge import merge
from backend.models import Track
from backend.sources import bandcamp, discogs, fromurl, itunes, musicbrainz, otodb, playlist, soundcloud, video, vocadb

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OUTPUTS = ROOT / "outputs"
GRIDS = ROOT / "grids"
FRONTEND = ROOT / "frontend"
FONTS = ROOT / "fonts"

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
# 1ソースあたりの検索の上限秒。超えたソースは「失敗」扱いにして他の結果を返す。
# 20秒だったのを12秒に下げた（2026-09-16）。MusicBrainzは1秒1回の制限＋順番待ち（MAX_QUEUE 6）＋
# 503の再試行（1.5 + 3秒）で20秒近くまで伸びることがあり、点検で /searchの最大が20.1秒になっていた。
# MusicBrainzはiTunesで0件のときの予備なので、それ以上待たせるより「見つからない」を返すほうが親切
SOURCE_TIMEOUT = 12
# ソースごとの上限秒（無ければSOURCE_TIMEOUT）。VocaDBは選んだときだけ使うソースで、応答に波がある
# （2026-09-19の実測で0.3〜6.5秒、点検で2時間に7件が12秒の時間切れ。利用者から「タイムアウトする」と報告）。
# 12秒はMusicBrainzの予備検索に合わせた値なので、選んで待っているVocaDBには短い
SOURCE_TIMEOUTS = {"vocadb": 25}
# 時間切れでも取得を捨てないソース。裏で最後まで待ち（`SOURCE_HARD_TIMEOUT` まで）、届いた結果を覚える。
# 以前は時間切れを60秒「失敗」として覚えていたので、言われたとおり再検索すると即座にまた失敗が返っていた。
# 今は再検索が走っている取得にそのまま合流するか、覚えた結果を即返す。
# MusicBrainzは入れない（1秒1回の順番待ちの枠を、誰も待っていない取得で握り続けることになる）
KEEP_ON_TIMEOUT = {"vocadb", "otodb"}
SOURCE_HARD_TIMEOUT = 45
_inflight: dict[tuple[str, str, str], asyncio.Task] = {}   # (ソース, 曲名, アーティスト) → 走っている取得
FAIL_TTL = 60         # 失敗した検索を覚えておく秒数（同じ検索の連打を外部に流さない）
_fail_log: dict[str, list] = {}   # (ソース名 + 理由) → [最後に出した時刻, その後の省略件数]。同じ失敗は60秒に1行


def _log_search_failure(name: str, reason: str) -> None:
    """同じソース・同じ理由の失敗は60秒に1行にまとめる（iTunesの遮断中などは毎秒出て読めなくなる）。"""
    key = f"{name}:{reason}"
    now = time.monotonic()
    ent = _fail_log.get(key)
    if ent and now - ent[0] < 60:
        ent[1] += 1
        return
    extra = f"（ほか{ent[1]}件を省略）" if ent and ent[1] else ""
    _fail_log[key] = [now, 0]
    print(f"[search] {name} failed: {reason}{extra}")
_recent_fail: dict[tuple[str, str, str], tuple[float, str]] = {}   # (source, q, artist) → (時刻, busy|error)

# source省略時はこの順で並べ、重複は先のソースを残す: iTunes > MusicBrainz > Discogs
# （iTunesは速くて安定、MusicBrainzは1秒1回の制限を全員で共有するため混雑しやすい）
SOURCES = {"itunes": itunes.search, "musicbrainz": musicbrainz.search}
if discogs.enabled():
    SOURCES["discogs"] = discogs.search
# **省略時はiTunesだけ**。MusicBrainzは「1秒に1リクエスト」の制限があり、常に一緒に引くと
# 検索が2秒かかる（iTunesだけなら0.2秒。2026-09-15の実測）。見つからなかったときだけ下で引き直す
DEFAULT_SOURCES = ("itunes",)
FALLBACK_SOURCE = "musicbrainz"
SOURCES["otodb"] = otodb.search     # 音MADデータベース。ALLには含めず、明示選択のときだけ
# ボカロのデータベース。**応答が1.6〜2.8秒**とiTunesより遅いので、これも明示選択のときだけ。
# iTunesに配信の無いボカロ曲（とその作者名）が引けるのが利点
SOURCES["vocadb"] = vocadb.search


@asynccontextmanager
async def lifespan(app: FastAPI):
    OUTPUTS.mkdir(exist_ok=True)
    GRIDS.mkdir(exist_ok=True)
    uploads.UPLOADS.mkdir(exist_ok=True)
    share.SHARES.mkdir(exist_ok=True)
    if public_mode():
        cleaned = housekeeping.run_all()
        if any(cleaned.values()):
            print(f"[housekeeping] {cleaned}")
        print(f"[public] 公開モード: CORS={cors_origins()} FRONTEND_URL={frontend_url() or '(このサーバー)'} RATE_LIMIT={rate_limit_per_minute()}/min")
    st = storage.get_storage()
    print(f"[storage] 共有の保存先: {st.name}" + (f"（公開URL: {st.public_url('') or '無し → バックエンドが中継'}）" if st.is_remote else ""))
    pruned = await asyncio.to_thread(cache.prune)
    if any(pruned.values()):
        print(f"[cache] pruned {pruned}")
    removed = render.prune_outputs()
    if removed:
        print(f"[outputs] removed {removed} old files")
    print(f"[public] PNGのURLは{public_base_url()}/outputs/... で返します（.envのPUBLIC_BASE_URL）")
    app.state.started_at = time.time()
    global _app_shell
    try:
        _app_shell = _check_app_shell()   # 切り出したCSS / JSがR2に載っていれば殻を配る
    except Exception as e:
        print(f"[app] 殻を確かめられませんでした（1枚のまま配ります）: {type(e).__name__}: {e}")
        _app_shell = None
    monitor = asyncio.create_task(_load_monitor()) if public_mode() else None
    # **全体の上限を使っているときだけ数える**（2026-09-21）。`count_today()` はバケットを1周するので
    # 起動あたりClass A 214回かかるが、`SHARE_LIMIT_PER_DAY` が0（＝無制限）だと復元した数を読む分岐
    # （`_share()` の `if per_day and …`）が成立せず、ログ1行のためだけに払っていた。
    # 共有の件数は毎日の掃除が `metrics/r2.jsonl` に残すので、運用ボードはそちらから出す
    seed = asyncio.create_task(_seed_share_count()) if public_mode() and st.is_remote and share_limits()[1] else None
    imgidx = asyncio.create_task(_seed_r2_index()) if st.is_remote else None
    listed = asyncio.create_task(_seed_listed_index())
    srchidx = asyncio.create_task(_seed_search_index()) if st.is_remote else None
    usage = asyncio.create_task(_usage_loop()) if (public_mode() or st.is_remote) else None
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=10),   # MusicBrainzやroxyは遅いことがある
        follow_redirects=True,
        headers={"User-Agent": os.getenv("MB_USER_AGENT", "trackmento/0.1 (+https://trackmento.com)")},
        event_hooks={"request": [_note_out]},   # 外へ出した要求をホストごとに数える（`[out]`）
    )
    try:
        yield
    finally:
        if monitor:
            monitor.cancel()
        if seed:
            seed.cancel()
        if imgidx:
            imgidx.cancel()
        if srchidx:
            srchidx.cancel()
        if usage:
            usage.cancel()
        listed.cancel()
        await app.state.http.aclose()
        cache.close()


app = FastAPI(title="TRACKMENTO", lifespan=lifespan)


@functools.lru_cache(maxsize=1)
def _r2_origin() -> str:
    """R2の公開URLのオリジン（CSPに足すための " https://…" 形式）。R2を使っていなければ空文字。"""
    st = storage.get_storage()
    if not st.is_remote:
        return ""
    from urllib.parse import urlsplit
    p = urlsplit(st.public_url("") or "")
    return f" {p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""

# ---------- 描画は専用の低優先度スレッドで ----------
# もとは無料ホスト（0.1 vCPU）向けに1本・待ち2件だった（描画が重なるとイベントループがCPUを
# 取れず、Renderのヘルスチェック（5秒）に落ちて再起動されるため）。**Standard（1 vCPU / 2048MB）に
# 上げたので広げる**。2026-09-15の点検でCPU最大0.118 / 1.0・メモリ203 / 2048MBと余っているのに、
# 2時間で `/share` の503が15件出ていた
from concurrent.futures import ThreadPoolExecutor

_RENDER_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="render", initializer=render.lower_thread_priority)
MAX_RENDER_QUEUE = 6   # サーバー描画（フォールバック）は1件40〜80秒かかる。待たせるより早めに断る。
                       # 2/4では1日36,000共有の時間帯に2時間で7件断っていた（点検の「異常あり」）。
                       # CPUは最大0.36/1.0・メモリ332/2048MBと余っているので3/6に広げた（2026-09-17）
_render_waiting = [0]


async def run_render(fn, *args):
    if _render_waiting[0] >= MAX_RENDER_QUEUE:
        raise HTTPException(503, "共有の生成が混み合っています。30秒ほど待ってからもう一度お試しください", headers={"Retry-After": "30"})
    _render_waiting[0] += 1
    try:
        return await asyncio.get_running_loop().run_in_executor(_RENDER_POOL, functools.partial(fn, *args))
    finally:
        _render_waiting[0] -= 1


# ---------- 負荷の診断ログ（公開モード）。IP・検索語・生のUser-Agentは含めない ----------
_stats: dict[str, list] = {}   # パス種別 → [件数, 合計秒, 最大秒, 5xx件数, 待ち時間の区切りごとの件数]
# 待ち時間の区切り（秒）。**平均と最大だけでは、25秒が1回だけの外れ値か、よくあることかが分からない**（2026-09-19）。
# 区切りごとの件数なら、点検が窓全体で足し合わせて「95% がこれ以内」を出せる（1分ごとのp95は足せない）
LAT_BUCKETS = (0.25, 0.5, 1, 2, 5, 10, 20)
_STATS_TOP = 10   # 1行に出す経路の数。残りは「ほか」にまとめて数だけ残す（以前は黙って落としていた）


def _lat_bucket(dt: float) -> int:
    for i, edge in enumerate(LAT_BUCKETS):
        if dt < edge:
            return i
    return len(LAT_BUCKETS)


def _stats_field(k: str, v: list) -> str:
    return (f"{k}:{v[0]}件/{v[1]:.1f}s/max{v[2]:.1f}s" + (f"/5xx{v[3]}" if v[3] else "")
            + "/h" + ".".join(str(n) for n in v[4]))


# ---------- ソースごとの検索（2026-09-19）----------
# `/search` はソースをまとめて数えるので、VocaDBが遅いのかMusicBrainzが遅いのかが分からなかった。
# ソースごとに「覚えていた（SQLite / R2）・外へ聞いた・失敗」の件数と、外へ聞いた時間の分布を出す
_srch_stats: dict[str, list] = {}   # ソース → [SQLite, R2, 外へ, 失敗, 外へ聞いた合計秒, 最大秒, 区切りごとの件数]


def _note_srch(source: str, kind: int, dt: float = 0.0) -> None:
    """kind: 0 = SQLiteに覚えていた / 1 = R2の控え / 2 = 外へ聞いた / 3 = 失敗（時間切れ・覚えていた失敗を含む）"""
    s = _srch_stats.setdefault(source, [0, 0, 0, 0, 0.0, 0.0, [0] * (len(LAT_BUCKETS) + 1)])
    s[kind] += 1
    if kind in (2, 3) and dt:
        s[4] += dt
        s[5] = max(s[5], dt)
        s[6][_lat_bucket(dt)] += 1


# ---------- 外へ出した要求（2026-09-20）----------
# 各サービスの規約には「1分にN件まで」「1日に数千件なら事前の許可が要る」といった決まりがある
# （VocaDBの件で分かった）。**守れているかを見るには、まずこちらが何回出しているかを知る必要がある**。
# 共有のクライアント（`app.state.http`）から出た要求をホストごとに数えて60秒ごとに出す。
# 画像の取得も同じクライアントを通るが、画像は別ホスト（`i.ytimg.com` と `www.youtube.com` など）なので混ざらない。
# **URLやパス、検索語は数えない**（`[src]` や `[ua]` と同じ方針で、ホスト名と回数だけ）
_out_stats: dict[str, int] = {}
_OUT_TOP = 14


async def _note_out(request: httpx.Request) -> None:
    host = request.url.host or "?"
    if len(_out_stats) < 200 or host in _out_stats:
        _out_stats[host] = _out_stats.get(host, 0) + 1


def _out_line() -> str:
    """`[out] host=件数 …`（多い順に `_OUT_TOP` 件、残りは「ほか」）。数えた分は消す"""
    items = sorted(_out_stats.items(), key=lambda kv: -kv[1])
    _out_stats.clear()
    if not items:
        return ""
    fields = [f"{h}={n}" for h, n in items[:_OUT_TOP]]
    if rest := items[_OUT_TOP:]:
        fields.append(f"ほか={sum(n for _, n in rest)}")
    return "[out] " + " ".join(fields)


# ---------- ブラウザ側で起きた失敗（2026-09-19）----------
# 共有画像の送信の途中停止・ブラウザでの描画の失敗・iTunesへの直接検索の失敗などはブラウザの中で起きるので、
# サーバーのログに何も残らなかった（「サーバーが重くて上手くいかなかった」という声の中身が分からなかった）。
# 画面が `/hiccup` に**種類と回数だけ**を送る。検索語・URL・曲名・端末の情報は受け取らない
CLIENT_KINDS = frozenset({
    "up_stall", "up_wait", "up_timeout", "up_net", "up_abort", "up_4xx", "up_5xx",   # 共有画像の送信
    "canvas_unsupported", "canvas_fail",          # ブラウザで描けずサーバー描画へ
    "server_render_fail", "share_fail",           # サーバー描画も失敗 / 共有そのものが失敗
    "font_fail",                                  # 共有画像用のフォントが読めない
    "cover_fail",                                 # ジャケットが取れず、そのマスが空のまま描かれた
    "itunes_fail", "itunes_busy", "mb_fail", "mb_busy",   # ブラウザからの直接検索
    "search_fail",                                # 検索そのものが失敗（サーバーに届かないなど）
    "migrate_unreachable",                        # 旧アドレスから新しいアドレスへつながらず、旧アドレスのまま使った
})
_client_stats: dict[str, int] = {}


# ---------- 共有の送信の内訳（2026-09-19）----------
# `/share/upload` の所要時間は「本文を受け取る時間」と「検査と保存の時間」の合計で、どちらが長いのか分からなかった。
# 点検で5% 以上が20秒を超え、送り終えたように見えてから画面が打ち切る件（up_wait）が出ていたので、分けて数える
_up_stats: dict[str, list] = {"recv": [], "save": [], "kb": [], "cut": [0], "busy": [0]}


def _note_upload(recv: float | None = None, save: float | None = None, kb: float | None = None,
                 cut: bool = False, busy: bool = False) -> None:
    if recv is not None:
        _up_stats["recv"].append(recv)
    if save is not None:
        _up_stats["save"].append(save)
    if kb is not None:
        _up_stats["kb"].append(kb)
    if cut:
        _up_stats["cut"][0] += 1
    if busy:
        _up_stats["busy"][0] += 1


def _upload_line() -> str | None:
    r, sv, kb = _up_stats["recv"], _up_stats["save"], _up_stats["kb"]
    cut, busy = _up_stats["cut"][0], _up_stats["busy"][0]
    if not (r or cut or busy):
        return None
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0.0   # noqa: E731
    line = (f"[upload] n={len(r)} recv_med={med(r):.1f}s recv_max={max(r, default=0):.1f}s "
            f"save_med={med(sv):.1f}s save_max={max(sv, default=0):.1f}s kb_med={med(kb):.0f} cut={cut} busy={busy}"
            + " recv_h=" + ".".join(str(sum(1 for x in r if _lat_bucket(x) == i)) for i in range(len(LAT_BUCKETS) + 1)))
    for k in ("recv", "save", "kb"):
        _up_stats[k].clear()
    _up_stats["cut"][0] = _up_stats["busy"][0] = 0
    return line


def _stat_key(path: str) -> str:
    for prefix in ("/grids/", "/s/", "/shares/", "/uploads/", "/outputs/"):
        if path.startswith(prefix):
            return prefix + "*"
    return path


# ---------- User-Agentの種別（経路ごとの内訳を見るため） ----------
# 生のUAは指紋になるので記録せず、この5種のどれかに丸めた名前だけを数える。
# 種別を分けているのは対策が別だから。「プレビュー」はXなどがリンクカードを作るための取得で、
# **止めてはいけない**（robots.txtで /s/ を塞ぐとXのカードが出なくなる）。
# 「検索」「AI」「その他ボット」はrobots.txtで減らせる。
_UA_KINDS = (
    # AIを先に見る（applebot-extendedがapplebotに当たってしまわないように）
    ("AI", ("gptbot", "oai-searchbot", "chatgpt-user", "claudebot", "claude-web", "anthropic-ai",
            "ccbot", "perplexitybot", "bytespider", "meta-externalagent", "google-extended",
            "amazonbot", "applebot-extended", "timpibot", "omgili", "diffbot")),
    ("検索", ("googlebot", "bingbot", "duckduckbot", "yandexbot", "baiduspider", "applebot",
             "petalbot", "seznambot", "naver", "sogou", "google-inspectiontool")),
    ("プレビュー", ("twitterbot", "facebookexternalhit", "slackbot", "discordbot", "telegrambot",
                "skypeuripreview", "whatsapp", "embedly", "redditbot", "pinterest",
                "bluesky", "mastodon", "misskey", "line-poker", "vkshare", "linkedinbot")),
    ("その他ボット", ("ahrefsbot", "semrushbot", "mj12bot", "dotbot", "dataforseo", "serpstat",
                 "screaming frog", "zoominfo", "bot", "crawler", "spider", "curl/",
                 "python-requests", "httpx", "wget", "go-http-client", "java/", "scrapy")),
)


def _ua_kind(ua: str) -> str:
    """User-Agentをおおまかな種別にする。生のUAは残さない。"""
    u = ua.lower()
    if not u:
        return "不明"
    for kind, tokens in _UA_KINDS:
        if any(t in u for t in tokens):
            return kind
    return "人"


_ua_stats: dict[tuple[str, str], int] = {}   # (パス種別, UA種別) → 件数
# どこから来たかの印（`?src=x` のように貼る側が付ける）。**数えるだけ**で、誰が来たかは残さない。
# 名前は英数と - _ の16文字までに刈り込む（ログに変な文字を入れない・種類を増やしすぎない）
_src_stats: dict[str, int] = {}
_SRC_RE = re.compile(r"^[a-z0-9_-]{1,16}$")
_SRC_MAX = 30   # 覚える種類の上限。いたずらで種類が増えても膨らまないように


# **どこから来たか（Refererのホスト名だけ）**。`?src=` はこちらが投稿に印を付けたときしか数えられないので、
# 素のリンクからの流入が分からなかった。**残すのはホスト名だけ**（パスも問い合わせも捨てるので、
# 「どの投稿から」までは分からない＝人の識別にならない）。うちのホストからの移動は数えない
_ref_stats: dict[str, int] = {}
_REF_RE = re.compile(r"^[a-z0-9.-]{1,32}$")
_REF_MAX = 40


def _note_ref(request: Request) -> None:
    ref = request.headers.get("referer") or ""
    if not ref:
        return
    try:
        host = (urllib.parse.urlsplit(ref).hostname or "").lower()
    except ValueError:
        return
    host = host.removeprefix("www.")
    mine = (request.url.hostname or "").lower().removeprefix("www.")
    if not host or host == mine or not _REF_RE.match(host):
        return
    if host not in _ref_stats and len(_ref_stats) >= _REF_MAX:
        host = "ほか"
    _ref_stats[host] = _ref_stats.get(host, 0) + 1


def _note_src(request: Request) -> None:
    _note_ref(request)
    v = (request.query_params.get("src") or "").strip().lower()
    if not v or not _SRC_RE.match(v):
        return
    if v not in _src_stats and len(_src_stats) >= _SRC_MAX:
        v = "ほか"
    _src_stats[v] = _src_stats.get(v, 0) + 1
_5xx_stats: dict[str, int] = {}   # "statusパス種別 理由" → 件数（_log_5xxが足し、1分ごとに [5xx] 行で出す）
_5XX_TOP = 6                      # 1分あたりに出す理由の数（多すぎる理由はログを膨らませるので上位だけ）


def _release_and_report(detail: bool, tasks: int) -> str:
    """gc＋malloc_trimを回し、`[mem]` の1行を返す（2026-10-06、RSSが再起動ごとに積み上がる原因を探すため）。

    見分け方: trimでRSSが大きく下がるならglibcの抱え込み、`blocks`（Pythonが割り当て中のブロック数）や
    索引の件数がRSSと一緒に増えるならPythonのオブジェクトが溜まっている。`top` はgcが追う入れ物
    （dict・list・tupleなど。strやintは入らない）の種類ごとの数。数えるのに一瞬GILを握るので1時間に1回だけ。
    **語やURLは出さない**（数だけ）。
    """
    import gc
    import sys
    before = _rss_mb()
    render._release_memory()
    after = _rss_mb()
    parts = [f"rss={before or 0:.0f}>{after or 0:.0f}MB", f"blocks={sys.getallocatedblocks()}",
             f"img_index={len(_IMG_INDEX)}", f"search_index={len(searchcache._INDEX)}", f"listed={shareindex.count()}",
             f"inflight={len(_inflight)}", f"tasks={tasks}"]
    if detail:
        objs = gc.get_objects()
        top = Counter(type(o).__name__ for o in objs).most_common(8)
        parts.append(f"objs={len(objs)}")
        parts.append("top=" + ",".join(f"{k}:{n}" for k, n in top))
        del objs
    return "[mem] " + " ".join(parts)


async def _load_monitor():
    """1秒ごとにループの遅れを測り（0.5秒超なら記録）、60秒ごとにリクエスト集計を出す。"""
    tick = 0
    while True:
        t0 = time.monotonic()
        await asyncio.sleep(1.0)
        lag = time.monotonic() - t0 - 1.0
        if lag > 0.5:
            print(f"[loop] lag={lag:.1f}s render_queue={_render_waiting[0]}")
        tick += 1
        if tick % 600 == 0:
            # 10分ごとにgc＋malloc_trim。画像中継やR2一覧の一時バッファをglibcが抱え込み、RSSが下がらないため。
            # その前後のRSSと中身の数を `[mem]` に出す（1時間に1回は種類ごとの数も）
            print(await asyncio.to_thread(_release_and_report, tick % 3600 == 0, len(asyncio.all_tasks())))
        if tick % 60 == 0 and _stats:
            items = sorted(_stats.items(), key=lambda kv: -kv[1][1])
            fields = [_stats_field(k, v) for k, v in items[:_STATS_TOP]]
            if rest := items[_STATS_TOP:]:
                agg = [sum(v[0] for _, v in rest), sum(v[1] for _, v in rest), max(v[2] for _, v in rest),
                       sum(v[3] for _, v in rest), [sum(col) for col in zip(*(v[4] for _, v in rest))]]
                fields.append(_stats_field("ほか", agg))
            print("[stats] " + " ".join(fields))
            _stats.clear()
        if tick % 60 == 0 and _srch_stats:
            print("[srch] " + " ".join(
                f"{k}:db{v[0]}/r2{v[1]}/net{v[2]}/fail{v[3]}/max{v[5]:.1f}s/h" + ".".join(str(n) for n in v[6])
                for k, v in sorted(_srch_stats.items())))
            _srch_stats.clear()
        if tick % 60 == 0 and (out_line := _out_line()):
            print(out_line)
        if tick % 60 == 0 and _img_stats:
            # imgcacheの当たり外れ。hit/(hit+miss) が42% を下回ると、R2に置くより
            # 中継したほうが安くなる（put $0.0000045対 帯域74KB $0.0000106）
            print("[img] " + " ".join(f"{k}={_img_stats[k]}" for k in ("hit", "miss", "put", "stale") if k in _img_stats))
            _img_stats.clear()
            if len(_img_stale) > _IMG_INDEX_MAX // 10:   # 取り直されないまま溜まったぶんは捨てる
                _img_stale.clear()
        if tick % 60 == 0 and (calls := vocadb.take_calls()):
            # VocaDBへ聞いた回数と、覚えていて聞かずに済んだ回数（種類ごと）。語そのものは数えない
            print("[vocadb] " + " ".join(f"{k}={n}" for k, n in sorted(calls.items())))
        if tick % 60 == 0 and (up_line := _upload_line()):
            print(up_line)
        if tick % 60 == 0 and _client_stats:
            print("[client] " + " ".join(f"{k}={n}" for k, n in sorted(_client_stats.items(), key=lambda kv: -kv[1])))
            _client_stats.clear()
        if tick % 60 == 0 and _5xx_stats:
            # 5xxの内訳。[stats] の5xxは件数しか分からないので、理由（HTTPExceptionのdetail）を添える。
            # 理由が _5XX_TOPを超えたぶんは「ほか」にまとめて数だけ残す（取りこぼさない）
            top = sorted(_5xx_stats.items(), key=lambda kv: -kv[1])
            for key, n in top[:_5XX_TOP]:
                print(f"[5xx] {n} {key}")
            if (rest := sum(n for _, n in top[_5XX_TOP:])):
                print(f"[5xx] {rest} 000 - ほか{len(top) - _5XX_TOP}種類")
            _5xx_stats.clear()
        if tick % 60 == 0 and _ua_stats:
            # 経路ごとのUA種別の内訳。どの経路をボットが踏んでいるかが分かると、
            # robots.txtで減らせるぶんと、減らしてはいけないぶん（リンクカード）を分けて考えられる
            by_path: dict[str, dict[str, int]] = {}
            for (path, kind), n in _ua_stats.items():
                by_path.setdefault(path, {})[kind] = n
            top = sorted(by_path.items(), key=lambda kv: -sum(kv[1].values()))[:6]
            print("[ua] " + " ".join(
                f"{path}:" + ",".join(f"{k}={n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1]))
                for path, kinds in top))
            _ua_stats.clear()
        if tick % 60 == 0 and _src_stats:
            # どこから来たか（`?src=…`）。多い順に出す。**人の識別になるものは含まない**
            print("[src] " + " ".join(f"{k}={n}" for k, n in sorted(_src_stats.items(), key=lambda kv: -kv[1])))
            _src_stats.clear()
        if tick % 60 == 0 and _ref_stats:
            # どこから来たか（Refererのホスト名）。多い順に上位12件だけ
            top_ref = sorted(_ref_stats.items(), key=lambda kv: -kv[1])[:12]
            print("[ref] " + " ".join(f"{k}={n}" for k, n in top_ref))
            _ref_stats.clear()


def _wants_html(request: Request) -> bool:
    """ブラウザのアドレスバーやリンクから直接開いた要求か（fetchはAccept: */* なのでJSONのまま）。"""
    return request.method in ("GET", "HEAD") and "text/html" in request.headers.get("accept", "")


def _lang_for(request: Request | None) -> str:
    """案内ページ・共有ページの言語。開いた人のAccept-Languageで決める。

    共有ページは受け取った人が開くものなので、共有した人が画面で選んだ言語ではなく、
    開く人のブラウザの設定に合わせる。ヘッダが無ければ日本語（このサイトの元の言語）。
    """
    if request is not None:
        # **URLの ?lang=en / ?lang=jaが最優先**（画面側と同じ規則）。共有ページを英語で見せたいときに使う
        q = (request.query_params.get("lang") or "").strip().lower()
        if q in ("ja", "en"):
            return q
    header = (request.headers.get("accept-language") or "") if request is not None else ""
    for part in header.split(","):
        tag = part.split(";")[0].strip().lower()
        if tag and tag != "*":
            return "ja" if tag.startswith("ja") else "en"
    return "ja"


def _log_5xx(request: Request, status: int, detail: str) -> None:
    """HTTPExceptionで返した5xxを理由ごとに数える。1分ごとに _load_monitorが [5xx] 行で出す。

    raise HTTPException(...) はunhandled_errorを通らないのでログに何も出ず、点検では
    「エラー行0・5xx N」としか分からなかった（/image-proxyの503/502がこれで、
    最大24秒の原因を突き止めるのに時間がかかった）。印は [error] と分ける。
    [error] は「想定外の例外」を数える枠で、そこに配信元都合の502を混ぜると判定が鈍るため。
    1件ごとに出さず [stats] と同じ60秒窓でまとめるのは、件数を取りこぼさずに行数を抑えるため。
    パスは _stat_keyで種別に潰す（queryには外部の画像URLが入るので出さない）。
    """
    if status < 500 and not (status == 404 and request.url.path.startswith("/image-proxy")):
        return   # /image-proxyの404（配信元に無い）だけは4xxでも内訳に残す（どの配信元が消えているかを見るため）
    key = f"{status} {_stat_key(request.url.path)} {detail[:80]}"
    if not public_mode():
        print(f"[5xx] 1 {key}")   # ローカルは _load_monitorが動かないので、その場で出す
        return
    if len(_5xx_stats) < 500:     # 理由が際限なく増える種類のものが出ても溜め込まない
        _5xx_stats[key] = _5xx_stats.get(key, 0) + 1


def _error_response(request: Request, status: int, detail: str, headers: dict | None = None) -> Response:
    """エラーはfetchにはJSON、ブラウザ遷移には案内ページ（存在しないURL・期限切れの画像・429・500で{"detail": …}を見せない）。"""
    if _wants_html(request):
        return HTMLResponse(share.notice_html(status, base_url_for(request), app_url_for(request), detail, _lang_for(request)), status_code=status, headers=headers)
    return JSONResponse({"detail": detail}, status_code=status, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
    """raise HTTPException(...) と、ルートに無いパスの404・メソッド違いの405。"""
    _log_5xx(request, exc.status_code, str(exc.detail))
    return _error_response(request, exc.status_code, str(exc.detail), exc.headers)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> Response:
    """想定外の例外もJSON（ブラウザ遷移なら案内ページ）で返す（フロントが「Internal Server Error」の生テキストをJSONとして
    読もうとして失敗しないように）。原因はサーバーログに残す。"""
    import traceback
    if isinstance(exc, ClientDisconnect):   # 利用者が送信途中で離脱しただけ（アプリ内ブラウザや回線切替）。トレースバック不要
        print(f"[error] {request.method} {request.url.path}: 送信途中で切断")
        return JSONResponse({"detail": "送信が途中で切れました"}, status_code=400)
    print(f"[error] {request.method} {request.url.path}: {exc!r}")
    print("".join(traceback.format_exception(exc)))
    return _error_response(request, 500, "サーバーでエラーが起きました。時間をおいてもう一度お試しください。直らない場合はお問い合わせフォームからお知らせください")


# gzipをかける種類。画像・フォント・動画は既に圧縮済みで、かけてもほとんど縮まずCPUだけ使う
_GZIP_TYPES = ("text/", "application/json", "application/javascript", "application/xml", "image/svg+xml")
_GZIP_MIN = 900          # これより小さい応答は掛けない（ヘッダのほうが重くなる）
_GZIP_LEVEL = 6          # 9との差は数 % で、時間は3倍かかる


class GZipText:
    """**textとJSONだけgzipで返す**。

    Renderの課金対象は「Renderが送るバイト数」で、**前段のCloudflareが付けるbrotliは
    そこには効かない**（`Content-Encoding: br` が返っていても、Render → Cloudflareは生のまま）。
    画面のHTMLは273KBあり、2時間の転送量の39% を占めていた。gzipで82KB（3.34分の1）になる。

    Starletteの `GZipMiddleware` を使わないのは**内容の種類で分けてくれない**ため。
    `/shares/*.jpg`（1件490KB）まで圧縮しようとしてCPUを捨てることになる。
    分割して送る応答（`more_body`）も素通しする（画像の中継など）。
    """

    def __init__(self, app, minimum_size: int = _GZIP_MIN) -> None:
        self.app, self.minimum_size = app, minimum_size

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or "gzip" not in Headers(scope=scope).get("accept-encoding", ""):
            return await self.app(scope, receive, send)
        start: dict | None = None

        async def send_wrapper(message: dict) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message          # 本文の種類と大きさを見てから送る
                return
            if message["type"] != "http.response.body" or start is None:
                return await send(message)
            body = message.get("body", b"")
            hdrs = MutableHeaders(raw=start["headers"])
            ctype = hdrs.get("content-type", "")
            if (message.get("more_body") or len(body) < self.minimum_size
                    or hdrs.get("content-encoding") or not ctype.startswith(_GZIP_TYPES)):
                head, start = start, None
                await send(head)
                return await send(message)
            packed = await asyncio.to_thread(gziplib.compress, body, _GZIP_LEVEL)
            hdrs["content-encoding"] = "gzip"
            hdrs["content-length"] = str(len(packed))
            hdrs.add_vary_header("Accept-Encoding")
            head, start = start, None
            await send(head)
            await send({"type": "http.response.body", "body": packed, "more_body": False})

        await self.app(scope, receive, send_wrapper)


if cors_origins():
    # GitHub Pagesなど別オリジンのフロントから呼べるようにする（Cookieは使わないのでcredentialsは不要）
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins(), allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["*"], max_age=600)
app.add_middleware(GZipText)

# ---------- 簡易レートリミット（IPごと・1分間の回数。公開時の連打・スクレイピング対策） ----------
_RATE_PATHS = ("/search", "/from-url", "/from-playlist", "/bandcamp", "/upload", "/share", "/share/upload", "/render", "/grids", "/hiccup")
_hits: dict[str, deque] = defaultdict(deque)
# 共有の1日あたり回数（IPごと／全体）。プロセス内カウンタ。日付が変わるとリセット
_share_day = {"date": "", "per_ip": defaultdict(int), "total": 0}


_IP_SALT = secrets.token_bytes(16)   # 起動ごとに変わる。IPを復元できない形で数えるためだけに使う


def _client_ip(request: Request) -> str:
    """回数制限のキー。生のIPは保持せず、プロセス限りの乱数と混ぜたハッシュにする。
    TRUST_PROXY=1のときはプロキシが付けたヘッダから利用者のIPを取る。
    RenderはCloudflareの後ろにいるので、X-Forwarded-Forの末尾はCloudflareのエッジIPになる。
    末尾を使うと利用者全員が数個のキーに集約され、初めての人でも「1日20回」に当たってしまう。
    そこでCloudflareが必ず付け直すCF-Connecting-IP（無ければTrue-Client-IP）を優先し、
    どちらも無ければX-Forwarded-Forの先頭（Renderの仕様: 先頭が利用者のIP）を使う。
    先頭は利用者が偽装できるが、影響は自分の回数制限を逃れられる程度（他人の枠は減らせない）"""
    ip = request.client.host if request.client else "?"
    if trust_proxy():
        forwarded = (request.headers.get("cf-connecting-ip") or request.headers.get("true-client-ip") or "").strip()
        if not forwarded:
            xff = [v.strip() for v in (request.headers.get("x-forwarded-for") or "").split(",") if v.strip()]
            if xff:
                forwarded = xff[0]
        if forwarded:
            ip = forwarded[:64]
    return hashlib.sha256(_IP_SALT + ip.encode("utf-8", "replace")).hexdigest()[:24]


def _check_share_quota(request: Request) -> None:
    per_ip, per_day = share_limits()
    if not per_ip and not per_day:
        return
    today = time.strftime("%Y-%m-%d")
    if _share_day["date"] != today:
        _share_day.update(date=today, per_ip=defaultdict(int), total=0)
    ip = _client_ip(request)
    if per_ip and _share_day["per_ip"][ip] >= per_ip:
        print(f"[share] quota: 端末の上限{per_ip}回 → 429")
        raise HTTPException(429, f"この端末からの共有は1日{per_ip}回までです。明日またお試しください")
    if per_day and _share_day["total"] >= per_day:
        print(f"[share] quota: 全体の上限{per_day}回（本日{_share_day['total']}件）→ 429")
        raise HTTPException(429, f"本日の共有回数がサーバー全体の上限（{per_day}回）に達しました。明日またお試しください")


async def _seed_share_count() -> None:
    """起動時に今日の共有数を保存先の一覧から数え、全体カウンタに入れる（プロセス内カウンタはデプロイ・再起動で0に戻るため。
    端末ごとの回数は復元しない）。一覧は数秒かかるのでスレッドで。"""
    try:
        n = await asyncio.to_thread(share.count_today)
    except Exception as e:
        print(f"[share] 今日の共有数の復元に失敗: {e!r}")
        return
    today = time.strftime("%Y-%m-%d")
    if _share_day["date"] != today:
        _share_day.update(date=today, per_ip=defaultdict(int), total=0)
    _share_day["total"] = max(_share_day["total"], n)
    print(f"[share] 本日の共有数を復元: {_share_day['total']}件（上限{share_limits()[1] or '無制限'}）")


def _count_share(request: Request) -> None:
    _share_day["per_ip"][_client_ip(request)] += 1
    _share_day["total"] += 1


_BODY_LIMIT_JSON = 1 * 1024 * 1024
_BODY_LIMIT_UPLOAD = 16 * 1024 * 1024


@app.middleware("http")
async def request_stats(request: Request, call_next):
    if not public_mode():
        return await call_next(request)
    t0 = time.monotonic()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        dt = time.monotonic() - t0
        key = _stat_key(request.url.path)
        s = _stats.setdefault(key, [0, 0.0, 0.0, 0, [0] * (len(LAT_BUCKETS) + 1)])
        s[0] += 1
        s[1] += dt
        s[2] = max(s[2], dt)
        s[4][_lat_bucket(dt)] += 1
        if status >= 500:
            s[3] += 1
        ua = _ua_kind(request.headers.get("user-agent", ""))
        _ua_stats[(key, ua)] = _ua_stats.get((key, ua), 0) + 1


# 移転先へ301で送る経路。**画面（`/`）とAPIは送らない**。
# APIを送ると、開いたままの古いタブが別オリジンへ投げることになりCORSで落ちる
_MIGRATE_PATHS = ("/s/", "/find", "/sitemap.xml", "/robots.txt", "/guide", "/howto", "/articles", "/privacy", "/terms", "/about", "/updates")


def _migrate_host(request: Request) -> str:
    """移転先が設定されていて、今の要求がそれと違うホストで来ていれば、移転先のベースURLを返す。"""
    target = migrate_to()
    if not target:
        return ""
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip().lower()
    return "" if not host or host == urllib.parse.urlsplit(target).netloc.lower() else target


def _migrate_redirect(request: Request) -> Response | None:
    """引っ越し中の古いドメインで、移すべき経路なら301を返す。それ以外はNone。"""
    if request.method not in ("GET", "HEAD"):
        return None
    path = request.url.path
    if not path.startswith(_MIGRATE_PATHS):
        return None
    if not (target := _migrate_host(request)):
        return None
    q = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"{target}{path}{q}", status_code=301)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # **引っ越し中の古いドメインは、共有ページなどを移転先へ301で送る**（MIGRATE_TO、2026-09-18）。
    # 画面（`/`）だけは送らずにそのまま返す。ブラウザに保存されている並びを引き継いでから、
    # 画面自身が移転先へ移動するため（サーバーの301ではlocalStorageを持っていけない）
    if (moved := _migrate_redirect(request)) is not None:
        return moved
    # 大きすぎるボディは読む前に断る（メモリ・ディスク消費を抑える）。ブラウザのfetchは必ずContent-Lengthを付ける
    if request.method in ("POST", "PUT"):
        cap = _BODY_LIMIT_UPLOAD if request.url.path in ("/upload", "/share/upload") else _BODY_LIMIT_JSON
        cl = request.headers.get("content-length")
        if cl is None or not cl.isdigit():
            return JSONResponse({"detail": "Content-Lengthが必要です"}, status_code=411)
        if int(cl) > cap:
            return JSONResponse({"detail": f"リクエストが大きすぎます（{cap // (1024*1024)}MBまで）"}, status_code=413)
    request.state.csp_nonce = secrets.token_urlsafe(16)
    limit = rate_limit_per_minute()
    if limit and request.url.path.startswith(_RATE_PATHS):
        ip = _client_ip(request)   # プロキシのヘッダを信頼するのはTRUST_PROXY=1のときだけ
        now = time.monotonic()
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return JSONResponse({"detail": "リクエストが多すぎます。1分ほど待ってからもう一度お試しください"}, status_code=429, headers={"Retry-After": "60"})
        q.append(now)
        if len(_hits) > 5000:  # メモリが膨らまないように古いIPを捨てる
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > 60][:1000]:
                _hits.pop(k, None)
    response = await call_next(request)
    if request.url.path.startswith("/fonts/"):
        # 同梱フォント（合計2.6 MBのWOFF2）は変わらないので長くキャッシュさせる。アプリ内ブラウザでも2回目以降は読み直さない
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    # CSP: スクリプトはこのサーバーが埋めたnonce付きのものだけ。画像は同一オリジン＋R2の公開URL（https:）＋Canvasのblob/data
    # 304には付けない: ブラウザは304のヘッダーでキャッシュ済み応答のヘッダーを更新するので、新しいnonceのCSPが
    # 古い本文（古いnonce）に適用されてスクリプトが止まる。付けなければキャッシュ済みのCSP（本文と一致）がそのまま残る
    if response.status_code != 304:
      # フォントと画像をR2から配るときは、その公開URLだけをfont-src / connect-srcに足す
      # （外部の任意のホストを開くわけではない。自分のバケット1つだけ）
      r2 = _r2_origin()
      # 引っ越し先へつながるかを画像で確かめる（frontendのreachable）。本番はhttps: で済むが、
      # 手元でhttp://127.0.0.1へ引っ越させて確かめるときのために、その1つだけ足す
      mig = f" {migrate_to()}" if migrate_to().startswith("http://") else ""
      response.headers.setdefault("Content-Security-Policy",
        # script-srcはnonceだけ（**外に出した <script src> にもnonceは効く**ので、R2のオリジンを足す必要はない）。
        # style-srcには足す: 切り出したapp.<hash>.cssをR2から <link> で読むため
        f"default-src 'self'; script-src 'nonce-{request.state.csp_nonce}'; style-src 'self' 'unsafe-inline'{r2}; "
        # connect-src: iTunesとMusicBrainz（＋Cover Art Archive → archive.orgへリダイレクト）の検索はブラウザから直接叩く
        # （サーバーの共有IPがAppleに遮断され、MusicBrainzにはレート制限されるため）
        f"img-src 'self' data: blob: https:{mig}; connect-src 'self' https://itunes.apple.com https://musicbrainz.org https://coverartarchive.org https://archive.org https://*.archive.org https://*.mzstatic.com{r2}; font-src 'self'{r2}; media-src 'self'{r2}; object-src 'none'; base-uri 'self'; "
        "form-action 'self'; frame-ancestors 'self'")
    if public_mode() and request.headers.get("x-forwarded-proto", request.url.scheme) == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response
app.mount("/outputs", StaticFiles(directory=OUTPUTS, check_dir=False), name="outputs")
app.mount("/fonts", StaticFiles(directory=FONTS, check_dir=False), name="fonts")
# 画面に貼る絵（PayPalの広告など）。殻を配るときはR2のapp/banners/ に差し替わる（CSS・JSと同じ）。1枚のHTMLで配るときだけここから出る
app.mount("/app/banners", StaticFiles(directory=FRONTEND / "banners", check_dir=False), name="banners")
if not storage.get_storage().is_remote:
    app.mount("/uploads", StaticFiles(directory=uploads.UPLOADS, check_dir=False), name="uploads")
else:
    @app.get("/uploads/{fname}")
    async def upload_file(fname: str) -> Response:
        got = await run_in_threadpool(uploads.read_bytes, uploads.PREFIX + fname)
        if got is None:
            raise HTTPException(404, "アップロード画像が見つかりません（期限切れの可能性）")
        return Response(content=got[0], media_type=got[1], headers={"Cache-Control": "public, max-age=86400"})
if not storage.get_storage().is_remote:
    app.mount("/shares", StaticFiles(directory=share.SHARES, check_dir=False), name="shares")
else:
    # R2のときはバックエンドが中継する（JSONはCORSを気にせず読めるように常にこちら。PNGは公開URLがあればそちらを案内）
    @app.get("/shares/{fname}")
    async def share_file(fname: str) -> Response:
        sid, _, ext = fname.rpartition(".")
        if ext == "jpg" and sid.endswith("-og"):
            sid = sid[:-3]
        if ext not in ("png", "json", "jpg") or not share.valid_id(sid):
            raise HTTPException(404, "not found")
        data = await run_in_threadpool(storage.get_storage().get, fname)
        if data is None:
            # **消えた共有は410（Gone）**。404だと検索エンジンが「一時的な不調」とみて数か月再訪する。
            # IDの形が正しいのに無い＝期限切れで消したもの、なので「もう無い」と伝える（2026-09-17）
            raise HTTPException(410, "この共有は見つかりません（期限切れの可能性）")
        # JSONはcharsetを明示する（付けないと端末によっては既定の文字コードで開かれ、曲名が文字化けする）
        return Response(content=data, media_type={"png": "image/png", "jpg": "image/jpeg"}.get(ext, "application/json;charset=utf-8"),
                        headers={"Cache-Control": "public, max-age=86400"})


_FONT_CSS_FALLBACK = """
@font-face { font-family: "IBM Plex Sans JP"; font-weight: 400; font-style: normal; font-display: swap; src: url("fonts/IBMPlexSansJP-Regular.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Sans JP"; font-weight: 700; font-style: normal; font-display: swap; src: url("fonts/IBMPlexSansJP-Bold.woff2") format("woff2"); }
@font-face { font-family: "JF Dot MPlus12"; font-weight: 400; font-style: normal; font-display: swap; src: url("fonts/JF-Dot-MPlus12.woff2") format("woff2"); }
"""


FONTS_R2_PREFIX = "fonts/"
# フォントをR2から配るか（既定は有効）。公開URLとR2が無ければ自動でこのサーバーから配る
FONTS_FROM_R2 = os.getenv("FONTS_FROM_R2", "1") not in ("0", "false", "no")


def _fonts_r2_base() -> str:
    """R2に置いたフォントの公開URLの先頭。使えないときは空文字。"""
    if not FONTS_FROM_R2:
        return ""
    st = storage.get_storage()
    if not st.is_remote:
        return ""
    return (st.public_url(FONTS_R2_PREFIX) or "").rstrip("/")


@app.get("/fonts-css/{name}")
async def fonts_css(name: str) -> Response:
    """分割フォントのCSS。中のsrcをR2の公開URLに差し替えて返す。

    フォントは新規の訪問1回あたり210KB（実測）で、Renderの転送量の大半を占めていた。
    前段のCloudflareはWeb Serviceの応答をキャッシュしないため、訪問のたびにここから出ていく。
    R2は転送量が無料なので、断片のURLだけそちらに向ける（CSS自体は12KBと小さい）。
    """
    if not re.fullmatch(r"fonts\.[0-9a-f]{8}\.css", name):
        raise HTTPException(404, "not found")
    p = FONTS / "split" / name
    if not p.is_file():
        raise HTTPException(404, "not found")
    css = p.read_text(encoding="utf-8")
    base = _fonts_r2_base()
    if base:
        css = css.replace('url("/fonts/split/', f'url("{base}/')
    return Response(css, media_type="text/css", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@functools.lru_cache(maxsize=1)
def _font_head() -> str:
    """分割フォントの @font-faceを読む <link>（scripts/build_fonts.pyが生成したfonts/split/fonts.<hash>.css。
    ハッシュ名なので1年キャッシュに乗る）。無ければフル版の @font-faceを埋め込む。"""
    hashed = sorted((FONTS / "split").glob("fonts.*.css")) if (FONTS / "split").is_dir() else []
    if hashed:
        # 断片をR2から配るときは、srcを書き換えたCSSを返す /fonts-css/ 経由にする
        base = _fonts_r2_base()
        # **URLにR2の公開ドメインの印を付ける**。CSSの中身（断片のURL）はR2のドメインで変わるのに、
        # ファイル名は断片の中身から作るので変わらない。1年のimmutableで配っているため、
        # 印が無いとドメインを替えたあとも古いCSSを使い続け、**CSPで新ドメイン以外は弾かれて
        # フォントが1つも読めなくなる**（2026-09-14に本番で実際に起きた。日本語がシステムフォントになり、
        # 共有画像もブラウザで作れずサーバー描画に落ちていた）
        tag = hashlib.sha1(base.encode()).hexdigest()[:8] if base else ""
        path = f"fonts-css/{hashed[-1].name}?o={tag}" if base else f"fonts/split/{hashed[-1].name}"
        return f'<link rel="stylesheet" href="{path}">'
    print("[fonts] fonts/split/fonts.<hash>.cssが無いのでフル版のフォントを配ります（python scripts/build_fonts.pyで生成）")
    return f"<style>{_FONT_CSS_FALLBACK}</style>"


APP_R2_PREFIX = "app/"
# 切り出したCSSとJSをR2から配るか（既定は有効）。R2と公開URLが無ければ自動で1枚のまま配る
APP_FROM_R2 = os.getenv("APP_FROM_R2", "1") not in ("0", "false", "no")
_app_shell: str | None = None   # 使える殻（frontend/dist/index.htmlの中身）。使わないならNone


def _check_app_shell() -> str | None:
    """殻を使ってよければその中身、駄目ならNone。起動時に1回だけ呼ぶ。

    **殻が指すapp.<hash>.css / .jsがR2に両方載っていることを確かめてから使う**。
    上げ忘れたままデプロイしても、1枚のindex.htmlに倒れるだけで白い画面にならない
    （フォントは上げ忘れると本番で404になる作りで、CLAUDE.mdに注意書きが要った。同じ轍を踏まない）。
    確かめるのはHeadObject 2回で、Class Bなので実質無料。
    """
    shell_path = FRONTEND / "dist" / "index.html"
    if not APP_FROM_R2 or not shell_path.is_file():
        return None
    st = storage.get_storage()
    base = st.public_url(APP_R2_PREFIX) if st.is_remote else ""
    if not base:
        return None
    shell = shell_path.read_text(encoding="utf-8")
    names = re.findall(r'"' + re.escape(APP_R2_PREFIX) + r'(app\.[0-9a-f]{8}\.(?:css|js))"', shell)
    if len(names) != 2:
        print(f"[app] 殻が指すファイルが{len(names)}個でした（cssとjsの2個であること）。1枚のまま配ります")
        return None
    for name in names:
        if not st.exists(APP_R2_PREFIX + name):
            print(f"[app] {name}がR2にありません。1枚のまま配ります"
                  "（python scripts/build_app.py → scripts/upload_app_r2.py）")
            return None
    # 殻の中は相対パス。配るときにR2の公開URLへ差し替える（フォントと同じやり方）
    shell = shell.replace(f'"{APP_R2_PREFIX}', f'"{base.rstrip("/")}/')
    print(f"[app] CSSとJSをR2から配ります（{', '.join(names)}）")
    return shell


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    # OGタグの絶対URL（__BASE__）をこのサーバーのURLに置き換えて配る
    _note_src(request)
    src = _app_shell if _app_shell is not None else (FRONTEND / "index.html").read_text(encoding="utf-8")
    html = src.replace("__BASE__", base_url_for(request))
    html = html.replace("__PUBLIC__", "1" if public_mode() else "0")   # /statusが遮断されても公開モードだと分かるように
    html = html.replace("__MIGRATE__", _migrate_host(request))   # 引っ越し中なら移転先。画面が並びを持って移動する
    html = html.replace("__RETENTION__", str(share_retention_days()))   # 共有が消えるまでの日数（説明文）
    html = html.replace("__SUPPORT__", support.meta(), 1)   # サーバー代の進み具合の棒（backend/support.py）
    html = html.replace("<!--__FONT_LINK__-->", _font_head(), 1)   # 分割フォントの @font-face（<link>）
    html = html.replace("__LOGO_FONT__", share.logo_font_url(), 1)   # ロゴ専用フォント（中身のハッシュ付き）
    # ピクセルフォント（Silkscreen）もR2から配る。分割していないので <link> ではなくHTML内の
    # @font-faceを直接書き換える。**ttfの控えはサーバーのまま**（woff2を読めない古い環境用で、まず使われない）
    if (fbase := _fonts_r2_base()):
        for _f in ("Silkscreen-Regular.woff2", "Silkscreen-Bold.woff2"):
            html = html.replace(f'url("fonts/{_f}")', f'url("{fbase}/{_f}")')   # **woff2だけ**（ttfはR2に置いていない）
    # Google Search Consoleの所有権確認（HTMLタグ方式）。GOOGLE_SITE_VERIFICATIONが無ければタグごと消す
    token = os.getenv("GOOGLE_SITE_VERIFICATION", "").strip()
    html = html.replace("<!--__VERIFY__-->", f'<meta name="google-site-verification" content="{token}">' if token else "", 1)
    # ETagはnonceを入れる前の内容から作る（nonceは毎回変わる）。ブラウザが同じETagを持っていれば304で本文（約40KB）を省く。
    # 304にはCSPヘッダーを付けない（付けるとキャッシュ済み本文のnonceと食い違ってスクリプトが止まる。middleware側で除外）
    etag = '"' + hashlib.sha256(html.encode("utf-8")).hexdigest()[:16] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    # CSP（script-src 'nonce-…'）用。**外に出した <script src> にもnonceは効く**ので、
    # 殻を配るときも1枚で配るときも同じ1行で済む（idで狙う）
    html = html.replace('<script id="app-js"', f'<script id="app-js" nonce="{request.state.csp_nonce}"', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache", "ETag": etag})   # no-cache = 毎回ETagで確認（更新をすぐ配る）


@app.get("/ads.txt")
async def ads_txt() -> Response:
    """AdSenseに出す広告枠の販売許可（IABのads.txt）。ルート直下に置く決まり。
    公開されることが前提のファイルなので、publisher IDを書いてよい。"""
    body = "google.com, pub-6662407728160305, DIRECT, f08c47fec0942fa0\n"
    return Response(body, media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})


_ROBOTS_DISALLOW = ("/search", "/from-url", "/from-playlist", "/image-proxy", "/grids", "/shares",
                    "/uploads", "/outputs", "/health", "/render", "/upload", "/share")
# 共有ページ（`/s/<id>`）を名指しの相手にだけ断る（2026-09-21）。ページ自体は前から `noindex` なので
# 検索結果には出ていないが、確かめるためのクロールは来続けていた（点検の2時間で検索ボットが102件、
# `/s/` への要求の70% が人以外）。30日で消えるページなので索引される値打ちがそもそも無い。
# **`User-agent: *` には入れない**。Xなどがリンクカードを作るための取得まで止まってしまう
_ROBOTS_SHARE_DENY = "/s/"
# 断る相手は、ログのUA種別（`_UA_KINDS`）の「AI」「検索」と同じ顔ぶれにする（名前を2か所に書かない）。
# ただしapplebotはiMessageなどのリンクカードにも使われるので外す（`applebot-extended` はAI学習用なので残す）
_ROBOTS_KEEP = ("applebot",)
_ROBOTS_DENY_AGENTS = tuple(t for kind, tokens in _UA_KINDS if kind in ("AI", "検索")
                            for t in tokens if t not in _ROBOTS_KEEP)


@app.get("/robots.txt")
async def robots(request: Request) -> Response:
    """トップは索引してよい。API・画像・共有の中身はクロール対象から外す"""
    common = [f"Disallow: {p}" for p in _ROBOTS_DISALLOW]
    lines = ["User-agent: *", "Allow: /$", *common, ""]
    # 名指しの相手は `*` のグループを見ないので、共通の分もここへ書き写す（robots.txtの決まり）
    lines += [f"User-agent: {name}" for name in _ROBOTS_DENY_AGENTS]
    lines += ["Allow: /$", *common, f"Disallow: {_ROBOTS_SHARE_DENY}", ""]
    lines += [f"Sitemap: {base_url_for(request)}/sitemap.xml", ""]
    return Response("\n".join(lines), media_type="text/plain", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/sitemap.xml")
async def sitemap(request: Request) -> Response:
    base = base_url_for(request)
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"<url><loc>{base}/</loc><changefreq>weekly</changefreq></url>"
            + "".join(f"<url><loc>{base}/{k}</loc><changefreq>monthly</changefreq></url>" for k in pages.BODIES)
            + "".join(f"<url><loc>{base}/articles/{a['slug']}</loc><lastmod>{a['date']}</lastmod></url>"
                      for a in articles.ARTICLES)
            + "</urlset>\n")
    return Response(body, media_type="application/xml", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/og.png")
async def og_image() -> FileResponse:
    return FileResponse(FRONTEND / "og.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.ico")
async def favicon_ico() -> FileResponse:
    return FileResponse(FRONTEND / "favicon.ico", media_type="image/x-icon", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/favicon.png")
async def favicon_png() -> FileResponse:
    return FileResponse(FRONTEND / "favicon.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/bg-mark.png")
async def bg_mark_png() -> FileResponse:
    """背景色の「画像」の既定（TRACKMENTOのロゴを敷き詰めた絵。scripts/build_icons.pyが作る）。"""
    return FileResponse(FRONTEND / "bg-mark.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/no-cover.png")
async def no_cover_png() -> FileResponse:
    """ジャケットが無い曲のマスに使う画像（scripts/build_icons.pyが作る）。"""
    return FileResponse(FRONTEND / "no-cover.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/apple-touch-icon.png")
async def apple_touch_icon() -> FileResponse:
    return FileResponse(FRONTEND / "apple-touch-icon.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/icon-192.png")
@app.get("/icon-512.png")
async def app_icon(request: Request) -> FileResponse:
    """ホーム画面のアイコン（scripts/build_icons.pyが作る）。manifest.webmanifestから指す。"""
    name = request.url.path.lstrip("/")
    return FileResponse(FRONTEND / name, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


# **Web Share Target**（2026-09-24、運用ボードのideas-0923）。ホーム画面に追加すると、Androidのほかのアプリの
# 「共有」にTRACKMENTOが出て、URLを直接送れる。受け取りはfrontendのtakeSharedUrl()。
# 引数の名前にst_ を付けるのは、共有ページから開く ?share=<id> と取り違えないため。
# **Service Workerは置かない**（Chromeのインストールの条件に入っていない。置くと古い画面が残る心配が増える）
MANIFEST = {
    "name": "TRACKMENTO",
    "short_name": "TRACKMENTO",
    "description": "好きなトラックのサムネイルを並べて1枚の画像に。",
    "lang": "ja",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#F6F6F4",
    "theme_color": "#F6F6F4",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
    "share_target": {
        "action": "/",
        "method": "GET",
        "enctype": "application/x-www-form-urlencoded",   # GETの既定と同じ。書かないとChromeが注意を出す
        "params": {"title": "st_title", "text": "st_text", "url": "st_url"},
    },
}


@app.get("/manifest.webmanifest")
async def manifest() -> Response:
    return Response(json.dumps(MANIFEST, ensure_ascii=False), media_type="application/manifest+json",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/health")
@app.get("/status")   # Webはこちらを使う。EasyPrivacyに「||onrender.com/health」があり、広告ブロッカー入りのブラウザ（Vivaldiなど）は /healthを遮断する
async def health() -> dict:
    # started_at / uptime_s: デプロイ無しの再起動（ディスク初期化）をログ無しで切り分けるため
    # itunes_server: サーバー経由のiTunesがAppleに制限されているか（Webはブラウザから直接叩くので参考情報）
    common = {
        "ok": True,
        "sources": sorted(SOURCES),
        "started_at": datetime.fromtimestamp(app.state.started_at, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "uptime_s": int(time.time() - app.state.started_at),
        "itunes_server": "blocked" if itunes.is_blocked() else "ok",
        "itunes_proxy": bool(itunes.proxy_url()),   # サーバー側iTunesをCloudflare Workers経由にしているか
        "frontend_url": frontend_url(),
        "storage": storage.get_storage().name,
    }
    if public_mode():
        # 公開時は内部情報（キャッシュのパス、内部IP、グリッド名）を出さない。
        # 常駐メモリはログにだけ出す。Renderのヘルスチェック（約5秒おき）でも呼ばれるので、出力は60秒に1回に間引く
        now = time.monotonic()
        if now - _health_logged_at[0] >= 60:
            rss = _rss_mb()
            if rss is not None:
                _health_logged_at[0] = now
                print(f"[health] rss={rss:.0f}MB uptime={common['uptime_s']}s")
        return {**common, "public": True}
    return {
        **common,
        "cache": await asyncio.to_thread(cache.stats),
        "public_base_url": public_base_url(),
        "public": False,
        "grids": grids.list_names(),
    }


@app.get("/artist-candidates")
async def artist_candidates(
    title: str = Query("", description="曲名", max_length=300),
    at: str = Query("", description="このマスの動画の投稿日（ISO）。これより新しい投稿は外す", max_length=40),
    self_id: str = Query("", description="このマスの動画ID（結果から外す）", max_length=32),
    url: str = Query("", description="このマスの動画のURL（ニコニコ / YouTube）。otoDBの作品を引く", max_length=300),
) -> dict:
    """**転載の元になった投稿の候補**（ニコニコ動画の同じ題の古い投稿と、otoDBの作品）。

    利用者が編集パネルで「元の投稿を探す」を押したときだけ呼ばれる。**自動では引かない**
    （100曲の並びで100リクエストになる）。ニコニコは古い順に最大3件。
    otoDBは、マスの動画が登録済みの作品なら作者（Creatorのタグ）と、作品に登録されたほかの投稿（2026-09-21）。

    結果は覚えておく（`cache` の `nicosearch` / `otodb-origin`、7日）。**検索語は鍵にしない**
    （`searchcache.py` と同じ決まり。プライバシーポリシーの「検索キーワードは恒常的に記録しない」）。
    otoDBの鍵は動画のURL（公開の動画を指すだけで、利用者の入れた語ではない）。
    """
    from backend.sources import nicosearch, otodb

    async def nico() -> tuple[list, bool]:
        key = f"{title}|{at}|{self_id}"
        hit = cache.get_search("nicosearch", key, "")
        if hit is not None:
            return hit, True
        rows = await nicosearch.older_posts(title, before=at, self_id=self_id)
        cache.set_search("nicosearch", key, "", rows)
        return rows, False

    (rows, cached), work = await asyncio.gather(nico(), otodb.origin_by_video(url))
    return {"candidates": rows, "otodb": work if work and work.get("artist") else None, "cached": cached}


@app.get("/search")
async def search(
    q: str = Query("", description="曲名", max_length=200),
    artist: str = Query("", description="アーティスト名", max_length=200),
    source: str | None = Query(None, description="itunes|musicbrainz|discogs|otodb|vocadb。省略時はiTunesだけ（otodb・vocadbは含まない）"),
    nocache: bool = Query(False, description="trueでキャッシュを使わず取り直す（公開モードでは無視）"),
    lang: str = Query("ja", pattern="^(ja|en)$", description="enでiTunesの曲名・アーティスト名を米国のストアの表記にする"),
) -> JSONResponse:
    if public_mode():
        nocache = False
    if not (q.strip() or artist.strip()):
        raise HTTPException(400, "qまたはartistを指定してください")
    if source:
        names = [s for s in source.split(",") if s]
        unknown = [s for s in names if s not in SOURCES]
        if unknown:
            raise HTTPException(400, f"未知のソース: {unknown}")
    else:
        names = list(DEFAULT_SOURCES)

    results, failed = await search_sources(names, q, artist, nocache=nocache)
    out: list[Track] = []
    for res in results:
        out.extend(res)
    # ソースの指定が無くて1件も出なければMusicBrainzでも引く（iTunesに無い音源の取りこぼしを埋める）。
    # **指定があるときは足さない**（利用者が選んだ通りに返す）
    if not out and not source and not failed:
        names = [FALLBACK_SOURCE]
        results, failed = await search_sources(names, q, artist, nocache=nocache)
        for res in results:
            out.extend(res)
    if lang == "en":
        # 英語の画面ではiTunesの表記を米国のストアのものに（まとめる前に差し替え、重複の判定も英語表記で行う）
        out = await itunes.to_english(out, client=app.state.http)
    tracks = merge(out) if len(names) > 1 else out
    headers = {}
    if failed:
        # 失敗したソースをフロントに知らせる（ヘッダはASCIIのみ）。例: "musicbrainz=busy,itunes=error"
        headers["X-Search-Failed"] = ",".join(f"{n}={k}" for n, k in failed.items())
    return JSONResponse([t.model_dump() for t in tracks], headers=headers)


async def search_sources(names: list[str], q: str, artist: str, *, nocache: bool = False) -> tuple[list[list[Track]], dict[str, str]]:
    """ソースごとにキャッシュを引き、無いものだけ並列で取りに行く。失敗したソースは空扱いにし、名前と理由（busy/error）を返す。"""
    failed: dict[str, str] = {}
    results: list[list[Track] | None] = [None] * len(names)
    now = time.monotonic()
    # 外へ聞く語（VocaDBは曲名だけ・表記の揺れをそろえたもの。下の `_narrow` で手元で絞る）
    keys = [_source_key(name, q, artist) for name in names]
    if not nocache:
        for i, name in enumerate(names):
            kq, ka = keys[i]
            hit = await asyncio.to_thread(cache.get_search, name, kq, ka)
            from_r2 = False
            if hit is None:
                # SQLiteはデプロイのたびに消えるので、R2の控えも見る（索引に無ければR2へは行かない）
                hit = await asyncio.to_thread(searchcache.get, name, kq, ka, _search_ttl(name))
                if hit is not None:
                    from_r2 = True
                    await asyncio.to_thread(cache.set_search, name, kq, ka, hit)
            if hit is not None:
                results[i] = _narrow(name, [Track.model_validate(t) for t in hit], q, artist)
                _note_srch(name, 1 if from_r2 else 0)
                continue
            # 直前に失敗した同じ検索は外部に聞き直さない（同じ検索の連打でiTunes / MusicBrainzを叩き続けないため）
            recent = _recent_fail.get((name, kq, ka))
            if recent and now - recent[0] < FAIL_TTL:
                results[i] = []
                failed[name] = recent[1]
                _note_srch(name, 3)
    misses = [i for i, r in enumerate(results) if r is None]
    if misses:
        client = app.state.http
        async def timed(i: int) -> tuple[float, list[Track]]:
            t0 = time.monotonic()
            try:
                got = await _fetch_source(names[i], *keys[i], client)
                return time.monotonic() - t0, got
            except Exception as e:
                e.elapsed = time.monotonic() - t0   # 失敗までの時間も分布に入れる（時間切れはここで25秒などになる）
                raise
        fetched = await asyncio.gather(*(timed(i) for i in misses), return_exceptions=True)
        for i, res in zip(misses, fetched):
            if isinstance(res, BaseException):
                _note_srch(names[i], 3, getattr(res, "elapsed", 0.0))
            else:
                dt, res = res
                _note_srch(names[i], 2, dt)
            if isinstance(res, BaseException):
                # 1ソースの失敗で全体を落とさない。失敗は永続キャッシュには入れず、FAIL_TTL秒だけ覚える
                _log_search_failure(names[i], brief(res))
                results[i] = []
                failed[names[i]] = "busy" if isinstance(res, (musicbrainz.SourceBusy, itunes.SourceBlocked, asyncio.TimeoutError)) or "503" in str(res) else "error"
                if isinstance(res, asyncio.TimeoutError) and names[i] in KEEP_ON_TIMEOUT:
                    continue   # 取得は裏で続いている。再検索はそこへ合流するので、失敗として覚えない
                _recent_fail[(names[i], *keys[i])] = (now, failed[names[i]])
                if len(_recent_fail) > 500:
                    for k in [k for k, v in _recent_fail.items() if now - v[0] >= FAIL_TTL]:
                        del _recent_fail[k]
                continue
            results[i] = _narrow(names[i], res, q, artist)
            if res and names[i] not in KEEP_ON_TIMEOUT:  # 空は保存しない（後からデータが増えたときや一時的な失敗で0件が固定されないように）
                dumped = [t.model_dump() for t in res]
                await asyncio.to_thread(cache.set_search, names[i], *keys[i], dumped)
                searchcache.put_bg(names[i], *keys[i], dumped)
    return [r or [] for r in results], failed


# ---- 外へ聞く語と、手元での絞り込み（2026-09-20）----
# VocaDBは曲名だけで引き、アーティストでの絞り込みは手元で行う（`vocadb.query_key` / `narrow`）。
# **控えの鍵もその語にする**ので、「メルトryo」と「メルトsupercell」、「ｼｬﾙﾙ」と「シャルル」は
# VocaDBへ1回しか聞かない。ほかのソースは今までどおり（曲名とアーティストをそのまま渡す）


def _source_key(name: str, q: str, artist: str) -> tuple[str, str]:
    """そのソースに渡す（曲名, アーティスト名）。控えとキャッシュの鍵にもこれを使う"""
    return (vocadb.query_key(q, artist), "") if name == "vocadb" else (q, artist)


def _narrow(name: str, tracks: list[Track], q: str, artist: str) -> list[Track]:
    """曲名だけで引いたソースの結果を、手元でアーティスト名で絞る"""
    return vocadb.narrow(tracks, q, artist) if name == "vocadb" else tracks


async def _fetch_source(name: str, q: str, artist: str, client: httpx.AsyncClient) -> list[Track]:
    """1ソースを取りに行く。`KEEP_ON_TIMEOUT` のソースは時間切れでも取得を止めず、
    同じ検索が走っていればそこへ合流する（同時に同じ語で検索されても外部へは1回）。"""
    limit = SOURCE_TIMEOUTS.get(name, SOURCE_TIMEOUT)
    if name not in KEEP_ON_TIMEOUT:
        return await asyncio.wait_for(SOURCES[name](q, artist, client=client), timeout=limit)
    key = (name, q, artist)
    task = _inflight.get(key)
    if task is None:
        async def run() -> list[Track]:
            try:
                res = await asyncio.wait_for(SOURCES[name](q, artist, client=client), timeout=SOURCE_HARD_TIMEOUT)
                if res:  # 空は保存しない（上と同じ理由）
                    dumped = [t.model_dump() for t in res]
                    await asyncio.to_thread(cache.set_search, name, q, artist, dumped)
                    searchcache.put_bg(name, q, artist, dumped)
                return res
            finally:
                _inflight.pop(key, None)
        task = asyncio.create_task(run())
        # 誰も待っていないまま失敗したときの「Task exception was never retrieved」を出さない
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        _inflight[key] = task
    # 時間切れで打ち切るのは「この応答が待つこと」だけで、取得そのものは続ける。
    # **`asyncio.shield` は使わない**。待つ側が先に諦めたあとで取得が失敗すると、shieldが
    # 「exception in shielded future」とTracebackをログに出し、点検のエラー行に数えられていた（2026-09-19）
    done, _ = await asyncio.wait({task}, timeout=limit)
    if not done:
        raise asyncio.TimeoutError
    return task.result()


@app.post("/hiccup", status_code=204)
async def hiccup(request: Request) -> Response:
    """画面から届く「ブラウザ側で起きた失敗」の件数（`CLIENT_KINDS`）。**種類と回数だけ**を受け取り、
    60秒ごとに `[client]` 行で出す。本文は `{"kind": 回数, …}`。知らない種類・多すぎる回数は捨てる。
    `navigator.sendBeacon` で送られてくるので、内容の型はtext/plainのこともある（JSONとして読む）"""
    try:
        body = json.loads((await request.body())[:2048] or b"{}")
    except ValueError:
        return Response(status_code=204)
    if isinstance(body, dict):
        for k, n in list(body.items())[:20]:
            if k in CLIENT_KINDS and isinstance(n, int) and 0 < n <= 50:
                _client_stats[k] = _client_stats.get(k, 0) + n
    return Response(status_code=204)


class BandcampBody(BaseModel):
    url: str = Field(max_length=2048)


@app.post("/from-playlist", response_model=list[Track])
async def from_playlist(body: BandcampBody) -> list[Track]:
    """プレイリスト（まとめ）のURLから複数曲を取る。ニコニコのマイリスト、SoundCloudのセット、
    bilibiliの収藏夹、Spotifyのプレイリストなど。単体のURLは /from-urlのまま。"""
    url = body.url.strip()
    if not playlist.is_playlist(url):
        raise HTTPException(400, "プレイリストのURLではありません")
    try:
        return await playlist.fetch(url, client=app.state.http)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except httpx.HTTPStatusError as e:
        print(f"[playlist] {playlist.label(url)} {e.response.status_code}")
        raise HTTPException(502, f"{playlist.label(url)}から取れませんでした。少し待ってからもう一度お試しください") from e
    except httpx.HTTPError as e:
        print(f"[playlist] {playlist.label(url)} {e!r}")
        raise HTTPException(502, f"{playlist.label(url)}につながりませんでした。少し待ってからもう一度お試しください") from e


@app.post("/from-url", response_model=Track)
@app.post("/bandcamp", response_model=Track)   # 旧名。互換のため残す
async def from_url(body: BandcampBody) -> Track:
    """Bandcamp / SoundCloud / YouTube / ニコニコ動画 / bilibili / SpotifyのURLからジャケット（サムネイル）・曲名・アーティストを取る。"""
    url = body.url.strip()
    label, _ = fromurl.resolve(url)
    try:
        return await fromurl.fetch(url, client=app.state.http)   # 直接取れなければroxyにフォールバックする
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except httpx.HTTPStatusError as e:
        print(f"[from-url] {label} {e.response.status_code}")
        raise HTTPException(502, f"{label}から取れませんでした。少し待ってからもう一度お試しください") from e
    except httpx.HTTPError as e:
        print(f"[from-url] {label} {e!r}")
        raise HTTPException(502, f"{label}につながりませんでした。少し待ってからもう一度お試しください") from e


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


async def _seed_search_index() -> None:
    """起動後にR2のsearchcache/ を一覧して索引を作る（検索結果の控え。backend/searchcache.py）。
    失敗しても外部に引き直すだけなので握りつぶす"""
    try:
        n = await asyncio.to_thread(searchcache.seed)
    except Exception as e:
        print(f"[error] 検索結果の控えの索引を作れませんでした: {type(e).__name__}: {e}")
        return
    print(f"[storage] searchcacheの索引: {n}件（デプロイ後も検索結果を使い回す）")


async def _seed_listed_index() -> None:
    """起動後に「みんなの並びから探せる」共有の索引を読み直す。

    共有そのもの（1日数千件）ではなく、**印を付けたものだけ**を読む。
    失敗しても探せなくなるだけで、共有は壊れない。
    """
    try:
        n = await asyncio.to_thread(shareindex.seed)
    except Exception as e:
        print(f"[error] みんなの並びの索引を作れませんでした: {type(e).__name__}: {e}")
        return
    print(f"[listed] みんなの並びの索引: {n}件")


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


@app.post("/image-r2")
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


@app.get("/image-proxy")
async def image_proxy(url: str = Query(..., description="取得する画像URL", max_length=2048),
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
                ctype, data = await fetch_image(url)
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
                        got = await fetch_image(alt)
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
        if u == url and u == orig:
            pass
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


async def fetch_image(url: str) -> tuple[str, bytes]:
    """画像を取得して (content-type, bytes) を返す。失敗はHTTPException。"""
    client: httpx.AsyncClient = app.state.http
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


# ---------- グリッドJSON（CLIとWebで共有） ----------
def _grid_name(name: str) -> str:
    try:
        return grids.validate_name(name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/grids")
async def grids_index() -> dict:
    if public_mode():
        raise HTTPException(404, "公開モードでは一覧を出しません")
    return {"grids": grids.list_names()}


@app.get("/grids/{name}", response_model=GridDoc)
async def grid_get(name: str) -> GridDoc:
    name = _grid_name(name)
    if not grids.exists(name):
        raise HTTPException(404, f"グリッド{name}はまだありません")
    try:
        return grids.load(name)
    except ValueError as e:
        raise HTTPException(500, str(e)) from e


@app.put("/grids/{name}", response_model=GridDoc)
async def grid_put(name: str, doc: GridDoc) -> GridDoc:
    """Webの自動保存とJSON読み込みが呼ぶ。savedAtが無ければ今の時刻を入れる。"""
    name = _grid_name(name)
    doc.name = name
    if not doc.savedAt:
        doc.touch()
    grids.save(doc)
    if public_mode():
        _grid_saves[0] += 1
        if _grid_saves[0] % 50 == 0:
            await run_in_threadpool(housekeeping.prune_grids_count)
    return doc


_grid_saves = [0]


_health_logged_at = [0.0]   # [health] を最後に出した時刻（monotonic）


def _rss_mb() -> float | None:
    """このプロセスの常駐メモリ（MB）。Linux以外はNone。"""
    try:
        with open("/proc/self/statm") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError, AttributeError, IndexError):
        return None


@app.delete("/grids/{name}")
async def grid_delete(name: str) -> dict:
    if public_mode():
        raise HTTPException(404, "公開モードでは削除できません")
    name = _grid_name(name)
    p = grids.path_for(name)
    if p.exists():
        p.unlink()
    return {"ok": True}


# ---------- サーバー側描画 ----------
class RenderBody(BaseModel):
    grid: str = "default"
    # 以下は省略可。指定したものだけグリッドのオプションを上書きし、グリッドJSONにも保存する
    size: str | None = None          # "3x3"
    ratio: str | None = None
    sidebar: bool | None = None
    overlay: bool | None = None
    title: str | None = None
    showTitle: bool | None = None
    numbers: bool | None = None
    bg: str | None = None
    bgCustom: str | None = None
    margin: int | None = None
    pad: str | None = None
    gap: int | None = None
    # Webが /shareで並びをそのまま送る用。サーバーのディスクが消えていても（Renderの再起動など）共有できるようにする
    doc: GridDoc | None = None


def _check_cells(doc: GridDoc) -> None:
    limit = max_cells()
    if limit and doc.size > limit:
        raise HTTPException(400, f"公開サーバーでは1枚あたり{limit}マスまでです（今は{doc.cols}×{doc.rows}）")


def apply_render_options(doc: GridDoc, body: RenderBody) -> bool:
    """bodyの指定をdocに反映。変更があればTrue。"""
    changed = False
    if body.size:
        try:
            c, r = (int(v) for v in body.size.lower().split("x"))
        except ValueError as e:
            raise HTTPException(400, "sizeは3x3のように指定してください") from e
        if (c, r) != (doc.cols, doc.rows):
            doc.resize(max(1, min(grids.MAX_COLS, c)), max(1, min(grids.MAX_ROWS, r)))
            changed = True
    if body.title is not None and body.title != doc.title:
        doc.title = body.title[:60]
        changed = True
    opts = doc.options.model_dump()
    for k in ("ratio", "sidebar", "overlay", "showTitle", "numbers", "bg", "bgCustom", "margin", "pad", "gap"):
        v = getattr(body, k)
        if v is not None and v != opts.get(k):
            opts[k] = v
            changed = True
    if body.bgCustom and body.bg is None:
        opts["bg"] = "custom"
    if body.sidebar and body.overlay is None and opts.get("overlay"):
        opts["overlay"] = False   # 横に並べると言われたら、重ねるのはやめる
        changed = True
    if changed:
        try:
            doc.options = GridOptions.model_validate(opts)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    return changed


@app.post("/render")
async def render_grid(request: Request, body: RenderBody = Body(default_factory=RenderBody)) -> dict:
    if public_mode():
        raise HTTPException(404, "公開モードでは /renderは使えません（「トラックを共有」を使ってください）")
    name = _grid_name(body.grid)
    try:
        doc = grids.load(name)
    except ValueError as e:
        raise HTTPException(500, str(e)) from e
    if not any(doc.cells):
        raise HTTPException(400, f"グリッド{name}に曲がありません")
    if apply_render_options(doc, body):
        doc.touch()
        grids.save(doc)
    _check_cells(doc)
    try:
        path, im = await run_render(render.render_to_file, doc)
    except HTTPException:
        raise
    except RuntimeError as e:  # フォント欠落など
        raise HTTPException(500, str(e)) from e
    return {
        "url": f"{base_url_for(request)}/outputs/{path.name}",
        "file": path.name,
        "width": im.width,
        "height": im.height,
        "grid": doc.model_dump(),
    }


# ---------- 手入力用の画像アップロード ----------
@app.post("/upload")
async def upload_image(request: Request, file: UploadFile = File(...)) -> dict:
    """PCやスマホの画像ファイルをuploads/ に保存し、Track.imageに入れる相対URLを返す。"""
    data = await file.read(uploads.MAX_BYTES + 1)
    if len(data) > uploads.MAX_BYTES:
        raise HTTPException(413, "画像が大きすぎます（15MBまで）")
    if not data:
        raise HTTPException(400, "ファイルが空です")
    try:
        url = await run_in_threadpool(uploads.save_image_bytes, data)
    except ValueError as e:
        raise HTTPException(415, str(e)) from e
    return {"url": url, "absolute": f"{base_url_for(request)}{url}"}


# ---------- トラックを共有（PNG + 並びのスナップショット + 共有ページ） ----------
def _doc_for_share(body: RenderBody) -> GridDoc:
    """共有する並びを決める。ブラウザが持っている並び（doc）を正とし、無ければサーバーのJSONを読む。"""
    name = _grid_name(body.grid)
    if body.doc is not None:
        # ブラウザが持っている並びを正とする（サーバー側のJSONは再起動で消えていることがある）
        doc = body.doc
        doc.name = name
        if not doc.savedAt:
            doc.touch()
        grids.save(doc)
    else:
        try:
            doc = grids.load(name)
        except ValueError as e:
            raise HTTPException(500, str(e)) from e
    if not any(doc.cells):
        raise HTTPException(400, f"グリッド{name}に曲がありません")
    if apply_render_options(doc, body):
        doc.touch()
        grids.save(doc)
    _check_cells(doc)
    return doc


async def _finish_share(request: Request, coro) -> dict:
    """保存処理（coroutine）を実行し、回数を数え、共有URLを付けて返す。失敗の扱いは共通。"""
    try:
        info = await coro
    except HTTPException:
        raise   # 待ち行列の上限（503）など
    except share.BudgetExceeded as e:
        raise HTTPException(507, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e
    except Exception as e:  # R2への保存失敗など
        import traceback
        print(f"[share] failed: {e!r}")
        print(traceback.format_exc())
        raise HTTPException(502, "共有の保存に失敗しました。少し待ってからもう一度お試しください") from e
    _count_share(request)
    if public_mode() and not storage.get_storage().is_remote:
        housekeeping.prune_shares()   # R2のときはバケットのライフサイクルルールに任せる
    base = base_url_for(request)
    img_abs = info["image"] if info["image"].startswith("http") else f"{base}{info['image']}"
    return {**info, "url": f"{base}/s/{info['id']}", "image_url": img_abs, "png_url": img_abs}   # png_urlは旧キー


@app.post("/share")
async def share_grid(request: Request, body: RenderBody = Body(default_factory=RenderBody)) -> dict:
    """サーバーで描いて共有する（CLIと、ブラウザ描画ができない端末のフォールバック）。"""
    doc = _doc_for_share(body)
    _check_share_quota(request)
    budget = share_budget_bytes() if (public_mode() or storage.get_storage().is_remote) else 0
    return await _finish_share(request, run_render(share.create, doc, budget))


# 同時に受け付ける共有アップロード。超えたら待たせず503（本文を抱えたまま並ぶとメモリが膨らむ）。
# **3は無料ホスト時代の値**。回線の遅い端末が枠を握ると後続が全部断られ、2026-09-15の点検で
# 2時間に21件の503が出ていた（`/share/upload` の最大応答85.2秒）。Standardなら8で足りる
_UPLOAD_SEM = asyncio.Semaphore(8)
# **受け取り中と、検査・保存は分けて数える**。一緒にすると、回線の細い端末が1件で枠を握り、
# その間の後続が全部503になる（2026-09-15の点検で `/share/upload` の最大応答が122.7秒、
# 653件中5件が503）。受け取りは待つだけなので広く取ってよい。本文の大きい部分は
# Starletteが一時ファイルに逃がすので、待たせてもメモリは膨らまない。
# **バイト列に読むのは内側（8枠）の中**で行う（外で読むと32件ぶん抱えることになる）
_UPLOAD_RECV = asyncio.Semaphore(int(os.getenv("SHARE_UPLOAD_RECV", "32") or 32))


@app.post("/share/upload")
async def share_upload(request: Request) -> dict:
    """ブラウザで描いた本体画像（JPEG。古いタブからはPNG）とカード用JPEGを受け取って共有する。サーバーはヘッダ検査と保存だけ
    （無料ホストの0.1 vCPUでは描画がヘルスチェックを止めるため、描画は端末側で行う）。
    フォーム: doc（JSON文字列）, image（旧名png）, og"""
    _check_share_quota(request)   # 本文（数MB）を読む前に断る。上限到達中に受け取ってから429にしない
    if _UPLOAD_RECV.locked():
        _note_upload(busy=True)
        raise HTTPException(503, "共有が混み合っています。10秒ほど待ってからもう一度お試しください", headers={"Retry-After": "10"})
    async with _UPLOAD_RECV:      # 受け取り（回線が細いと数十秒かかる）
        t_recv = time.monotonic()
        try:
            form = await request.form()
        except ClientDisconnect:   # 利用者が送信途中で離脱（アプリ内ブラウザや回線切替）。サーバー側の異常ではないので5xxにしない
            _note_upload(recv=time.monotonic() - t_recv, cut=True)
            print("[share] 送信途中で切断（利用者側の離脱）")
            raise HTTPException(400, "送信が途中で切れました。もう一度お試しください")
        _note_upload(recv=time.monotonic() - t_recv, kb=int(request.headers.get("content-length") or 0) / 1024)
        doc, image, og = form.get("doc"), form.get("image") or form.get("png"), form.get("og")
        # **カード用（og）は送られてこないのがふつう**（2026-09-16から、本体だけ送ってカードはサーバーで作る）。
        # 開いたままの古いタブは今までどおり送ってくるので、来たときはそれを使う
        if not isinstance(doc, str) or not isinstance(image, StarletteUploadFile):   # request.form() が返すのはstarletteのUploadFile
            raise HTTPException(400, "並び（doc）と画像（image）が必要です")
        try:
            raw = json.loads(doc)   # {"grid": "u-…", "doc": {...}}（/shareのJSONボディと同じ形）
            body = RenderBody(grid=raw.get("grid", "default"), doc=GridDoc.model_validate(raw["doc"]))
        except Exception as e:
            print(f"[share] 並びが読めない: {e!r}")
            raise HTTPException(400, "並びのデータを読めませんでした。ページを読み込み直してからもう一度お試しください") from e
        gdoc = _doc_for_share(body)
        async with _UPLOAD_SEM:   # 検査と保存（CPUとR2。数百msで終わる）
            img_b = await image.read(share.MAX_UPLOAD_IMAGE + 1)
            og_b = await og.read(share.MAX_UPLOAD_OG + 1) if isinstance(og, StarletteUploadFile) else None
            try:
                w, h, ext = await asyncio.to_thread(share.check_uploaded, img_b, og_b)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            _check_share_quota(request)
            budget = share_budget_bytes() if (public_mode() or storage.get_storage().is_remote) else 0
            t_save = time.monotonic()
            try:
                return await _finish_share(request, run_in_threadpool(share.store, gdoc, img_b, og_b, w, h, budget, ext))
            finally:
                _note_upload(save=time.monotonic() - t_save)


# ---------- 自分の共有をあとから外す・消す（2026-09-26、利用者の案） ----------
# 共有したときに返した鍵（ownerKey）を持っている端末だけが頼める。鍵は並びのJSONにSHA-256だけ置いてある（backend/share.py）。
# 鍵は144ビットの乱数なので総当たりは現実的でないが、念のため端末ごとに1時間30回まで
_OWNER_TRIES: dict[str, list[float]] = defaultdict(list)
_OWNER_TRIES_MAX = 30


def _check_owner_tries(request: Request) -> None:
    ip, now = _client_ip(request), time.monotonic()
    tries = [t for t in _OWNER_TRIES[ip] if now - t < 3600]
    if len(tries) >= _OWNER_TRIES_MAX:
        raise HTTPException(429, "しばらく時間をおいてからもう一度お試しください")
    tries.append(now)
    _OWNER_TRIES[ip] = tries
    if len(_OWNER_TRIES) > 10_000:   # 覚えている端末が増えすぎたら古いものを捨てる
        for k in [k for k, v in _OWNER_TRIES.items() if not v or now - v[-1] >= 3600]:
            _OWNER_TRIES.pop(k, None)


class OwnerBody(BaseModel):
    key: str = Field("", max_length=64)


@app.post("/s/{sid}/unlist")
@app.post("/s/{sid}/delete")
async def share_owner_action(request: Request, sid: str, body: OwnerBody) -> dict:
    """みんなのグリッドから外す（unlist）／共有ごと消す（delete）。鍵が合わなければ403、共有が無ければ404。"""
    _check_owner_tries(request)
    if not share.valid_id(sid):
        raise HTTPException(404, "共有が見つかりません")
    action = request.url.path.rsplit("/", 1)[-1]
    try:
        await run_in_threadpool(share.unlist if action == "unlist" else share.delete, sid, body.key)
    except FileNotFoundError:
        raise HTTPException(404, "共有が見つかりません（期限切れか、もう消えています）")
    except share.NotOwner:
        raise HTTPException(403, "この端末からは操作できません（共有したときの端末・ブラウザからだけ操作できます）")
    print(f"[share] {action}: 共有した人の操作")
    return {"id": sid, "action": action}


# 「みんなの並びを探す」。**印を付けた共有だけ**が対象（backend/shareindex.py）。
# `/shares/{fname}` と経路がぶつからないよう、JSONは `/find.json` にしてある
# 文章のページ（使い方・コラム・プライバシーポリシー・利用規約・運営者）。backend/pages.py。言語は共有ページと同じ決め方
@app.get("/guide", response_class=HTMLResponse)
@app.get("/howto", response_class=HTMLResponse)
@app.get("/articles", response_class=HTMLResponse)
@app.get("/privacy", response_class=HTMLResponse)
@app.get("/terms", response_class=HTMLResponse)
@app.get("/about", response_class=HTMLResponse)
@app.get("/updates", response_class=HTMLResponse)
async def text_page(request: Request) -> HTMLResponse:
    kind = request.url.path.strip("/")
    return HTMLResponse(pages.page_html(kind, base_url_for(request), app_url_for(request), _lang_for(request), nonce=request.state.csp_nonce),
                        headers={"Cache-Control": "public, max-age=3600"})


@app.get("/articles/{slug}", response_class=HTMLResponse)
async def article_page(request: Request, slug: str) -> HTMLResponse:
    """コラム1本（backend/articles.py）。本文は日本語だけ"""
    page = pages.article_html(slug, base_url_for(request), app_url_for(request), _lang_for(request))
    if page is None:
        raise HTTPException(404, "コラムが見つかりません")
    return HTMLResponse(page, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/find", response_class=HTMLResponse)
async def find_page(request: Request, q: str = "") -> HTMLResponse:
    _note_src(request)
    q = (q or "").strip()[:80]
    varied = [] if q else shareindex.varied()
    rows = shareindex.search(q) if q else shareindex.newest(skip={r["id"] for r in varied})
    return HTMLResponse(share.find_html(q, rows, base_url_for(request), app_url_for(request),
                                        _lang_for(request), shareindex.count(), varied, nonce=request.state.csp_nonce))


@app.get("/find.json")
async def find_json(q: str = "", limit: int = 40) -> dict:
    q = (q or "").strip()[:80]
    limit = max(1, min(100, limit))
    if q:
        return {"q": q, "total": shareindex.count(), "ready": shareindex.ready(),
                "results": shareindex.search(q, limit)}
    varied = shareindex.varied()
    return {"q": q, "total": shareindex.count(), "ready": shareindex.ready(), "varied": varied,
            "results": shareindex.newest(limit, skip={r["id"] for r in varied})}


@app.get("/s/{sid}", response_class=HTMLResponse)
async def share_page(request: Request, sid: str) -> HTMLResponse:
    _note_src(request)   # 共有ページにも印を付けられる（投稿に貼るのはこちらのことが多い）
    # share.loadはR2への同期GET。ループ内で呼ぶと閲覧が重なったときにサーバー全体が止まり、
    # Renderのヘルスチェック（5秒）に落ちて再起動される
    snap = await run_in_threadpool(share.load, sid)
    if not snap:
        shareindex.forget(sid)   # 期限より前に消した共有（scripts/delete_share.py）を「みんなのグリッド」から外す
        # JSONの404だとXから開いた人に何が起きたか伝わらない。案内ページ（期限切れ・作り直し）を返す
        return HTMLResponse(share.expired_html(sid, base_url_for(request), app_url_for(request), _lang_for(request)), status_code=410)   # 消えた共有は410（Gone）
    return HTMLResponse(share.page_html(snap, base_url_for(request), app_url_for(request), _lang_for(request), nonce=request.state.csp_nonce))
