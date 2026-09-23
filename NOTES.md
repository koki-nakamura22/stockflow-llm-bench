# ローカルLLMベンチマーク 実行方針メモ

作成: 2026-09-21
対象: 本リポジトリ(StockFlow Local LLM Benchmark)
**候補 9 モデルの速度スクリーニング: `SCREENING.md`**(2026-09-22。かける 6 / かけない 3)
**結果: `RESULTS.md`**(2026-09-21〜22、3 モデル本番)
**結論(2026-09-22 更新)**: 相対的には **ornith:35b**(Index 77.1、A00 を通した唯一のモデル)。絶対的には依然「レビュー前提」。ただし冪等性(laguna 80)・migration 互換(laguna / gemma4 100)は解けることが分かった。詳細は RESULTS.md「結論」
構成の要約: `ARCHITECTURE.md`
ベンダー推奨設定の根拠: `VENDOR_SETTINGS.md`
変更履歴: `CHANGELOG.md`(ディレクトリ名からバージョンを外し、バージョンはこのファイルで管理)

## 環境

- Apple M5 / 32GB unified memory / macOS (Darwin 25.5.0)
- Ollama 0.32.13(`/usr/local/bin/ollama`)
- Python 3.12.14(pyenv。runner は 3.11+ 必須、システムは 3.9)
- Docker: Rancher Desktop(`~/.rd/bin/docker`、VM 6GB / 2CPU)。server 29.5.3 / compose v5.3.1

## 対象モデル(Ollama)

| Model | 量子化 | サイズ | 備考 |
|---|---|---|---|
| gpt-oss:20b | MXFP4 | 13 GB | thinking は off にできない(low/medium/high) |
| qwen3.6:35b-a3b-coding-nvfp4 | nvfp4 | 21 GB | Ollama 独自エンジン向け形式(requires 0.19.0) |
| qwen3.6:35b-a3b | Q4_K_M | 23 GB | 同じ重みの Q4_K_M 版。nvfp4 との速度差の比較対象 |
| north-mini-code-1.0:latest | Q4_K_M | 18 GB | cohere2moe(requires 0.30.10) |

`qwen3.6:27b` は 2026-09-21 に削除済み(未使用のため)。

## ランタイム選択: Ollama を採用

- 4 モデル中 3 つ(nvfp4 / cohere2moe / gptoss)は Ollama 独自エンジン向け形式で、upstream llama.cpp では読めない可能性が高い
- tool call パーサ(Harmony / Qwen XML / Cohere)は Ollama が一次サポート
- llama.cpp / LM Studio(MLX) / mlx_lm.server は速度差が数%〜10% 程度で、エージェントループの壁時間には効かない。tool call パースの品質はむしろ劣る
- 壁時間を決めるのは tok/s より **prefix cache の効き**。Ollama で全モデルとも効いていることを実測済み

## 速度計測結果(Ollama, num_ctx=32768, temperature 0)

| Model | cold load | pp tok/s(初回 ~5K tok) | tg tok/s(長文脈後) | tg tok/s(短 prompt) |
|---|---:|---:|---:|---:|
| qwen3.6:35b-a3b-coding-nvfp4 | 21.4s | 989 | 38–40 | 38.4 |
| gpt-oss:20b | 4.8s | 688 | 26–30 | 31.4 |
| qwen3.6:35b-a3b | 6.7s | 452 | 23–27 | 27.2 |
| north-mini-code-1.0 | 5.6s | 348 | 24–25 | 30.5 |

- nvfp4 は同じ重みの Q4_K_M 版の約 2 倍速い
- 実タスクでは write_file 1 回で 2〜4K トークン → 1 タスク 20〜60 分、4 モデル × 6 タスクで 8〜20 時間の見込み
- 実効 tok/s は合成計測ではなく、run ごとの transcript(prompt_tokens / completion_tokens / duration_seconds)から出す

## コンテキスト長ごとのメモリ実測(`ollama ps`, デフォルト設定)

