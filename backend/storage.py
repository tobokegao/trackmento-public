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
import threading
import time
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

    def usage_bytes(self) -> int:
        return sum(p.stat().st_size for p in SHARES.glob("*") if p.is_file()) if SHARES.exists() else 0

    def list_objects(self):
        """(キー, バイト数, 最終更新 UTC) を順に返す。"""
        from datetime import datetime, timezone
        if not SHARES.exists():
            return
        for p in SHARES.glob("*"):
            if p.is_file():
                st = p.stat()
                yield p.name, st.st_size, datetime.fromtimestamp(st.st_mtime, timezone.utc)

    def delete_many(self, keys: list[str]) -> int:
        for k in keys:
            self.delete(k)
        return len(keys)


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

    def usage_bytes(self) -> int:
        """バケット内の合計バイト数。一覧（ListObjectsV2）は Class A 操作だが 1000 件ごとに 1 回なので安い"""
        return sum(size for _, size, _ in self.list_objects())

    def list_objects(self):
        """(キー, バイト数, 最終更新 UTC) を順に返す。1000 件ごとに 1 回の一覧呼び出し（7,000 件で 8 回・数秒）。"""
        token = None
        while True:
            kw = {"Bucket": self.bucket, "MaxKeys": 1000}
            if token:
                kw["ContinuationToken"] = token
            r = self._client.list_objects_v2(**kw)
            for o in r.get("Contents", []):
                yield o["Key"], o.get("Size", 0), o["LastModified"]
            if not r.get("IsTruncated"):
                return
            token = r.get("NextContinuationToken")

    def delete_many(self, keys: list[str]) -> int:
        """まとめて削除（1 回 1000 件まで）。削除できた件数を返す。"""
        done = 0
        for i in range(0, len(keys), 1000):
            chunk = keys[i:i + 1000]
            r = self._client.delete_objects(Bucket=self.bucket, Delete={"Objects": [{"Key": k} for k in chunk], "Quiet": True})
            done += len(chunk) - len(r.get("Errors", []))
        return done


# ---- 使用量の集計（10 分キャッシュ。保存のたびに加算するので、その間も上限判定がずれない） ----
_usage_lock = threading.Lock()
_usage: tuple[float, int] | None = None   # (取得時刻, バイト数)
USAGE_CACHE_SEC = 600


_listing = False   # 一覧取得中（重複して回さない）


def usage_bytes(refresh: bool = False) -> int:
    """合計バイト数。R2 の一覧は数秒かかるのでロックの外で行う（握ったままだと共有の保存が全部その後ろに並び、
    上限到達時に共有のたび一覧が走ってサーバーが詰まる）。取得中に別スレッドが来たら手元の値で代用する。"""
    global _usage, _listing
    with _usage_lock:
        if _usage and (not refresh and time.monotonic() - _usage[0] < USAGE_CACHE_SEC or _listing):
            return _usage[1]
        _listing = True
    try:
        n = get_storage().usage_bytes()
    finally:
        with _usage_lock:
            _listing = False
    with _usage_lock:
        _usage = (time.monotonic(), n)
    return n


def add_usage(n: int) -> None:
    global _usage
    with _usage_lock:
        if _usage:
            _usage = (_usage[0], _usage[1] + n)


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
