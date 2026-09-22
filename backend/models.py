"""全ソース共通のレスポンス型。"""
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

Source = Literal["itunes", "musicbrainz", "discogs", "bandcamp", "soundcloud", "youtube", "nicovideo", "bilibili", "spotify", "otodb", "vocadb", "manual"]


MAX_TEXT = 300
MAX_URL = 2048
# 曲ごとのメモ（選んだ理由など）。**共有ページの曲名リストにだけ出す**（書き出し画像には描かない）。
# 200 字・3 行まで（frontend の `NOTE_MAX` / `NOTE_LINES` と同じ）
MAX_NOTE = 200
MAX_NOTE_LINES = 3


def _is_http(v: str) -> bool:
    return v.lower().startswith(("http://", "https://")) and len(v) <= MAX_URL


# ジャケットが無い曲に使う、うちの画像（scripts/build_icons.py が作る）。
# 絶対 URL にすると手元と公開とで別の URL になり、共有した並びが他の人の環境で壊れるので相対で持つ
NO_COVER = "/no-cover.png"


def _safe_ref(v: str) -> bool:
    return _is_http(v) or v == NO_COVER or (v.startswith("/uploads/") and "/" not in v[len("/uploads/"):] and len(v) <= 80)


class Origin(BaseModel):
    """この動画の**元になった動画**（転載元）。YouTube の概要欄に「転載」「本家」などと
    書かれていたときだけ入る（`backend/sources/video.py`）。アーティスト名の候補として使う"""
    kind: Literal["nicovideo", "youtube"]
    id: str
    artist: str = ""

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return str(v)[:32]

    @field_validator("artist", mode="before")
    @classmethod
    def _artist(cls, v):
        return " ".join(str(v).split())[:MAX_TEXT] if isinstance(v, str) else ""


class Track(BaseModel):
    source: Source
    title: str
    artist: str
    album: Optional[str] = None
    image: str
    thumb: Optional[str] = None
    external_url: Optional[str] = None
    # 正方形でないマスに、この絵をどう入れるか。None なら並び全体の設定（`GridOptions.cellFit`）に従う。
    # "crop" は中央で切る、"blur" は切らずに左右をぼかした下地で埋める。**マスに置いたあとの見た目の話**なので
    # 検索結果には出ない（`backend/render.py` と frontend の `paintCover` が読む）
    fit: Optional[str] = None
    # 転載元の動画（分かったときだけ）。アーティスト名の候補に使う
    origin: Optional[Origin] = None
    # 作った人のメモ。共有ページ（`share.page_html`）が曲名の下に出す。「みんなのグリッドを探す」の索引には入れない
    note: Optional[str] = None

    @field_validator("fit")
    @classmethod
    def _fit(cls, v):
        return v if v in ("crop", "blur") else None

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, v):
        # 行ごとに空白を詰め、空行を落として 3 行・200 字まで。何も残らなければ None
        if not isinstance(v, str):
            return None
        lines = [" ".join(x.split()) for x in v.splitlines()]
        v = "\n".join([x for x in lines if x][:MAX_NOTE_LINES])[:MAX_NOTE].strip()
        return v or None

    @field_validator("title", "artist", "album", mode="before")
    @classmethod
    def _one_line(cls, v):
        # 改行・タブは空白 1 つに（Pillow は改行を含む文字列の幅計測で ValueError を投げる）。長さも抑える
        return " ".join(str(v).split())[:MAX_TEXT] if isinstance(v, str) else v

    @field_validator("image", mode="before")
    @classmethod
    def _image_url(cls, v):
        # 画像は https?:// の URL か、アップロード（/uploads/<name>）だけ。それ以外は不正としてマスごと落とす
        if not isinstance(v, str) or not _safe_ref(v.strip()):
            raise ValueError("image は https?:// の URL か /uploads/ の参照だけ受け付けます")
        return v.strip()[:MAX_URL]

    @field_validator("thumb", "external_url", mode="before")
    @classmethod
    def _opt_url(cls, v):
        # リンク先は https?:// だけ。javascript: や data: は捨てる（共有を読み込んだ他人のブラウザで開かれるため）
        if v is None:
            return None
        v = str(v).strip()
        return v[:MAX_URL] if _is_http(v) else None
