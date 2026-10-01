# 外部サービスの規約・上限と、問い合わせの記録

各サービスに「どれだけ・どうやって聞いてよいか」。**数字の上限**と、**自動取得そのものの可否**の2つがある。
うちの実測（ホスト別の1日換算）は運用ボードと `metrics/series.jsonl` を見る。

（`CLAUDE.md` から分けたもの。2026-09-20）

## ニコニコ動画のスナップショット検索API（2026-09-21）

転載の元をたどるために使う（`backend/sources/nicosearch.py`）。**公開APIで、規約上の問題は無い**。

- 窓口: `https://snapshot.search.nicovideo.jp/api/v2/snapshot/video/contents/search`
- **`_context` にアプリ名を入れる決まり**（`trackmento`）
- **1秒に1リクエストまで**が目安。`_wait_turn()` で間隔を空けている
- **押したときだけ引く**（利用者が編集パネルで「元の投稿を探す」を押したとき）。自動では引かない。
  100曲の並びで100リクエストになるため
- 投稿者名は `contentId` から `getthumbinfo`（既存の取得先）で引く。上位3件だけ

## otoDBの作品APIを転載元の候補にも使う（2026-09-21）

「元の投稿を探す」を押したとき、roxy（既存）と `api/work/work`・`api/work/sources`（新）を引く（`otodb.origin_by_video`）。
**押したときだけ・1本につき3回・結果を7日覚える**。問い合わせの頻度は2026-09-13の返答（「今の量なら問題ない」）の範囲に収まる見込み。
`api/work/sources` は説明の見当たらない窓口（名前から当てて見つけた）なので、形が変わったら候補が出なくなるだけで壊れはしない作りにしてある

## YouTube Data APIの使い道が増えた（2026-09-21）

再生リスト（`playlistItems.list`）に加えて、**単体の動画にも `videos.list` を使う**ようになった
（概要欄から転載元を読むため。`backend/sources/video.py`）。

- `videos.list` は **1 unit / 回**で、`id` は50件までまとめられる
- **`fields` で絞ること**。`part=snippet` を丸ごと受けると1件5.7KB、絞れば1.0KB（実測）
- 日あたりの見込みは **76 units**（YouTube由来は全体の23%、画像取得16,546件/日から。
  無料枠10,000 units/日の0.8%）
- **鍵が無い・枠切れ（403）ならoEmbedに倒す**。再生リストの取得を巻き添えにしない

