"""PreToolUse フック: Claude が .env（鍵の入ったファイル）を直接読むのを止める。

permissions.deny の Read(./.env) は Read ツールにしか効かないので、
シェル（Bash / PowerShell）と Grep から .env を名指しする操作をここで止める。
スクリプトが自分で .env を読むのは止めない（コマンド文字列に .env が出てこないため）。

止めたら exit 2 と stderr の理由で Claude に返す。.env.example は雛形なので通す。
"""
import json
import re
import sys

# 前が行頭・空白・引用符・区切り記号の「.env」だけを拾う（process.env や os.environ は拾わない）。
# 後ろに英数字が続くもの（.environ など）は拾わない。.env.bak-* などの控えは拾い、.env.example は通す。
ENV_REF = re.compile(r"""(?:^|[\s'"`/\\=:;|&(<>,])\.env(?![\w-])(?!\.example\b)""")

# 中身を出さない git の命令は通す（site-safety-check の履歴検査で使う）
SAFE_GIT = re.compile(r"^\s*git\s+(log|ls-files|check-ignore|status)\b")
# ただし差分を出す指定（-p など）や、別の命令をつなげたものは通さない
UNSAFE_IN_GIT = re.compile(r"(\s-p\b|\s-u\b|--patch|--stat\b|[;&|`$<>])")


def main() -> int:
    # Windows の既定（cp932）で出すと、Claude Code 側で文字化けする
    sys.stderr.reconfigure(encoding="utf-8")
    data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    tool = data.get("tool_name", "")
    inp = data.get("tool_input") or {}

    if tool in ("Bash", "PowerShell"):
        cmd = inp.get("command") or ""
        if SAFE_GIT.match(cmd) and not UNSAFE_IN_GIT.search(cmd):
            return 0
        targets = [cmd]
    elif tool == "Grep":
        targets = [inp.get("path") or "", inp.get("glob") or ""]
    else:
        return 0

    if any(ENV_REF.search(t) for t in targets):
        print(
            ".env には鍵が入っているので直接読まない（.claude/hooks/block_env.py が止めた）。"
            "値が要るならスクリプト経由で使い、変数名だけで話す。雛形は .env.example。",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
