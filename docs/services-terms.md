# 外部サービスの規約・上限と、問い合わせの記録

各サービスに「どれだけ・どうやって聞いてよいか」。**数字の上限**と、**自動取得そのものの可否**の 2 つがある。
うちの実測（ホスト別の 1 日換算）は運用ボードと `metrics/series.jsonl` を見る。

（`CLAUDE.md` から分けたもの。2026-09-20）

## ニコニコ動画のスナップショット検索 API（2026-09-21）

転載の元をたどるために使う（`backend/sources/nicosearch.py`）。**公開 API で、規約上の問題は無い**。

- 窓口: `https://snapshot.search.nicovideo.jp/api/v2/snapshot/video/contents/search`
- **`_context` にアプリ名を入れる決まり**（`trackmento`）
- **1 秒に 1 リクエストまで**が目安。`_wait_turn()` で間隔を空けている
- **押したときだけ引く**（利用者が編集パネルで「元の投稿を探す」を押したとき）。自動では引かない。
  100 曲の並びで 100 リクエストになるため
- 投稿者名は `contentId` から `getthumbinfo`（既存の取得先）で引く。上位 3 件だけ

## YouTube Data API の使い道が増えた（2026-09-21）

再生リスト（`playlistItems.list`）に加えて、**単体の動画にも `videos.list` を使う**ようになった
（概要欄から転載元を読むため。`backend/sources/video.py`）。

- `videos.list` は **1 unit / 回**で、`id` は 50 件までまとめられる
- **`fields` で絞ること**。`part=snippet` を丸ごと受けると 1 件 5.7KB、絞れば 1.0KB（実測）
- 日あたりの見込みは **76 units**（YouTube 由来は全体の 23%、画像取得 16,546 件/日から。
  無料枠 10,000 units/日の 0.8%）
- **鍵が無い・枠切れ（403）なら oEmbed に倒す**。再生リストの取得を巻き添えにしない

- **外部サービスの規約とアクセス上限を一通り調べた**（2026-09-20）。robots.txt は 7 サイトとも実際に取得して確認した
  - **数字の上限があるもの**: Apple の iTunes Search API **約 20 回/分**（1 日の上限は明記なし。キャッシュは推奨と明記）、
    MusicBrainz **1 回/秒・IP ごと**（連絡先入り UA 必須。超えると 100% 拒否）、Discogs 認証あり **60 回/分**（本番では未使用）、
    Cover Art Archive **「制限は無い」と明記**（条件は「coverartarchive.org 経由で取ること」＝守れている）、
    YouTube Data API **1 日 10,000 ユニット**（読み取りは 1 件 1 ユニット）。**どれも実測では余裕がある**
  - **数ではなく「自動取得そのもの」が規約に触れていたもの**を直した:
    - **Spotify** … robots.txt が `Disallow: /embed/`、Developer Terms IV.2.4 が robot / spider を禁止。
      **公式 Web API（Client Credentials）に移した**。鍵が無ければ公式 oEmbed（曲名とジャケット 300px だけ・アーティスト名なし）
    - **YouTube の再生リスト** … 利用規約が自動アクセスを禁止（例外は公開検索エンジンと書面許可）。
      **Data API の `playlistItems.list` に移した**（1 ページ 50 件・1 ユニット）。単体の動画は公式 oEmbed なので今までどおり
    - **SoundCloud のセット** … 一覧を揃えるのに内部 API（`api-v2.soundcloud.com`）が要り、API Terms §10 の
      scraping 禁止・§01 の client ID 必須に触れる。**セットの展開はやめた**（曲ごとの URL は公式 oEmbed で残る）
    - **bilibili** … 規約 4.2.11 が「事前の明確な書面許可」を要求し、`api.bilibili.com` の robots.txt は
      `User-agent: * / Disallow: /`。**許可を求める窓口が見当たらない**ので、**対応そのものをやめた**
      （`video.fetch_bilibili` と `playlist._bilibili` は案内を返すだけ。`fromurl._ROXY_FALLBACK` からも外した）。
      画像 URL の手入力でマスには入れられる。**すでに並びに入っている曲はそのまま映る**
    - **名乗りを正直にする** … `playlist.py` と `applemusic.py` が素の Chrome の UA を、旧 `spotify.py` が
      facebookexternalhit を名乗っていた。**ブラウザやクローラのふりをすると、相手は誰が来ているか分からず、
      連絡も遮断もできない**。今は全部 `trackmento/0.1 (+https://trackmento.com)`（HTML を読む所は
      `Mozilla/5.0 (compatible; trackmento/0.1; +https://trackmento.com)` の互換形）
  - **Spotify は鍵を入れていない**。2026 年 2 月から、開発者アプリを登録するアカウントに **Spotify Premium が必須**に
    なったため（新しい Client ID は 2/11、既存は 3/9 から）。コードは鍵があれば公式 API に切り替わる形にしてあるので、
    入れるだけで曲名・アーティスト・640px のジャケット・プレイリストが戻る
  - **YouTube の鍵は入れた**（2026-09-20）。Google Cloud のプロジェクト `trackmento`（ID は `project-a969726d-0008-4752-ab6`。
    `My First Project` から名前だけ変えたもの）で YouTube Data API v3 を有効にし、API キー `trackmento-youtube` を作った。
    **キーの制限は「API の制限＝YouTube Data API v3 だけ」。アプリケーションの制限は「なし」**（Render の送信 IP は固定でないので
    IP 制限は掛けられず、サーバーから叩くのでリファラ制限も効かない）。OAuth 同意画面は要らない（公開データを読むだけで、
    利用者の Google アカウントには触らないため。認証情報ページに出る警告は OAuth クライアント ID 向けの常設の注意書き）。
    手元は `.env`、本番は Render の Environment に `YOUTUBE_API_KEY` として入れてある。
    183 曲の再生リストで、手元と本番の両方から取れることを確かめた
  - **Bandcamp への問い合わせは送付済み・返答待ち**（2026-09-20、利用者が `bandcamp.com/contact?subj=API%20Access` から送った）。
    AUP が scraper を名指しで禁止しているが、曲メタデータの公開 API が無く正規ルートが無い。
    「何をしているか（公開ページを 1 回・1 週間キャッシュ・1 日数百回）・Bandcamp へ戻すリンク・名乗り」を書き、
    「この使い方でよいか／駄目なら外す／正規の口があれば移りたい」を聞いた。**フォームに文字数の上限があり、
    2,423 字の版は送れなかった**（送ったのは 1,270 字の短縮版）。返事で「駄目」なら `bandcamp.py` と
    `playlist._bandcamp` を bilibili と同じ形（案内を返すだけ）にする
  - **今のままにすると決めたもの**（2026-09-20、利用者の判断）:
    **ニコニコ**（規約に禁止条項は無いが robots.txt の `Disallow: /api/` が getthumbinfo を覆う。
    Snapshot API は非営利限定なので代わりにならない）、
    **Apple の Promo Content 条項**（「宣伝目的から離れた独立した娯楽価値のために使わない」。ジャケットを並べる
    用途は文面と噛み合わないが、アフィリエイトのリンクは使っていない）
  - 調べた元の資料と実測の突き合わせは、この日の scratchpad の `外部サービスの規約と実測.md`
