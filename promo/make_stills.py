"""紹介動画の静止画を作る（promo/public/stills/*.png）。

- 17 小節「曲名リストが賢くなりました」: 組み方の違う 16 枚（smart-01〜16）を 16 分音符ずつ切り替える
- 44–45 小節「できあがり」: 4 枚（show-1〜4）を 2 拍ずつ切り替える（1 枚目 = 1 行型、4 枚目 = マスに重ねる）

**サーバー描画（backend.render）で作る**。ブラウザ描画と同じ絵になることは compare_render.py / compare_layout.py で確かめてある。
**必ず PUBLIC_MODE=1 で動かす**（出力の最大辺が 2400 になる。付けないと割り付けが別物になり、文字が豆粒になる）。

    PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python promo/make_stills.py            # 曲を集めて（初回だけ）16＋4 枚
    PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python promo/make_stills.py --refetch  # 曲を集め直す
    PUBLIC_MODE=1 PYTHONUTF8=1 .venv/Scripts/python promo/make_stills.py --fetch-only  # 曲を集めるだけ（描かない）

曲は iTunes の検索で集め、promo/stills-tracks.json に控える（2 回目からは検索しない）。

2026-09-21（初見向け・16:9 のサムネ中心）から:
- smart は**横長 16:9 のマス**で、曲は**デモ用マイリストのニコニコ動画**（promo/stills-tracks-nico.json）で作る
- `--hook` … 4–5 小節のつかみ（hook-square / hook-wide）。本編の録画の並び（takes/tall-main-ja/reorder/end.json）を
  正方形のマスと 16:9 のマスで描く。**録画を撮り直したら作り直す**
縦（tall）と横（wide）の動画で同じ画を使う（`<名前>.png` と `<名前>-pc.png` に同じものを置く。Scenes.tsx がこの名前で読む）。
割り付けの規則を直したら作り直す。
"""
from __future__ import annotations

import json
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
from backend import render as R  # noqa: E402
from backend.grids import GridDoc  # noqa: E402

OUT = ROOT / "promo" / "public" / "stills"
TRACKS = ROOT / "promo" / "stills-tracks.json"
NICO_TRACKS = ROOT / "promo" / "stills-tracks-nico.json"
MYLIST = "https://www.nicovideo.jp/mylist/79113711"
# 題に出ると困る語（動画の中で曲名リストとして読めてしまう）。消えた動画も外す
NG = ("エロ", "エ口", "ローション", "熟女", "えっち", "注意", "しにたく", "死", "殺", "非公開", "削除", "葬")
REORDER_END = ROOT / "promo" / "public" / "takes" / "tall-main-ja" / "reorder" / "end.json"
MAX_OUT = 1600   # 動画の中では 1080px の辺に収まるので、これ以上は重いだけ

# 集める曲（曲名, アーティスト）。iTunes の日本のストアで引く
WANT = [
    ("マトリョシカ", "ハチ"), ("ローリンガール", "wowaka"), ("メルト", "ryo"), ("千本桜", "黒うさP"), ("砂の惑星", "ハチ"),
    ("ロキ", "みきとP"), ("シャルル", "バルーン"), ("命に嫌われている", "カンザキイオリ"), ("ヴァンパイア", "DECO*27"),
    ("ゴーストルール", "DECO*27"), ("劣等上等", "Giga"), ("脱法ロック", "Neru"), ("天ノ弱", "164"), ("ワールドイズマイン", "ryo"),
    ("炉心融解", "iroha"), ("裏表ラバーズ", "wowaka"), ("アンノウン・マザーグース", "wowaka"), ("愛して愛して愛して", "きくお"),
    ("酔いどれ知らず", "Kanaria"), ("KING", "Kanaria"), ("グッバイ宣言", "Chinozo"), ("フォニイ", "ツミキ"), ("神っぽいな", "ピノキオピー"),
    ("ラグトレイン", "稲葉曇"), ("エンヴィーベイビー", "Kanaria"), ("ブリキノダンス", "日向電工"), ("気まぐれメルシィ", "八王子P"),
    ("乙女解剖", "DECO*27"), ("右肩の蝶", "のりP"), ("ODDS&ENDS", "ryo"), ("テオ", "Omoi"), ("聖槍爆裂ボーイ", "れるりり"),
    ("妄想税", "DECO*27"), ("夜咄ディセイブ", "じん"), ("カゲロウデイズ", "じん"), ("少女レイ", "みきとP"),
    ("ビターチョコデコレーション", "syudou"), ("アイロニ", "すこっぷ"), ("ヒバナ", "DECO*27"), ("強風オールバック", "ゆこぴ"),
]

# 17 小節の 16 枚（エディタの「画の切り替え」の 01〜16 と同じ順）。(名前, 横, 縦, 比率, 曲名リスト, タイトル)
SMART = [
    ("1 行型", 3, 3, "16:9", "side"), ("回り込み", 5, 4, "1:1", "side"), ("柱", 1, 8, "1:1", "side"), ("流し込み", 10, 15, "16:9", "side"),
    ("マスに重ねる", 3, 3, "4:5", "overlay"), ("2 列", 5, 5, "16:9", "side"), ("マスごと", 2, 5, "1:1", "side"), ("帯", 32, 1, "1:1", "side"),
    ("回り込み", 6, 9, "4:5", "side"), ("下に流す", 7, 10, "9:16", "side"), ("回り込み", 12, 12, "1:1", "side"), ("流し込み", 16, 16, "16:9", "side"),
    ("コの字", 8, 12, "9:16", "side"), ("柱", 1, 32, "16:9", "side"), ("重ねる", 4, 4, "1:1", "overlay"), ("設定なし", 3, 3, "free", "side"),
]
# 44–45 小節の 4 枚（1 枚目 = 1 行型、4 枚目 = マスに重ねる）
SHOW = [
    ("1 行型", 3, 3, "16:9", "side"), ("回り込み", 6, 6, "1:1", "side"), ("2 列", 5, 5, "16:9", "side"), ("マスに重ねる", 3, 3, "4:5", "overlay"),
]
BG = ["paper", "ink", "mustard", "cerulean", "lavender", "mint", "pink", "vermilion"]


