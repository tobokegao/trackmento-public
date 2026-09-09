"""横断検索の重複マージ。title+artist+album の正規化キーが同じものは1件にまとめる。

アルバム名を鍵に含めるのは、同じ曲でもジャケットが違う盤（シングル／アルバム／ベスト）を
別候補として残すため。アルバム名が無いソースの結果は空文字として扱う。
"""
from __future__ import annotations

import re
import unicodedata

from backend.models import Track

_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)
# よくある盤種の接尾辞は鍵から落とす（"Lemon - Single" と "Lemon" を同一視）
_ALBUM_NOISE_RE = re.compile(r"\s*[-–—]\s*(single|ep)\s*$", re.IGNORECASE)
# 同じ曲が複数ソースにあればこの順で残す
PRIORITY = {"musicbrainz": 0, "discogs": 1, "itunes": 2, "bandcamp": 3, "soundcloud": 4, "spotify": 5, "youtube": 6, "nicovideo": 7, "bilibili": 8, "manual": 9}


def _n(s: str | None) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = s.replace("featuring", "feat").replace("feat.", "feat")
    return _STRIP_RE.sub("", s)


def norm_key(title: str, artist: str, album: str | None = None) -> str:
    album = _ALBUM_NOISE_RE.sub("", album or "")
    return f"{_n(title)}|{_n(artist)}|{_n(album)}"


def merge(tracks: list[Track]) -> list[Track]:
    """優先度の高いソースを残しつつ、元の出現順を保つ。"""
    best: dict[str, Track] = {}
    order: list[str] = []
    for t in tracks:
        k = norm_key(t.title, t.artist, t.album)
        if k not in best:
            best[k] = t
            order.append(k)
        elif PRIORITY.get(t.source, 9) < PRIORITY.get(best[k].source, 9):
            best[k] = t
    return [best[k] for k in order]
