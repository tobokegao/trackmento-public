"""note の記事に貼るグラフを `outputs/note/series.json`（点検の要約から拾った数値）から描く。

    PYTHONUTF8=1 .venv/Scripts/python scripts/note_charts.py

出力: `outputs/note/chart-shares.png`（日ごとの共有数）、`chart-requests.png`（2 時間ごとの要求数）、
`chart-bandwidth.png`（2 時間ごとの帯域）。見た目はサイトと同じ（クリームの地・黒い縁取り・右下に影）。

series.json の 1 件は点検 1 回ぶん（`jst`、`gb`、`req_total`、`shares_today` など）。
点検のログから足すのは、要約の行を正規表現で拾うだけ（このスクリプトの `extend()`）。
**共有数の日付は UTC の日**（サーバーの「本日」が 09:00 JST で切り替わるため）。
09:00 JST 直後の点検に前日の値が残ることがあるので、直後の点検で数が減っていたら前日に入れる。
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "note"
SERIES = OUT / "series.json"

# サイトの色（frontend の CSS 変数と同じ値）
PAPER, INK, MUTED = "#f6f5f3", "#121717", "#6b6f73"
MUSTARD, VERMILION, CERULEAN, GRID = "#e5b52e", "#e5462c", "#0a8fd1", "#b9c0c8"

for name in ("IBMPlexSansJP-Bold.ttf", "IBMPlexSansJP-Regular.ttf"):
    font_manager.fontManager.addfont(str(ROOT / "fonts" / name))
plt.rcParams["font.family"] = "IBM Plex Sans JP"
plt.rcParams["axes.unicode_minus"] = False


def extend(log_paths: list[pathlib.Path]) -> None:
    """点検のログ（GitHub Actions の生ログでも要約でもよい）から series.json に足す。"""
    series = json.loads(SERIES.read_text(encoding="utf-8"))
    have = {e["jst"] for e in series}
    num = lambda s: int(s.replace(",", ""))  # noqa: E731
    for f in log_paths:
        t = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"直近 (\d+) 時間、(\d{4}-\d\d-\d\d \d\d:\d\d) JST", t)
        if not m or m.group(2) in have:
            continue
        e = {"jst": m.group(2), "hours": int(m.group(1))}
        g = re.search(r"帯域: 合計 ([\d.]+) GB、最大 ([\d.]+) GB/時", t)
        e["gb"], e["gb_peak"] = (float(g.group(1)), float(g.group(2))) if g else (None, None)
        g = re.search(r"\[stats\] (\d+) 行", t); e["stats"] = int(g.group(1)) if g else None
        g = re.search(r"メモリ（メトリクス）: 最大 (\d+) MB", t); e["mem"] = int(g.group(1)) if g else None
        g = re.search(r"CPU: 最大 ([\d.]+)", t); e["cpu"] = float(g.group(1)) if g else None
        g = re.search(r"5xx 合計 (\d+)", t); e["fivexx"] = int(g.group(1)) if g else None
        g = re.search(r"本日の共有数（最後の復元値）: ([\d,]+) 件", t); e["shares_today"] = num(g.group(1)) if g else None
        ua = re.search(r"User-Agent: (.+)", t)
        if ua:
            parts = re.findall(r"([^、]+?) ([\d,]+) 件", ua.group(1))
            e["human"] = next((num(n) for k, n in parts if k.strip() == "人"), None)
            e["req_total"] = sum(num(n) for _, n in parts)
        e["paths"] = {k: num(n) for k, n in re.findall(r"^  - `([^`]+)` ([\d,]+) 件", t, re.M)}
        series.append(e); have.add(e["jst"])
        print("add", e["jst"])
    series.sort(key=lambda e: e["jst"])
    SERIES.write_text(json.dumps(series, ensure_ascii=False, indent=1), encoding="utf-8")


def load() -> list[dict]:
    series = json.loads(SERIES.read_text(encoding="utf-8"))
    for e in series:
        e["t"] = dt.datetime.strptime(e["jst"], "%Y-%m-%d %H:%M")
    return series


def sane(series: list[dict]) -> list[dict]:
    """折れ線に使える点だけ（API の単位が取れず 40GB になった回、帯域 0 の空振り、2 時間以外の窓を捨てる）。
    **共有数の集計には使わない**。帯域が欠けた点にも共有数は入っていて、捨てるとその日の最大値を取り逃す"""
    return [e for e in series if e.get("hours") == 2 and e.get("gb") and 0 < e["gb"] < 10]


def shares_by_day(series: list[dict]) -> dict[dt.date, int]:
    """UTC の日ごとの共有数（その日の最大値）。09:00 JST 直後の点検に前日の値が残っていたら前日へ。"""
    days: dict[dt.date, int] = {}
    prev = None
    for e in series:
        n = e.get("shares_today")
        if not n:
            continue
        utc = e["t"] - dt.timedelta(hours=9)
        day = utc.date()
        if utc.hour == 0 and utc.minute < 40 and prev is not None and n >= prev:
            day = day - dt.timedelta(days=1)   # まだ切り替わる前の値
        days[day] = max(days.get(day, 0), n)
        prev = n
    return days


def frame(title: str, sub: str, unit: str):
    fig, ax = plt.subplots(figsize=(16, 9), dpi=100)
    fig.patch.set_facecolor(PAPER); ax.set_facecolor(PAPER)
    fig.subplots_adjust(left=0.095, right=0.965, top=0.75, bottom=0.14)
    fig.text(0.068, 0.905, title, fontsize=30, fontweight="bold", color=INK, va="baseline")
    fig.text(0.068, 0.86, sub, fontsize=14, color=MUTED, va="baseline")
    fig.text(0.04, 0.765, unit, fontsize=14, fontweight="bold", color=INK, va="baseline")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color(INK); ax.spines["bottom"].set_linewidth(2)
    ax.tick_params(colors=MUTED, labelsize=13, length=0)
    ax.grid(axis="y", color=GRID, linewidth=1); ax.set_axisbelow(True)
    return fig, ax


def chart_shares(series: list[dict], stamp: str) -> None:
    days = shares_by_day(series)
    keys = sorted(days)
    fig, ax = frame("作られた画像の枚数", "その日に作られた枚数（UTC の日ごと）。1 枚あたり約 900KB が置き場所に積み上がっていく", "枚 / 日")
    xs = range(len(keys))
    for i, d in enumerate(keys):
        v = days[d]
        last = i == len(keys) - 1
        ax.bar(i + 0.03, v, width=0.5, color=INK, zorder=2)             # 影
        ax.bar(i, v, width=0.5, color=VERMILION if last else MUSTARD, edgecolor=INK, linewidth=2, zorder=3)
        ax.text(i, v + max(days.values()) * 0.02, f"{v:,}", ha="center", va="bottom", fontsize=15, fontweight="bold", color=INK)
    ax.set_xticks(list(xs), [d.strftime("%m/%d") + ("\n（" + stamp + " 時点）" if i == len(keys) - 1 else "") for i, d in enumerate(keys)])
    ax.set_xlim(-0.5, len(keys) - 0.5)
    ax.set_ylim(0, max(days.values()) * 1.18)
    ax.yaxis.set_major_formatter(lambda v, _: f"{int(v):,}")
    fig.savefig(OUT / "chart-shares.png"); plt.close(fig)


def _line(series, key, color, fill, unit, title, sub, out, fmt, peak_label, marks):
    pts = [(e["t"], e[key]) for e in series if e.get(key) is not None]
    fig, ax = frame(title, sub, unit)
    xs, ys = zip(*pts)
    ax.fill_between(xs, ys, color=fill, zorder=2)
    ax.plot(xs, ys, color=color, linewidth=3, zorder=3)
    ax.scatter(xs, ys, s=40, color=INK, zorder=4)
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.grid(axis="x", color=GRID, linewidth=1)
    ax.set_ylim(0, max(ys) * 1.15)
    ax.yaxis.set_major_formatter(fmt)
    ax.set_xlim(xs[0], xs[-1] + dt.timedelta(hours=2))
    i = max(range(len(ys)), key=lambda k: ys[k])
    ax.annotate(peak_label(ys[i]), (xs[i], ys[i]), xytext=(0, 12), textcoords="offset points",
                ha="right" if i > len(ys) * 0.7 else "center", fontsize=16, fontweight="bold", color=INK)
    for when, text, col in marks:
        ax.axvline(when, color=col, linestyle="--", linewidth=2, zorder=1)
        ax.text(when, max(ys) * 1.1, text, ha="center", va="center", fontsize=13, fontweight="bold", color="white",
                bbox=dict(boxstyle="square,pad=0.35", facecolor=col, edgecolor=INK, linewidth=2))
    fig.savefig(OUT / out); plt.close(fig)


def main() -> int:
    logs = [pathlib.Path(a) for a in sys.argv[1:]]
    if logs:
        extend(logs)
    series = load()
    stamp = series[-1]["t"].strftime("%H:%M")
    chart_shares(series, stamp)
    _line(sane(series), "req_total", CERULEAN, "#bfe3f4", "回 / 2h", "どれくらい見られたか", "2 時間ごと・サイトが受け取ったアクセスの数",
          "chart-requests.png", lambda v, _: f"{int(v):,}", lambda v: f"最大 {v:,} 回", [])
    _line(sane(series), "gb", MUSTARD, "#f4e8bf", "GB / 2h", "サーバーから送り出したデータの量",
          "2 時間ごと・GB。無料で使えるのは月 100GB までなので、山が続くと足が出る",
          "chart-bandwidth.png", lambda v, _: f"{v:.1f}", lambda v: f"最大 {v:.2f} GB",
          [(dt.datetime(2026, 9, 13, 11, 0), "画像と文字を別の置き場所へ", VERMILION),
           (dt.datetime(2026, 9, 16, 0, 30), "画面を圧縮して送る", CERULEAN)])
    print("書き出し:", OUT / "chart-*.png", "点検", len(series), "件、最後", series[-1]["jst"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
