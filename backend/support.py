"""サーバー代の進み具合の棒（2026-09-26、利用者の希望）。

「サーバー代のおねがい」の欄と、共有したあとの欄に「○ 月のサーバー代 約 N 円のうち M 円を支援でまかなえた」を
棒で見せる。数字はここに手で書き、`main.py` が HTML の `<meta name="trackmento-support">` に差し込む
（画面の JS はそれを読むだけ。取りに行く通信は増やさない）。**変えたらデプロイで反映**（R2 の CSS / JS は出し直さなくてよい）。

- `COST_JPY` … その月のサーバー代の見込み。`scripts/board_data.py` の `money()` の `jpy`
  （Render のインスタンス＋帯域の超過＋ R2 の保存の超過を、その日のレートで円にしたもの）
- `RECEIVED_JPY` / `SUPPORTERS` … Bandcamp で買ってもらった額（受け取った額）と人数。利用者から聞いて足す
- 月が変わったら `MONTH` を進め、受け取った額と人数を 0 に戻す。**戻し忘れても画面には月が出る**ので、嘘にはならない
- 金額と人数だけを出す。**買った人の名前や、どの曲かは出さない**
"""

MONTH = "2026-09"
COST_JPY = 4375                    # 2026-09-26 の money()（$27.76 × 157.59）
RECEIVED_JPY = 388 + 104 + 1596    # 2026-09 の Bandcamp の購入 3 件（受け取った額）
SUPPORTERS = 3


def meta() -> str:
    """`<meta name="trackmento-support">` の中身。「月,サーバー代,支援の額,人数」をカンマで並べる。"""
    return f"{MONTH},{COST_JPY},{RECEIVED_JPY},{SUPPORTERS}"