| Model | 32K | 64K |
|---|---|---|
| gpt-oss:20b | 12 GB / 100% GPU | 12 GB / 100% GPU |
| qwen3.6:35b-a3b-coding-nvfp4 | 22 GB / 100% GPU | 22 GB / 100% GPU |
| qwen3.6:35b-a3b | 23 GB / 100% GPU | 24 GB / **4% CPU 溢れ** |
| north-mini-code-1.0 | 19 GB / 100% GPU | 19 GB / 100% GPU |

## cohort の切り替え(2026-09-21、0.2.0)

当初の「thinking off + temperature 0 + 32K」は廃止。目的(実用できるモデルを知る)に対して、3 ベンダーの推奨に反する条件で測っても答えにならないため。根拠と引用は `VENDOR_SETTINGS.md`。

- 各モデルをベンダー推奨 sampling(qwen 2 本は precise coding 値で揃える)+ thinking on(gpt-oss は medium)+ 64K で回す
- 値は CLI で明示し `run-config.json` に記録(`scripts/run_cohort.sh`)
- 再現性は seed 固定ではなく、同条件の複数回の幅で報告
- Ollama は `OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` で再起動済み(4 モデル 64K で 100% GPU)
- 0.1.x の run 結果はハーネス慣らしデータとして残す。モデル比較には使わない
- **nvfp4 は使わない**(2026-09-21): 同一条件で Q4_K_M と比較し、nvfp4 だけがインデントの自己増幅ループ(136 スペース)に入ることを確認。Qwen 代表は `qwen3.6:35b-a3b`(Q4_K_M)。詳細は CHANGELOG「nvfp4 vs Q4_K_M 切り分け」
- 1 ターンの生成上限は 24576(0.2.1)。thinking モデルは切られると次ターンで熟考をやり直すため

以下の「ハーネス修正方針」「コンテキスト長」の記述は旧 cohort 時点のもの。

## ハーネス修正方針(決定済み・0.1.1 で実装済み)

### (a) 終了条件
- 問題: `bench/agent.py` は tool call なし + 本文ありの返答を「完了」扱いにする。一言喋ってから tool を呼ぶ癖のモデルが 1 ターン目で 0 点になる
- 決定: **`finish` tool の呼び出しだけを正式な終了とする**。本文だけの返答には「続けるか finish を呼べ」と返し、**tool なし 3 連続で打ち切り**(status `no_tool_call`)

### (b) thinking
- 問題: adapter が think を指定しておらず、モデルごとのデフォルトでバラバラ。Qwen は thinking + temperature 0 が非推奨(反復ループ)。thinking トークンが 32K を食う
- 決定: **1 周目は全モデル thinking off(gpt-oss は medium)**。`config/run.yaml` に記録する
  - 当初は gpt-oss を `low` にする予定だったが、試走で `low` だと 3 ターン目に「時間が無い」と放棄することが判明し、gpt-oss の既定 effort である `medium` に変更(2026-09-21)
- **保留**: 1 周目の結果を見て気になる点があれば、thinking を調整して 2 周目を回す

### (c) コンテキスト溢れ
- 問題: ハーネスは履歴のトークン数を数えていない。32K を超えると Ollama は黙って先頭(system prompt / タスク文)から切り捨て、モデルが迷走する。結果からはモデルの弱さと区別できない
- 決定: **prompt_tokens が 30K を超えたターンで打ち切り、status `context_exceeded` として記録**。それまでの成果物はそのまま評価する

### コンテキスト長
- 決定: **1 周目は 32K のまま**(仕様書の cohort どおり、全モデル GPU に収まる)
- **保留**: 溢れが頻発するなど気になる点があれば、以下を入れて **64K で再計測**
  - `OLLAMA_FLASH_ATTENTION=1`
  - `OLLAMA_KV_CACHE_TYPE=q8_0`
  - Rancher VM のメモリを 6GB → 4GB
  - Ollama の環境変数は `launchctl setenv` で設定して Ollama を再起動
- 条件を変えるときは 1 つずつ(thinking と 64K を同時に変えると切り分けできない)

## 実行コマンド(0.2.0)

