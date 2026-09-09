"""TRACKMENTO CLI。Claude Code（Remote Control でスマホから）が Bash で叩く想定。

  python cli.py add    --artist A --title T [--grid NAME] [--source itunes|lastfm|mb|discogs] [--first]
  python cli.py add    --bandcamp URL [--grid NAME]
  python cli.py add    --image URL --artist A --title T [--grid NAME]     # 手入力
  python cli.py pick   --index N [--grid NAME]                            # 直前の候補から選択
  python cli.py search --artist A --title T [--source ...]               # 候補を見るだけ
  python cli.py list   [--grid NAME]                                      # 現在の並びを表示
  python cli.py move   --from N --to M [--grid NAME]                      # 入れ替え
  python cli.py remove --index N [--grid NAME]
  python cli.py share  [--grid NAME] [--size 3x3] [--ratio 16:9] [--sidebar] [--title "..."] ...   # PNG + 共有ページ URL
  python cli.py render [--grid NAME] ...                                  # PNG だけ
  python cli.py clear  [--grid NAME]
  python cli.py grids                                                     # グリッド一覧

- 番号 N は画面の番号バッジと同じ 1 始まり
- 既定グリッド名は default。状態は grids/<NAME>.json に保存され Web と共有される
- share / render の最後の行は必ず `URL: http://...`（Claude Code がそのまま転記する）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import grids  # noqa: E402
from backend.cache import cache  # noqa: E402
from backend.grids import GridDoc, GridOptions  # noqa: E402
from backend.merge import merge, norm_key  # noqa: E402
from backend.models import Track  # noqa: E402

PENDING = grids.GRIDS / ".pending.json"
SOURCE_ALIAS = {"mb": "musicbrainz", "musicbrainz": "musicbrainz", "itunes": "itunes", "lastfm": "lastfm", "discogs": "discogs"}
SOURCE_LABEL = {"itunes": "iTunes", "lastfm": "Last.fm", "musicbrainz": "MusicBrainz", "discogs": "Discogs", "bandcamp": "Bandcamp", "manual": "手入力"}
MAX_CANDIDATES = 8


class CliError(Exception):
    pass


# ---------- 表示 ----------
def fmt_track(t: Track) -> str:
    s = f"{t.title} / {t.artist}"
    if t.album and norm_key(t.album, "") != norm_key(t.title, ""):
        s += f"（{t.album}）"
    return f"{s} [{SOURCE_LABEL.get(t.source, t.source)}]"


def print_list(doc: GridDoc) -> None:
    placed = doc.placed()
    print(f"グリッド {doc.name}: {doc.cols}×{doc.rows}（{len(placed)}/{doc.size} 曲）" + (f" タイトル「{doc.title}」" if doc.title else ""))
    for i, t in enumerate(doc.cells):
        print(f"  {i + 1:02d}  {fmt_track(t) if t else '（空）'}")
    if doc.stash:
        print(f"  退避中: {len(doc.stash)} 曲（グリッドを広げると戻ります）")


# ---------- 検索 ----------
async def _search(q: str, artist: str, sources: list[str]) -> tuple[list[Track], str | None]:
    """sources の順に検索し、最初に候補が出たソースの結果を返す。"""
    import httpx

    from backend.sources import discogs, itunes, lastfm, musicbrainz

    fns = {"itunes": itunes.search, "lastfm": lastfm.search, "musicbrainz": musicbrainz.search, "discogs": discogs.search}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for name in sources:
            if name == "lastfm" and not lastfm.enabled():
                continue
            if name == "discogs" and not discogs.enabled():
                continue
            hit = cache.get_search(name, q, artist)
            if hit is not None:
                res = [Track.model_validate(t) for t in hit]
            else:
                try:
                    res = await fns[name](q, artist, client=client)
                except Exception as e:  # 1ソースの失敗は次へ
                    print(f"  ({SOURCE_LABEL[name]} で失敗: {e})", file=sys.stderr)
                    continue
                if res:
                    cache.set_search(name, q, artist, [t.model_dump() for t in res])
            if res:
                return merge(res), name
    return [], None


def search_candidates(title: str, artist: str, source: str | None) -> list[Track]:
    if source:
        key = SOURCE_ALIAS.get(source.lower())
        if not key:
            raise CliError(f"未知のソース: {source}（itunes / lastfm / mb / discogs）")
        order = [key]
    else:
        order = ["itunes", "lastfm", "musicbrainz", "discogs"]
    tracks, _ = asyncio.run(_search(title, artist, order))
    return tracks[:MAX_CANDIDATES]


def exact(t: Track, title: str, artist: str) -> bool:
    return norm_key(t.title, t.artist) == norm_key(title, artist)


def save_pending(name: str, tracks: list[Track]) -> None:
    grids.GRIDS.mkdir(exist_ok=True)
    PENDING.write_text(json.dumps({"grid": name, "candidates": [t.model_dump() for t in tracks]}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_pending() -> tuple[str, list[Track]]:
    if not PENDING.exists():
        raise CliError("選択待ちの候補がありません。先に add か search を実行してください")
    d = json.loads(PENDING.read_text(encoding="utf-8"))
    return d.get("grid", "default"), [Track.model_validate(t) for t in d.get("candidates", [])]


def print_candidates(tracks: list[Track], name: str) -> None:
    print(f"候補が {len(tracks)} 件あります。番号で選んでください: python cli.py pick --index N" + (f" --grid {name}" if name != "default" else ""))
    for i, t in enumerate(tracks, 1):
        print(f"  {i}. {fmt_track(t)}")


# ---------- グリッド操作 ----------
def place(doc: GridDoc, t: Track) -> int:
    i = doc.first_empty()
    if i is None:
        raise CliError(f"空きマスがありません（{doc.cols}×{doc.rows} が全部埋まっています）。remove で外すか render --size で広げてください")
    doc.cells[i] = t
    doc.touch()
    grids.save(doc)
    return i


def cmd_add(a: argparse.Namespace) -> int:
    doc = grids.load(a.grid)
    if a.bandcamp:
        from backend.sources import bandcamp

        t = asyncio.run(bandcamp.fetch(a.bandcamp))
    elif a.image:
        if not (a.title and a.artist is not None):
            raise CliError("--image には --title と --artist が必要です")
        image = a.image
        if not image.lower().startswith(("http://", "https://", "/uploads/")):
            # PC 上のファイルパスなら uploads/ に取り込む
            from backend import uploads

            image = uploads.import_file(image)
            print(f"画像を取り込みました: {image}")
        t = Track(source="manual", title=a.title, artist=a.artist or "", image=image, thumb=image)
    else:
        if not (a.title or a.artist):
            raise CliError("--title か --artist を指定してください")
        cands = search_candidates(a.title or "", a.artist or "", a.source)
        if not cands:
            raise CliError("見つかりませんでした。表記を変える、--source mb を試す、Bandcamp なら --bandcamp URL、それでも無ければ --image URL で手入力してください")
        if a.first or len(cands) == 1 or exact(cands[0], a.title or "", a.artist or ""):
            t = cands[0]
            others = cands[1:]
        else:
            save_pending(a.grid, cands)
            print_candidates(cands, a.grid)
            return 0
        if others:
            save_pending(a.grid, cands)
    i = place(doc, t)
    print(f"{i + 1:02d} 番に追加: {fmt_track(t)}")
    if not (a.bandcamp or a.image) and len(cands) > 1:
        print(f"（他に {len(cands) - 1} 件の候補あり。違う盤にしたい場合: python cli.py remove --index {i + 1} のあと pick --index N）")
        for j, c in enumerate(cands, 1):
            if c is not t:
                print(f"  {j}. {fmt_track(c)}")
    print_list(doc)
    return 0


def cmd_pick(a: argparse.Namespace) -> int:
    name, cands = load_pending()
    if a.grid != "default":
        name = a.grid
    if not 1 <= a.index <= len(cands):
        raise CliError(f"--index は 1〜{len(cands)} で指定してください")
    doc = grids.load(name)
    t = cands[a.index - 1]
    i = place(doc, t)
    PENDING.unlink(missing_ok=True)
    print(f"{i + 1:02d} 番に追加: {fmt_track(t)}")
    print_list(doc)
    return 0


def cmd_search(a: argparse.Namespace) -> int:
    if not (a.title or a.artist):
        raise CliError("--title か --artist を指定してください")
    cands = search_candidates(a.title or "", a.artist or "", a.source)
    if not cands:
        print("見つかりませんでした")
        return 1
    save_pending(a.grid, cands)
    print_candidates(cands, a.grid)
    return 0


def cmd_list(a: argparse.Namespace) -> int:
    print_list(grids.load(a.grid))
    return 0


def _check_index(doc: GridDoc, n: int, label: str) -> int:
    if not 1 <= n <= doc.size:
        raise CliError(f"{label} は 1〜{doc.size} で指定してください")
    return n - 1


def cmd_move(a: argparse.Namespace) -> int:
    doc = grids.load(a.grid)
    i, j = _check_index(doc, a.src, "--from"), _check_index(doc, a.dst, "--to")
    doc.cells[i], doc.cells[j] = doc.cells[j], doc.cells[i]
    doc.touch()
    grids.save(doc)
    print(f"{a.src:02d} 番と {a.dst:02d} 番を入れ替えました")
    print_list(doc)
    return 0


def cmd_remove(a: argparse.Namespace) -> int:
    doc = grids.load(a.grid)
    i = _check_index(doc, a.index, "--index")
    t = doc.cells[i]
    if not t:
        raise CliError(f"{a.index:02d} 番は空です")
    doc.cells[i] = None
    doc.touch()
    grids.save(doc)
    print(f"{a.index:02d} 番の {fmt_track(t)} を外しました")
    print_list(doc)
    return 0


def cmd_clear(a: argparse.Namespace) -> int:
    doc = grids.load(a.grid)
    n = len(doc.placed())
    doc.cells = [None] * doc.size
    doc.stash = []
    doc.touch()
    grids.save(doc)
    PENDING.unlink(missing_ok=True)
    print(f"グリッド {doc.name} を空にしました（{n} 曲を外しました）")
    return 0


def cmd_grids(a: argparse.Namespace) -> int:
    names = grids.list_names()
    if not names:
        print("保存されたグリッドはありません")
        return 0
    for n in names:
        d = grids.load(n)
        print(f"  {n}: {d.cols}×{d.rows} {len(d.placed())}/{d.size} 曲" + (f" 「{d.title}」" if d.title else "") + (f"  {d.savedAt}" if d.savedAt else ""))
    return 0


def cmd_render(a: argparse.Namespace) -> int:
    from backend import render, share
    from backend.config import public_base_url

    doc = grids.load(a.grid)
    if not doc.placed():
        raise CliError(f"グリッド {doc.name} に曲がありません。先に add してください")
    changed = False
    if a.size:
        try:
            c, r = (int(v) for v in a.size.lower().split("x"))
        except ValueError as e:
            raise CliError("--size は 3x3 のように指定してください") from e
        if not (1 <= c <= grids.MAX_COLS and 1 <= r <= grids.MAX_ROWS):
            raise CliError(f"--size は 1〜{grids.MAX_COLS} の範囲で")
        if (c, r) != (doc.cols, doc.rows):
            doc.resize(c, r)
            changed = True
    if a.title is not None:
        doc.title = a.title[:60]
        changed = True
    opts = doc.options.model_dump()
    updates = {
        "ratio": a.ratio, "sidebar": a.sidebar, "showTitle": a.show_title, "numbers": a.numbers,
        "bg": a.bg, "bgCustom": a.bg_custom, "margin": a.margin, "gap": a.gap,
    }
    if a.bg_custom and a.bg is None:
        updates["bg"] = "custom"
    for k, v in updates.items():
        if v is not None and v != opts.get(k):
            opts[k] = v
            changed = True
    if changed:
        doc.options = GridOptions.model_validate(opts)
        doc.touch()
        grids.save(doc)

    print_list(doc)
    o = doc.options
    base = public_base_url()
    if not _server_alive(base):
        print("注意: サーバーが応答しません。URL を開くには uvicorn を起動してください（uvicorn backend.main:app --host 0.0.0.0 --port 8000）", file=sys.stderr)
    if a.cmd == "share":
        info = share.create(doc)
        print(f"共有: {info['id']}  {info['width']}×{info['height']}px  比率 {o.ratio}  サイドバー {'あり' if o.sidebar else 'なし'}  背景 {o.bg}")
        print(f"PNG: {base}{info['png']}")
        print(f"URL: {base}/s/{info['id']}")
        return 0
    path, im = render.render_to_file(doc)
    print(f"出力: {path.name}  {im.width}×{im.height}px  比率 {o.ratio}  サイドバー {'あり' if o.sidebar else 'なし'}  背景 {o.bg}")
    print(f"URL: {base}/outputs/{path.name}")
    return 0


def _server_alive(base: str) -> bool:
    import httpx

    try:
        return httpx.get("http://127.0.0.1:8000/health", timeout=1.5).status_code == 200
    except httpx.HTTPError:
        return False


# ---------- 引数 ----------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cli.py", description="TRACKMENTO CLI（曲を探してグリッドに置き、PNG を作る）")
    sub = p.add_subparsers(dest="cmd", required=True)

    def grid_arg(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--grid", default="default", help="グリッド名（既定: default）")

    sp = sub.add_parser("add", help="曲を探して次の空きマスに置く")
    grid_arg(sp)
    sp.add_argument("--title", "-t", help="曲名")
    sp.add_argument("--artist", "-a", help="アーティスト名")
    sp.add_argument("--source", "-s", help="itunes | lastfm | mb | discogs（省略時は iTunes → Last.fm → MusicBrainz → Discogs の順）")
    sp.add_argument("--first", action="store_true", help="候補が複数でも先頭を採用する")
    sp.add_argument("--bandcamp", metavar="URL", help="Bandcamp のトラック／アルバム URL")
    sp.add_argument("--image", metavar="URL|PATH", help="手入力: ジャケット画像の URL か PC 上のファイルパス（--title --artist と併用）")
    sp.set_defaults(fn=cmd_add)

    sp = sub.add_parser("pick", help="直前の候補から番号で選んで置く")
    grid_arg(sp)
    sp.add_argument("--index", "-i", type=int, required=True)
    sp.set_defaults(fn=cmd_pick)

    sp = sub.add_parser("search", help="候補を表示するだけ（pick で選べる）")
    grid_arg(sp)
    sp.add_argument("--title", "-t")
    sp.add_argument("--artist", "-a")
    sp.add_argument("--source", "-s")
    sp.set_defaults(fn=cmd_search)

    sp = sub.add_parser("list", help="現在の並びを表示")
    grid_arg(sp)
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("move", help="2 つのマスを入れ替える")
    grid_arg(sp)
    sp.add_argument("--from", dest="src", type=int, required=True)
    sp.add_argument("--to", dest="dst", type=int, required=True)
    sp.set_defaults(fn=cmd_move)

    sp = sub.add_parser("remove", help="マスを空にする")
    grid_arg(sp)
    sp.add_argument("--index", "-i", type=int, required=True)
    sp.set_defaults(fn=cmd_remove)

    sp = sub.add_parser("share", help="トラックを共有: PNG と並びのスナップショットを保存し、共有ページの URL を表示（render と同じオプション）")
    grid_arg(sp)
    _render_opts(sp)
    sp.set_defaults(fn=cmd_render)

    sp = sub.add_parser("render", help="PNG だけを作って outputs/ に保存し URL を表示")
    grid_arg(sp)
    _render_opts(sp)
    sp.set_defaults(fn=cmd_render)

    sp = sub.add_parser("clear", help="グリッドを空にする")
    grid_arg(sp)
    sp.set_defaults(fn=cmd_clear)

    sp = sub.add_parser("grids", help="保存されているグリッドの一覧")
    sp.set_defaults(fn=cmd_grids)
    return p


def _render_opts(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--size", help="3x3 / 4x6 / 3x8 / 5x5 / 任意 WxH")
    sp.add_argument("--ratio", choices=["1:1", "16:9", "9:16", "free"])
    sp.add_argument("--sidebar", dest="sidebar", action="store_true", default=None, help="曲名リストを付ける")
    sp.add_argument("--no-sidebar", dest="sidebar", action="store_false")
    sp.add_argument("--title", help="タイトル文字列（空文字で消す）")
    sp.add_argument("--no-title", dest="show_title", action="store_false", default=None, help="タイトルを描かない")
    sp.add_argument("--show-title", dest="show_title", action="store_true")
    sp.add_argument("--numbers", dest="numbers", action="store_true", default=None, help="番号バッジを付ける")
    sp.add_argument("--no-numbers", dest="numbers", action="store_false")
    sp.add_argument("--bg", choices=["paper", "ink", "mustard", "cerulean", "lavender", "vermilion", "mint", "pink"], help="背景色")
    sp.add_argument("--bg-custom", metavar="#RRGGBB", help="背景色を直接指定")
    sp.add_argument("--margin", type=int, help="余白 px（0〜160）")
    sp.add_argument("--gap", type=int, help="マスとマスの間隔 px（0〜96、既定 12）")


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    a = build_parser().parse_args(argv)
    try:
        if getattr(a, "grid", None):
            grids.validate_name(a.grid)
        return a.fn(a)
    except CliError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
