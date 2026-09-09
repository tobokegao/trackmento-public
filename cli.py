"""Claude Code から叩く CLI（タスク15で実装）。

cli.py add    --artist A --title T [--grid NAME] [--source itunes|lastfm|mb|discogs]
cli.py add    --bandcamp URL [--grid NAME]
cli.py add    --image URL --artist A --title T [--grid NAME]
cli.py pick   --index N
cli.py list   [--grid NAME]
cli.py move   --from N --to M
cli.py remove --index N
cli.py render [--grid NAME] [--size 3x3] [--ratio 16:9] [--sidebar] [--title "..."]
cli.py clear  [--grid NAME]
"""
import sys


def main(argv: list[str]) -> int:
    print("cli.py は未実装です（タスク15）", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
