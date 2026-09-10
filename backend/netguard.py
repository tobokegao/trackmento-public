"""外部 URL を取りに行くときの SSRF 対策。

- 私設アドレス・ループバック・リンクローカル・予約アドレス宛てを拒否する（DNS 解決後の IP で判定）
- 検査した IP にそのまま接続する（DNS ピンニング）。名前解決を検査時と接続時で 2 回行うと、その間に答えを
  変えられる（DNS rebinding）ので、URL のホストを IP に置き換え、Host ヘッダと TLS の SNI に元のホスト名を渡す。
  証明書の検証も元のホスト名で行う（httpx の sni_hostname 拡張）
- リダイレクトは自動追従せず、1 ホップごとに宛先を再検査・再ピンする（許可ホストから内部へ飛ばされないように）
画像プロキシ、サーバー側描画の画像取得、Bandcamp などページ取得の入口で使う。
"""
from __future__ import annotations

import ipaddress
import socket
import time
import asyncio
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

MAX_REDIRECTS = 5


def _ip_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        # ::ffff:a.b.c.d（IPv4 射影）や 64:ff9b::a.b.c.d（NAT64）は中の IPv4 で判定する
        inner = ip.ipv4_mapped
        if inner is None and ip in ipaddress.ip_network("64:ff9b::/96"):
            inner = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
        if inner is not None:
            return _ip_public(inner)
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return False
    return ip.is_global   # 100.64/10（CGNAT）や 192.0.0/24 なども外す


_RESOLVE_TTL = 60.0        # 名前解決の結果を覚える秒数（サムネイル 1 枚ごとに DNS を引かない）
_RESOLVE_FAIL_TTL = 10.0   # 解決できなかった／非公開だったホストを覚える秒数
_resolve_cache: dict[str, tuple[float, str | None]] = {}


def resolve_public(host: str) -> str | None:
    """名前解決し、全アドレスが公開アドレスなら接続に使う 1 つ（IPv4 優先）を返す。1 つでも駄目なら None。
    同期呼び出し（getaddrinfo は数秒かかることがある）。async から呼ぶときは safe_get のようにスレッドへ逃がす。"""
    now = time.monotonic()
    hit = _resolve_cache.get(host)
    if hit and hit[0] > now:
        return hit[1]
    ip = _resolve_public_uncached(host)
    if len(_resolve_cache) > 1000:
        _resolve_cache.clear()
    _resolve_cache[host] = (now + (_RESOLVE_TTL if ip else _RESOLVE_FAIL_TTL), ip)
    return ip


def _resolve_public_uncached(host: str) -> str | None:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            ips.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            return None
    if not ips or not all(_ip_public(ip) for ip in ips):
        return None
    v4 = [ip for ip in ips if ip.version == 4]
    return str((v4 or ips)[0])


def is_public_host(host: str) -> bool:
    """名前解決した全アドレスが公開アドレスなら True。解決できなければ False。"""
    return resolve_public(host) is not None


def url_ok(url: str, allowlist: tuple[str, ...] = ()) -> bool:
    """http(s) で、許可ホスト（末尾一致）か公開アドレスの URL だけ許す。"""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    host = p.hostname.lower()
    if any(host == d or host.endswith("." + d) for d in allowlist):
        return True
    return is_public_host(host)


class BlockedURL(ValueError):
    pass


def _plan(url: str, allowlist: tuple[str, ...]) -> tuple[str, dict, dict]:
    """1 ホップ分の接続計画。(接続に使う URL, 追加ヘッダ, httpx の extensions)。
    許可ホストはそのまま。それ以外は公開 IP に解決して IP へ接続し、Host と SNI に元のホスト名を使う。"""
    try:
        p = urlparse(url)
    except ValueError as e:
        raise BlockedURL("URL が不正です") from e
    if p.scheme not in ("http", "https") or not p.hostname:
        raise BlockedURL("http(s) の URL だけ取得できます")
    host = p.hostname.lower()
    if any(host == d or host.endswith("." + d) for d in allowlist):
        return url, {}, {}
    ip = resolve_public(host)
    if ip is None:
        raise BlockedURL(f"この宛先は取得できません: {host}")
    ip_lit = f"[{ip}]" if ":" in ip else ip
    netloc = f"{ip_lit}:{p.port}" if p.port else ip_lit
    pinned = urlunparse((p.scheme, netloc, p.path or "/", p.params, p.query, ""))
    host_hdr = f"{host}:{p.port}" if p.port else host
    ext = {"sni_hostname": host} if p.scheme == "https" else {}
    return pinned, {"Host": host_hdr}, ext


def _next(url: str, r: httpx.Response) -> str | None:
    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
        return urljoin(url, r.headers["location"])
    return None


async def safe_get(client: httpx.AsyncClient, url: str, *, allowlist: tuple[str, ...] = (), **kw) -> httpx.Response:
    """検査した IP に接続しながら GET し、リダイレクトは 1 ホップずつ再検査して追う。
    返す Response の final_url に、最後に取得した論理 URL（IP ではなく元のホスト名のもの）を入れる。"""
    kw.pop("follow_redirects", None)
    headers = dict(kw.pop("headers", None) or {})
    for _ in range(MAX_REDIRECTS + 1):
        # _plan の名前解決は同期（getaddrinfo）。イベントループを止めないようスレッドで行う
        pinned, extra, ext = await asyncio.to_thread(_plan, url, allowlist)
        r = await client.get(pinned, follow_redirects=False, headers={**headers, **extra}, extensions=ext or None, **kw)
        nxt = _next(url, r)
        if nxt is None:
            r.final_url = url  # type: ignore[attr-defined]
            return r
        url = nxt
    raise BlockedURL("リダイレクトが多すぎます")


def safe_get_sync(url: str, *, allowlist: tuple[str, ...] = (), timeout: float = 20, headers: dict | None = None) -> httpx.Response:
    """同期版（サーバー側描画・CLI 用）。"""
    headers = dict(headers or {})
    with httpx.Client(timeout=timeout, follow_redirects=False) as c:
        for _ in range(MAX_REDIRECTS + 1):
            pinned, extra, ext = _plan(url, allowlist)
            r = c.get(pinned, headers={**headers, **extra}, extensions=ext or None)
            nxt = _next(url, r)
            if nxt is None:
                r.final_url = url  # type: ignore[attr-defined]
                return r
            url = nxt
    raise BlockedURL("リダイレクトが多すぎます")
