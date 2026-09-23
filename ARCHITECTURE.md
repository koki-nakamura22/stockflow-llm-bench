# リポジトリ構成の要約: これは何をしているベンチマークか

作成: 2026-09-21
対象: 本リポジトリ(StockFlow Local LLM Benchmark v0.1.x)
関連: `CHANGELOG.md`(変更履歴)、`NOTES.md`(実行方針)

## 一言で

**このリポジトリ自体がハーネスである。** ただしその中身は、モデルの応答をシリアルに連結するための最小限のエージェントループと、モデルに渡す情報(プロンプト・tool 定義・開始コード)の構造的な管理であり、リッチなハーネスエンジニアリングは意図的に行っていない。

## 全体構造

```
local-llm-benchmark/
├── bench/              ← ① ハーネス(エージェントループ)
│   ├── cli.py            CLI 入口(--model / --think / --context-window / --context-guard など)
│   ├── adapters.py       Ollama / OpenAI 互換 API の呼び出し(think, num_ctx, temperature, seed)
│   ├── agent.py          エージェントループ本体(ターン制御、終了条件、context guard)
│   ├── tools.py          モデルに渡す 7 つの tool の実装と引数検証
│   └── workflow.py       workspace 準備、git baseline、評価呼び出し、summary 集計
├── evaluator/          ← ② 採点(モデルからは見えない)
│   ├── evaluate.py       Docker で PostgreSQL + app を起動 → hidden pytest 実行 → JSON
│   ├── tests/test_*.py   hidden tests(A00 / C01〜C05)※Public 版には非同梱
│   └── scoring.json      テスト名 → 配点(各課題 100 点)※Public 版には非同梱
├── tasks/*.md          ← ③ モデルに渡す課題文
├── platform-skeleton/    A00 の開始点(空の FastAPI + alembic.ini + Dockerfile)
├── reference/base/       C01〜C05 の開始点(A00 の基準実装)
├── public-tests/         モデルが run_check で実行できる公開スモークテスト
├── scripts/public_check.py  run_check("public-tests") の実体(Docker 起動 → 公開テスト)
├── config/run.yaml       記録用の既定値(実際に使った値は results/<group>/run-config.json)
├── tests/test_runner.py  ①ハーネス自身の単体テスト(モデル不要、mock サーバー)
├── results/            ← ④ 実行結果(run group ごと。詳細は RESULTS.md)
└── *.md                  NOTES(実行方針) / RESULTS(結果) / SCREENING(速度足切り) /
                          VENDOR_SETTINGS(設定根拠) / CHANGELOG / 仕様書 2 本
```

## ① ハーネスが制御していること

モデルには **shell も Python 実行環境も渡さない**。渡すのは `bench/tools.py` で定義された 7 つの tool だけ:

| tool | できること |
|---|---|
| `list_files` / `read_file` / `search_text` | workspace 内の読み取り |
| `write_file` / `replace_text` | workspace 内の書き込み(`.git`、`benchmark-tests/`、`compose.yaml`、`Dockerfile` は read-only) |
| `run_check` | `syntax` / `compose-config` / `public-tests` の 3 種だけ。任意コマンドは実行不可 |
| `finish` | 終了宣言 |

`bench/agent.py` のループは:

1. system prompt + 課題文を積む
2. Ollama に「全履歴 + tool 定義」を送る
3. 返ってきた `tool_calls` を順に実行し、結果を履歴に追記
4. 終了条件(`finish` / 上限 / エラー / context guard)を見て 2 に戻る

これだけ。150 行程度で、状態は `messages` リストひとつ。**終了条件・thinking・コンテキスト長・引数検証・tool の戻り値の形式**、つまり「モデルがどう振る舞えるか」を決めるものは全部ここにある。

## ② 採点はハーネスから分離されている

`evaluator/evaluate.py` はモデルの run が終わった**後**に `workflow.py` から呼ばれ、workspace を Docker に読み込んで hidden tests を回す。モデルの実行中は `evaluator/` はマウントされず、tool からも到達できない(`safe_path` で workspace 外を拒否)。

## 「Codex / Claude Code をオーケストレーターに」の意味

構築・実行の依頼プロンプト(Public 版には非同梱)の「オーケストレーター」は、**人の代わりに CLI を叩いて結果を読む役**であって、エージェントループの中に入るわけではない。ローカル LLM に tool を渡してターンを回しているのは `bench/agent.py`。オーケストレーターの役割は「ハーネスを直し、走らせ、結果を報告する」だけで、モデルの提出物には手を触れない(同プロンプトの手順 5)。

## `tests/test_runner.py` は「ハーネスのテスト」

名前が紛らわしいが、これはローカル LLM を評価するテストではなく、**ハーネス自身が正しく動くかの単体テスト**(mock の Ollama サーバーを立てて、tool 実行・終了条件・引数検証を検証)。

## リッチなハーネスなら持っているが、ここには無いもの

- コンテキスト圧縮・要約(履歴が膨らんでも切り詰めない。context guard は「溢れる前に止める」だけ)
- 計画立案・サブタスク分解・サブエージェント
- 失敗時の自動リトライや自己修復(tool エラーはそのまま返すだけ)
- lint / typecheck 結果の自動フィードバック(モデルが `run_check` を呼ばなければ何も起きない)
- 任意コマンドの sandbox 実行(shell は無い。`run_check` の 3 種固定)
- モデル別の system prompt 調整やプロンプトテンプレートの最適化
- ストリーミング、並列 tool 実行、途中打ち切り
- 出力の検証・修正(提出物はそのまま採点に回る)

## それは意図的な設計

このベンチの目的は「モデルの実装能力を測る」ことなので、ハーネスが賢いと **ハーネスの賢さを測ってしまう**。だから薄くしてある。設計仕様書(Public 版には非同梱)も「Codex / Claude Code による主観採点は使わない」「固定テストと静的計測だけ」と言っており、思想として一貫している。

## ただし、薄いことの副作用

ハーネスが薄い = **ハーネスの癖がそのままスコアに転写される**。2026-09-21 の試走で見つかったものは全部それだった(詳細は `CHANGELOG.md` 0.1.2〜0.1.4):

- `list_files("")` を弾く → モデルが「ファイルが無い」と誤認して 0 点
- diff 形式の戻り値 → モデルがそれを引用して `replace_text` に失敗し続け、10 ターン浪費
- 引数名の違いを黙って無視 → モデルは気付けないままコンテキストを浪費
- stale image → モデルの修正がテストに反映されず、モデルが自分を疑う
- skeleton の `pyproject.toml` が build 不能 → 仕様どおり実装すると必ず失敗

これらへの修正は「リッチにする」のではなく「**モデルの能力以外の要因でスコアが変わらないようにする**」もの。ハーネスエンジニアリングとしては最低限の正しさ(fairness)を整えただけで、性能を引き出す方向の工夫は入れていない。そこは意図的に入れないのが、このベンチの立場である。
