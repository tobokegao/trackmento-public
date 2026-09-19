"""サイトの文章のページ（使い方・プライバシーポリシー・運営者・更新情報）。

2026-09-18 に AdSense の審査に通らなかった（理由は示されない）ため足した。道具の画面だけでは
「完全な文章や段落」と言える文章がほとんど無く、プライバシーポリシーも同じドメインに無かった。

- 見た目と言語の決め方は共有ページと同じ（`share._page_css`、`?lang=` と Accept-Language）
- **JavaScript を使わない**。文章だけのページなので、検索エンジンにもそのまま読める（noindex は付けない）
- 保持日数などの数字は設定から差し込む（`config.share_retention_days()`）。文章に焼き付けない
"""
from __future__ import annotations

import html
import re

from backend import share
from backend.config import share_retention_days

TITLES = {
    "guide": {"ja": "使い方", "en": "How to use"},
    "privacy": {"ja": "プライバシーポリシー", "en": "Privacy policy"},
    "about": {"ja": "運営者・お問い合わせ", "en": "About & contact"},
    "updates": {"ja": "更新情報", "en": "Updates"},
}
NAV = {"ja": ("画面へ戻る", "使い方", "プライバシーポリシー", "運営者", "更新情報"),
       "en": ("Back to the app", "How to use", "Privacy policy", "About", "Updates")}
UPDATED = {"ja": "最終更新: 2026年9月18日", "en": "Last updated: September 18, 2026"}
OFFICIAL = "https://tobokegao.github.io/ja/about/", "https://tobokegao.github.io/about/"


