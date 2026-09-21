"""曲名とアーティスト名から、確実に蛇足だと言える部分だけを外す。

**frontend/index.html の `trimName()` と対で直すこと**。片方だけ直すと、画面と書き出しで
曲名が違うものになる（`scripts/compare_trim.py` で突き合わせられる）。

外すのは「媒体の表記」「チャンネル名の尾」「分類のタグ」「アーティスト名の重複」だけで、
サークル名（【魂音泉】）・原曲名（【ハルトマンの妖怪少女】）・原作名（【東方紅魔郷】）・
歌唱者（（Vo:あよ））は残す。消すと情報が落ちるため。

規則と実測は docs/superpowers/specs/2026-09-21-trim-names-design.md。
"""
from __future__ import annotations

import re

from backend.merge import _n

# 括弧は同じ種類どうしで対にする（「【初音ミク(とく)】」を「【初音ミク(とく」と読まない）
BRACKETS = (("【", "】"), ("［", "］"), ("[", "]"), ("〔", "〕"), ("《", "》"))
# R4（作者名との突き合わせ）でだけ丸括弧も括弧として扱う。**R1/R3 には入れない**:
# 入れると「(on vocal)」が分類語の「Vocal」に当たって外れ、ニコカラの版の違いが消える
BRACKETS_R4 = BRACKETS + (("（", "）"), ("(", ")"))

# R1 媒体・字幕の表記。括弧の中身がこれ「だけ」なら括弧ごと外す
MEDIA = (
    r"(?:Full\s*|Short\s*|Long\s*)?(?:M/?V|P/?V|Music\s*Video|Lyric\s*Video|Official\s*(?:Music\s*)?Video"
    r"|Official\s*Audio|Visualizer|Audio|Teaser|Trailer|Live\s*Video)"
    r"|(?:ENG\s*)?Sub(?:s|bed|title[ds]?)?|字幕(?:付き?)?|歌詞(?:付き?)?"
    r"|Full\s*ver\.?|Short\s*ver\.?|(?:公式|Official)\s*(?:MV|PV|Video)"
)
MEDIA_ONLY = re.compile(rf"^\s*(?:{MEDIA})\s*$", re.I)
MEDIA_TAIL = re.compile(rf"[\s　]*[/／|・-]?[\s　]*(?:{MEDIA})[\s　]*$", re.I)

# R3 分類・区分の語。括弧の中身にこれが含まれるなら括弧ごと外す。
# **「東方」単独は入れない**（【東方紅魔郷・東方花映塚】のような原作名まで消える）
GENRE = re.compile(
    r"Vocal|ボーカル|ヴォーカル|アレンジ|arrange|ニコカラ|カラオケ|歌ってみた|演奏してみた|踊ってみた"
    r"|公式|Official|M/?V|P/?V|Music\s*Video|Lyric\s*Video|Sub(?:s|bed)?|字幕|歌詞付|Full\s*ver"
    r"|初音ミク|MMD|音MAD|実況", re.I)

# R2 アーティスト名の末尾に付く、YouTube が作るチャンネル名の尾
CHANNEL_TAIL = re.compile(
    r"\s*(?:[-–—]\s*Topic|Official\s*(?:YouTube\s*)?Channel|公式\s*(?:YouTube\s*)?チャンネル"
    r"|(?<!\w)VEVO|Channel|チャンネル)\s*$", re.I)

# A2 宣伝の文句。アーティスト名の要素にこれが入っていたら、その要素は名前ではない
PROMO = re.compile(
    r"発売中|販売中|配信中|通販|予約|受付中|好評|新譜|NEW\s*(?:ALBUM|SINGLE|SONG)|最新|"
    r"公開中|投稿中|更新中|チャンネル登録|Subscribe|公式(?:サイト|ストア|通販)|Store|"
    r"毎週|毎月|毎日|活動中|始めました", re.I)

SEP = r"[/／,、，|｜]|\s+[-–—]\s+"          # アーティスト名の区切り
# 曲名の区切り（R4 で使う）。アーティスト名と違い「、」「,」では割らない（曲名の一部であることが多い）
TITLE_SEP = re.compile(r"[\s　]*(?:[/／|｜]|(?<=[\s　])[-–—](?=[\s　]))[\s　]*")
SEP_REPEAT = r"[_/／|｜・･]|\s+[-–—]\s+"    # A1 で使う区切り（`_` を含む）
STRIP = " 　/／|-–—,、"                     # 刈ったあとに端から落とす文字

# G3 題の後半から落とす、作品への言及
WORK_TAIL = re.compile(r"(?:テーマ曲?|主題歌|挿入歌|OP|ED|イメージソング|より|収録)\s*$")
WORK_BRACKET = re.compile(r"[『「【\[（(][^』」】\])）]*[』」】\])）]")


def _usable(s: str) -> bool:
    """刈った結果として使えるか（空・短すぎは不可）"""
    return len(_n(s)) >= 2


def _spans(s: str, brackets=BRACKETS) -> list[tuple[int, int, str]]:
    """括弧の (開始, 終了, 中身) を左から。対応しない括弧は無視する"""
    out: list[tuple[int, int, str]] = []
    i = 0
    while i < len(s):
        for op, cl in brackets:
            if s.startswith(op, i):
                j = s.find(cl, i + len(op))
                if j >= 0:
                    out.append((i, j + len(cl), s[i + len(op):j]))
                    i = j + len(cl)
                    break
        else:
            i += 1
            continue
    return out


def _drop_brackets(s: str) -> str:
    """括弧のかたまりを全部落とした残り（R4 で作者名と突き合わせるのに使う）"""
    out, cut = "", 0
    for st, en, _ in _spans(s, BRACKETS_R4):
        out += s[cut:st]
        cut = en
    return out + s[cut:]


