"""環境変数まわりの共通処理（.env は main.py / cli.py の起動時に読む）。"""
from __future__ import annotations

import os
import socket


def lan_ip() -> str:
    """LAN 内でこの PC に届く IPv4 を推定する（外向き UDP ソケットの自アドレス。送信はしない）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1。実際にはパケットを出さない
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def public_base_url(port: int = 8000) -> str:
    """生成 PNG の URL に使うベース。PUBLIC_BASE_URL が未設定か auto なら LAN IP を使う。"""
    v = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not v or v.lower() == "auto":
        return f"http://{lan_ip()}:{port}"
    return v