def _guide(lang: str, days: int) -> str:
    if lang == "en":
        return f"""
<p>TRACKMENTO is a tool that lays out the artwork (cover art) of your favourite tracks in a grid and turns it into a single image.
You can make images like “9 tracks that made me” by combining tracks from many different music sites, whether or not you
subscribe to a streaming service. Its distinguishing feature is that you can arrange music freely <b>track by track</b>, not only
album by album. It is completely free, and no sign-up is required.</p>

<h2>How to make a grid</h2>
<ol class="steps">
<li><b>Set the number of cells:</b> Choose how many cells go down and across (up to 32 per side, 256 cells in total).</li>
<li><b>Pick a cell and find a track:</b> Tap (or click) a cell and search by track title or artist name. Besides the standard
iTunes search, you can switch to MusicBrainz, VocaDB (Vocaloid songs) or otoDB (otomad works).</li>
<li><b>Add directly from a URL:</b> You can paste links from Bandcamp, SoundCloud, YouTube, Niconico, bilibili, Spotify and
Apple Music. If a track has no cover, you can fill it in with an image URL or by uploading an image from your device.</li>
<li><b>Rearrange:</b> Select two cells one after the other to swap their positions. “Enlarge” shows the grid full-screen,
so rearranging stays comfortable even with many cells.</li>
<li><b>Export and share the image:</b> Choose the aspect ratio (1:1, 4:5, 16:9, 9:16 or no fixed ratio), the background colour
and how the track list is shown, then share. You get the finished image and a dedicated share URL.</li>
</ol>

<h2>Handy features</h2>
<ul>
<li><b>Import whole playlists:</b> Paste a single playlist, mylist or set URL to load up to 500 tracks at once.
Tracks that don't fit in the grid stay in the candidate list.</li>
<li><b>Automatic recovery of deleted videos:</b> Even if a Niconico video has been deleted, TRACKMENTO automatically restores the
official title, creator name and thumbnail when the work is registered in otoDB (the otomad database).</li>
<li><b>Three track list styles:</b> Choose from “beside the grid”, “on the covers” or “hidden”. When cells are too small and the
text would be unreadable, the “on the covers” style turns off automatically.</li>
<li><b>Colour palettes:</b> Switch the colour theme of the whole screen. You can also create your own set of eight colours, copy
the colour codes and share them with others.</li>
<li><b>Everyone's grids:</b> If you turn on “Add to everyone's grids” when sharing, other users can find your grid by track title or
artist name (shares without the check are not listed).</li>
<li><b>Japanese and English:</b> Switch the language with the button at the top right of the screen. In English, iTunes track
information is also fetched as it appears in the US store.</li>
</ul>

<h2>Data storage and retention</h2>
<p>Data you are editing is saved in your browser, and a backup is temporarily kept on the server so that you can resume your work.
Images and share pages created with the share feature are deleted automatically {days} days after they are created. For details,
please see the <a href="/privacy?lang=en">privacy policy</a>.</p>

<h2>FAQ</h2>
<dl>
<dt>Is it free? Do I need to register?</dt>
<dd>Everything is free and no account is required. Note that ads may be shown to help cover the cost of running the servers.</dd>
<dt>I want to revise a grid I already shared.</dt>
<dd>Press “Open in TRACKMENTO” on the share page to load that layout into the editor. Make your changes, then share it again.</dd>
<dt>A cover image doesn't show up.</dt>
<dd>The image may have been deleted or made private by the original site. In that case, specify an image URL or set an image from
your device manually.</dd>
<dt>What about the rights to the cover art?</dt>
<dd>Copyright and other intellectual property rights in the artwork and track titles belong to the respective artists and rights
holders. TRACKMENTO displays images that each music platform provides through its API or similar means, so that users can introduce
and share the music they love. When sharing, please follow the terms of use and guidelines of each service.</dd>
</dl>
"""
    return f"""
<p>TRACKMENTO（トラックメント）は、好きな曲のアートワーク（ジャケット写真）を格子状に並べて1枚の画像にするツールです。「私を構成する9曲」のような画像を、サブスクリプションへの加入有無に関わらず、さまざまな配信サイトの曲を組み合わせて作成できます。アルバム単位だけでなく、<b>曲単位</b>で自由に並べられるのが特徴です。完全無料で、会員登録も不要です。</p>

<h2>並べ方</h2>
<ol class="steps">
<li><b>マスの数を決める：</b>縦・横のマスの数を指定します（1辺最大32マス、合計256マスまで対応）。</li>
<li><b>マスを選んで曲を探す：</b>マスをタップ（クリック）して曲名やアーティスト名で検索します。標準のiTunes検索のほか、MusicBrainz、VocaDB（ボカロ曲）、otoDB（音MAD）に切り替えて探すこともできます。</li>
<li><b>URLから直接追加する：</b>Bandcamp、SoundCloud、YouTube、ニコニコ動画、bilibili、Spotify、Apple Musicのリンク貼り付けに対応しています。ジャケットがない曲は、画像URLの指定や端末内の画像アップロードで補えます。</li>
<li><b>並べ替える：</b>2つのマスを順番に選ぶと位置が入れ替わります。「大きく見る」でグリッドを全画面表示にすると、マス数が多い場合でも快適に並べ替えができます。</li>
<li><b>画像を出力・共有する：</b>画像の比率（1:1、4:5、16:9、9:16、比率固定なし）、背景色、曲名リストの表示形式を選んで共有すると、完成画像と専用の共有URLが発行されます。</li>
</ol>

<h2>便利な機能</h2>
<ul>
<li><b>プレイリストの一括読み込み：</b>プレイリスト、マイリスト、セットリストなどのURLを1つ貼るだけで、最大500曲を一気に読み込みます。マスに入り切らなかった曲は候補リストに残ります。</li>
<li><b>削除動画の自動補完：</b>ニコニコ動画で削除済みの動画であっても、otoDB（音MADデータベース）に登録があれば、正式なタイトル・作者名・サムネイルを自動で復元・補完します。</li>
<li><b>選べる3種類の曲名リスト：</b>曲名リストは「グリッドの横に並べる」「ジャケットに重ねる」「表示しない」の3通りから選択可能です。マスが小さく文字が潰れてしまう場合は、重ねる表示が自動でオフになります。</li>
<li><b>カラーパレット：</b>画面全体の配色テーマを切り替えられます。好みの8色セットを自作してカラーコードをコピーし、他の人と共有することも可能です。</li>
<li><b>みんなのグリッド：</b>共有時に「みんなのグリッドに載せる」を有効にすると、他のユーザーが曲名やアーティスト名からあなたのグリッドを探せるようになります（チェックを外した共有は一覧に載りません）。</li>
<li><b>日本語・英語対応：</b>画面右上のボタンから言語を切り替えられます。英語表示時は、iTunesの楽曲情報もUSストアの表記で取得されます。</li>
</ul>

<h2>データの保存と保持期間</h2>
<p>編集中のデータはお使いのブラウザに保存され、作業を再開できるようサーバー側にもバックアップが一時保持されます。共有機能で生成された画像および共有ページは、作成から{days}日が経過すると自動的に削除されます。詳しくは<a href="/privacy">プライバシーポリシー</a>をご確認ください。</p>

<h2>よくある質問</h2>
<dl>
<dt>無料で使えますか？ 登録は必要ですか？</dt>
<dd>すべて無料で、アカウント登録も不要です。なお、サーバーの運用費をまかなうために広告を表示する場合があります。</dd>
<dt>共有したグリッドを後から手直ししたいです。</dt>
<dd>共有ページにある「TRACKMENTOで開く」を押すと、その配置がエディタに読み込まれます。修正を行ったうえで、再度共有を行ってください。</dd>
<dt>ジャケット画像が表示されません。</dt>
<dd>配信元で画像が削除・非公開になっている可能性があります。その場合は、画像URLを指定するか、端末内の画像を手動で設定してください。</dd>
<dt>ジャケット写真の権利関係はどうなっていますか？</dt>
<dd>アートワークや曲名の著作権・知的財産権は、それぞれのアーティストや権利者に帰属します。TRACKMENTOは、利用者が好きな音楽を紹介・共有する用途のために、各配信プラットフォームがAPI等で提供している画像を表示しています。共有の際は、各サービスの利用規約やガイドラインに従ってご利用ください。</dd>
</dl>
"""


