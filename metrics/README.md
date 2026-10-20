# metrics/

点検（`scripts/render_check.py --append metrics/series.jsonl`）が1回につき1行ずつ書き足す記録。
GitHub Actionsの `render-check.yml` が2時間おきに走り、この1行をcommitする。

- **Renderのログは日が経つと消える**ので、あとから推移を描くにはここに残しておくしかない
- 1行の中身: 時刻（JST）・窓の長さ・要求数・帯域GB・5xx・rss・CPU・本日の共有数・外へ出した要求（ホスト別）・
  ソースごとの検索・VocaDBへ聞いた回数・ブラウザ側の失敗・異常の数
- `gb` は `/metrics/bandwidth`。**HTTP応答もサービス発も入った合計**（請求の対象と同じ。2026-10-21に確かめた）。
  同日から内訳 `gb_src`（http / nat=サービス発 / privatelink / websocket）も書く。請求画面の内訳と並べて読むため
- **語やURLは入れない**（ホスト名と件数だけ。ログの `[out]` `[src]` と同じ方針）
- `metrics/` は `render.yaml` の `buildFilter` に入っていないので、**ここへのpushでデプロイは走らない**
- 2026-09-12〜09-17の60行は `outputs/note/series.json`（noteの記事用に手で集めていたもの）から移した。
  09-20の2行は手で写した。09-17〜09-20は記録が無い
