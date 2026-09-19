"""利用者向けの文章（更新情報・案内ページなど）を Gemini に添削してもらう。

    PYTHONUTF8=1 .venv/Scripts/python scripts/proofread.py <下書き.txt> [--out <添削.txt>] [--model gemini-3.8-flash]

- 鍵は `.env` の `GEMINI_API_KEY`（git には入らない）。無ければ止まる
- **Gemini の直しをそのまま採らない**。事実（言い切りすぎ）と画面の表記（「マスに重ねる」など）は Claude が
  突き合わせて取捨する。このスクリプトは添削案と「直した理由」を並べて返すだけ
- 書き方の好み（`STYLE`）は利用者が手直しで選んだもの。変わったらここを直す
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.8-flash"

STYLE = """あなたは日本語の Web サービスの告知文を整える編集者です。次の文章を添削してください。

対象: 音楽のジャケットを並べて画像にする Web サービス「TRACKMENTO」の、利用者向けの文章。
守ること:
- 文体は「〜しました」「〜です」の丁寧語。硬すぎず、専門用語は避けるか短く言い換える
- 「〜しにくく」ではなく「〜しづらく」を使う
- 効果を言い切りすぎない。確実でない改善を「防ぐ」「止まらない」「必ず」と書かない（「起きづらく」などにする）
- 「」で囲まれた語は画面上のボタンや機能の名前なので、**言い換えない**
- 事実・数値・固有名詞（サービス名、URL、日付）は変えない。内容を足したり削ったりしない
- 行頭の記号・見出し・日付の区切りなど、元の形式はそのまま残す

出力は次の 2 部に分けてください:
1. 「## 添削後」の見出しのあとに、添削後の全文
2. 「## 直した箇所」の見出しのあとに、直した箇所ごとに「元 → 後（理由）」を 1 行ずつ。直していない箇所は書かない
"""


# 作業する人向けの文書（README など）の添削。告知文の STYLE は「です・ます」にそろえるので、そのまま流すと文体ごと書き換わる（2026-09-20）
STYLE_DOC = """あなたは日本語の技術文書を整える編集者です。次の文章を添削してください。

対象: 音楽のジャケットを並べて画像にする Web サービス「TRACKMENTO」の、開発・運用する人向けの文書（GitHub の README など、Markdown）。
守ること:
- 文体は今のまま（常体・体言止め）。「です・ます」にそろえない
- 誤字脱字、意味の通りにくい文、同じことの重複、係り受けの分かりにくさを直す。専門用語はそのままでよい
- 「〜しにくく」ではなく「〜しづらく」を使う
- 事実・数値・固有名詞（サービス名、URL、日付）、コード・ファイル名・パス・環境変数名・コマンド（`` ` `` で囲まれた部分）は変えない。内容を足したり削ったりしない
- Markdown の形式（見出し・箇条書き・表・コードブロック）はそのまま残す

出力は次の 2 部に分けてください:
1. 「## 添削後」の見出しのあとに、添削後の全文
2. 「## 直した箇所」の見出しのあとに、直した箇所ごとに「元 → 後（理由）」を 1 行ずつ。直していない箇所は書かない
"""


def ask(text: str, model: str, key: str, style: str = STYLE) -> str:
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": style + "\n---\n" + text}]}],
        "generationConfig": {"temperature": 0.2},
    }).encode()
    req = urllib.request.Request(API.format(model=model), data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    # 混雑（503）と回数制限（429）は少し待って取り直す。`gemini-3.8-flash` は混んでいて 503 が返ることがある（2026-09-19 実測）
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < 4:
                wait = 10 * (attempt + 1)
                print(f"Gemini API {e.code} → {wait} 秒待って取り直す", file=sys.stderr)
                time.sleep(wait)
                continue
            raise SystemExit(f"Gemini API {e.code}: {e.read().decode('utf-8', 'replace')[:500]}") from e
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    out = "".join(p.get("text", "") for p in parts).strip()
    if not out:
        raise SystemExit(f"応答が空です: {json.dumps(data, ensure_ascii=False)[:500]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="添削してもらう文章（UTF-8 のテキスト）")
    ap.add_argument("--out", help="添削結果を書き出すファイル（無ければ標準出力）")
    ap.add_argument("--model", default=os.getenv("GEMINI_MODEL", DEFAULT_MODEL))
    ap.add_argument("--doc", action="store_true", help="作業する人向けの文書（README など）として添削する（文体は常体のまま）")
    a = ap.parse_args()
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY が .env にありません", file=sys.stderr)
        return 1
    out = ask(pathlib.Path(a.src).read_text(encoding="utf-8"), a.model, key, STYLE_DOC if a.doc else STYLE)
    if a.out:
        pathlib.Path(a.out).write_text(out + "\n", encoding="utf-8")
        print(f"書き出し: {a.out}（{a.model}）")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