def _privacy(lang: str, days: int) -> str:
    if lang == "en":
        return f"""
<p>This policy sets out how TRACKMENTO (https://trackmento.com, “the Site”) handles user information.</p>

<h2>1. Information the Site stores</h2>
<ul>
<li><b>Grid editing data:</b> The tracks placed in cells, the title and the display/output settings are saved in your browser
(local storage). To let you restore your session, a temporary backup is also kept on the server, linked to a random ID issued for
each browser. It contains no personally identifying information such as your name or email address.</li>
<li><b>Shared images and share pages:</b> When you share, the image data and layout data are stored on Cloudflare R2. This data is
permanently deleted automatically {days} days after it is created.</li>
<li><b>Images uploaded from your device:</b> These are resized appropriately and stored after removing metadata such as location
information (Exif).</li>
<li><b>Everyone's grids:</b> Only data you have allowed to be listed (opted in) when sharing is stored and made searchable within the Site.</li>
</ul>

<h2>2. Access logs</h2>
<p>For stable operation and maintenance, the server records the number of requests and response times for each type of request. Your browser also reports the kind and number of problems it runs into, such as a failed image upload or render, so we can count them (no track names, search terms, or URLs are included).
To prevent abuse, limit rapid repeated requests and manage the daily share limit, IP addresses are converted into an irreversible
(hashed) form and used only temporarily. Search keywords, the full text of URLs you enter and raw browser User-Agent strings are not
kept. Only broad categories (for example, whether an access is by a person or by a URL preview bot) and statistics on referring
domains (host names) are aggregated.</p>

<h2>3. Communication with external services</h2>
<p>When searching for or retrieving track and cover information, the search terms and URLs you enter are sent to the relevant external
services (for example, the Apple iTunes Search API, MusicBrainz / Cover Art Archive, VocaDB, otoDB, Bandcamp, SoundCloud, YouTube,
Niconico, bilibili and Spotify). Some searches are sent directly from your browser to these APIs. Information sent is handled under
each platform's privacy policy.</p>
<p>The Site's server infrastructure runs on Render, and Cloudflare is used to deliver and cache shared files.</p>

<h2>4. Cookies and advertising</h2>
<p>The Site itself does not use its own cookies (settings are saved in your browser's local storage).</p>
<p>The Site uses (or plans to use) Google AdSense, a third-party advertising service. Third-party vendors, including Google, use
cookies to serve ads based on a user's prior visits to this website or other websites.</p>
<p>You can opt out of personalised advertising in Google's <a href="https://www.google.com/settings/ads" rel="noopener">Ads Settings</a>.
You can also opt out of third-party vendors' use of cookies by visiting <a href="https://www.aboutads.info/" rel="noopener">www.aboutads.info</a>.
For details, please see <a href="https://policies.google.com/technologies/ads" rel="noopener">Google's Privacy &amp; Terms</a>.</p>

<h2>5. Requests to delete data</h2>
<p>You can reset your working data at any time by using “Clear all cells” in the editor or by deleting (clearing) this site's data in
your browser. Shared data is erased automatically after {days} days; if you would like it removed before then, please contact the
operator (see <a href="/about?lang=en">About &amp; contact</a>) with the share URL.</p>

<h2>6. Changes to this policy</h2>
<p>This privacy policy may be revised without notice in response to changes in law or to additions and changes in the service's features.
The latest version is always published on this page.</p>
"""
    return f"""
<p>TRACKMENTO（https://trackmento.com、以下「当サイト」）における利用者情報の取り扱いについて、以下のとおり定めます。</p>

<h2>1. 当サイトが保存する情報</h2>
<ul>
<li><b>グリッドの編集データ：</b>マスに配置した曲、タイトル、表示・出力設定は、お使いのブラウザ（ローカルストレージ）に保存されます。また、セッションを復元できるようにするため、ブラウザごとに発行されるランダムなIDと紐づけてサーバーにも一時バックアップを保持します。氏名、メールアドレス等の個人を特定する情報は一切含みません。</li>
<li><b>共有画像および共有ページ：</b>共有を実行した際、画像データおよび配置データをCloudflare R2に保存します。これらのデータは生成から{days}日後に自動で完全削除されます。</li>
<li><b>端末からアップロードされた画像：</b>適切なサイズへのリサイズを行い、位置情報などのメタデータ（Exif）を削除したうえで保存します。</li>
<li><b>みんなのグリッド：</b>共有時に掲載を許可（オプトイン）されたデータに限り、当サイト内の検索対象として公開・保存されます。</li>
</ul>

<h2>2. アクセスログの収集について</h2>
<p>サービスの安定運用・保守のため、サーバーはリクエスト種別ごとの件数および応答時間を記録しています。また、画像の送信や作成の失敗といった、ブラウザ側で起きた不具合の種類と回数をサーバーに送って集計しています（曲名・検索語・URL などの内容は含みません）。不正アクセス防止や連続リクエストの制限、1日の共有上限管理のため、IPアドレスは不可逆な形式（ハッシュ化）に変換したうえで一時的に利用します。検索キーワード、入力されたURLの全文、ブラウザのUser-Agentそのものは恒常的に記録しません。「人間によるアクセスか」「URLプレビューボットか」といった大まかな種別、および参照元ドメイン（ホスト名）の統計のみを集計します。</p>

<h2>3. 外部サービスとの通信</h2>
<p>楽曲やジャケットの情報を取得・検索する際、入力された検索語句やURLを各外部サービスに送信します（例：Apple iTunes Search API、MusicBrainz / Cover Art Archive、VocaDB、otoDB、Bandcamp、SoundCloud、YouTube、ニコニコ動画、bilibili、Spotify）。一部の検索処理は、ブラウザから直接これらのAPIへリクエストを送信します。送信された情報は、各プラットフォームのプライバシーポリシーに従って管理されます。</p>
<p>また、当サイトのサーバーインフラにはRenderを採用しており、共有ファイルの配信・キャッシュにはCloudflareを利用しています。</p>

<h2>4. Cookieおよび広告配信について</h2>
<p>当サイト本体は独自のCookieを使用していません（設定データはブラウザのローカルストレージに保存されます）。</p>
<p>当サイトでは、第三者配信の広告サービス「Google AdSense」を利用（または利用を予定）しています。Googleなどの第三者配信事業者は、Cookieを使用し、ユーザーが当サイトや他のウェブサイトに過去にアクセスした際の情報に基づいて広告を配信します。</p>
<p>ユーザーは、Googleの<a href="https://www.google.com/settings/ads" rel="noopener">広告設定</a>からパーソナライズ広告を無効にできます。また、<a href="https://www.aboutads.info/" rel="noopener">www.aboutads.info</a>にアクセスすることで、第三者配信事業者のCookie使用を無効化できます。詳細につきましては、<a href="https://policies.google.com/technologies/ads?hl=ja" rel="noopener">Googleポリシーと規約</a>をご確認ください。</p>

<h2>5. データの削除依頼</h2>
<p>作業中のデータは、エディタ上の「マスを全部外す」を実行するか、ブラウザのサイトデータを削除（クリア）することでいつでも初期化できます。共有済みのデータは{days}日後に自動消去されますが、期限前の早期削除をご希望の場合は、該当の共有URLを明記のうえ、<a href="/about">運営者連絡先</a>までご連絡ください。</p>

<h2>6. ポリシーの改定</h2>
<p>本プライバシーポリシーは、法令の改正やサービスの機能追加・変更に応じて予告なく改定されることがあります。常に最新の内容を本ページに掲載します。</p>
"""