```bash
PY=~/.pyenv/versions/3.12.14/bin/python   # runner は 3.11+
export PATH="$HOME/.rd/bin:$PATH"          # Rancher Desktop の docker
cd /path/to/local-llm-benchmark   # このリポジトリのルート
scripts/run_cohort.sh              # 4 モデル × 6 課題、ベンダー推奨設定(VENDOR_SETTINGS.md)
scripts/run_cohort.sh --task A00   # 引数は bench.cli にそのまま渡る
```

## 試走で分かったこと(2026-09-21、詳細は CHANGELOG 0.1.2 / 0.1.3)

- 配布物は**そのままでは採点が成立しない**状態だった(stale image 使い回し、skeleton / reference の `pyproject.toml` が build 不能)。0.1.3 で修正し、reference/base で A00=100 / C01=25 を確認済み
- context guard は `num_ctx − 8K` に(生成余裕が無いと thinking でウィンドウを使い切る)
- gpt-oss:20b は `--think low` だと「時間が無い」と思い込んで放棄する。(b) の再検討材料
- 検討点 4 件(write_file の diff 戻り値、tool 引数未検証、run_check ノイズ、thinking 方針)は 0.1.4 で全て反映済み

## TODO: コンテキスト長の差分実験(2026-09-22 メモ、未実施)

**問い**: コンテキストウィンドウを 64K → 96K(guard 72K)に上げると、`context_exceeded` で切られた run の結果は変わるか。

**予想**: 変わっても小さい。落ちた理由の大半は「app が起動しない変更」でコンテキスト不足ではない。切られた run は turn 30 前後なので、次は `max_turns`(40)に当たる。後半ターンは文脈が長いほど遅くなる(glm は 20K 文脈で 10 tok/s)。Index で +5 前後、順位は変わらない見込み。

**やること**:
1. glm 再走が終わってから、96K / 128K で各モデルが 100% GPU に載るか実測(`ollama ps`。KV は q8_0 で 32K あたり約 1GB、64K 時点で 17〜22GB。Rancher VM 6GB 同居)
2. 全モデル再走ではなく、Round 2 で `context_exceeded` になった run だけ 96K で回し直す差分実験:
   - laguna-xs-2.1: C01 / C02 / C05
   - gemma4 26b-a4b: C02
   - ornith: C05
   - (nemotron は 64K すら載らないので対象外。glm は速度で対象外)
   - `bench.cli run --task <task> --context-window 98304` を 5 本、合計 2 時間程度
3. 同じ課題の 64K の結果と並べて `RESULTS.md` に追記

**やらないこと**: `--request-timeout` をこれ以上伸ばす(24K トークン思考が 40 分に収まらないモデルは、実用速度を割っていると判断する)。

## 実行前に必要な設定

- `OLLAMA_NUM_PARALLEL=1`(並列スロット数だけ KV を確保するため明示)
- `OLLAMA_KEEP_ALIVE` を長め(評価中にアンロードされないように)
- Docker イメージ: `postgres:16-alpine`, `python:3.12-slim`, evaluator image(`stockflow-bench-evaluator:0.1`)。2026-09-21 時点で pull が EOF エラーになったため要再試行
- 実行前に `ollama ps` で対象モデルが 100% GPU に乗っているか確認
- `OLLAMA_NUM_PARALLEL=1` は Ollama 0.32.13 の既定値で既に有効(server.log で確認済み)

## 実行手順

(2026-09-22 時点: 本番 cohort 1 周完了。結果は RESULTS.md。次は 0.2.2(Ollama parse error の吸収)と各モデル 3 回実行)

1. ~~(a)(c) の修正を入れ~~(0.1.1 で実装済み)`python -m unittest discover -s tests -v` と `python -m bench.cli preflight` を通す
2. ~~`gpt-oss:20b` × A00 だけ 1 本試走~~(3 本実施済み。ハーネス経路は全 tool・Docker 評価とも検証完了)
3. 問題なければ 4 モデル × `--all-controlled`(`--include-self` なし)を無人実行
4. 結果を見て thinking / 64K の 2 周目を判断
