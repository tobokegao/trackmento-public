"""Cloudflare R2の初期設定をS3互換APIで行う（ダッシュボードで見つからないときの代替）。

  python scripts/r2_setup.py            # .envのR2_* を使う。バケットが無ければ作り、7日で削除するライフサイクルルールを設定（APIトークンにバケット設定権限が要る。無ければダッシュボードで）
  python scripts/r2_setup.py --days 60  # 期限を変える
  python scripts/r2_setup.py --check    # 設定を表示するだけ

公開URL（R2.dev subdomainの有効化）はS3 APIでは設定できないので、ダッシュボードのバケット → Settings → Public accessで行う。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import storage  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="共有ファイルを削除するまでの日数（既定7）")
    ap.add_argument("--check", action="store_true", help="設定を表示するだけ")
    a = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    cfg = storage.configured_r2()
    if not cfg:
        print("R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKETを .envに設定してください", file=sys.stderr)
        return 1
    st = storage.get_storage()
    assert isinstance(st, storage.R2Storage)
    c, bucket = st._client, st.bucket

    # バケット
    try:
        c.head_bucket(Bucket=bucket)
        print(f"バケット{bucket}: あり")
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket", "NotFound") and not a.check:
            try:
                c.create_bucket(Bucket=bucket)
                print(f"バケット{bucket}: 作成しました")
            except Exception as e2:
                print(f"バケット{bucket}: 無いので作ろうとしましたが失敗しました（{e2}）。ダッシュボードのR2 → Create bucketで作ってから再実行してください", file=sys.stderr)
                return 1
        else:
            print(f"バケット{bucket}: 確認できません（{code or e}）。アカウントID・トークンの権限（Object Read & Write）を確認してください", file=sys.stderr)
            return 1

    # ライフサイクルルール
    if not a.check:
        c.put_bucket_lifecycle_configuration(
            Bucket=bucket,
            LifecycleConfiguration={"Rules": [{
                "ID": "trackmento-expire-shares",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Expiration": {"Days": a.days},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
            }]},
        )
        print(f"ライフサイクルルール: 全オブジェクトを{a.days}日で削除、に設定しました")
    try:
        rules = c.get_bucket_lifecycle_configuration(Bucket=bucket).get("Rules", [])
        for r in rules:
            print(f"  現在のルール: {r.get('ID')} status={r.get('Status')} expire={r.get('Expiration', {}).get('Days')}日")
        if not rules:
            print("  現在のルール: なし")
    except Exception as e:
        print(f"  ルールを読めません: {e}")

    # 使用量と公開URL
    print(f"使用量: {st.usage_bytes() / 1024**2:.1f} MB")
    print(f"公開URL: {cfg.get('R2_PUBLIC_URL') or '未設定 → ダッシュボードのバケット → Settings → Public accessでR2.dev subdomainをAllowにし、.envのR2_PUBLIC_URLに入れる'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