def _about(lang: str, days: int) -> str:
    ja_url, en_url = OFFICIAL
    if lang == "en":
        return f"""
<p>TRACKMENTO is developed and run by <b>Tobokegao</b>, a chiptune artist who has been composing with the Game Boy since 2014.
Tobokegao runs the independent label TBKgao and contributed the song “Nouveau Monde” to <i>YARS RISING</i> for Nintendo Switch,
among other work.</p>
<p>TRACKMENTO began as a personal tool for making “tracks that made me” images that include works not available on streaming
services, such as Vocaloid songs, otomad and doujin music, and was later released to the public as a web service.</p>

<h2>Contact</h2>
<p>For questions, bug reports or requests to delete shared data, please use the contact details listed on the
<a href="{en_url}" rel="noopener">official site</a>. When asking about shared data, please be sure to include the share URL.</p>

<h2>Supporting development and operation</h2>
<p>Anyone can use TRACKMENTO for free. If you would like to support the server costs and continued development, buying or listening to
music on <a href="https://tbkgao.bandcamp.com/album/okane-ga-tarinai-toki-no-uta?from=trackmento" rel="noopener noreferrer">Bandcamp</a>
would be a great encouragement.</p>

<h2>Data sources and attribution</h2>
<p>Track information shown in this service is obtained from the iTunes Search API, MusicBrainz, Cover Art Archive, VocaDB (CC BY 3.0),
otoDB and the music sites of the links you enter. TRACKMENTO is not affiliated with these services or their operators.</p>
"""
    return f"""
<p>TRACKMENTO は <b>Tobokegao（とぼけがお）</b>が開発・運営しています。2014年よりゲームボーイを用いた作曲活動を行っているチップチューンアーティストで、自主レーベル「TBKgao」の主宰や、Nintendo Switch用ソフト『YARS RISING』への楽曲提供（「Nouveau Monde」）などを手がけています。</p>
<p>ボカロ曲や音MAD、同人音楽など、サブスクリプションサービスでは配信されていない作品も含めて「私を構成する曲」の画像を作りたい、という自分用のツール開発からスタートし、Webサービスとして一般公開しました。</p>

<h2>お問い合わせ</h2>
<p>ご質問、不具合のご報告、共有データの削除依頼などは、<a href="{ja_url}" rel="noopener">公式サイト</a>に記載の連絡先よりお願いいたします。共有データに関するお問い合わせの際は、必ず対象の共有URLを添えてご連絡ください。</p>

<h2>開発・運営のサポートについて</h2>
<p>TRACKMENTO はどなたでも無料でご利用いただけます。サーバー代や開発の継続をご支援いただける方は、<a href="https://tbkgao.bandcamp.com/album/okane-ga-tarinai-toki-no-uta?from=trackmento" rel="noopener noreferrer">Bandcamp</a>にて楽曲をご購入・ご試聴いただけますと大きな励みになります。</p>

<h2>データの出典・権利表記</h2>
<p>本サービスで表示される楽曲情報は、iTunes Search API、MusicBrainz、Cover Art Archive、VocaDB（CC BY 3.0）、otoDB、ならびに入力されたリンク先の各配信サイトから取得しています。TRACKMENTO は、これらのサービスおよび運営元と提携関係にあるものではありません。</p>
"""