def fetch_tracks() -> list[dict]:
    out = []
    for title, artist in WANT:
        q = urllib.parse.urlencode({"term": f"{title} {artist}", "country": "JP", "media": "music", "entity": "song", "limit": 5})
        try:
            with urllib.request.urlopen(f"https://itunes.apple.com/search?{q}", timeout=15) as r:
                res = json.load(r).get("results", [])
        except Exception as e:  # noqa: BLE001
            print("  !", title, e)
            continue
        hit = next((x for x in res if title.lower() in x.get("trackName", "").lower()), res[0] if res else None)
        if not hit:
            print("  - 見つからない:", title, artist)
            continue
        out.append({"source": "itunes", "title": hit["trackName"], "artist": hit["artistName"],
                    "image": hit["artworkUrl100"].replace("100x100bb", "600x600bb"), "external_url": hit.get("trackViewUrl")})
        print("  +", hit["trackName"], "/", hit["artistName"])
    return out


def fetch_nico() -> list[dict]:
    """デモ用マイリストの動画（16:9 のサムネ）。作者（投稿者）の違うものを優先し、題に NG の語を含むものは外す"""
    import asyncio

    import httpx

    from backend.sources import playlist

    async def go():
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            return await playlist._nicovideo(MYLIST, c)
    out, seen = [], set()
    for t in asyncio.run(go()):
        if not t.artist or not t.image or any(w in t.title for w in NG) or t.artist in seen:
            continue
        seen.add(t.artist)
        out.append({"source": t.source, "title": t.title, "artist": t.artist, "image": t.image, "thumb": t.thumb, "external_url": t.external_url})
    print(f"  ニコニコ {len(out)} 本（作者ごとに 1 本）")
    return out


def hook() -> None:
    """4–5 小節のつかみ。本編の並びを正方形のマスと 16:9 のマスで（タイトル・曲名リストなし）"""
    st = json.loads(REORDER_END.read_text(encoding="utf-8"))
    grid = json.loads(st["ls"]["trackmento:grid:default"])
    cells = grid["cells"][:9]
    OUT.mkdir(parents=True, exist_ok=True)
    for name, cr in (("hook-square", "1:1"), ("hook-wide", "16:9")):
        doc = GridDoc(name="stills", cols=3, rows=3, cells=cells, stash=[], title="",
                      options={"ratio": "free", "showTitle": False, "sidebar": False, "overlay": False, "numbers": False,
                               "bg": "paper", "margin": 16, "gap": 16, "cellRatio": cr, "cellFit": "crop"})
        im = R.render(doc).convert("RGB")
        k = MAX_OUT / max(im.size)
        if k < 1:
            im = im.resize((round(im.width * k), round(im.height * k)))
        im.save(OUT / f"{name}.png", optimize=True)
        print(f"  {name}: {im.size}")


def make(name: str, spec: tuple, tracks: list[dict], i: int, cell_ratio: str = "1:1") -> None:
    _, cols, rows, ratio, mode, *rest = spec
    n = cols * rows
    cells = [tracks[(i * 7 + k) % len(tracks)] for k in range(n)]   # 画ごとに並びをずらす（同じ並びが続かないように）
    title = f"私を構成する{n}曲"
    doc = GridDoc(name="stills", cols=cols, rows=rows, cells=cells, stash=[], title=title,
                  options={"ratio": ratio, "showTitle": True, "sidebar": mode == "side", "overlay": mode == "overlay",
                           "numbers": False, "bg": BG[i % len(BG)], "margin": 16, "gap": 16, "cellRatio": cell_ratio})
    im = R.render(doc).convert("RGB")
    k = MAX_OUT / max(im.size)
    if k < 1:
        im = im.resize((round(im.width * k), round(im.height * k)))
    OUT.mkdir(parents=True, exist_ok=True)
    im.save(OUT / f"{name}.png", optimize=True)
    shutil.copyfile(OUT / f"{name}.png", OUT / f"{name}-pc.png")
    print(f"  {name}: {cols}x{rows} {ratio} {mode} → {im.size}")


def main() -> int:
    if "--refetch" in sys.argv or not TRACKS.exists():
        print("曲を集める")
        tracks = fetch_tracks()
        TRACKS.write_text(json.dumps(tracks, ensure_ascii=False, indent=1), encoding="utf-8")
    tracks = json.loads(TRACKS.read_text(encoding="utf-8"))
    print(f"曲 {len(tracks)} 曲")
    if "--refetch" in sys.argv or not NICO_TRACKS.exists():
        NICO_TRACKS.write_text(json.dumps(fetch_nico(), ensure_ascii=False, indent=1), encoding="utf-8")
    nico = json.loads(NICO_TRACKS.read_text(encoding="utf-8"))
    if "--fetch-only" in sys.argv:   # 撮影中など、重い描画を後回しにしたいとき
        return 0
    if "--hook" in sys.argv:
        hook()
        return 0
    for i, spec in enumerate(SMART):
        make(f"smart-{i + 1:02d}", spec, nico, i, "16:9")
    for i, spec in enumerate(SHOW):
        make(f"show-{i + 1}", spec, tracks, i + 3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
