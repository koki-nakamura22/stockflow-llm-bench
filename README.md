# StockFlow Local LLM Benchmark

ローカルLLMへ実システム寄りの実装課題を与え、agent loop、hidden integration tests、固定配点で自動評価するベンチマークです。


## Public 版について

このリポジトリは、ベンチマークを継続運用している非公開リポジトリから
allowlist で生成した公開版です。**次のものは含まれていません。**

| 非同梱 | 理由 |
|---|---|
| `evaluator/tests/` (hidden tests)、`evaluator/scoring.json` | 公開すると、以後この物差しで新しいモデルを測れなくなるため |
| 各 run の `test-output.log` / `evaluator-result.json` / `evaluator-console.log` / `pytest.xml` | pytest の失敗出力と per-test の配点内訳が hidden test の内容そのものになるため |
| ベンチマーク設計・採点仕様書、実装プロファイル、構築プロンプト | 同上(課題別の配点内訳を含む) |

**含まれているもの**: エージェントループ (`bench/`)、モデルへ渡した課題文
(`tasks/`)、モデルから見えていた公開テスト (`public-tests/`)、開始点
(`platform-skeleton/` と `reference/base/`)、採点の仕組み
(`evaluator/evaluate.py`)、そして全 run の成果物・会話ログ・実行条件
(`results/`)。

したがって次のことができます。

- 各モデルが実際に書いたコードを読む (`results/**/workspace/`)
- 全ターンの会話・tool 呼び出し・トークン数を追う (`results/**/transcript.jsonl`)
- どの設定で回したかを確認する (`results/*/run-config.json`、`VENDOR_SETTINGS.md`)
- workspace の git リポジトリを復元する (`scripts/rebuild_workspace_git.sh`)

- **自分のモデルで回す** (`python -m bench.cli run --adapter ollama --model <model>`)

できないのは**採点**だけです。`evaluator/tests/` と `evaluator/scoring.json` は、
件数と配点の合計だけを本物に合わせた**伏せ字版**に差し替えてあります (テスト名は
伏せ、中身は全て skip)。ハーネスの preflight を通すためのもので、公開版で評価を
走らせると Capability は常に 0 点になります。エージェントループ自体は本物と同一です。

### 汚染についての注記

`reference/base/` は C01〜C05 の開始点であると同時に A00 の基準実装でもあります。
C01〜C05 では全モデルへ実行時に渡しているため公開による影響はありませんが、
**A00 については 2026-09-23 以降、基準実装が公開されている前提で読んでください。**
この日付以降に学習されたモデルの A00 スコアは、実装能力ではなく記憶を反映して
いる可能性があります。

## 必要環境

- Python 3.11以上（runnerは標準ライブラリのみ）
- Docker Engine / Docker Desktop と `docker compose`
- Ollama、またはOpenAI互換Chat Completions endpoint
- 20GB以上の空きディスクを推奨

runnerは対象モデルへファイル操作toolだけを渡します。対象モデルからhidden testsは見えません。実装後にrunnerがDocker上でhidden testsを実行し、JSON / Markdownへ集計します。

## cohort全体を実行

```bash
scripts/run_cohort.sh            # 4 model × 6 task、ベンダー推奨設定
scripts/run_cohort.sh --task A00 # 引数は bench.cli にそのまま渡る
```

## 1モデル・1課題を実行

Ollama:

```bash
python -m bench.cli run \
  --adapter ollama \
  --model qwen3.6:35b-a3b-coding-nvfp4 \
  --think on --temperature 0.6 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 0 \
  --context-window 65536 \
  --task A00
```

OpenAI互換endpoint:

```bash
python -m bench.cli run \
  --adapter openai \
  --base-url http://127.0.0.1:1234/v1 \
  --model local-model-name \
  --task A00
```

## 1モデルで全課題を実行

```bash
python -m bench.cli run \
  --adapter ollama \
  --model qwen3-coder:30b \
  --all-controlled
```

これは次を実行します。

- `A00`: 空スケルトンから0→1実装
- `C01`〜`C05`: 共通の基準実装へ、課題ごとにfresh sessionで仕様変更

自身のA00成果物へのcold changeも実行する場合:

```bash
python -m bench.cli run \
  --adapter ollama \
  --model qwen3-coder:30b \
  --all-controlled \
  --include-self
```

## model一覧

