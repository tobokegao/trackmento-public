"""R2 の使用量の履歴を Cloudflare の GraphQL Analytics から引いて `metrics/r2_history.jsonl` に残す。

使い方:
  PYTHONUTF8=1 .venv/Scripts/python scripts/r2_history.py [--days 31] [--out metrics/r2_history.jsonl] [--dry-run]

  `.env` の `CLOUDFLARE_API_TOKEN`（権限は Account → Account Analytics → Read）と
  `R2_ACCOUNT_ID` / `R2_BUCKET` を読む。**R2 の S3 キーとは別のトークン**が要る
  （発行は https://dash.cloudflare.com/profile/api-tokens の Custom token から）。

なぜこれを使うか:
  毎日の掃除（`r2_prune.py --append`）が残すのは、その日から先の内訳だけ。**過去は残っていない**。
  GraphQL なら直近 31 日ぶんをさかのぼって引ける。**Class A / B の課金対象という記述は無い**ので、
  バケットを一覧するのと違って回数を気にしなくてよい。

取れないもの:
  プレフィックスごとの内訳。次元は `bucketName` と `datetime` だけなので、`imgcache/` が何 GB かは分からない。
  内訳が要るなら掃除の相乗り（`metrics/r2.jsonl`）のほうを使う。

注意:
  Cloudflare は「この数字を請求額の根拠にするな」と明記している。目安として見る。
  同じ日の行は上書きする（何度回しても増えない）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

ENDPOINT = "https://api.cloudflare.com/client/v4/graphql"

# `max` を取るのは、1 日の中の複数の計測点から「その日いちばん多かったとき」を代表にするため。
# 平均にすると、増え続けている時期に実際より小さく見える。
QUERY = """
query ($account: string!, $bucket: string!, $start: Time!, $end: Time!) {
  viewer {
    accounts(filter: { accountTag: $account }) {
      r2StorageAdaptiveGroups(
        limit: 10000
        filter: { datetime_geq: $start, datetime_leq: $end, bucketName: $bucket }
        orderBy: [datetime_DESC]
      ) {
        max { objectCount payloadSize metadataSize }
        dimensions { datetime }
      }
    }
  }
}
"""


def fetch(token: str, account: str, bucket: str, days: int) -> list[dict]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    body = json.dumps({
        "query": QUERY,
        "variables": {
            "account": account,
            "bucket": bucket,
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }).encode()
    req = urllib.request.Request(
        ENDPOINT, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            doc = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"Cloudflare が {e.code} を返した: {detail}")

    if doc.get("errors"):
        raise SystemExit(f"GraphQL がエラーを返した: {json.dumps(doc['errors'], ensure_ascii=False)[:500]}")
    accounts = (doc.get("data") or {}).get("viewer", {}).get("accounts") or []
    if not accounts:
        raise SystemExit("アカウントが返ってこなかった。R2_ACCOUNT_ID とトークンの Account Resources を確かめる")
    return accounts[0].get("r2StorageAdaptiveGroups") or []


def to_daily(groups: list[dict]) -> dict[str, dict]:
    """計測点を日ごとにまとめる。1 日に複数あるので、その日のいちばん大きい値を採る。"""
    daily: dict[str, dict] = {}
    for g in groups:
        dt = (g.get("dimensions") or {}).get("datetime", "")
        date = dt[:10]
        if not date:
            continue
        m = g.get("max") or {}
        size = (m.get("payloadSize") or 0) + (m.get("metadataSize") or 0)
        cur = daily.get(date)
        if cur is None or size > cur["bytes"]:
            daily[date] = {"date": date, "bytes": size, "objects": m.get("objectCount") or 0}
    return daily


def merge(path: Path, daily: dict[str, dict]) -> int:
    """同じ日は上書きして書き戻す。何度回しても行が増えない。"""
    existing: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("date"):
                existing[r["date"]] = r
    added = sum(1 for d in daily if d not in existing)
    existing.update(daily)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(existing[d], ensure_ascii=False) + "\n" for d in sorted(existing)),
        encoding="utf-8",
    )
    return added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=31, help="さかのぼる日数（保持は 31 日まで）")
    ap.add_argument("--out", type=Path, default=ROOT / "metrics" / "r2_history.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="書かずに表示するだけ")
    a = ap.parse_args()

    token = os.getenv("CLOUDFLARE_API_TOKEN")
    account = os.getenv("R2_ACCOUNT_ID")
    bucket = os.getenv("R2_BUCKET")
    missing = [k for k, v in (("CLOUDFLARE_API_TOKEN", token), ("R2_ACCOUNT_ID", account), ("R2_BUCKET", bucket)) if not v]
    if missing:
        raise SystemExit(
            f"{', '.join(missing)} が無い。CLOUDFLARE_API_TOKEN は R2 の S3 キーとは別物で、\n"
            "https://dash.cloudflare.com/profile/api-tokens の Custom token から\n"
            "Account → Account Analytics → Read の権限で発行して .env に足す"
        )

    daily = to_daily(fetch(token, account, bucket, a.days))
    if not daily:
        print("計測点が返ってこなかった（バケット名が違うか、まだ記録が無い）")
        return 1

    for d in sorted(daily):
        r = daily[d]
        print(f"  {r['date']}  {r['bytes'] / 1024**3:7.2f} GB  {r['objects']:>9,} 件")

    if a.dry_run:
        print(f"（{len(daily)} 日ぶん。--dry-run なので書いていない）")
        return 0
    added = merge(a.out, daily)
    print(f"{a.out} に {len(daily)} 日ぶんを書いた（新しく増えたのは {added} 日）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
