"""利用者向けの文章（更新情報・案内ページなど）を Gemini に添削してもらう。

    PYTHONUTF8=1 .venv/Scripts/python scripts/proofread.py <下書き.txt> [--out <添削.txt>] [--model gemini-3.8-flash]
    （--doc = 作業する人向けの文書、--letter = 英語の問い合わせ、--ui = 画面の文言の一覧を HIG の決まりで見直す）

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


# 画面の文言（ボタン・見出し・確認窓・エラー）の見直し。書き換えではなく「分かりにくい順・理由・候補」をもらう。
# 見た目を Mac OS 9 に寄せているので、言葉も Macintosh Human Interface Guidelines（1992、dev.os9.ca の
# HIGuidelines の 7 章「Button Names」と 11 章「Language」「Dialog Box Messages」）の決まりに合わせる（2026-09-23）
STYLE_UI = """あなたは日本語の Web アプリの画面の文言を見直す編集者です。

対象: 音楽のジャケットを格子状に並べて 1 枚の画像にする無料の Web サービス「TRACKMENTO」の、画面に出る文言の一覧。
見た目を Mac OS 9 に寄せているので、言葉も Apple の Macintosh Human Interface Guidelines の決まりに合わせたい。
利用者は音楽好きの一般の人。専門語を避けたやわらかい日本語にしている（「エクスポート」ではなく「並びを保存」、「グリッドサイズ」ではなく「横 × 縦」）。

一覧の形: 1 行 1 項目で「ID<TAB>文言<TAB>[種類 @置き場所]」。{} や {n} は数や名前が入る所。種類は自動で推定したもので外れもある。

見る観点（HIG の決まり）:
1. ボタン名は、押すと起きる動作を表す動詞にする。1〜2 語がよく、3 語を超えない。「OK」「はい」より「保存」「外す」のような具体的な動作名
2. 押すと続きの窓（入力や選択を求める窓）が開くボタンだけ、名前の後ろに「…」を付ける。確認を求めるだけの窓なら付けない
3. 確認の窓のボタンは、承諾したときの結果を表す語にする（「元に戻しますか？」なら「元に戻す」）。取り消すボタンは「何もせずに窓を閉じる」意味の 1 語にそろえる
4. 警告・エラーの文は「何が起きたか・なぜか・利用者はどうすればよいか」を利用者の言葉で書く。評価や責める調子ではなく状況を述べる。利用者が手を打てない内部の情報（例外名・ステータス番号・ホスト名）は出さない
5. 同じものは画面のどこでも同じ名前で呼ぶ（例: 「グリッド」「並び」「マス」、「共有」「シェア」の揺れ）。案内文の中で「」付きで引いているボタン名が、実際のボタン名と一致しているか
6. ラベルは具体的に。短さのために分かりやすさを犠牲にしない。専門語・開発者の言葉（キャッシュ・クエリ・ソースなど）は利用者の言葉に
7. チェックボックスやラジオボタンの名前は、選んだ状態が一目で分かる言い方に

TRACKMENTO の決まり:
- 「〜しにくく」ではなく「〜しづらく」
- 確実でない効果を言い切らない
- 固有名詞（サービス名・URL）、数値、{} の位置は変えない
- 文体の混在（です・ます と 常体）は、種類ごとにそろっているかを見る（ボタン・ラベルは体言や動詞の終止形、説明文は「です・ます」）

出力（書き換えた全文は要らない）:
1. 「## 分かりにくい順」: 直したほうがよい項目を、影響の大きい順に。各項目は
   「ID｜今の文言｜理由（上の観点の番号）｜候補 2〜3 個」を 1 行で。問題のない項目は書かない。多くても 60 項目まで
2. 「## 名前の揺れ」: 同じものを違う名前で呼んでいる組を、ID を添えて列挙し、どちらにそろえるかの案
3. 「## 「…」を付ける候補」: 観点 2 に当たりそうなボタン（押すと何が開くかは推定でよい。推定と書く）
"""


# 外部の運営への英語の問い合わせ（2026-09-20、VocaDB への許可の依頼で足した）
STYLE_LETTER = """You are an editor for a short English message that a solo Japanese developer will post to the maintainers of an
open music database (on their Discord or GitHub). Please proofread it.

Keep:
- A polite, concise, friendly tone suitable for a volunteer-run community. Not overly formal, not salesy
- All facts, numbers, URLs, API paths and names exactly as they are. Do not add claims or promises, and do not remove content
- The structure (paragraphs, numbered lists)
Fix grammar, unnatural phrasing, ambiguity, and anything that could read as demanding or rude.

Output in two parts:
1. A heading "## Revised" followed by the full revised text
2. A heading "## Changes" followed by one line per change: "original → revised (reason, in Japanese)". Do not list unchanged parts
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
    ap.add_argument("--letter", action="store_true", help="外部の運営への英語の問い合わせとして添削する")
    ap.add_argument("--ui", action="store_true", help="画面の文言の一覧（ID<TAB>文言<TAB>[場所]）を HIG の決まりで見直す（書き換えずに候補を返す）")
    a = ap.parse_args()
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        print("GEMINI_API_KEY が .env にありません", file=sys.stderr)
        return 1
    style = STYLE_UI if a.ui else STYLE_LETTER if a.letter else STYLE_DOC if a.doc else STYLE
    out = ask(pathlib.Path(a.src).read_text(encoding="utf-8"), a.model, key, style)
    if a.out:
        pathlib.Path(a.out).write_text(out + "\n", encoding="utf-8")
        print(f"書き出し: {a.out}（{a.model}）")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