# ---- 更新情報（2026-09-19）----
# **利用者に見える変化だけ**を、日付と 1〜2 行で書く（内部の直し・点検の話は書かない）。新しいものを先頭に足す。
# 「検討中」の一覧は置かない（一人で運営しているので、約束に見えるものを増やさない）
CHANGES: list[tuple[str, str, str]] = [
    ("2026-09-19", "スマートフォンでの共有画像の容量を最適化し、アップロードにかかる時間を約3割短縮しました（X等のSNSでの見た目はほぼ変わりません）。",
     "Share images made on phones are now smaller, cutting upload time by about 30% (they look almost the same on X and other social media)."),
    ("2026-09-19", "ニコニコ動画で投稿者名が取得できない曲（退会・非公開・転載動画など）について、VocaDBのデータから作者名を自動補完するようにしました。",
     "For Niconico videos whose uploader name is unavailable (deleted or private accounts, re-uploads and so on), the producer name is now filled in automatically from VocaDB."),
    ("2026-09-19", "VocaDBの作者名からレーベルやチャンネル等の表記を除外し、「kz feat. 初音ミク」のようにすっきりとしたアーティスト名で表示するようにしました。",
     "VocaDB artist names no longer include labels or channels, so they read cleanly, e.g. “kz feat. Hatsune Miku”."),
    ("2026-09-19", "曲名とアーティスト名を1行で並べるとき、アーティスト名だけが不自然に次行へ改行されないようレイアウトを調整しました。",
     "When a track’s title and artist share one line, the artist no longer drops awkwardly onto the next line."),
    ("2026-09-19", "VocaDBの検索処理を改善し、アクセス集中時のタイムアウトが起きづらくなるようにしました。また、一度検索された曲はキャッシュにより次回以降すばやく表示されます。",
     "VocaDB searches are now less likely to time out when traffic is heavy, and songs that have been searched once come up quickly afterwards thanks to caching."),
    ("2026-09-19", "更新情報ページ（本ページ）を公開しました。",
     "Published this Updates page."),
    ("2026-09-18", "独自ドメイン（trackmento.com）へ移転しました。旧アドレスからアクセスした場合でも、作成中の配置を引き継いで自動転送されます。",
     "TRACKMENTO moved to its own domain, trackmento.com. Opening the old address forwards you automatically and brings your grid along."),
    ("2026-09-18", "曲名リストの表示形式を「横に並べる／マスに重ねる／表示しない」の3通りから選べるようにしました。「マスに重ねる」を選ぶと、ジャケットの下部に白文字で曲情報が表示されます。",
     "The track list can now be shown three ways: “Beside the grid”, “On the covers” or “Hidden”. “On the covers” puts the track info in white text along the bottom of each cover."),
    ("2026-09-18", "曲数が少ないときは、曲名とアーティスト名を1行に並べてアーティスト名を右端に揃えるレイアウトを追加しました。余白を減らし、文字が大きく見やすくなります。",
     "With fewer tracks, the title and artist now sit on one line with the artist aligned to the right, leaving less empty space and making the text larger and easier to read."),
    ("2026-09-18", "使い方ガイド、プライバシーポリシー、運営者情報の各ページを公開しました。",
     "Published the How to use, Privacy policy and About pages."),
    ("2026-09-17", "英語表示の場合、iTunesの曲名・アーティスト名をUSストアの英語表記で取得・表示するようにしました（例：「マリーゴールド / あいみょん」→「Marigold / Aimyon」）。",
     "In the English interface, iTunes titles and artists are shown as listed on the US store (e.g. “Marigold / Aimyon”)."),
    ("2026-09-17", "「マスを全部外す」を押した際、誤操作を防ぐ確認ダイアログを表示するようにしました。外してしまった後も「元に戻す」で復元できます。",
     "“Clear all cells” now asks for confirmation first, and you can still bring everything back with “Undo” afterwards."),
    ("2026-09-17", "曲名リストの描画を見直し、画像の縦幅を最大限使って文字を大きく配置するようにしました。",
     "The track list now uses the full height of the image so the text can be larger."),
    ("2026-09-16", "ボカロ曲データベース「VocaDB」からの楽曲検索に対応しました。サブスク未配信の楽曲も検索でき、原曲が上位にヒットしやすくなっています。",
     "You can now search VocaDB, the Vocaloid song database. It finds songs that aren’t on streaming services, with original songs ranked near the top."),
    ("2026-09-16", "「みんなのグリッド」機能を追加しました。共有時に許可のチェックを入れたグリッドのみ、曲名やアーティスト名から他のユーザーが閲覧・検索できます。",
     "Added “Everyone’s grids”. Only grids you tick to list when sharing can be found and viewed by others, by track or artist."),
    ("2026-09-16", "「大きく見る（全画面表示）」機能を追加しました。マス数が多い配置や細長いレイアウトでも、画面いっぱいに広げて快適に並べ替えられます。",
     "Added “Enlarge” (full screen). Grids with many cells or long, narrow layouts can be opened to fill the screen for easier rearranging."),
    ("2026-09-16", "BandcampのアルバムURLを貼り付けると、収録曲を各マスに一括で追加できるようになりました。",
     "Pasting a Bandcamp album URL now adds each of its tracks to the grid in one go."),
    ("2026-09-16", "カラーパレットを8色1組で管理できるようにし、画面全体の背景色ごと切り替えられるようにしました。暗い配色の「ナイト」も選べます。",
     "Colour palettes now come in sets of eight and switch the background of the whole interface too, including the dark “Night” palette."),
    ("2026-09-16", "画像共有時に、アップロードの進捗状況（プログレスバー）を表示するようにしました。途中でキャンセルすることも可能です。",
     "Sharing now shows an upload progress bar, and you can cancel partway through."),
    ("2026-09-16", "「マスを全部外す」ボタンを誤タップしづらい位置へ移動し、実行後も「元に戻す」で復元できるようにしました。",
     "Moved “Clear all cells” to a spot that’s harder to tap by mistake, and made it possible to undo."),
    ("2026-09-16", "長い曲名の自動折り返しを最大3行までに拡張し、文字が途中で省略（…）されづらくしました。",
     "Long titles now wrap onto up to three lines, so they are cut off with “…” less often."),
    ("2026-09-16", "1〜3列の並びでは、曲名リストを各マスの真横に同じ並び順で配置するようにしました。どのジャケットがどの曲か一目で視線移動できます。",
     "In grids one to three cells wide, each title now sits right beside its cell in the same order, so it’s easy to see which cover is which song."),
    ("2026-09-16", "完成画像のプレビューと保存を端末内（ローカル）で直接処理するように改善しました。通信状態が不安定な環境でも保存に失敗しづらくなります。",
     "The finished image is now previewed and saved directly on your device, so saving is less likely to fail on an unstable connection."),
    ("2026-09-15", "カラーパレット機能を追加しました。好みのパレットを自作でき、カラーコードをコピーして他の人と共有することも可能です。",
     "Added colour palettes. You can make your own and share it by copying its colour codes."),
    ("2026-09-15", "共有ページの曲名から、各配信元（YouTube、ニコニコ動画、Bandcampなど）の元ページへ直接リンクで飛べるようにしました。",
     "Track titles on share pages now link to their original pages (YouTube, Niconico, Bandcamp and so on)."),
    ("2026-09-15", "共有画像および共有ページの保存期間を、7日間から30日間に延長しました。",
     "Share images and share pages are now kept for 30 days instead of 7."),
    ("2026-09-15", "曲名リストを「曲名＋アーティスト名」の2行組みレイアウトに対応させました。曲数が多い場合は自動で列数を増やし、文字サイズを大きく保ちます。",
     "The track list now shows the title and artist on two lines. With many tracks it adds columns automatically to keep the text large."),
    ("2026-09-15", "正方形に近い比率で曲数が多い場合、曲名リストをグリッドの周りに回り込ませることで、ジャケット画像をできるだけ大きく表示できるようにしました。",
     "For near-square ratios with many tracks, the track list now wraps around the grid so the covers can be as large as possible."),
    ("2026-09-15", "1×8や32×1などの極端に細長いレイアウトでも、マスと曲名がきれいに収まるよう表示を最適化しました。",
     "Very long, narrow layouts such as 1×8 or 32×1 now fit the cells and titles neatly."),
    ("2026-09-15", "URLの末尾に「?lang=en」「?lang=ja」を付けることで、表示言語を直接指定できるようにしました。",
     "Adding “?lang=en” or “?lang=ja” to a URL now sets the display language."),
    ("2026-09-15", "スマートフォンでの誤操作を防ぐため、スライダー（余白・マスの間隔・色調など）はつまみを正しくドラッグした時のみ動くように改善しました。",
     "To prevent accidental changes on phones, sliders (margin, cell spacing, colour and so on) now move only when you drag the handle."),
    ("2026-09-14", "長い曲名が2行に折り返されるよう調整し、続くアーティスト名が見切れたり消えたりしないようにしました。",
     "Long titles now wrap onto two lines so the artist name that follows is no longer cut off or lost."),
    ("2026-09-14", "曲数が多い場合、曲名リストを文章のように連続して流し込み、画像内に無駄なく収めるレイアウトを追加しました。",
     "With many tracks, the track list can now flow continuously like running text to fit neatly in the image."),
    ("2026-09-13", "プレイリストURLの一括読み込みに対応しました（ニコニコ動画のマイリスト、SoundCloud、bilibili、Spotify、Bandcamp、YouTubeに対応、最大500曲まで）。",
     "You can now load a whole playlist from its URL (Niconico mylists, SoundCloud, bilibili, Spotify, Bandcamp and YouTube; up to 500 tracks)."),
    ("2026-09-13", "プレイリスト内の削除済み動画について、otoDB（音MADデータベース）の情報をもとに正式なタイトル・サムネイルを自動復元・補完するようにしました。",
     "Deleted videos in a playlist now get their proper title and thumbnail restored automatically from otoDB, the otomad database."),
    ("2026-09-13", "「URL を貼る」に、改行区切りで複数のURLをまとめて貼り付けて一括登録できるようにしました。",
     "“Paste a page URL” now accepts several URLs at once, one per line."),
    ("2026-09-13", "Apple MusicのURL（楽曲・アルバム・プレイリスト）に対応しました。",
     "Added support for Apple Music URLs (songs, albums and playlists)."),
    ("2026-09-13", "グリッドの上限を256マスに拡大し、16×16や自由な縦長・横長の配置を作れるようにしました。",
     "Grids can now have up to 256 cells, so you can make 16×16 or any tall or wide layout."),
    ("2026-09-13", "画面右上のボタンから英語表示への切り替えに対応しました。共有ページもアクセスした人のブラウザ言語に合わせて表示されます。",
     "The interface can now be switched to English with the button at the top right. Share pages follow the viewer’s browser language."),
    ("2026-09-11", "共有画像の生成処理をお使いの端末（ブラウザ側）で行うようにし、アクセス集中時でも画像生成が止まりづらくなるようにしました。",
     "Share images are now made on your device (in the browser), so making them is less likely to stall when traffic is heavy."),
    ("2026-09-11", "画像の既定比率をX（旧Twitter）に適した「16:9」に変更しました。Instagram投稿向けの「4:5」も選択可能です。",
     "The default image ratio is now 16:9, which suits X (formerly Twitter). 4:5 for Instagram posts is also available."),
    ("2026-09-11", "カスタムカラー設定に、色相・彩度・明度を微調整できるスライダーを追加しました。",
     "Custom colours now have hue, saturation and brightness sliders for fine-tuning."),
    ("2026-09-11", "共有ページ上に、ページの有効期限（掲載終了予定日）を表示するようにしました。",
     "Share pages now show when they will expire."),
    ("2026-09-09", "TRACKMENTOを一般公開しました。iTunes、MusicBrainz、Discogs、otoDBからの楽曲検索に加え、Bandcamp、SoundCloud、YouTube、ニコニコ動画、bilibili、SpotifyのURL貼り付けに対応。ジャケットが無い曲は手動で画像をアップロードして設定できます。",
     "TRACKMENTO launched. Search iTunes, MusicBrainz, Discogs and otoDB, or paste URLs from Bandcamp, SoundCloud, YouTube, Niconico, bilibili and Spotify. For tracks without a cover, you can upload an image yourself."),
]
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


