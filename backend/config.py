"""環境変数まわりの共通処理（.env は main.py / cli.py の起動時に読む）。

公開運用（GitHub Pages のフロント + 別ホストのバックエンド）に関わる設定:
- PUBLIC_MODE=1     : 公開モード。CORS を開き、グリッドはブラウザごとの ID で分け、ディスクを自動で掃除する
- CORS_ORIGINS      : フロントのオリジン（カンマ区切り）。未設定で公開モードなら * を許可
- FRONTEND_URL      : 共有ページの「TRACKMENTO で開く」が指すフロントの URL（例: https://user.github.io/musicgrid-local）
- PUBLIC_BASE_URL   : PNG や共有ページの URL のベース。auto なら LAN IP（ローカル）／リクエストのホスト（公開モード）
- RATE_LIMIT        : API の 1 分あたりのリクエスト上限（IP ごと。既定 120）
"""
from __future__ import annotations

import os
import socket


def _flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def public_mode() -> bool:
    return _flag("PUBLIC_MODE")


def frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "").strip().rstrip("/")


def cors_origins() -> list[str]:
    v = os.getenv("CORS_ORIGINS", "").strip()
    if v:
        return [o.strip().rstrip("/") for o in v.split(",") if o.strip()]
    return ["*"] if public_mode() else []


def trust_proxy() -> bool:
    """リバースプロキシ（Render など）の後ろにいるとき 1。X-Forwarded-For の末尾（プロキシが付けた値）をクライアント IP とみなす。
    直接公開しているのに 1 にすると、ヘッダを偽装してレートリミットを逃れられるので注意。"""
    return _flag("TRUST_PROXY")


def max_cells() -> int:
    """1 枚に描けるマスの上限（公開モードでの重い描画対策。既定 64 = 8×8。ローカルは無制限）。"""
    try:
        v = int(os.getenv("MAX_CELLS", "64" if public_mode() else "0"))
    except ValueError:
        v = 64
    return max(0, v)


def rate_limit_per_minute() -> int:
    try:
        return max(0, int(os.getenv("RATE_LIMIT", "120")))
    except ValueError:
        return 120


def lan_ip() -> str:
    """LAN 内でこの PC に届く IPv4 を推定する（外向き UDP ソケットの自アドレス。送信はしない）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1。実際にはパケットを出さない
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def public_base_url(port: int = 8000) -> str:
    """生成 PNG の URL に使うベース（リクエスト情報が無いとき用。CLI など）。"""
    v = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not v or v.lower() == "auto":
        return f"http://{lan_ip()}:{port}"
    return v


def base_url_for(request) -> str:
    """HTTP リクエストから見たベース URL。PUBLIC_BASE_URL が明示されていればそれ、
    公開モードならリクエストのホスト（リバースプロキシの X-Forwarded-* を尊重）、それ以外は LAN IP。"""
    v = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if v and v.lower() != "auto":
        return v
    if public_mode() and request is not None:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        return f"{proto}://{host}"
    return public_base_url()


def app_url_for(request) -> str:
    """共有ページから戻る先（フロント）。FRONTEND_URL が無ければバックエンド自身（/ で index を配っている）。"""
    return frontend_url() or base_url_for(request)
