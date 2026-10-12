"""負荷の診断ログの数え（公開モードで60秒ごとに出す）。**IP・検索語・生のUser-Agentは含めない**。

数えるだけの入れ物と、その足し方・1行への組み方。60秒ごとに出す監視ループ（`_load_monitor`）は
ほかのモジュールの数え（画像・検索）もまとめて読むので `main.py` に置いてある。
2026-10-12に `main.py` から分けた（名前はそのまま）。
"""
from __future__ import annotations

import os
import re
import urllib.parse

import httpx
from fastapi import Request


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


def _rss_mb() -> float | None:
    """このプロセスの常駐メモリ（MB）。Linux以外はNone。"""
    try:
        with open("/proc/self/statm") as f:
            pages = int(f.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError, AttributeError, IndexError):
        return None
