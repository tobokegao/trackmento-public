# 取得元（backend/sources/）

iTunes・MusicBrainz・VocaDB・otoDB・Bandcampなどからの取得と、画像の大きさの選び方。
各サービスの規約と上限は `docs/services-terms.md` を見る。

（`CLAUDE.md` から分けたもの。2026-09-20。中身は当時のまま）

## 転載元の候補（2026-09-21）

YouTubeの取得は **Data API（`videos.list`）**が主になった（概要欄が要るため。鍵が無ければoEmbed）。
概要欄に「転載」「本家」などの語と元動画のURLがあれば `Track.origin` に持たせる。

概要欄に何も書いていないものは、**ニコニコのスナップショット検索**（`backend/sources/nicosearch.py`）で
同じ題の古い投稿を探せる。利用者が押したときだけ。詳しくは `docs/services-terms.md`。

**otoDBの作品からも引く**（2026-09-21、`otodb.origin_by_video`）。マスの動画のURLをroxyに渡し、
`identifier` が `otodb:<id>` なら（**登録済みの作品ならYouTubeのURLでも返る**。未登録のYouTubeは404）
`api/work/work` のCreatorタグを作者に、`api/work/sources` を作品に登録されたほかの投稿（`platform` 1 = YouTube・2 = ニコニコ、`published_date`）にする。
例: `T9Cb_iP5uNI`（YouTube）→ 作品22373 → 作者「CB」、ほかの投稿sm29308357（2016-07-24）。
- **どれが本人の投稿かは決めない**。sourcesの `work_origin`（0 / 1）がそれらしいが意味を確かめていない（22373では古いニコニコ側が1だった）
- 押したときだけ。1本につきroxy 1回＋otoDB 2回。結果は `cache` の `otodb-origin` に7日（見つからなかった分も空で覚える。一時的な失敗は覚えない）。鍵は動画のURL
- ニコニコの検索と並行して引く（`asyncio.gather`）ので、待ち時間は増えない

- ジャケットの取得サイズは書き出しのマス（600px = `CELL_PX`）に合わせる。それ以上の解像度は縮小されて捨てられるだけで、転送量（Renderの課金対象）が増える。配信元ごとに `clamp_size()` を持ち、`/image-proxy` から呼んで保存済みのグリッドにも効かせる。**やっているのはURLの書き換えだけで、こちらで圧縮や再エンコードはしない**（配信元が用意している小さい版をそのまま返す。Bandcampの `_16` で取ったものは配信元から直接取ったバイト列と完全に一致する＝画質の劣化なし）
  - iTunes `itunes.clamp_size` … `/1000x1000bb.jpg` → `/600x600bb.jpg`（171KB → 77KB）
  - Bandcamp `bandcamp.clamp_size` … 欲しい実寸を満たす最小のサイズコードを選ぶ（`_7` 150px/11KB → `_9` 210px/20KB →
    `_4` 300px/34KB → `_16` 700px/88KB）。**原寸 `_0` は1枚6.5MBあった**。コードと実寸の対応は総当たりで調べた値を `_CODE_PX` に持つ
  - bilibili `video.clamp_size` … 指定なし（原寸）→ `@600w_600h_1c`（640KB → 50KB）。**2026-09-20に動画ページから取るのをやめたので、すでに並びに入っている画像にだけ効く**（2026-09-24からの取り込みはotoDB・VocaDBの画像で、hdslbは使わない）
  - **うちが知らないホストの画像（利用者が手で貼ったURL）も、サーバー側で縮める**（2026-09-15）。
    どこのサイトか分からないので `clamp_size` が効かず、原寸のまま通っていた（実測で3000x3000が素通し）。
    `_known_image_host()`（`IMAGE_HOST_ALLOWLIST` に末尾一致するか）で判定し、知らないホストならotoDBと同じ扱いにする。
    実測: 660KB / 3000x3000 → **99KB / 600x600**、小さいマス（px=200）なら5KB
    - **透明があるものはPNGのまま返す**（`shrink_bytes`）。JPEGに倒すと透明が黒く潰れる。動くGIFは最初のコマだけ
    - 端末から選んだ画像（`uploads.py`）は保存時に長辺2048pxへ縮めてある。**手入力URLだけ無加工だったのを揃えた**
  - **otoDBのCDNはContent-Typeを返さない**。`/image-proxy` もサーバー描画（`render.fetch_image_bytes`）も、ヘッダが無ければ中身の先頭で型を見分ける（`imgtools.sniff_image_type`）。
    **2026-09-22まで描画の側にだけこれが無く**、Canvasの使えない端末の共有（サーバー描画）とCLIでotoDBのサムネが抜けていた（紹介動画の画を作っていて気付いた）
  - otoDBだけは例外で、`/image-proxy` がサーバー側で縮める（`imgtools.shrink_bytes`）。URLに大きさ指定の仕組みが無く、
    常に1280x720 / 平均166KBを返すため、256マスだと合計41.5MBになる。**マスは正方形で中央を切り抜くので短辺を基準に縮める**
    （長辺で縮めると短辺が足りず拡大ボケする）。刻みは200px単位（200/400/600）で、キャッシュとR2のキーは `<url>#px=<N>` と分ける。
    短辺200pxで1枚22.6KB（256マスで5.7MB、-86%）。これだけJPEG品質85で再エンコードするので原本とはバイト列が変わる
  - 実測して問題が無かったもの: SoundCloud 78KB、YouTube 32KB、ニコニコ10KB、Spotify 120KB（640px。鍵があるときの値。本番は鍵なしでoEmbedの300px）、Cover Art Archiveは `front-250`（28KB）が最小で250/500/1200の3段階しかない
    （ブラウザから直接読むのでRenderを通らない）
