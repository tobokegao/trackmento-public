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
    """リバースプロキシ（Render など）の後ろにいるとき 1。CF-Connecting-IP（Cloudflare）、無ければ X-Forwarded-For の先頭を
    クライアント IP とみなす。直接公開しているのに 1 にすると、ヘッダを偽装してレートリミットを逃れられるので注意。"""
    return _flag("TRUST_PROXY")


def max_cells() -> int:
    """1 枚に描けるマスの上限（公開モードでの重い描画対策。既定 256。ローカルは無制限）。

    256 はフロント（index.html の MAX_CELLS）と同じ。書き出しは最大辺 2400px に収まるので、
    マスが増えるほど 1 マスは小さくなり、16x16 で約 146px。これ以上は何の絵か分からなくなる。
    """
    try:
        v = int(os.getenv("MAX_CELLS", "256" if public_mode() else "0"))
    except ValueError:
        v = 256
    return max(0, v)


def max_side() -> int:
    """サーバー描画の PNG の最大辺。公開モードは 2400px（ブラウザで描けない端末のフォールバック用。0.1 vCPU なので軽く）。
    ローカルは 8000px。MAX_SIDE で変更可。ブラウザ描画の大きさは端末ごとに frontend 側で決める（最大 3200）"""
    try:
        return max(1000, int(os.getenv("MAX_SIDE", "2400" if public_mode() else "8000")))
    except ValueError:
        return 2400 if public_mode() else 8000


def share_budget_bytes() -> int:
    """共有ファイルの合計サイズの上限。SHARE_BUDGET_GB（既定 9.5 = R2 無料枠 10GB の手前）。0 で無制限"""
    try:
        gb = float(os.getenv("SHARE_BUDGET_GB", "9.5"))
    except ValueError:
        gb = 9.5
    return int(gb * 1024 ** 3) if gb > 0 else 0


def share_limits() -> tuple[int, int]:
    """(IP ごとの 1 日の共有回数, サーバー全体の 1 日の共有回数)。公開モードの既定は 100 / 1500。ローカルは無制限。0 で無制限。
    IP ごとの上限は携帯回線（多数の端末が同じ IP を共有）で無関係な利用者が合算で当たるため、連打対策程度に緩くする。
    容量の保護は SHARE_BUDGET_GB（実バイト数）で別に行うので、全体の回数は連打・暴走の歯止め程度。
    目安: 1 件 約0.35MB（JPEG 品質 90・最大辺 2400）× 1500 件/日 × 保持 7 日 ≈ 3.7GB"""
    d_ip, d_all = ("100", "1500") if public_mode() else ("0", "0")
    try:
        return max(0, int(os.getenv("SHARE_LIMIT_PER_IP_DAY", d_ip))), max(0, int(os.getenv("SHARE_LIMIT_PER_DAY", d_all)))
    except ValueError:
        return (100, 1500) if public_mode() else (0, 0)


def share_retention_days() -> int:
    """共有ファイルが消えるまでの日数（画面の説明文に使う）。実際の削除は R2 のライフサイクル規則（scripts/r2_setup.py --days N）。
    SHARE_RETENTION_DAYS、既定 7"""
    try:
        return max(1, int(os.getenv("SHARE_RETENTION_DAYS", "7")))
    except ValueError:
        return 7


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