- **外部サービスの規約とアクセス上限を一通り調べた**（2026-09-20）。robots.txtは7サイトとも実際に取得して確認した
  - **数字の上限があるもの**: AppleのiTunes Search API **約20回/分**（1日の上限は明記なし。キャッシュは推奨と明記）、
    MusicBrainz **1回/秒・IPごと**（連絡先入りUA必須。超えると100% 拒否）、Discogs認証あり **60回/分**（本番では未使用）、
    Cover Art Archive **「制限は無い」と明記**（条件は「coverartarchive.org経由で取ること」＝守れている）、
    YouTube Data API **1日10,000ユニット**（読み取りは1件1ユニット）。**どれも実測では余裕がある**
  - **数ではなく「自動取得そのもの」が規約に触れていたもの**を直した:
    - **Spotify** … robots.txtが `Disallow: /embed/`、Developer Terms IV.2.4がrobot / spiderを禁止。
      **公式Web API（Client Credentials）に移した**。鍵が無ければ公式oEmbed（曲名とジャケット300pxだけ・アーティスト名なし）
    - **YouTubeの再生リスト** … 利用規約が自動アクセスを禁止（例外は公開検索エンジンと書面許可）。
      **Data APIの `playlistItems.list` に移した**（1ページ50件・1ユニット）。単体の動画は公式oEmbedなので今までどおり
    - **SoundCloudのセット** … 一覧を揃えるのに内部API（`api-v2.soundcloud.com`）が要り、API Terms §10の
      scraping禁止・§01のclient ID必須に触れる。**セットの展開はやめた**（曲ごとのURLは公式oEmbedで残る）
    - **bilibili** … 規約4.2.11が「事前の明確な書面許可」を要求し、`api.bilibili.com` のrobots.txtは
      `User-agent: * / Disallow: /`。**許可を求める窓口が見当たらない**ので、**対応そのものをやめた**
      （`video.fetch_bilibili` と `playlist._bilibili` は案内を返すだけ。`fromurl._ROXY_FALLBACK` からも外した）。
      画像URLの手入力でマスには入れられる。**すでに並びに入っている曲はそのまま映る**
      - **2026-09-23に開放平台（open.bilibili.com/doc）を読み直した**（JSで描かれるページなのでPlaywrightで開き、
        文書の目次API `open.bilibili.com/arcopen/user/open-doc/view?id=4` から全文を取った）。**個人は登録できない**
        （「暂未开通个人开发者的申请入驻」。営業許可証・押印した公函・ICP備案が要る）。稿件の詳細（`arcopen/fn/archive/view`）は
        **作者本人のOAuthが前提**で、任意のBVから題名やカバーを引く口は無い。載っていない用途の相談先は
        `openplatform-feedback@bilibili.com`（CC `live-open@bilibili.com`、3〜5営業日）で、「合作内容・双方の定量的な利益・会社情報」を
        書くよう求めている。戻すなら、この窓口に書面許可を頼むか、VocaDBのPVから引く（bilibiliを叩かない）かのどちらか
      - **2026-09-24に「よそのデータベース経由」で戻した**（利用者と相談。VocaDBだけではボカロに偏り、音MAD・YTPMVが取れないため）。
        otoDBはbilibiliの投稿も登録していて（検索で当たった36件中20件がbilibili）、roxyにBVのURLを渡すと
        登録済みなら題とサムネイル（otoDBのCDN）が返る。無ければVocaDBのbyPv（bilibiliのPVはav番号）。
        **bilibiliには一度も問い合わせない**（BV↔avは手元の計算、b23.tvは展開できないので断る、hdslbの画像は使わない）。
        書面許可のメールは送っていない。**2026-09-28に利用者の判断で「頼まない」と決めた**（個人・非商用では
        「双方の定量的な利益・会社情報」を書けず、望みが薄い。DB経由で足りている）
    - **名乗りを正直にする** … `playlist.py` と `applemusic.py` が素のChromeのUAを、旧 `spotify.py` が
      facebookexternalhitを名乗っていた。**ブラウザやクローラのふりをすると、相手は誰が来ているか分からず、
      連絡も遮断もできない**。今は全部 `trackmento/0.1 (+https://trackmento.com)`（HTMLを読む所は
      `Mozilla/5.0 (compatible; trackmento/0.1; +https://trackmento.com)` の互換形）
  - **Spotifyは鍵を入れていない**。2026年2月から、開発者アプリを登録するアカウントに **Spotify Premiumが必須**に
    なったため（新しいClient IDは2/11、既存は3/9から）。コードは鍵があれば公式APIに切り替わる形にしてあるので、
    入れるだけで曲名・アーティスト・640pxのジャケット・プレイリストが戻る
  - **YouTubeの鍵は入れた**（2026-09-20）。Google Cloudのプロジェクト `trackmento`（IDは `project-a969726d-0008-4752-ab6`。
    `My First Project` から名前だけ変えたもの）でYouTube Data API v3を有効にし、APIキー `trackmento-youtube` を作った。
    **キーの制限は「APIの制限＝YouTube Data API v3だけ」。アプリケーションの制限は「なし」**（Renderの送信IPは固定でないので
    IP制限は掛けられず、サーバーから叩くのでリファラ制限も効かない）。OAuth同意画面は要らない（公開データを読むだけで、
    利用者のGoogleアカウントには触らないため。認証情報ページに出る警告はOAuthクライアントID向けの常設の注意書き）。
    手元は `.env`、本番はRenderのEnvironmentに `YOUTUBE_API_KEY` として入れてある。
    183曲の再生リストで、手元と本番の両方から取れることを確かめた
  - **Bandcampへの問い合わせは送付済み・返答待ち**（2026-09-20、利用者が `bandcamp.com/contact?subj=API%20Access` から送った）。
    AUPがscraperを名指しで禁止しているが、曲メタデータの公開APIが無く正規ルートが無い。
    「何をしているか（公開ページを1回・1週間キャッシュ・1日数百回）・Bandcampへ戻すリンク・名乗り」を書き、
    「この使い方でよいか／駄目なら外す／正規の口があれば移りたい」を聞いた。**フォームに文字数の上限があり、
    2,423字の版は送れなかった**（送ったのは1,270字の短縮版）。返事で「駄目」なら `bandcamp.py` と
    `playlist._bandcamp` をbilibiliと同じ形（案内を返すだけ）にする
  - **今のままにすると決めたもの**（2026-09-20、利用者の判断）:
    **ニコニコ**（規約に禁止条項は無いがrobots.txtの `Disallow: /api/` がgetthumbinfoを覆う。
    Snapshot APIは非営利限定なので代わりにならない）、
    **AppleのPromo Content条項**（「宣伝目的から離れた独立した娯楽価値のために使わない」。ジャケットを並べる
    用途は文面と噛み合わないが、アフィリエイトのリンクは使っていない）
  - 調べた元の資料と実測の突き合わせは、この日のscratchpadの `外部サービスの規約と実測.md`