- **Bandcampのアーティスト名は `data-tralbum` から取る**（`bandcamp.fetch`、2026-09-16）。
  JSON-LDの `byArtist` だけを見ていたが、**レーベルのアカウントが上げた曲ではそこがレーベル名**に
  なっていることがある（利用者から「レーベル名がアーティストになる」と報告）。
  ページには `data-tralbum` も埋まっていて、`current.artist` と**曲ごとの `trackinfo[].artist`** を持つ。
  - 見る順は「1曲のページなら `trackinfo[0].artist` → `current.artist` → `artist` → JSON-LDの `byArtist`」。
    **アルバムのページで `trackinfo[0]` を見てはいけない**（1曲目のアーティストがアルバム全体の名前になる）
  - `og:site_name` は**最後の保険**。あれは「ページの持ち主」の名前なので、レーベルのページでは必ずレーベル名になる
  - **BandcampのアルバムURLは収録曲に展開する**（2026-09-16）。以前は1マス（アルバム1枚）に
    しかならず、レーベルのアカウントのものだと、その1マスのアーティストがレーベル名になっていた。
    `playlist.kind()` が `/album/<名前>` も拾い、`_bc_album` が `data-tralbum` の `trackinfo` を読む
    - **曲ごとの `artist` を優先**する（コンピレーションでは曲ごとに違う）。無ければアルバムの `artist`
    - ジャケットは曲ごとの `art_id`、無ければアルバムの `art_id` から組み立てる
    - ファンのプレイリスト（`bandcamp.com/<user>/playlist/…`）は今までどおり `data-blob` を読む。
      アルバムの読み取りを先に試し、空なら従来の経路に落ちる
    - 判定は画面側（`isPlaylist`）にも同じものがある。**片方だけ直すと、貼っても1マスのまま**になる