```bash
python -m bench.cli models --adapter ollama
python -m bench.cli models --adapter openai --base-url http://127.0.0.1:1234/v1
```

## preflightだけ実行

```bash
python -m bench.cli preflight
```

Docker、Compose、task asset、reference baseline、採点表を確認します。

## 結果

```text
results/<run-group-id>/
├── summary.json
├── summary.csv
├── summary.md
└── runs/<model>/<track>/<task>/
    ├── metadata.json
    ├── transcript.jsonl
    ├── submission.patch
    ├── evaluator-result.json   ※Public 版には非同梱
    ├── pytest.xml              ※Public 版には非同梱
    └── test-output.log         ※Public 版には非同梱
```

Capability、Code Health、効率値は混ぜずに出力されます。主要順位はCapabilityだけで決まります。

## 公平性の既定値（cohort "practical settings"、0.2.0）

- Pass@1。ただし再現性は temperature 0 ではなく、同条件の複数回実行の幅として報告する
- 各modelをベンダー推奨のsampling値で実行し、値はCLIで明示して `run-config.json` に記録する
  （`scripts/run_cohort.sh`、根拠は `../VENDOR_SETTINGS.md`）
- thinking on（gpt-ossは`off`を無視し`low`では課題を放棄するため`--think medium`）
- 64K context（`--context-window 65536`。Ollamaに `OLLAMA_FLASH_ATTENTION=1` `OLLAMA_KV_CACHE_TYPE=q8_0` が必要）
- taskごとに新規conversation
- taskごとに新規workspace / PostgreSQL volume
- 対象モデルの外部network toolなし
- hidden testsは実装終了後だけmount
- model failureの再試行なし

`config/run.yaml` は記録用の既定値です。CLI optionが優先されます。実際に使った値は
`results/<run-group-id>/run-config.json` と各 `metadata.json` の `run_config` に記録されます。

## toolの挙動

- `write_file` は `created path (N lines)` / `replaced path (N lines)` だけを返す。diffは返さない。
- tool定義にない引数、必須引数の欠落、型不一致はerrorとして返し、正しい引数名を提示する。黙って無視しない。
- `run_check` の結果からdocker build / composeの進捗行を除き、pytest / migration / buildエラーの出力だけを返す。
- `run_check("syntax")` はSyntaxErrorごとにファイル・行・列・メッセージ・該当行を返す。
- 同じtool callが同じ結果で連続すると、3回目からその旨のnoticeを結果に付ける。

## agent loopの終了条件

- `completed`: 対象modelが `finish` toolを呼んだ。tool callのない本文だけの返答は終了と見なさず、
  「toolを使って続けるかfinishを呼べ」と促す。
- `no_tool_call`: tool callのない返答が `--max-no-tool-turns`（既定3）回連続した。
- `repeated_call`: 同一のtool callが同一の結果で `--max-repeated-calls`（既定8）回連続した。
- 1turnの生成は `--max-output-tokens`（既定24576）で打ち切る。打ち切られた返答はtool callを含まないので、
  上の「続けるかfinishを呼べ」に乗る。thinking modelは打ち切られると次turnで同じ熟考をやり直すため、
  上限は1回の熟考が収まる大きさにする。
- `context_exceeded`: 次のrequestの推定prompt長が `--context-guard`（既定は context window − max-output-tokens）を超えた。
  endpointがsystem promptやtask文を黙って切り捨てる前、かつ1turn分の生成余裕が残るうちに止める。
  それまでの成果物は通常どおり採点する。
- `max_turns` / `output_limit` / `model_error`: 従来どおり。

## 制約

- native tool calling対応modelが対象です。text-only modelは同じcohortへ混ぜません。
- この配布物には正解patchを含めません。基準実装はA00だけです。変更課題はhidden testと既存regressionで採点します。
- Dockerのない環境ではrunner単体のunit testは可能ですが、integration評価はできません。
- C05は完全な本番migration認証ではなく、expand/contract構造、旧schema互換、backfill、API結果を機械評価する縮約版です。

## runner unit test

```bash
python -m unittest discover -s tests -v
```

## 参考

- SWE-bench Evaluation Guide: https://www.swebench.com/SWE-bench/guides/evaluation/
- Ollama Chat API: https://docs.ollama.com/api/chat
- OpenAI Chat Completions: https://platform.openai.com/docs/api-reference/chat

