# metrics/

点検（`scripts/render_check.py --append metrics/series.jsonl`）が 1 回につき 1 行ずつ書き足す記録。
GitHub Actions の `render-check.yml` が 2 時間おきに走り、この 1 行を commit する。

- **Render のログは日が経つと消える**ので、あとから推移を描くにはここに残しておくしかない
- 1 行の中身: 時刻（JST）・窓の長さ・要求数・帯域 GB・5xx・rss・CPU・本日の共有数・外へ出した要求（ホスト別）・
  ソースごとの検索・VocaDB へ聞いた回数・ブラウザ側の失敗・異常の数
- `gb` は `/metrics/bandwidth`（HTTP 応答だけらしい）。**2026-10-21 から `gb_src`（経路別: http / nat=サービス発 / privatelink / websocket）も書く**。
  請求は経路の合計なので、ボードの帯域と月の見込みは `gb_src` の合計を使う（無い古い行は `gb`）
- **語や URL は入れない**（ホスト名と件数だけ。ログの `[out]` `[src]` と同じ方針）
- `metrics/` は `render.yaml` の `buildFilter` に入っていないので、**ここへの push でデプロイは走らない**
- 2026-09-12〜09-17 の 60 行は `outputs/note/series.json`（note の記事用に手で集めていたもの）から移した。
  09-20 の 2 行は手で写した。09-17〜09-20 は記録が無い