- **VocaDB（ボカロのデータベース）**（`backend/sources/vocadb.py`、2026-09-16）。iTunesに配信の無い
  ボカロ曲を引くための、**選んだときだけ使う**ソース（応答が1.6〜2.8秒とiTunesより遅い）
  - **並べ替えを指定しないと原曲が上に来ない**。`sort=RatingScore` と `preferAccurateMatches=true` を
    付けると「メルト」でryoの原曲が1位になる（付けないと歌ってみた・REMIXが先に並ぶ。実測）
  - `artistString` が**「ハチfeat. 初音ミク」の形**で返る。作者と歌声合成ソフトがまとめて手に入るので、
    そのまま曲名リストに出している
  - **サムネイルはURLを書き換えて大きくする**（`clamp_size`。他のソースと同じ考え方で、再エンコードはしない）
    - YouTube … VocaDBが返すのは `default.jpg`（120x90・4.8KB）。`hqdefault.jpg`（480x360・39KB）へ。
      `sddefault` は無い動画があるので使わない
    - ニコニコ … 素のURLは130x100。`.L` を足すと360x270。ただし**古い動画には大きい版が無い**
      （実測で17,000,000番台までは404、19,000,000番台から200）ので `NICO_L_FROM` で線を引く
  - **queryは曲名だけにして、アーティストはこちらで絞る**（2026-09-16）。「シャルル バルーン」のように
    2語をつないで送るとVocaDBは曲名にその全文が含まれるものを探して0件になる（`artistName` パラメータは
    無視される。実測）。絞り込みは `merge._n` の部分一致で、1件も残らなければ絞らずに返す。
    利用者からは「半角濁点のアーティストが引っかからない」と報告されたが、半角（ﾊﾞ）はVocaDB側も
    こちらも吸収していて、実際の原因は2語の連結だった
  - 曲名リストのリンク先は、PVがあればその動画のページ、無ければVocaDBの曲のページ
  - **ニコニコの投稿者名が取れない動画は、VocaDBで作者名を補う**（`vocadb.artist_by_pv`、2026-09-19）。
    投稿者が退会・非公開だと `getthumbinfo` にuser_nicknameもch_nameも無く、アーティスト名が空になっていた
    （利用者の25曲の共有で2曲）。`/api/songs/byPv?pvService=NicoNicoDouga&pvId=sm…` で引く。単体のURL
    （`video.fetch_nicovideo`）とマイリスト（`playlist._fill_missing_artists`、上限24件・15秒）の両方。
    同時3本、見つからなかった分も1日メモリに覚える
    - **先にotoDBの作品の作者で埋め、無ければVocaDB**（`otodb.origin_by_video`、2026-09-27、利用者の希望。
      音MADのほうが作者の退会が多そう、という見立てでotoDBを先にした。転載の音MADをVocaDBが題から別の曲に取り違えるのも減る）。
      音MADはVocaDBに無いので、それまでは空のままだった。roxyに動画のURLを渡し、`otodb:<id>` が返れば作品のCreatorタグ。
      結果は `otodb-origin` に7日（見つからなかった分も）。マイリストではroxyを `_ROXY_SEM` で絞り、
      待つ時間を10 → 15秒に延ばした。例: sm29308357 → 「CB」。**YouTubeの再生リストには掛けていない**
      （投稿者名はチャンネル名で、空になるのは消えた動画だけ。そちらは `_fill_from_otodb` が埋める）
  - **転載の動画（動画IDがVocaDBに無い）は題から曲を探す**（`vocadb.artist_by_title`、利用者の提案）。
    括弧の中身などから曲名の候補を取り（「初音ミク」「オリジナル」「歌ってみた」「MAD」などは外す）、VocaDBで検索する。
    **間違った作者名は空欄より悪い**ので、採るのは「原曲（songType=Original）で、曲名が題に含まれ、題に歌声の名前が
    あればその歌声の曲」で、さらに「題に作者名が入っている」か「当てはまる原曲が1つ、または評価が2番目の
    `WEAK_LEAD`（5）倍以上」のときだけ。利用者の25曲で24曲が正しい作者、1曲が空欄、誤り0。
    絞る前は「歌ってみた」「MAD」という語そのものや、同名の別の原曲（「ハロー」「ロキ」のGUMI版）の作者を拾っていた
  - **アーティスト名から発行元だけの名前を外す**（`vocadb.artist_name`、2026-09-19、利用者の指摘）。`artistString` は
    発行元のサークルも並べるので「kz, Google feat. 初音ミク」（Tell Your WorldはGoogle ChromeのCM曲）や
    「マチゲリータ, ProjectDIVAチャンネルfeat. 初音ミク」になっていた。`fields=Artists` の役割（roles）が
    Publisher / Distributorだけの名前を抜く。**作曲者だけで組み直してはいけない**（「Omoi」のような作り手のユニットは
    サークル扱いなので消える）。検索・動画ID・題からの補完の3つとも同じ関数を通す
  - **キーは要らない**。データはCCライセンスなので、画面のフッターに出典が出る（`#foot-sources` が自動）
  - **聞く回数を減らす作り**（2026-09-20）。VocaDBの決まりに「1日数千件の問い合わせには事前の許可が要る」とあり、
    本番は2時間で118〜215件（1日1,500〜2,500件）とその線に近かった。問い合わせを送る前に次の3つを入れた
    - **曲名だけで引き、アーティストでの絞り込みは手元で行う**（`query_key` / `narrow`、`main.py` の
      `_source_key` / `_narrow`）。**控えとキャッシュの鍵もその語にする**ので、「メルトryo」と
      「メルトsupercell」はVocaDBへ1回しか聞かない。ほかのソースは今までどおり（曲名とアーティストをそのまま）
    - **表記の揺れをそろえてから送る**（NFKC＋casefold＋ 続く空白をまとめる）。「ｼｬﾙﾙ」と「シャルル」、
      「Tell Your World」と「tell  your world」が1回にまとまる。**記号は落とさない**
      （`merge._n` は落とすが、送る語が変わればVocaDBの結果も変わりかねない）
    - **作者名の控え（動画ID・題）をR2にも置く**（`searchcache` の擬似ソース `vocadb-pv` / `vocadb-title`、6日）。
      メモリの控えは1日もつが**デプロイのたびに消える**ので、同じマイリストを貼り直すたびに聞き直していた。
      **見つからなかった分（空文字）も覚える**（転載・未登録の動画のほうが多い）
    - 回数は `[vocadb]` 行に種類ごとに出す（`CALLS` / `take_calls`。`search` / `pv` / `title` と、覚えていた
      `*_mem` / `*_r2`）。点検の要約に「1日に直すと約N」として出る。**語そのものは数えない**
  - ソースを足すときに触る所: `backend/sources/<名前>.py`、`backend/models.py` の `Source`、
    `backend/main.py` のimportと `SOURCES`、frontendの `SOURCE_LABEL` / `ALL_SOURCES` / `SOURCE_ORDER`、
    バッジのCSS、ソースの説明（`#src-modal`）とEN表
