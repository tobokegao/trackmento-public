"""Render点検（render-check.yml）を起こして、終わるまで待つ。ボード更新のルーティンが最初に呼ぶ（2026-11-28）。

  python3 scripts/ping_render_check.py [--wait 900]

クラウドのルーティンからは `gh workflow run` が打てない（GH_TOKENが無効）ので、origin/masterの上に空コミットを作り、
`claude/render-check-ping-<UTCの時刻>` という名前の新しいブランチにpushして合図にする。
workflow側は記録をmasterに足し、最後にこのブランチを消す（`.github/workflows/render-check.yml`）。

- 毎回違う名前で、force pushはしない。push先はこの名前だけ
- 終わったかは公開のAPI（認証なし、1時間60回まで）で、合図のコミットの実行を見る
- **失敗しても終了コードは0**（呼ぶ側はボードの更新をそのまま続ける）。結果は標準出力の最後の行に出す
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

REPO = "tobokegao/trackmento-public"
PREFIX = "claude/render-check-ping-"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def runs_for(sha: str) -> list[dict]:
    url = f"https://api.github.com/repos/{REPO}/actions/runs?head_sha={sha}&per_page=20"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "trackmento-board"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r).get("workflow_runs") or []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=900, help="点検が終わるのを待つ秒数の上限（既定900）")
    args = ap.parse_args()
    try:
        git("fetch", "-q", "origin", "master")
        sha = git("-c", "user.name=trackmento-board", "-c", "user.email=board@trackmento.invalid",
                  "commit-tree", "origin/master^{tree}", "-p", "origin/master", "-m", "ping: render-check（ボード更新のルーティンから）")
        branch = PREFIX + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        git("push", "-q", "origin", f"{sha}:refs/heads/{branch}")
    except subprocess.CalledProcessError as e:
        print(f"[ping] 合図のpushに失敗: {(e.stderr or '').strip()[:300]}")
        print("RESULT: push-failed")
        return 0
    print(f"[ping] {branch} にpushした（{sha[:7]}）")

    deadline = time.time() + args.wait
    seen = None
    while time.time() < deadline:
        time.sleep(30)
        try:
            run = next((r for r in runs_for(sha) if r.get("path", "").endswith("render-check.yml")), None)
        except Exception as e:   # 公開APIの一時的な失敗は待ち続ける
            print(f"[ping] 実行の確認に失敗（続ける）: {type(e).__name__}")
            continue
        if run and run.get("status") == "completed":
            print(f"[ping] 点検が終わった: {run.get('conclusion')} {run.get('html_url')}")
            print(f"RESULT: {run.get('conclusion')}")
            return 0
        if run and not seen:
            seen = run.get("html_url")
            print(f"[ping] 点検が走っている: {seen}")
    print(f"[ping] {args.wait}秒待ったが終わらなかった（{'起動は確認' if seen else '起動を確認できない'}）")
    print("RESULT: timeout")
    return 0


if __name__ == "__main__":
    sys.exit(main())
