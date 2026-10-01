"""PreToolUseフック: Claudeが .env（鍵の入ったファイル）を直接読むのを止める。

permissions.denyのRead(./.env) はReadツールにしか効かないので、
シェル（Bash / PowerShell）とGrepから .envを名指しする操作をここで止める。
スクリプトが自分で .envを読むのは止めない（コマンド文字列に .envが出てこないため）。

止めたらexit 2とstderrの理由でClaudeに返す。.env.exampleは雛形なので通す。
"""
import json
import re
import sys

# 前が行頭・空白・引用符・区切り記号の「.env」だけを拾う（process.envやos.environは拾わない）。
# 後ろに英数字が続くもの（.environなど）は拾わない。.env.bak-* などの控えは拾い、.env.exampleは通す。
ENV_REF = re.compile(r"""(?:^|[\s'"`/\\=:;|&(<>,])\.env(?![\w-])(?!\.example\b)""")

# 中身を出さないgitの命令は通す（site-safety-checkの履歴検査で使う）
SAFE_GIT = re.compile(r"^\s*git\s+(log|ls-files|check-ignore|status)\b")
# ただし差分を出す指定（-pなど）や、別の命令をつなげたものは通さない
UNSAFE_IN_GIT = re.compile(r"(\s-p\b|\s-u\b|--patch|--stat\b|[;&|`$<>])")


def main() -> int:
    # Windowsの既定（cp932）で出すと、Claude Code側で文字化けする
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
            ".envには鍵が入っているので直接読まない（.claude/hooks/block_env.pyが止めた）。"
            "値が要るならスクリプト経由で使い、変数名だけで話す。雛形は .env.example。",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