- 消えた動画（削除・非公開）はotoDBで埋める。otoDBのサムネイルは元動画が消えてもCDNに残るため
  - **「その動画が消えているか」はotoDBのAPIだけで分かる**。`/api/work/sources?work_id=N` が返す
    `work_status` が **1なら削除済み**（生きているものは0）。`platform` は1=YouTube / 2=ニコニコ。
    roxyを1件ずつ叩かなくても復活のデモに使える動画を探せるので、**候補探しではroxyを叩かない**
    （検索 `/api/work/search?query=…&limit=30` → workごとにsources、で足りる）
  - **「有名 × 削除済み」は珍しい**。転載の多い作品は誰かが再アップし続けるので生き残り、
    消えるのは1本しか上がっていない作品が多い。2026-09-14に75 workを調べて、
    ソースが5件以上あって削除済みを含むのは1件だけだった（動画の素材探しの結論は `video-notes.md`）
  - **roxyが未登録の動画を各サイトから取りに行くのはニコニコだけ**（2026-09実測）。YouTube / bilibili /
    SoundCloudは生きているURLでも404 `Cannot fallback` になる。otoDBに登録済みの作品なら
    他のサイト出典でも引ける可能性はあるが未確認。SoundCloud対応を足すならここが確認できてから
  - **roxyの応答にはCache-Controlが無い**ので、結果を `cache.sqlite3` のsearchテーブルに
    擬似ソース `roxy`（`otodb.ROXY_CACHE`）として1日覚える。**見つからなかった分も空リストで覚える**
    （消えた動画の大半はotoDBにも無く、そちらのほうが多い）。同じプレイリストを貼り直してもroxyを叩かない
  - roxyはもともと「人が表計算に1件ずつ貼る」ような使われ方を想定した小さなサービスで、公開サイトから
    まとめて自動で叩くうちは例外的。**`playlist._ROXY_SEM` はモジュール変数にしてプロセス全体で1つ持つ**
    （リクエストごとに作ると、同時にn人がプレイリストを貼ったときにn倍の並列で殴ることになる）。
    利用者が何人いてもroxyから見た同時接続は既定3（`ROXY_CONCURRENCY` で変更可）