def _brackets_only(s: str) -> str:
    """括弧のかたまりだけを連結したもの（作者名を落としても原曲名は残すのに使う）"""
    return "".join(s[st:en] for st, en, _ in _spans(s, BRACKETS_R4))


def _split_outside(s: str) -> list[str]:
    """**括弧の外にある区切りだけ**で割る。[要素, 区切り, 要素, …] の形で返す。

    括弧の中の「/」まで割ると、「【人形裁判/不思議の国のアリス】」（原曲名）が 2 つに切れて
    片方だけ残る。区切りはそのまま返すので、落とさなかった所の書き方は元のまま保てる。
    """
    inside: set[int] = set()
    for st, en, _ in _spans(s, BRACKETS_R4):
        inside.update(range(st, en))
    out: list[str] = []
    last = 0
    for m in TITLE_SEP.finditer(s):
        if m.start() in inside:
            continue
        out.append(s[last:m.start()])
        out.append(m.group(0))
        last = m.end()
    out.append(s[last:])
    return out


def _graft(title: str, artist: str) -> str | None:
    """G: 題からアーティスト名を移植してよいか。よければ移植先の名前、だめなら None。

    **判定は刈る前の元の名前で行う**（先に「公式チャンネル」を刈ると G1 が立たなくなる）。
    `trim()` を呼び返すが、そのときは作者名が空なので G1 で必ず止まる（無限に潜らない）。
    """
    items = [p.strip() for p in re.split(SEP, artist) if p.strip()]
    if not any(PROMO.search(p) for p in items):
        return None                                    # G1 宣伝の文句が無い＝名前として妥当
    nt = _n(title)
    if any(_n(p) and _n(p) in nt for p in items):
        return None                                    # G2 題に出てくる＝名前として妥当
    bits = re.split(r"[/／]", title)
    if len(bits) != 2:
        return None                                    # G3 「/」がちょうど 1 つでない
    cand = WORK_BRACKET.sub("", bits[1])
    cand = WORK_TAIL.sub("", cand).strip(STRIP)
    cand = trim(cand, "")[0]
    if not _usable(cand) or _n(cand) == _n(artist):
        return None
    return cand


def _tidy_artist(a: str) -> str:
    """A1 同じ名前の繰り返しを 1 つに、A2 宣伝の文句を含む要素を落とす"""
    parts = [p for p in re.split(SEP_REPEAT, a) if p.strip()]
    if len(parts) >= 2 and len({_n(p) for p in parts}) == 1 and _usable(parts[0]):
        a = parts[0].strip()                           # A1 `ytr_ytr` → `ytr`
    items = [p.strip() for p in re.split(SEP, a) if p.strip()]
    if len(items) >= 2:
        keep = [p for p in items if not PROMO.search(p)]
        if keep and len(keep) < len(items):
            a = " / ".join(keep)                       # A2
    return a


def trim(title: str, artist: str) -> tuple[str, str]:
    """曲名とアーティスト名から蛇足を外す。**データは変えず、表示のときだけ通す**"""
    t, a = (title or "").strip(), (artist or "").strip()

    grafted = _graft(t, a)                             # G 題からの移植
    if grafted:
        # 移植したら、題の中の移植元（「/」の後ろ）は落とす。同じ名前が題と作者欄に
        # 二重に出るのを防ぐ（「/」がちょうど 1 つなのは `_graft` が確かめている）
        a = grafted
        head = re.split(r"[/／]", t)[0].strip(STRIP)
        if _usable(head):
            t = head
    a = _tidy_artist(a)

    for _ in range(3):                                 # R2 チャンネル名の尾（重なることがある）
        n = CHANNEL_TAIL.sub("", a).strip(STRIP)
        if n == a or not _usable(n):
            break
        a = n

    names = {_n(p) for p in re.split(SEP, a) if _usable(p)}   # R4 で突き合わせる作者名

    kept, cut = "", 0                                  # R1/R3/R4 括弧のかたまり
    for st, en, inner in _spans(t):
        if MEDIA_ONLY.match(inner) or _n(inner) in names or GENRE.search(inner):
            kept += t[cut:st]
            cut = en
    nt = re.sub(r"\s{2,}", " ", (kept + t[cut:]).strip()).strip(STRIP)
    if _usable(nt):
        t = nt

    for _ in range(2):                                 # R1 括弧に入っていない末尾の媒体語
        n = MEDIA_TAIL.sub("", t).strip(STRIP)
        if n == t or not _usable(n):
            break
        t = n

    # R4 区切りで割って、**作者名と同じ要素を落とす**（位置は問わない）。
    # 「psychology / Adust Rain【ハルトマンの妖怪少女】」のように括弧が付いていることがあるので、
    # 括弧を除いた残りで突き合わせ、当たったら**括弧だけ残す**（原曲名は消さない）
    bits = _split_outside(t)
    if len(bits) >= 3:
        keep = [True] * len(bits)
        for i in range(0, len(bits), 2):
            bare = _drop_brackets(bits[i]).strip()
            if not bare or not (_n(bare) in names or _n(bare) == _n(a)):
                continue
            rest = _brackets_only(bits[i]).strip()     # 括弧（原曲名など）は残す
            bits[i] = rest
            if not rest:
                keep[i] = False
            if i > 0:
                keep[i - 1] = False                    # 前の区切りごと落とす
            elif not rest:
                keep[1] = False                        # 先頭なら後ろの区切りを落とす
        nt = "".join(b for b, k in zip(bits, keep) if k).strip(STRIP)
        if nt != t and _usable(nt):
            t = nt
    return t, a
