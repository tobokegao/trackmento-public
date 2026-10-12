"""textとJSONだけgzipで返すミドルウェア（2026-10-12に `main.py` から分けた）。"""
from __future__ import annotations

import asyncio
import gzip as gziplib

from starlette.datastructures import Headers, MutableHeaders


# gzipをかける種類。画像・フォント・動画は既に圧縮済みで、かけてもほとんど縮まずCPUだけ使う
_GZIP_TYPES = ("text/", "application/json", "application/javascript", "application/xml", "image/svg+xml")
_GZIP_MIN = 900          # これより小さい応答は掛けない（ヘッダのほうが重くなる）
_GZIP_LEVEL = 6          # 9との差は数 % で、時間は3倍かかる


class GZipText:
    """**textとJSONだけgzipで返す**。

    Renderの課金対象は「Renderが送るバイト数」で、**前段のCloudflareが付けるbrotliは
    そこには効かない**（`Content-Encoding: br` が返っていても、Render → Cloudflareは生のまま）。
    画面のHTMLは273KBあり、2時間の転送量の39% を占めていた。gzipで82KB（3.34分の1）になる。

    Starletteの `GZipMiddleware` を使わないのは**内容の種類で分けてくれない**ため。
    `/shares/*.jpg`（1件490KB）まで圧縮しようとしてCPUを捨てることになる。
    分割して送る応答（`more_body`）も素通しする（画像の中継など）。
    """

    def __init__(self, app, minimum_size: int = _GZIP_MIN) -> None:
        self.app, self.minimum_size = app, minimum_size

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or "gzip" not in Headers(scope=scope).get("accept-encoding", ""):
            return await self.app(scope, receive, send)
        start: dict | None = None

        async def send_wrapper(message: dict) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message          # 本文の種類と大きさを見てから送る
                return
            if message["type"] != "http.response.body" or start is None:
                return await send(message)
            body = message.get("body", b"")
            hdrs = MutableHeaders(raw=start["headers"])
            ctype = hdrs.get("content-type", "")
            if (message.get("more_body") or len(body) < self.minimum_size
                    or hdrs.get("content-encoding") or not ctype.startswith(_GZIP_TYPES)):
                head, start = start, None
                await send(head)
                return await send(message)
            packed = await asyncio.to_thread(gziplib.compress, body, _GZIP_LEVEL)
            hdrs["content-encoding"] = "gzip"
            hdrs["content-length"] = str(len(packed))
            hdrs.add_vary_header("Accept-Encoding")
            head, start = start, None
            await send(head)
            await send({"type": "http.response.body", "body": packed, "more_body": False})

        await self.app(scope, receive, send_wrapper)