- otoDBのAPIは**匿名のGETを60秒キャッシュする**（otoDB側 `middleware.py` の `AnonymousReadOnlyCacheMiddleware`）。
  実測で初回364〜597ms、2回目以降29〜33ms。`Cache-Control: max-age=60` が返る。ログインしないので常にこの対象。
  画像は `cdn.otodb.net`（CDN）なのでオリジンには行かない。検索は `offset` でページングできる
  （1ページ30件が上限。31以上の `limit` は422。`otodb.PAGE` / `MAX_PAGES`）
  - **配信元の一時的な不調は1回だけ引き直す**（2026-09-21、`otodb.RETRY_STATUS` / `RETRY_WAIT` / `_get`）。
    点検の2時間で64回中5回が503 / 521で落ちていて（1日に直すと約60回）、そのたび検索結果から
    otoDBが丸ごと抜けていた。521はCloudflareの「配信元が応答しない」で、数百ミリ秒で戻ることが多い。
    0.5秒待って1回だけ。2回目も駄目なら今までどおり失敗扱い（利用者の待ちを伸ばさない）。
    **roxy（`roxy_fetch`）はこの `_get` を通さない**。プレイリストの穴埋めで24件まとめて呼ぶので、
    落ちている相手に要求を倍にしたくないのと、全体10秒で打ち切る側の待ちを増やさないため
  - 単体URL … `fromurl.fetch` が直接取得に失敗したらroxyに聞く（`_ROXY_FALLBACK`）。`sm12345` や `BV…` のような
    IDだけの貼付は `fromurl.normalize()` がそのサイトのURLに組み立ててから同じ流れに乗せる。
    **IDをそのままroxyに投げてはいけない**（roxyが扱えるのはニコニコだけなのでBV… とYouTubeの11文字は必ず失敗し、
    毎回roxyへの無駄打ちになる。以前はそうなっていた）
  - プレイリスト … **こちらは失敗しない**。ニコニコのマイリストAPIは消えた動画にも「削除された動画」という
    タイトルと決まったサムネイル（黒地に×印のテレビ）を付けて返すため、例外にならず素通りする。`playlist.is_gone()` で
    決まり文句のタイトルを見つけ、`_fill_from_otodb()` がroxyで差し替える（並び順は変えない。
    リンク先は元の動画のまま残す）。roxyは1件ずつ各サイトへ取りに行くので、上限24件・並列6・全体25秒で打ち切る

- **英語の画面ではiTunesの曲名・アーティスト名を米国のストアの表記にする**（`itunes.to_english` とfrontendの
  `itunesEnglish`、2026-09-17。海外の利用者の共有が増えたため）。「マリーゴールド / あいみょん」→「Marigold / Aimyon」
  - **検索と絞り込みは日本のストアのまま**。米国のストアで検索すると、無い曲がある（「ずっと真夜中でいいのに 秒針を噛む」は
    カラオケ版が先頭）うえ、日本語の入力と英語表記が合わず絞り込みで候補から消える
  - 見つかった曲のID（trackViewUrlの `i=`）をまとめて `lookup?country=US` に **1回だけ**問い合わせ、表記があるものだけ
    差し替える（IDで引くので、米国の検索では出なかったZUTOMAYOも英語表記になる）。無い曲・失敗は日本語のまま
  - サーバー経由（`/search?lang=en`）はキャッシュ済みの結果にも効く（IDをURLから取るため）。キャッシュの鍵は変えていない
  - **言語を切り替えても、出ている候補は取り直さない**（次の検索から効く）
- **検索は既定でiTunesだけ**（2026-09-15から）。MusicBrainzは「1秒に1リクエスト」の制限があり、
  常に一緒に引くと検索が2秒かかっていた（iTunesだけなら0.06〜0.5秒。本番実測2052ms → 58ms）。
  **見つからなかったときだけMusicBrainzで引き直す**ので、iTunesに無い音源の取りこぼしは埋まる
  - サーバー（`main.py` の `DEFAULT_SOURCES` / `FALLBACK_SOURCE`）: `source` の指定が無くて0件ならMusicBrainz。
    **指定があるときは足さない**（利用者が選んだ通りに返す）
  - 画面（`frontend/index.html`）: 選んだソースで0件かつ失敗も無いときだけMusicBrainzを直接引き、
    「iTunesに無かったのでMusicBrainzでも探しました。」と添える
  - 画面のソース選択の既定は前からiTunesだけだったので、**遅かったのは `source` を省く呼び出し**（CLI・API）

