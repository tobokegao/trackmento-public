"""共有ファイル（PNG と並びの JSON）の置き場所。

- ローカル: shares/ ディレクトリ（既定）
- Cloudflare R2: S3 互換 API（boto3）。無料枠はストレージ 10GB、書き込み 100 万回／月、読み出し 1,000 万回／月、転送量は無料。
  環境変数:
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET   … これらが揃うと R2 を使う
    R2_PUBLIC_URL … バケットの公開 URL（例 https://pub-xxxx.r2.dev や独自ドメイン）。あれば PNG をそこから直接配信して
                    サーバーの転送量を節約する。無ければバックエンドが R2 から読んで中継する
    R2_ENDPOINT   … 省略時は https://<account_id>.r2.cloudflarestorage.com
  有効期限はバケットの「オブジェクトライフサイクルルール」で設定する（README 参照。既定は 30 日を推奨）
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARES = ROOT / "shares"


class LocalStorage:
    is_remote = False
    name = "local"

    def put(self, key: str, data: bytes, content_type: str) -> None:
        p = SHARES / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes | None:
        p = SHARES / key
        return p.read_bytes() if p.is_file() else None

    def exists(self, key: str) -> bool:
        return (SHARES / key).is_file()

    def delete(self, key: str) -> None:
        try:
            (SHARES / key).unlink()
        except FileNotFoundError:
            pass

    def public_url(self, key: str) -> str | None:
        return None


class R2Storage:
    is_remote = True
    name = "r2"

    def __init__(self, account_id: str, access_key: str, secret_key: str, bucket: str, public_url: str = "", endpoint: str = ""):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._public = public_url.rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint or f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}, connect_timeout=10, read_timeout=30),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type, CacheControl="public, max-age=86400")

    def get(self, key: str) -> bytes | None:
        try:
            r = self._client.get_object(Bucket=self.bucket, Key=key)
        except self._client.exceptions.NoSuchKey:
            return None
        except Exception as e:  # botocore の 404 は ClientError
            if getattr(e, "response", {}).get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        return r["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            if getattr(e, "response", {}).get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def public_url(self, key: str) -> str | None:
        return f"{self._public}/{key}" if self._public else None


_storage: LocalStorage | R2Storage | None = None


def configured_r2() -> dict[str, str] | None:
    keys = {k: os.getenv(k, "").strip() for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")}
    if all(keys.values()):
        keys["R2_PUBLIC_URL"] = os.getenv("R2_PUBLIC_URL", "").strip()
        keys["R2_ENDPOINT"] = os.getenv("R2_ENDPOINT", "").strip()
        return keys
    return None


def get_storage() -> LocalStorage | R2Storage:
    global _storage
    if _storage is None:
        cfg = configured_r2()
        if cfg:
            _storage = R2Storage(cfg["R2_ACCOUNT_ID"], cfg["R2_ACCESS_KEY_ID"], cfg["R2_SECRET_ACCESS_KEY"], cfg["R2_BUCKET"], cfg["R2_PUBLIC_URL"], cfg["R2_ENDPOINT"])
        else:
            _storage = LocalStorage()
    return _storage


def reset() -> None:
    """テスト用。環境変数を変えたあとに呼ぶ。"""
    global _storage
    _storage = None
