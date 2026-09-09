"""横断検索の重複マージ。title+artist の正規化キーが同じものは1件にまとめる。"""
from __future__ import annotations

import re
import unicodedata

from backend.models import Track

_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)
# 同じ曲が複数ソースにあればこの順で残す
PRIORITY = {"itunes": 0, "lastfm": 1, "musicbrainz": 2, "discogs": 3, "bandcamp": 4, "manual": 5}


def norm_key(title: str, artist: str) -> str:
    def n(s: str) -> str:
        s = unicodedata.normalize("NFKC", s).casefold()
        s = s.replace("featuring", "feat").replace("feat.", "feat")
        return _STRIP_RE.sub("", s)
    return f"{n(title)}|{n(artist)}"


def merge(tracks: list[Track]) -> list[Track]:
    """優先度の高いソースを残しつつ、元の出現順を保つ。"""
    best: dict[str, Track] = {}
    order: list[str] = []
    for t in tracks:
        k = norm_key(t.title, t.artist)
        if k not in best:
            best[k] = t
            order.append(k)
        elif PRIORITY.get(t.source, 9) < PRIORITY.get(best[k].source, 9):
            best[k] = t
    return [best[k] for k in order]