## Spotifyのアーティスト名をiTunesで補う（2026-09-24）

本番はSpotifyの鍵を入れていない（開発者登録にPremiumが要る。`backend/sources/spotify.py`）ので、URLを貼っても
公式oEmbedの曲名とジャケットだけで、アーティスト名が空になる。9/23にWeb APIの課金を検討して見送り
（戻るのはアーティスト名・640px・プレイリスト一括だけ。640pxはマスに要らない）、代わりにブラウザで補うことにした。

- 画面（`frontend/index.html` の `spotifyArtistNames` / `askSpotifyArtist`）が、曲名で **iTunesをブラウザから直接**引き、
  曲名が `nkey()` でぴったり合う曲のアーティスト名を集める。サーバーは通さない（iTunesの上限はIPごとなので、利用者の端末に散らす）
- **1人なら入れる**（「iTunesで同じトラック名のものから補いました。違っていたら直してください」と添える）。
  **2人以上なら勝手に選ばない**。1件だけ貼ったときに限り、メッセージにアーティスト名のボタンを最大4つ並べる。
  押すと候補と、もうマスに入れていた同じURLの曲（アーティスト名が空のもの）の両方に入る
- 「曲名 - Remastered 2011」のようなSpotifyの添え書きは「 - 」の前でも突き合わせる
- アルバムのURLは題がアルバム名なので引かない。まとめて貼ったときは先頭5件を3秒おき（iTunesは約20回/分）
- CLI（`cli.py add --url`）はサーバーの `/from-url` を使うので補わない（空のまま）

## bilibili（2026-09-24、otoDBとVocaDB経由）

bilibiliの規約4.2.11は自動取得に書面許可を求め、`api.bilibili.com` もrobots.txtで全面Disallowなので、
**bilibiliには一度も問い合わせない**。動画のURL（`www.bilibili.com/video/BV…` / `av…`、IDだけも可）が貼られたら:

1. BVとavを手元で相互に変換する（`video.bv_to_av` / `av_to_bv`。決まった計算。`av170001` ↔ `BV17x411w7KC` で確かめた）
2. **otoDB（roxy）** に `https://www.bilibili.com/video/<BV>` を渡す。登録済みなら題・サムネイル（otoDBのCDN）・作者。
   音MAD・YTPMV・鬼畜はここで取れる。roxyはavを受けない（400）。未登録は404 "Cannot fallback"（roxyもbilibiliに取りに行かない）
3. **VocaDB** の `songs/byPv?pvService=Bilibili&pvId=<av番号>`（`vocadb.song_by_pv`）。ボカロなど。
   ジャケットは曲の代表サムネイルで、**hdslb（bilibiliのCDN）の画像しか無ければ使わず、見つからなかった扱い**。
   見つからなかった分も、メモリとR2（`vocadb-song`）に14日覚える
4. どちらにも無ければ「手入力で…」の案内

- 短縮URL（`b23.tv`）は展開にbilibiliへの問い合わせが要るので断る（「開いたあとのURLを貼って」）
- 収藏夹（まとめ）は中身をbilibiliに聞かないと分からないので、今までどおり読み込まない
- リンク先（`external_url`）は `https://www.bilibili.com/video/<BV>` に揃える

## 曲名の正規化（`merge.py` の `_n()` とfrontendの `nkey()`）

CLAUDE.mdの「二重実装の一覧」から移した（2026-09-25）。

- 曲名の正規化: `backend/merge.py` の `_n()` とfrontendの `nkey()`。
  **Pythonの `casefold()` は ß をssに畳むがJSの `toLowerCase()` は畳まない**ので手で合わせてある。
  **単独の濁点・半濁点（゛゜）は結合文字に置き換えてからNFKC**（「ハ゛」→「バ」。NFKCだけでは合成されない）
