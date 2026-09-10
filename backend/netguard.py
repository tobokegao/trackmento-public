"""外部 URL を取りに行くときの SSRF 対策。

- 私設アドレス・ループバック・リンクローカル・予約アドレス宛てを拒否する（DNS 解決後の IP で判定）
- リダイレクトは自動追従せず、1 ホップごとに宛先を再検査する（許可ホストから内部へ飛ばされないように）
画像プロキシ、サーバー側描画の画像取得、Bandcamp などページ取得の入口で使う。
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

MAX_REDIRECTS = 5


def is_public_host(host: str) -> bool:
    """名前解決した全アドレスが公開アドレスなら True。解決できなければ False。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not _ip_public(ip):
            return False
    return True


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


async def safe_get(client: httpx.AsyncClient, url: str, *, allowlist: tuple[str, ...] = (), **kw) -> httpx.Response:
    """リダイレクトを手動で追い、各ホップの宛先を検査しながら GET する。"""
    kw.pop("follow_redirects", None)
    for _ in range(MAX_REDIRECTS + 1):
        if not url_ok(url, allowlist):
            raise BlockedURL(f"この宛先は取得できません: {urlparse(url).hostname}")
        r = await client.get(url, follow_redirects=False, **kw)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            continue
        return r
    raise BlockedURL("リダイレクトが多すぎます")


def safe_get_sync(url: str, *, allowlist: tuple[str, ...] = (), timeout: float = 20, headers: dict | None = None) -> httpx.Response:
    """同期版（サーバー側描画・CLI 用）。"""
    with httpx.Client(timeout=timeout, follow_redirects=False) as c:
        for _ in range(MAX_REDIRECTS + 1):
            if not url_ok(url, allowlist):
                raise BlockedURL(f"この宛先は取得できません: {urlparse(url).hostname}")
            r = c.get(url, headers=headers)
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            return r
    raise BlockedURL("リダイレクトが多すぎます")
