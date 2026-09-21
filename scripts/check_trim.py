"""backend/names.py の刈り込みを、既知の入力と期待値で確かめる。

規則を直したらこれを回す。**期待値は実際の共有から取った本物の題**なので、
落ちたときは「規則が変わってよいのか」を必ず考えること（黙って期待値を書き換えない）。

    PYTHONUTF8=1 .venv/Scripts/python scripts/check_trim.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from backend.names import trim   # noqa: E402

# (題, 作者, 期待する題, 期待する作者)
CASES = [
    # R3 分類のタグ
    ("【東方Vocal／Traditional Rock】「心綺楼」「凋叶棕」【ENG Subs】", "Kappashiro",
     "「心綺楼」「凋叶棕」", "Kappashiro"),
    # R2 チャンネル名の尾
    ("リバースイデオロギー", "KISIDA KYODAN & THE AKEBOSI ROCKETS - Topic",
     "リバースイデオロギー", "KISIDA KYODAN & THE AKEBOSI ROCKETS"),
    ("psychology / Adust Rain【ハルトマンの妖怪少女】", "Adust Rain Official YouTube Channel",
     "psychology【ハルトマンの妖怪少女】", "Adust Rain"),
    # R4 括弧の中身が作者名
    ("【東方MV】ラクト・ガール【ビートまりお】", "ビートまりお / COOL&CREATE",
     "ラクト・ガール", "ビートまりお / COOL&CREATE"),
    # A1 名前の繰り返し。**A1 のあと【ｙｔｒ】が作者名と一致するので R4 で外れる**
    # （【東方】は分類語に当たらないので残る）
    ("【東方】物凄いヴァイブスで魔理沙が物凄いラップ【ｙｔｒ】", "ytr_ytr",
     "【東方】物凄いヴァイブスで魔理沙が物凄いラップ", "ytr"),
    # G 題からの移植
    ("「幻想に咲いた花」MV FULL ver./岸田教団&THE明星ロケッツ×草野華余子『東方ダンマクカグラ』テーマ曲",
     "アンノウンX公式チャンネル / 東方ダンマクカグラ発売中",
     "「幻想に咲いた花」", "岸田教団&THE明星ロケッツ×草野華余子"),   # MV FULL ver. は R1 で外れる
    # 残すもの（サークル名・原曲名・歌唱者・原作名）
    ("流星ドライヴ 【魂音泉】", "ディレイド", "流星ドライヴ 【魂音泉】", "ディレイド"),
    ("AbsoЯute Zero / いざ宵裂く矢となれ【東方紅魔郷・東方花映塚】", "AbsoЯute Zero Channel",
     "いざ宵裂く矢となれ【東方紅魔郷・東方花映塚】", "AbsoЯute Zero"),
    ("【東方ヴォーカルMV】インスタントブルー（Vo:あよ）【森羅万象公式】", "森羅万象/Shinra-Bansho",
     "インスタントブルー（Vo:あよ）", "森羅万象/Shinra-Bansho"),
    # 名前を壊さない（要素が違えば A1 は効かない）
    ("Rock 'n' Rock 'n' Beat", "qfeuille3_v2 🥐⚓", "Rock 'n' Rock 'n' Beat", "qfeuille3_v2 🥐⚓"),
    # 空・短すぎは刈らない
    ("【MV】", "", "【MV】", ""),
]


def main() -> int:
    bad = 0
    for title, artist, want_t, want_a in CASES:
        got_t, got_a = trim(title, artist)
        if (got_t, got_a) != (want_t, want_a):
            bad += 1
            print(f"[違う] {title} / {artist}")
            print(f"   期待: {want_t!r} / {want_a!r}")
            print(f"   実際: {got_t!r} / {got_a!r}")
        # **掛け直しても結果が変わらないこと**。`render.py` は `layout()` と `render()` の
        # 両方の入口で刈るので、二重に掛かっても同じでないと描く題と測った題がずれる
        again = trim(got_t, got_a)
        if again != (got_t, got_a):
            bad += 1
            print(f"[二度目で変わる] {got_t!r} / {got_a!r} → {again[0]!r} / {again[1]!r}")
    print(f"{len(CASES) - bad} / {len(CASES)} 件そろいました")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