- **VocaDBへの問い合わせは返答済み**（2026-09-20にDiscordで送り、同日に返答。利用者の操作）。
  **返答**: 「1分に2回くらいなら気にする量ではない」「このendpointとこの量ならこちらに影響は無い」
  「ちゃんとしたUser-Agentを付けてくれてありがとう」。**唯一の要望は「間隔を空けて、同時に多く送らないでほしい」**。
  CORSは「検討して後で連絡する」
  - 受けて入れた直し（`vocadb.py` の `_GATE` / `_pace`、`090a6e0`）: **VocaDBへのすべての要求**（検索・動画ID・題からの検索）を
    1本の列に通し、**同時2本まで・直前の要求から0.5秒（`MIN_GAP`）空ける**。以前は動画IDの補完が間隔なしで同時3本だった。
    実測で5件を同時に投げても階段状に出る（4.78秒）。マイリストの穴埋め（全体10秒で打ち切り）は埋まる数が減るが、行儀を取った
  - **CORSの連絡が来たら**: 許可されればブラウザから直接引く形にできる（そのときは利用者のIPと検索語がVocaDBに渡るので、
    **プライバシーポリシーに1行足す**）。断られてもこのままでよい
  - 以下は送ったときの記録。
  APIの決まりに「1日数千件には事前の許可が要る」とあり、うちは1日1,500〜2,500件でその線に近い。
  **決まりを確かめないまま送り続けていたことのお詫び**を冒頭と締めに入れ、使い方・量・減らす工夫を書き、
  「この量でよいか／1日の上限は／やめてほしければ外す」と「`https://trackmento.com` からのCORSを許可してもらえないか」を聞いた
  - **返答で決まること**: 上限を言われたらそれに合わせる（`SOURCE_TIMEOUTS` ではなく、聞く回数のほうを減らす）。
    やめてほしいと言われたらVocaDBを出どころから外す（`SOURCES["vocadb"]` と画面の `ALL_SOURCES` など、ソースを足したときの5か所）。
    **CORSを許可されたら**、VocaDBの検索はiTunes・MusicBrainzと同じくブラウザから直接引く形にできる
    （そのときは利用者のIPと検索語がVocaDBに渡るので、**プライバシーポリシーに1行足す**）
  - 問い合わせ文と添削の取捨はscratchpadの `VocaDB問い合わせ.txt`（このセッションのもの。残す必要があれば手元へ）
- **otoDB開発者への問い合わせは返答済み**（2026-09-13にDiscordで送り、SnO₂WMaNさんとmmakerさんから返答。2026-09-18に記録）:
  1. roxyへの問い合わせ頻度（うちは同時接続3・1リストあたり24件・結果を1日キャッシュ）
     → **問題ない**（mmakerさん: "That request volume is fine, we already get plenty more than that"）。
     サーバーの運用はmmakerさんの担当。負荷の相談はotoDBのDiscordサーバーで
  2. roxyはotoDB登録済みの作品なら **ニコニコ以外**のURLでも引けるのか
     → **引けない**（SnO₂WMaNさん: 「roxyはニコニコしかフォールバックない」）。mmakerさんによればroxyは
     もともとGoogleスプレッドシート向けのもの。**SoundCloudのプレイリストの穴埋めは足さない**と決めた
  3. サムネイルのサイズ指定 → **いずれ用意する予定だが優先度は低い**。こちらで縮小しているので現状のままでよい
  - 今の使い方（同時接続3・結果を1日キャッシュ・見つからなかった分も覚える）は、この返答を踏まえて**そのまま維持**する
