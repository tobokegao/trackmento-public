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


def ask(text: str, model: str, key: str) -> str:
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": STYLE + "\n---\n" + text}]}],
        "generationConfig": {"temperature": 0.2},
    }).encode()
    req = urllib.request.Request(API.format(model=model), data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
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
    a = ap.parse_args()
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY が .env にありません", file=sys.stderr)
        return 1
    out = ask(pathlib.Path(a.src).read_text(encoding="utf-8"), a.model, key)
    if a.out:
        pathlib.Path(a.out).write_text(out + "\n", encoding="utf-8")
        print(f"書き出し: {a.out}（{a.model}）")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
