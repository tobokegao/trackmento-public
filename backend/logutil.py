"""ログ用の例外要約。URL（検索語や貼られたページの URL を含む）をログに残さない。"""
from __future__ import annotations

import re

import httpx

_URL_RE = re.compile(r"https?://\S+")


def brief(e: BaseException) -> str:
    """例外を「種類 + 短い理由」に切り詰める。URL は <url> に置き換える。"""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    msg = str(e)
    if msg:
        msg = _URL_RE.sub("<url>", msg).splitlines()[0][:120]
        return f"{type(e).__name__}({msg})"
    return type(e).__name__