def _date_label(date: str, lang: str) -> str:
    y, m, d = (int(x) for x in date.split("-"))
    return f"{_MONTHS[m - 1]} {d}, {y}" if lang == "en" else f"{y}年{m}月{d}日"


def _updates(lang: str, days: int) -> str:
    en = lang == "en"
    rows: list[str] = []
    last = None
    for date, ja, e in CHANGES:
        if date != last:
            if last is not None:
                rows.append("</ul>")
            rows.append(f"<h3>{_date_label(date, lang)}</h3><ul>")
            last = date
        rows.append(f"<li>{html.escape(e if en else ja)}</li>")
    if last is not None:
        rows.append("</ul>")
    changes = "\n".join(rows)
    if en:
        return f"""
<p>A list of new features, improvements and other changes to TRACKMENTO, along with problems we currently know about. We update it whenever we fix or release something.</p>
<h2>Recent changes</h2>
{changes}
<h2>Known problems</h2>
<ul>
<li><b>Old Niconico videos:</b> the source only has low-resolution images, so their covers may look blurry.</li>
<li><b>Covers of deleted videos:</b> deleted videos that aren’t registered on otoDB can’t have their thumbnail or other details restored.</li>
<li><b>Special characters:</b> titles with some unusual symbols (such as ◈) may be placed slightly differently in the image depending on your device and fonts.</li>
<li><b>In-app browsers:</b> in the browsers built into X, LINE and similar apps, sharing may be slow or fail. Reopening the page in a regular browser such as Safari or Chrome is more reliable.</li>
</ul>
<h2>If something doesn’t work</h2>
<ul>
<li><b>The page won’t open:</b> switch between Wi-Fi and mobile data, or try another browser. School or work networks may temporarily block newly registered domains with security filters.</li>
<li><b>Sharing takes a long time:</b> upload speed depends on your connection. Please try somewhere with good reception.</li>
<li><b>Still not solved:</b> please contact us using the details on the <a href="/about?lang=en">About</a> page, with the date and time, your device and browser, and what you were doing.</li>
</ul>
"""
    return f"""
<p>TRACKMENTO の機能追加・改善などの変更点や、現在確認されている不具合をまとめています。修正やアップデートを実施した際に随時更新します。</p>
<h2>最近の変更</h2>
{changes}
<h2>確認されている不具合</h2>
<ul>
<li><b>古いニコニコ動画の画質：</b>配信元の仕様により低解像度の画像しか存在しないため、ジャケット画像が粗く表示される場合があります。</li>
<li><b>削除済み動画のジャケット：</b>otoDBに登録のない削除済み動画は、サムネイル等の情報を復元できません。</li>
<li><b>特殊文字による表示のズレ：</b>一部の特殊な記号（◈ など）を含む曲名は、ご利用の端末やフォント環境によって画像内の文字位置がわずかにずれることがあります。</li>
<li><b>アプリ内ブラウザでの動作：</b>XやLINEなどのアプリ内ブラウザで開いている場合、画像の共有が遅くなったり失敗したりすることがあります。SafariやChromeなどの標準ブラウザで開き直すと安定します。</li>
</ul>
<h2>うまくいかないとき</h2>
<ul>
<li><b>ページが開けない場合：</b>Wi-Fiとモバイル回線を切り替えるか、別のブラウザでお試しください。学校や職場のネットワークでは、新設ドメインがセキュリティフィルターによって一時的に制限されている場合があります。</li>
<li><b>共有に時間がかかる場合：</b>画像の送信速度はお使いの通信回線に左右されます。電波状況の良い場所でお試しください。</li>
<li><b>それでも解決しない場合：</b><a href="/about">運営者ページ</a>記載の連絡先より、発生した日時・ご利用環境・具体的な操作内容を添えてお問い合わせください。</li>
</ul>
"""


