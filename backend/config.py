"""環境変数まわりの共通処理（.envはmain.py / cli.pyの起動時に読む）。

公開運用（GitHub Pagesのフロント + 別ホストのバックエンド）に関わる設定:
- PUBLIC_MODE=1     : 公開モード。CORSを開き、グリッドはブラウザごとのIDで分け、ディスクを自動で掃除する
- CORS_ORIGINS      : フロントのオリジン（カンマ区切り）。未設定で公開モードなら * を許可
- FRONTEND_URL      : 共有ページの「TRACKMENTOで開く」が指すフロントのURL（例: https://user.github.io/trackmento）
- PUBLIC_BASE_URL   : PNGや共有ページのURLのベース。autoならLAN IP（ローカル）／リクエストのホスト（公開モード）
- RATE_LIMIT        : APIの1分あたりのリクエスト上限（IPごと。既定120）
- MIGRATE_TO        : ドメインの引っ越し先（例https://trackmento.com）。空なら引っ越さない
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
    """リバースプロキシ（Renderなど）の後ろにいるとき1。CF-Connecting-IP（Cloudflare）、無ければX-Forwarded-Forの先頭を
    クライアントIPとみなす。直接公開しているのに1にすると、ヘッダを偽装してレートリミットを逃れられるので注意。"""
    return _flag("TRUST_PROXY")


def max_cells() -> int:
    """1枚に描けるマスの上限（公開モードでの重い描画対策。既定256。ローカルは無制限）。

    256はフロント（index.htmlのMAX_CELLS）と同じ。書き出しは最大辺2400pxに収まるので、
    マスが増えるほど1マスは小さくなり、16x16で約146px。これ以上は何の絵か分からなくなる。
    """
    try:
        v = int(os.getenv("MAX_CELLS", "256" if public_mode() else "0"))
    except ValueError:
        v = 256
    return max(0, v)


def max_side() -> int:
    """サーバー描画のPNGの最大辺。公開モードは2400px（ブラウザで描けない端末のフォールバック用。0.1 vCPUなので軽く）。
    ローカルは8000px。MAX_SIDEで変更可。ブラウザ描画の大きさは端末ごとにfrontend側で決める（最大3200）"""
    try:
        return max(1000, int(os.getenv("MAX_SIDE", "2400" if public_mode() else "8000")))
    except ValueError:
        return 2400 if public_mode() else 8000


def share_budget_bytes() -> int:
    """共有ファイルの合計サイズの上限。SHARE_BUDGET_GB（既定9.5 = R2無料枠10GBの手前）。0で無制限"""
    try:
        gb = float(os.getenv("SHARE_BUDGET_GB", "9.5"))
    except ValueError:
        gb = 9.5
    return int(gb * 1024 ** 3) if gb > 0 else 0


def share_limits() -> tuple[int, int]:
    """(IPごとの1日の共有回数, サーバー全体の1日の共有回数)。公開モードの既定は100 / 1500。ローカルは無制限。0で無制限。
    IPごとの上限は携帯回線（多数の端末が同じIPを共有）で無関係な利用者が合算で当たるため、連打対策程度に緩くする。
    容量の保護はSHARE_BUDGET_GB（実バイト数）で別に行うので、全体の回数は連打・暴走の歯止め程度。
    目安: 1件 約0.35MB（JPEG品質90・最大辺2400）× 1500件/日 × 保持7日 ≈ 3.7GB"""
    d_ip, d_all = ("100", "1500") if public_mode() else ("0", "0")
    try:
        return max(0, int(os.getenv("SHARE_LIMIT_PER_IP_DAY", d_ip))), max(0, int(os.getenv("SHARE_LIMIT_PER_DAY", d_all)))
    except ValueError:
        return (100, 1500) if public_mode() else (0, 0)


def share_retention_days() -> int:
    """共有ファイルが消えるまでの日数（画面の説明文に使う）。実際の削除はR2のライフサイクル規則（scripts/r2_setup.py --days N）。
    SHARE_RETENTION_DAYS、既定30"""
    try:
        return max(1, int(os.getenv("SHARE_RETENTION_DAYS", "30")))
    except ValueError:
        return 7


def rate_limit_per_minute() -> int:
    try:
        return max(0, int(os.getenv("RATE_LIMIT", "120")))
    except ValueError:
        return 120


def lan_ip() -> str:
    """LAN内でこのPCに届くIPv4を推定する（外向きUDPソケットの自アドレス。送信はしない）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1。実際にはパケットを出さない
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def public_base_url(port: int = 8000) -> str:
    """生成PNGのURLに使うベース（リクエスト情報が無いとき用。CLIなど）。"""
    v = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not v or v.lower() == "auto":
        return f"http://{lan_ip()}:{port}"
    return v


def migrate_to() -> str:
    """**ドメインを引っ越すときの移転先**（例 `https://trackmento.com`）。空なら引っ越しをしない。

    設定すると、これと違うホストで来た要求のうち、共有ページなどは301で移転先へ送り、
    画面（`/`）だけはそのまま返す（ブラウザに保存されている並びを引き継いでから自分で移動するため）。
    """
    return os.getenv("MIGRATE_TO", "").strip().rstrip("/")


def base_url_for(request) -> str:
    """HTTPリクエストから見たベースURL。PUBLIC_BASE_URLが明示されていればそれ、
    公開モードならリクエストのホスト（リバースプロキシのX-Forwarded-* を尊重）、それ以外はLAN IP。"""
    v = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if v and v.lower() != "auto":
        return v
    if public_mode() and request is not None:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        return f"{proto}://{host}"
    return public_base_url()


def app_url_for(request) -> str:
    """共有ページから戻る先（フロント）。FRONTEND_URLが無ければバックエンド自身（/ でindexを配っている）。"""
    return frontend_url() or base_url_for(request)
