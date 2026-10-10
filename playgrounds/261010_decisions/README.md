# 261010 playground — OpenAI Decisions / gpt-6-luna vs DeepSeek

RCS の AI 前処理・後処理を、今の DeepSeek v4-flash から OpenAI に替えたときの精度・速さ・コストを測る。
RCS エンジンと本番の `web/backend/ai_pipeline.py` は変更しない（プロンプトと正規化関数を import して使う）。

| ステージ | 比べるもの | 指標 |
|---|---|---|
| 前処理 | なし / DeepSeek v4-flash / gpt-6-luna（同じ `PREPROCESS_SYSTEM`） | 清掃後クエリでの RCS top-1・top-10 一致率 |
| 後処理 | DeepSeek v4-flash（本番）/ gpt-6-luna（同じプロンプト）/ **Decisions API**（gpt-6-luna） | AI top-1 一致率、棄権率、確信度別の精度 |

両ステージとも p50・p95 の応答時間と 1,000 クエリあたりの費用を出す。

- 正解: `build_testdata/rcs_ai_compare.csv` の `expected_homba_id`（verified 100 件。略語と正式名称を別クエリにする）。`--dataset core` で `rcs_core.csv`
- 前処理は、元のクエリに加えてノイズ付き版（`right X Drd1 neurons` など）でも測る。RCS 自身もある程度ノイズを落とすので、「なし」が基準
- 後処理は前処理を通さず、同じ RCS top-10 を 3 方式に渡す
- Decisions は「最良候補」の choice 質問 1 つと、候補ごとの関係（`=` `<` `>` `wrong`）の choice 質問を 1 回の呼び出しで聞く。確信度が高いものだけ Decisions で答え、残りを DeepSeek に回す運用の目安として、確信度しきい値ごとの回答率と精度も出す

```bash
export DEEPSEEK_API_KEY=... OPENAI_API_KEY=...
python playgrounds/261010_decisions/decisions_harness.py --limit 10      # 試し
python playgrounds/261010_decisions/decisions_harness.py --workers 8     # 全件
python playgrounds/261010_decisions/decisions_harness.py --stage post --post decisions
python playgrounds/261010_decisions/decisions_harness.py --mock          # API なしの動作確認
```

Claude Code のクラウド環境で回す場合は、キーを環境変数ではなくネットワークシークレット（`api.openai.com` と `api.deepseek.com` に 1 つずつ）に入れてもよい。環境変数が空ならハーネスは Authorization を付けずに送り、プロキシが付ける。

出力は `runs/<dataset>/`: `summary.md`（表）、`summary.json`、`pre_records.json`・`post_records.json`（1 件ずつ）、`cache.json`（API 応答。再実行では失敗分と新しい方式だけ呼ぶ）。

注意:
- Decisions API はパブリックベータ（2026-10-06〜）。リクエスト形はガイドの `model` / `input` / `questions`（`type`・`name`・`instructions`・`choices[value, description]`）に合わせた。`usage` の形が文書化されていないため、返らない場合はトークン数を文字数 ÷ 4 で推定し、`summary.json` に `cost_note` を付ける
- 単価は 2026-10 の定価（DeepSeek flash: 入力 $0.14 / キャッシュ $0.0028 / 出力 $0.28、gpt-6-luna: $0.10 / $0.01 / $0.50、Decisions: 入力 $0.10・出力無料、いずれも 100 万トークンあたり）