BODIES = {"guide": _guide, "privacy": _privacy, "about": _about, "updates": _updates}

_JA_BREAK = re.compile(r"(?<=[^\x00-\x7f>])\n(?=[^\x00-\x7f<])")


def _updated_of(lang: str) -> str:
    """更新情報のページの「最終更新」は、いちばん新しい変更の日付"""
    label = _date_label(CHANGES[0][0], lang)
    return f"Last updated: {label}" if lang == "en" else f"最終更新: {label}"


def body_of(kind: str, lang: str) -> str:
    """ページの本文。**日本語の字と字のあいだの改行は詰める**（ソースの折り返しが、表示では余計な空白になる）"""
    b = BODIES[kind](lang, share_retention_days())
    return _JA_BREAK.sub("", b) if lang == "ja" else b


def page_html(kind: str, base: str, app_url: str | None = None, lang: str = "ja") -> str:
    lang = lang if lang in ("ja", "en") else "ja"
    app_url = (app_url or base).rstrip("/")
    title = TITLES[kind][lang]
    other = "en" if lang == "ja" else "ja"
    q = "?lang=en" if lang == "en" else ""
    back, n_guide, n_privacy, n_about, n_updates = NAV[lang]
    body = body_of(kind, lang)
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} — TRACKMENTO</title>
<meta name="description" content="{html.escape(title)} — TRACKMENTO">
<link rel="icon" href="/favicon.ico"><link rel="icon" type="image/png" href="/favicon.png" sizes="64x64"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="canonical" href="{base.rstrip('/')}/{kind}{q}">
<link rel="alternate" hreflang="ja" href="{base.rstrip('/')}/{kind}"><link rel="alternate" hreflang="en" href="{base.rstrip('/')}/{kind}?lang=en">
<style>{share._page_css(base)}
main {{ max-width: 44rem; }}
h3 {{ font-size: .95rem; margin: 12px 0 4px; }}
h2 {{ font-size: 1.05rem; margin: 20px 0 4px; padding-bottom: 2px; border-bottom: 2px solid #12171b; }}
p, dd {{ margin: 0; }}
main a {{ color: #12171b; }}
ul, ol.steps {{ margin: 0; padding-left: 1.4em; display: grid; gap: 6px; }}
ol.steps {{ list-style: decimal; }}
ol.steps li, ul li {{ display: list-item; }}
dl {{ margin: 0; display: grid; gap: 10px; }}
dt {{ font-weight: 700; }}
nav.pages {{ display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: .9rem; }}
nav.pages a {{ color: #12171b; }}
</style></head>
<body>
<header><a class="mark" href="{app_url}/" style="color:inherit;text-decoration:none">TRACKMENTO</a></header>
<main>
  <h1>{html.escape(title)}</h1>
  {body}
  <p class="meta">{_updated_of(lang) if kind == "updates" else UPDATED[lang]} ・ <a href="/{kind}{'?lang=' + other if other == 'en' else ''}">{'English' if other == 'en' else '日本語'}</a></p>
  <nav class="pages"><a href="{app_url}/{q}">{back}</a><a href="/guide{q}">{n_guide}</a><a href="/privacy{q}">{n_privacy}</a><a href="/about{q}">{n_about}</a><a href="/updates{q}">{n_updates}</a></nav>
</main>
</body></html>"""