- **VocaDB への問い合わせは返答済み**（2026-09-20 に Discord で送り、同日に返答。利用者の操作）。
  **返答**: 「1 分に 2 回くらいなら気にする量ではない」「この endpoint とこの量ならこちらに影響は無い」
  「ちゃんとした User-Agent を付けてくれてありがとう」。**唯一の要望は「間隔を空けて、同時に多く送らないでほしい」**。
  CORS は「検討して後で連絡する」
  - 受けて入れた直し（`vocadb.py` の `_GATE` / `_pace`、`090a6e0`）: **VocaDB へのすべての要求**（検索・動画 ID・題からの検索）を
    1 本の列に通し、**同時 2 本まで・直前の要求から 0.5 秒（`MIN_GAP`）空ける**。以前は動画 ID の補完が間隔なしで同時 3 本だった。
    実測で 5 件を同時に投げても階段状に出る（4.78 秒）。マイリストの穴埋め（全体 10 秒で打ち切り）は埋まる数が減るが、行儀を取った
  - **CORS の連絡が来たら**: 許可されればブラウザから直接引く形にできる（そのときは利用者の IP と検索語が VocaDB に渡るので、
    **プライバシーポリシーに 1 行足す**）。断られてもこのままでよい
  - 以下は送ったときの記録。
  API の決まりに「1 日数千件には事前の許可が要る」とあり、うちは 1 日 1,500〜2,500 件でその線に近い。
  **決まりを確かめないまま送り続けていたことのお詫び**を冒頭と締めに入れ、使い方・量・減らす工夫を書き、
  「この量でよいか／1 日の上限は／やめてほしければ外す」と「`https://trackmento.com` からの CORS を許可してもらえないか」を聞いた
  - **返答で決まること**: 上限を言われたらそれに合わせる（`SOURCE_TIMEOUTS` ではなく、聞く回数のほうを減らす）。
    やめてほしいと言われたら VocaDB を出どころから外す（`SOURCES["vocadb"]` と画面の `ALL_SOURCES` など、ソースを足したときの 5 か所）。
    **CORS を許可されたら**、VocaDB の検索は iTunes・MusicBrainz と同じくブラウザから直接引く形にできる
    （そのときは利用者の IP と検索語が VocaDB に渡るので、**プライバシーポリシーに 1 行足す**）
  - 問い合わせ文と添削の取捨は scratchpad の `VocaDB問い合わせ.txt`（このセッションのもの。残す必要があれば手元へ）
- **otoDB 開発者への問い合わせは返答済み**（2026-09-13 に Discord で送り、SnO₂WMaN さんと mmaker さんから返答。2026-09-18 に記録）:
  1. roxy への問い合わせ頻度（うちは同時接続 3・1 リストあたり 24 件・結果を 1 日キャッシュ）
     → **問題ない**（mmaker さん: "That request volume is fine, we already get plenty more than that"）。
     サーバーの運用は mmaker さんの担当。負荷の相談は otoDB の Discord サーバーで
  2. roxy は otoDB 登録済みの作品なら **ニコニコ以外**の URL でも引けるのか
     → **引けない**（SnO₂WMaN さん: 「roxy はニコニコしかフォールバックない」）。mmaker さんによれば roxy は
     もともと Google スプレッドシート向けのもの。**SoundCloud のプレイリストの穴埋めは足さない**と決めた
  3. サムネイルのサイズ指定 → **いずれ用意する予定だが優先度は低い**。こちらで縮小しているので現状のままでよい
  - 今の使い方（同時接続 3・結果を 1 日キャッシュ・見つからなかった分も覚える）は、この返答を踏まえて**そのまま維持**する
