# 変更履歴

このディレクトリの配布物のバージョンと、ローカルで加えた変更の記録。
バージョンの正は `pyproject.toml` と `config/run.yaml` の `benchmark_version`。

## 0.2.3 — 2026-10-22

eMudhra(emSign)の中間証明書の秘密鍵漏えいへの対応。certifi 2026.10.19 で関連するルート CA 証明書が外され、certifi を同梱する pip も 26.2.2 で更新された。

### 変更

- **image 内の pip を 26.2.2 以上に上げてから `pip install` する**(`evaluator/Dockerfile`, `platform-skeleton/Dockerfile`, `reference/base/Dockerfile`)
  - `python:3.12-slim` 付属の pip は、古い certifi を同梱したまま依存を取りに行っていた。
  - 既存の `RUN pip install` の行に `pip install -U "pip>=26.2.2" &&` を前置した(layer 数は変えない)。
  - アプリの依存とコードは変わらないので、0.2.2 以前の結果との比較には影響しない。`platform-skeleton/` の tree が変わるため、今後の run の `baseline_tree_sha` は 0.2.2 以前と異なる。
  - 検証: 3 image を `docker build --pull --no-cache` で作り直し、いずれも `pip 26.2.2`、skeleton と reference/base は `make` が通ることを確認。
- version 0.2.3。

## 0.2.2 — 2026-09-22

Round 2(候補 6 モデル、`scripts/run_cohort_round2.sh`)の途中で見つかった 2 件。

### 変更

- **サーバー側 tool call パースエラーを致命扱いしない**(`bench/agent.py`)
  - Ollama はモデルが崩れた tool call を出すと HTTP 500 を返す(gpt-oss: `error parsing tool call`、GLM: `mismatched arg_key and arg_value counts`)。ハーネスはこれを `model_error` として run を終了していた(gpt-oss C04、glm-4.7-flash A00 turn 4)。OpenAI 互換サーバーなら本文として返るだけで nudge に乗るので、Ollama だけ不利だった。
  - 該当エラー(`HTTP 500` + 既知のマーカー)は「tool call をスキーマどおりに出し直せ」という nudge にして続行。tool なし streak にカウントし、3 連続で `no_tool_call`。transcript に `malformed_tool_call` event を記録。接続失敗など他のエラーは従来どおり `model_error`。
- **`--request-timeout` の既定を 1200 → 2400 秒**
  - 0.2.1 で `max_output_tokens` を 24576 にしたときにタイムアウトを据え置いたため、ornith A00 turn 23 が 20 分で切られ `model_error`(18K 文脈で 24K トークン思考すると 20 tok/s 程度に落ちる)。成果物は完成済みだったので 100 点は付いたが、ハーネスとしては不整合。
- `tests/test_runner.py`: パースエラー nudge と、他エラーの致命扱い維持を追加(計 20 件)。version 0.2.2。

## 本番 cohort 実行(0.2.1)— 2026-09-21〜22

3 モデル(nvfp4 除外)× 6 課題を `scripts/run_cohort.sh` で実行。結果と所見は **`RESULTS.md`**。

| Model | Index | 所要 |
|---|---:|---:|
| qwen3.6:35b-a3b(Q4_K_M) | 32.4 | 45 分 |
| gpt-oss:20b | 27.0 | 86 分 |
| north-mini-code-1.0 | 17.4 | 142 分 |

ハーネス側で見つかった点(0.2.2 で対応予定):
- gpt-oss C04 が `model_error`: モデルが壊れた tool call JSON を出し、Ollama の Harmony パーサが HTTP 500(`error parsing tool call`)で request 全体を失敗させた。OpenAI 互換サーバーなら本文として返るだけで nudge に乗る。Ollama の parse error 500 は tool エラーとしてモデルに返し、run を続行させるべき(no-tool streak にはカウント)。
- `scripts/run_cohort.sh` の `"${EXTRA[@]}"` が macOS bash 3.2 + `set -u` で引数なしのとき "unbound variable" になる不具合を修正(`${EXTRA[@]+"${EXTRA[@]}"}`)。

## nvfp4 vs Q4_K_M 切り分け(0.2.0 設定、8192 上限)— 2026-09-21

`qwen3.6:35b-a3b`(Q4_K_M、`results/20260921T114955347212Z-qwen3.6-35b-a3b`)を nvfp4 と完全同一条件(thinking on、temp 0.6 / top_p 0.95 / top_k 20、64K、上限 8192)で実行。50 分。

| Task | nvfp4 | Q4_K_M | Q4_K_M の agent |
|---|---:|---:|---|
| A00 | 0(インデント自己増幅、max_turns) | 0(`POST /products` 500、実行時バグ) | completed |
| C01 | 70 | 45 | completed |
| C02 | 9(3 × 8K thinking) | 9 | completed |
| C03 | 96 | 100 | completed |
| C04 | 58 | 100 | completed |
| C05 | 0(3 × 8K thinking、変更ゼロ) | **100** | completed |
| Index | 28.0 | **42.5** | 6 課題すべて `finish` 到達 |

所見:
- **インデント自己増幅は nvfp4 固有**。Q4_K_M の A00 は 14 回の write が 9 ファイルに分散、`run_check` 11 回、書いた行の最大インデントは 16 スペース(nvfp4 は models.py を 35 回書き直し、136 スペース)。同じ重み・同じ設定なので、差は量子化(と Ollama / Metal の nvfp4 実装)にある。旧 cohort でも nvfp4 だけが「unindent does not match」を繰り返していたことと整合。
- Q4_K_M は 8192 上限でも 3 × 8K thinking ループに入らなかった(6 課題すべて `completed`)。nvfp4 の C02 / C05 の堂々巡りも量子化の影響を受けている可能性がある。0.2.1 の上限 24576 が Q4_K_M にどう効くかは次の run で見る。
- 速度: Q4_K_M 50 分 vs nvfp4 68 分。nvfp4 は tok/s では 2 倍速いが、ループで時間を溶かして結局遅い。
- **現時点の判断**: この環境(Ollama 0.32.13 / Metal)の nvfp4 はコード生成に使えない。以後の本番 cohort では `qwen3.6:35b-a3b`(Q4_K_M)を Qwen 代表とし、nvfp4 は参考扱い。

## 0.2.1 — 2026-09-21

新 cohort での qwen nvfp4 1 周目(`results/20260921T101916568217Z-qwen3.6-35b-a3b-coding-nvfp4`、Index 28.0、68 分)で見つかった cohort パラメータの問題。

### 変更

- **`--max-output-tokens` の既定を 8192 → 24576**(guard は `context_window − 24576` = 40960)
  - C02 と C05 で、ファイルを読み終えた直後のターンの thinking が 8,192 トークンで切られ、tool call に至らなかった。次のターンは Qwen のチャットテンプレートが前ターンの thinking を落とす(prompt が 7,982 → 7,703 に減少)ため、**同じ熟考をゼロからやり直し**、3 回で `no_tool_call`。C05 はファイル変更ゼロで 0 点。
  - 8192 は 0.1.5 で thinking off 前提に決めた値。Qwen の推奨出力長は 32K で、64K のうち 24K を生成余裕に回す。
- `scripts/run_cohort.sh` に `MAXOUT`(既定 24576)を追加。`run.yaml` / README を更新。version 0.2.1。

### nvfp4 新 cohort 1 周目(8192 上限)の結果

| Task | Capability | agent | 所見 |
|---|---:|---|---|
| A00 | 0 | max_turns | `stockflow/models.py` を 35 回書き直し。`__tablename__` 前のインデントが 4 → 7 → 61 → **136 スペース**と自己増幅。thinking は「同じ間違いを繰り返している」と自覚しつつ悪化。`run_check` 未使用 |
| C01 | 70 | completed | |
| C02 | 9 | no_tool_call | 3 × 8K thinking(同一 key の同時リクエスト設計で堂々巡り) |
| C03 | 96 | completed | |
| C04 | 58 | completed | |
| C05 | 0 | no_tool_call | 3 × 8K thinking、ファイル変更ゼロ |

- A00 のインデント自己増幅はハーネス起因ではない(tool は `write_file` のみ、内容はそのまま書いている)。nvfp4 固有かは Q4_K_M(`qwen3.6:35b-a3b`)の同条件 run で切り分ける。

## 0.2.0 — 2026-09-21

**cohort の切り替え**: 「thinking off + temperature 0 + 32K」→「ベンダー推奨 sampling + thinking on + 64K」。根拠と引用は `VENDOR_SETTINGS.md`。採点(`evaluator/`、`scoring.json`、hidden tests)は無変更。

### 背景

- 旧 cohort は 3 ベンダーの model card に反していた(Qwen: "DO NOT use greedy decoding"、Cohere: thinking は "works best when turned on"、Qwen: 長期タスクは 128K 以上)。
- 実測でも、temperature 0 は再現性を与えず(A00 が 4 周で 4 種類の失敗、C04 が 100 → 58)、greedy の退化ループ(同一チェック 24 回、同一ファイル 8 回)を頻発させた。
- 目的は「実用できるモデルを知る」ことであり、推奨外設定での挙動を測っても答えにならない。

### 変更

- **sampling を明示指定**(`bench/adapters.py`, `bench/cli.py`)
  - `--temperature` / `--top-p` / `--top-k` / `--min-p` / `--presence-penalty` / `--repeat-penalty` / `--seed` を追加。指定した値だけを Ollama `options` に送り、未指定は Modelfile 既定に任せる。`temperature 0` / `seed 42` の強制を廃止。
  - OpenAI adapter は Chat Completions が受ける `temperature` / `top_p` / `presence_penalty` / `seed` だけを送る。
  - 使った値を `run-config.json` の `sampling` に記録。
- `--think` の既定を `off` → `on`。
- **`scripts/run_cohort.sh`**: 4 モデルをそれぞれの推奨値で順に回す。qwen 2 本は precise coding 値で揃え、差を量子化だけにする。
- `config/run.yaml` を新 cohort の内容に書き直し(モデル別 sampling、thinking、64K、guard 57344)。旧 cohort はコメントで記録。
- Ollama 環境: `launchctl setenv OLLAMA_FLASH_ATTENTION 1` / `OLLAMA_KV_CACHE_TYPE q8_0` を設定し、アプリを完全終了して再起動(`ollama serve` だけ kill しても親アプリが古い環境変数を渡すので効かない)。4 モデルとも 64K で 100% GPU を確認。
- `README.md`: 公平性の既定値と実行例を更新。
- `tests/test_runner.py`: sampling の passthrough と `run-config.json` への記録を追加(計 18 件)。
- version 0.2.0。

## 0.1.7 検証 run — 2026-09-21

`qwen3.6:35b-a3b-coding-nvfp4` 3 周目(0.1.7、`results/20260921T064850272747Z-qwen3.6-35b-a3b-coding-nvfp4`)。目的はハーネス起因の失敗が残っていないかの確認。**6 課題すべてハーネス起因なし。** 39.3 分。

| Task | Capability | agent | 落ちた理由(すべてモデル側) |
|---|---:|---|---|
| A00 | 0 | context_exceeded | migration に `revision` 変数が無く Alembic が id を判定できない |
| C01 | 100 | context_exceeded | — |
| C02 | 75 | completed | 一部の新規テストが fail |
| C03 | 100 | completed | — |
| C04 | 58 | context_exceeded | 一部の新規テストと regression が fail |
| C05 | **52** | context_exceeded | 一部のテストが fail。`make` 修正で評価が成立 |

Primary Capability Index **46.2**(1 周目 24.0 → 2 周目 36.0 → 3 周目 46.2。上昇分はすべてハーネス修正による)。

所見:
- temperature 0 / seed 42 でも run 間で結果が揺れる(A00 の失敗理由が 3 周とも違う、C04 が 100 → 58)。C01 / C03 は 3 周ともターン数・トークン数まで一致しているので、決定的に動くこともある。MoE + Metal の非決定性と思われる。Pass@1 の単発値には幅があることを前提に読む必要がある。
- `context_exceeded` が 6 課題中 4 課題。qwen(thinking off)は同じファイルを何度も読み直す癖があり、24.5K の guard に早く到達する。64K 検討の材料。

## 0.1.7 — 2026-09-21

`qwen3.6:35b-a3b-coding-nvfp4` の 2 周目(0.1.6、`results/20260921T060042218654Z-qwen3.6-35b-a3b-coding-nvfp4`)の C05 で見つかった、**C05 が全モデルで必ず失敗する**欠陥の修正。

### 変更

- **app image に `make` が無い**(`platform-skeleton/Dockerfile`, `reference/base/Dockerfile`)— 致命的(C05 限定)
  - C05 は課題文で `make migrate-expand` / `make migrate-contract` を要求し、evaluator と public_check も `compose run app make migrate-expand` を実行する。しかしベースイメージ `python:3.12-slim` に `make` が入っておらず、`exec: "make": executable file not found in $PATH` で必ず `migration failed` になっていた。Dockerfile は benchmark-owned(read-only)なのでモデルには直せない。
  - gpt-oss(0.1.4)と qwen(0.1.5 / 0.1.6)の C05 はすべてこれで 0 点だった。
  - 修正: `apt-get install make` を両 Dockerfile に追加(`RUN` 1 行、image は約 +3MB)。
  - 検証: reference/base が build でき `make --version` が通る。qwen 2 周目の C05 workspace を修正版 Dockerfile で診断評価 → **52/100**。モデルは課題の意図どおり expand / contract の migration 2 本と Makefile target と `MIGRATION.md` を書いていた。
- version 0.1.7。

### qwen3.6 coding nvfp4 2 周目(0.1.6)の結果 — 41.8 分

| Task | Capability | agent | turns | 所要 | 1 周目(0.1.5) |
|---|---:|---|---:|---:|---:|
| A00 | 0 | context_exceeded | 28 | 12.1m | 0(syntax ループ) |
| C01 | 100 | context_exceeded | 13 | 4.2m | 100 |
| C02 | 0 | context_exceeded | 24 | 8.1m | 0(syntax ループ) |
| C03 | 100 | completed | 14 | 2.9m | 100 |
| C04 | **100** | context_exceeded | 27 | 6.9m | 0(syntax ループ) |
| C05 | 0(make 無し) | context_exceeded | 21 | 7.8m | 0(syntax ループ) |

Primary Capability Index 36.0(1 周目 24.0)。0.1.6 の syntax 位置報告で C04 が 0 → 100。A00 は SyntaxError なしで app 起動まで進み、`POST /products` が 500(実行時エラー、モデルの実装バグ)。C02 は turn 22 の `write_file` で 5 スペースのインデント行を生成し、turn 23 で位置を受け取った直後に context guard で終了。

### 所見: nvfp4 の空白生成

qwen nvfp4 は 1 周目 A00、2 周目 C02 で「unindent does not match」(1 行だけインデントが 1 文字ずれる)を `write_file` の全文生成で出している。同じ重みの Q4_K_M 版(`qwen3.6:35b-a3b`)で再現するかは、量子化の影響を切り分ける比較点として価値がある。

## 0.1.6 — 2026-09-21

`qwen3.6:35b-a3b-coding-nvfp4` の run(0.1.5、`--think off`、`results/20260921T052806898096Z-qwen3.6-35b-a3b-coding-nvfp4`)の A00 で見つかった問題への対応。

### 変更

- **`run_check("syntax")` がエラー内容を返していなかった**(`bench/tools.py` `syntax_check`)
  - `compileall.compile_dir(quiet=1)` はエラーを runner プロセスの stdout に出すだけで、tool 結果は `syntax: fail` の 1 行。モデルにはファイル名・行番号・メッセージが一切届かなかった。
  - `ast.parse` で submission の全 `.py`(`benchmark-tests/` と `.git` を除く)を検査し、`file:line:col: msg` と該当行を返す。pass 時は検査ファイル数を返す。
  - 実例: qwen の A00 は `stockflow/main.py:148:40: unindent does not match any outer indentation level`(インデント 1 箇所)を直せず、turn 17〜40 の 24 回を `run_check("syntax")` → `fail` の繰り返しで使い切った。
- **同一 tool call の反復ガード**(`bench/agent.py`)
  - 同じ tool・同じ引数・同じ結果が連続したとき、3 回目から結果末尾に「前回と同じ呼び出しで結果も変わっていない。ファイルを編集するか finish を呼べ」という notice を付ける。
  - `--max-repeated-calls`(既定 8)回連続で status `repeated_call` として打ち切る。
  - 位置づけ: モデルを助ける仕組みではなく、情報ゼロの退化ループで残り予算を燃やすのを止めるだけ。呼び出し内容か結果が変われば streak はリセットされる。
- **public-tests の pytest 出力を短く**(`scripts/public_check.py`)
  - `--tb=short -p no:cacheprovider` を追加。既定の長いトレースバックは `requests` / `urllib3` 内部まで辿り、read-only マウントのキャッシュ警告も加わって 12K 文字を超え、末尾 12,000 文字の cap で先頭が欠け、要約行も `FAILED test_health - requests.except...` と切れていた(qwen C01 turn 11)。
- `tests/test_runner.py`: syntax 報告、反復ガード(notice → 打ち切り、streak リセット)を追加(計 18 件)。
- version 0.1.6。

### 所見

- qwen(thinking off、temperature 0)は A00 の 40 turn を **3.7 分**で使い切った(出力 6.5K tok)。速度自体は速い。turn 3 で `read_file` を 6 並列で呼ぶなど tool の使い方は gpt-oss より洗練されている。
- 一方、情報が無いと同じ呼び出しを黙って繰り返す(thinking off の副作用の可能性。(b) の再検討材料)。

## 0.1.5 — 2026-09-21

gpt-oss:20b の本番 run(0.1.4、`--think medium`、`results/20260921T035128086493Z-gpt-oss-20b`)で C04 / C05 が request timeout で死んだことへの対応。

### 変更

- **1 turn の生成上限**(`bench/adapters.py`, `bench/cli.py`)
  - `--max-output-tokens`(既定 8192)を追加し、Ollama `num_predict` / OpenAI `max_tokens` に渡す。
  - 理由: 上限なしだと temperature 0 の thinking モデルはループに入ったとき context を使い切るか timeout するまで生成し続け、どちらでも run 全体が死ぬ。gpt-oss は 1 turn 7〜9 分(12K tok 前後)が珍しくなく、C04 turn 30 と C05 turn 14 が 600 秒で `TimeoutError` → `model_error`。
  - 打ち切られた返答は tool call を含まないので、既存の nudge(「続けるか finish を呼べ」)に乗り、run は続く。
  - context guard の既定値を `context_window − max_output_tokens` に(値は 24576 で変わらず。生成余裕と上限が同じ値になった)。
- `--request-timeout` の既定を 600 → 1200 秒(安全網。8192 tok は 17 tok/s でも 8 分で終わる)。
- `run-config.json` に `max_output_tokens` と `request_timeout_seconds` を記録。
- version 0.1.5。

### gpt-oss:20b 本番 run の結果(0.1.4、ハーネス慣らし。最終データではない)

| Task | 評価 | Capability | Code Health | agent | turns | 所要 |
|---|---|---:|---:|---|---:|---:|
| A00 | error(migration) | 0 | 100 | max_turns | 40 | 18.2m |
| C01 | completed | 100 | 100 | context_exceeded | 22 | 23.4m |
| C02 | completed | 0 | 90 | context_exceeded | 27 | 10.3m |
| C03 | completed | 100 | 100 | context_exceeded | 18 | 9.3m |
| C04 | error(migration) | 0 | 70 | model_error(timeout) | 29 | 17.1m |
| C05 | error(migration) | 0 | 100 | model_error(timeout) | 13 | 10.9m |

Primary Capability Index 24.0。合計 89 分、prompt 1.3M tok / 出力 77K tok。
落ちた課題は全て「app が起動しない」(`fileConfig` 未 import、`uuid` 未 import、migration 失敗)。評価パイプラインは 6 課題すべてで正常(stale image 再発なし、実提出物で 100 点が出る)。

### 方針

毎回ハーネス側の問題が見つかっているので、最も賢いと見込む `qwen3.6:35b-a3b-coding-nvfp4`(最速でもある)で数回回してハーネスを固めてから、確定版で全モデルを再走する。gpt-oss の上記結果は慣らしデータとして扱う。

## 0.1.4 — 2026-09-21

0.1.3 末尾の「未修正の検討点」4 件をすべて反映。採点(`evaluator/`、`scoring.json`、hidden tests)は無変更。

### 変更

- **`write_file` の戻り値**(`bench/tools.py`)
  - unified diff(`+`/`-` 行頭付き、最大 80 行)を返すのをやめ、`created path (N lines)` / `replaced path (N lines)` だけを返す。
  - 理由: モデルが diff 行を引用して `replace_text` の `old` を組み立て、一致せず 4 連続失敗した(試走 #3 turn 10〜19)。
- **tool 引数の検証**(`bench/tools.py` `validate_arguments`)
  - `TOOL_DEFINITIONS` の schema と照合し、未知の引数・必須引数の欠落・型不一致・enum 外・minimum 未満を `error: ...` で返す。未知の引数のときは受け付ける引数名を併記する。明示的な `null` は「未指定」として扱う。
  - 理由: `read_file(line_start=176, line_end=400)` が黙って無視され、常に 1〜400 行が返っていた(試走 #3 で 6 回)。モデルは自分の指示が通ったと信じたまま、コンテキストを浪費していた。
- **`run_check` 出力の縮約**(`bench/tools.py` `condense_check_output`)
  - buildkit の step 行(`#N ...`)はエラーを含むものだけ prefix を外して残す。compose の進捗行(`Container ... Healthy` 等)、echo された docker コマンド、空行を落とす。
  - 実測: 試走 #3 turn 26 の出力 12,007 文字 → 175 文字。`FAILED: Path doesn't exist: '/app/alembic'` はそのまま残る。pip の build 失敗も `error: Multiple top-level packages ...` が残る。
- **thinking 方針(b)の決定**(`config/run.yaml`, `README.md`, `bench/cli.py` の help)
  - gpt-oss の override を `low` → **`medium`**(gpt-oss 自身の既定 effort)。他モデルは `off` のまま。
  - 理由: `low` では 3 ターン目に「時間が無い」と放棄し、実質不戦敗になる(試走 #2)。
- `tests/test_runner.py`: `write_file` の戻り値、引数検証、出力縮約のテストを追加(計 15 件)。
- version 0.1.4。

## 0.1.3 — 2026-09-21

gpt-oss:20b × A00 の試走 #2(`--think low`)、#3(`--think medium`、`results/20260921T023315706640Z-gpt-oss-20b`)で見つかった、**採点結果を無効にするレベルの不具合** 2 件と、context guard の調整。

### 変更

- **stale image の使い回し**(`evaluator/evaluate.py`, `scripts/public_check.py`)— 致命的
  - `compose up -d --build db` は db だけを build し、続く `compose run --rm app alembic upgrade head` と `compose up -d app` は app image を **rebuild しない**。
  - compose の project 名は `sfb-<task>-<workspace dir 名>` で、workspace dir 名は常に `workspace` のため、**image 名が全 run・全モデルで同一**。試走 #1(空の提出物)で build された `sfb-a00-workspace-app:latest` が、#2 以降の全 A00 評価で使い回されていた。
  - `run_check public-tests` も同じ構造で、初回チェック後に追加したファイルが以降のチェックに反映されなかった(#3 では `alembic/` を作った後も「`/app/alembic` が無い」と言われ続け、モデルが 8 ターンを浪費)。
  - 修正: `compose run --build`、`compose up -d --build app`、cleanup で `down -v --rmi local`。
- **スケルトン / 基準実装の `pyproject.toml` が build 不能**(`platform-skeleton/pyproject.toml`, `reference/base/pyproject.toml`)— 致命的
  - setuptools の flat-layout 自動探索が `alembic/` と `stockflow/` を両方 top-level package と見なし、`pip install .` が `Multiple top-level packages discovered` で失敗する。
  - 課題は `alembic/` の作成を要求している(`alembic.ini` の `script_location = alembic`)ので、**仕様どおりに作ると必ず Docker build が壊れる**。`reference/base` 自体も build できず、C トラック全課題が配布時点で `migration failed` になる状態だった。
  - 修正: `[tool.setuptools.packages.find] include = ["stockflow*"]` を両方に追加。
  - 検証: `reference/base` を A00 として評価 → **100/100(6/6)**、C01 として評価 → **25/100(regression 6/6、新規 0/3)**。evaluator は期待どおり動作する。
- **context guard の既定値**(`bench/cli.py`, `bench/agent.py`, `bench/workflow.py`, `config/run.yaml`)
  - 30000 → `context_window − 8192`(32K なら 24576)。
  - 理由: #3 の turn 33 で prompt 26,796 + 出力 5,972 = **32,768 = num_ctx** となり、思考中にウィンドウを使い切って本文も tool call も出せなかった。guard は「切り捨て防止」だけでなく「1 turn 分の生成余裕」も見る必要がある。
- version 0.1.3(`pyproject.toml`, `run.yaml`)。README の context guard 説明を更新。

### 試走 #2 / #3 の所見(採点は stale image のため無効。transcript は有効)

| run | think | agent status | turns | 所要 | 所見 |
|---|---|---|---|---|---|
| #2 | low | `no_tool_call` | 5 | 0.3m | thinking に "Time limited / Time's up" と書いて 3 ターン目で放棄。プロンプトに時間制限は無い。**gpt-oss の `low` は「思考短縮」ではなく「作業放棄」に近い** |
| #3 | medium | `context_exceeded` | 33 | 20.0m | 全ファイルを書き、public-tests を 2 回実行、alembic を追加。診断評価(pyproject 差し替え)では app 起動するが `/health` が 503(`conn.execute("SELECT 1")` を `text()` で包んでいない SQLAlchemy 2.x のバグ)→ 0/100。これはモデル側の正当な失敗 |

#3 の実効速度: prompt 累計 375,671 tok / 出力 21,142 tok / 1,199 s。prefix cache が効いているので、壁時間はほぼ出力 21K tok ÷ 約 26 tok/s ≈ 800 s + tool 実行(docker build 含む)。

### 未修正の検討点(要判断)

1. **`write_file` の戻り値が unified diff**(`+`/`-` 行頭付き)。#3 ではモデルがそれを引用して `replace_text` の `old` を組み立て、4 回連続失敗 → 諦めてファイル丸ごと書き直し(turn 10〜19 を浪費)。plain な確認("wrote path, N lines")に変える案。
2. **tool 引数の未検証**。schema は `additionalProperties: false` だが runner は未知の引数を黙って無視する。#3 では `read_file(line_start=176, line_end=400)` が `start_line`/`end_line` でないため常に 1〜400 行が返り、モデルは気付かないままコンテキストを浪費。未知の引数を error で返して自己修正させる案。
3. **`run_check` の出力ノイズ**。docker build の進捗ログ込みで 12,000 文字(≈ 3〜4K tok)返り、肝心の `FAILED: Path doesn't exist` 1 行が埋もれる。build ログを落として pytest / alembic の出力だけ返す案。
4. **(b) thinking 方針の再考材料**。gpt-oss は `low` だと放棄、`medium` だと 1 ターン最大 6K の思考。「全モデル off、gpt-oss は low」の cohort では gpt-oss が実質不戦敗になる。

## 0.1.2 — 2026-09-21

gpt-oss:20b × A00 の試走(`results/20260921T023103258573Z-gpt-oss-20b`、0.1.1 で実行)で見つかったハーネス不具合の修正。

### 変更

- **tool path の正規化** (`bench/tools.py` `safe_path`)
  - `list_files(path="")` が `invalid path`、`list_files(path="/")` が `path escapes workspace` で弾かれていた。tool 定義では `path` は省略可(`default: "."`)なのに、空文字や `/` でリポジトリ root を指す一般的な呼び方が失敗し、モデルが「ファイルが無い」と誤認して `no_tool_call` 終了していた。
  - 空文字 / `None` / 先頭 `/` は workspace root 相対として扱う。`..` による escape 検査は従来どおり。
- `tests/test_runner.py`: root alias(`""`, `"/"`, `None`)と `/../escape` の拒否を追加(計12件)。

### 試走で確認できたこと

- Docker 評価パイプライン(evaluator image build → compose up → hidden pytest)は Rancher Desktop 上で動作(空提出で 9.8 秒、`migration failed` は正当なエラー)。
- 0.1.1 の終了条件は意図どおり動作(text-only 3 連続で `no_tool_call`、`summary.md` に agent status / turns / duration が出る)。

## 0.1.1 — 2026-09-21

ディレクトリ名を `local-llm-benchmark-v0.1.0/` から `local-llm-benchmark/` に変更し、バージョンはこのファイルで管理する。

runner(ハーネス)の挙動変更。採点(`evaluator/`、`scoring.json`、hidden tests)は変更していない。
背景と判断理由は`NOTES.md` を参照。

### 変更

- **終了条件** (`bench/agent.py`)
  - tool callのない本文だけの返答を「完了」と見なさなくなった。`finish` toolの呼び出しだけが `completed`。
  - 本文だけの返答には "Continue implementing using the tools, or call finish when complete." を返して続行させる。
  - tool callのない返答が連続で `--max-no-tool-turns`(既定3)回に達したら `no_tool_call` で打ち切る。
- **コンテキスト保護** (`bench/agent.py`)
  - 直前の `prompt_tokens + completion_tokens` に、追加されたtool結果の推定トークン数(3文字/token)を足して次のprompt長を見積もる。
  - `--context-guard`(既定30000)を超えたら次のrequestを送らず `context_exceeded` で打ち切る。成果物は通常どおり採点する。
  - transcriptに `context_exceeded` / `no_tool_call` eventを記録。agent結果に `last_prompt_tokens` を追加。
  - `turns` は実際にmodelへrequestした回数になった(従来は打ち切りturnを含んで数えていた)。
- **thinking制御** (`bench/adapters.py`, `bench/cli.py`)
  - `--think {default,off,on,low,medium,high}` を追加。既定は `off`。Ollama `/api/chat` の `think` fieldへ渡す。
  - `default` はfieldを送らずmodelの既定に任せる(従来の挙動)。
  - gpt-ossは `off`(`false`)を無視するため `--think low` で実行する方針(`config/run.yaml` の `thinking_overrides`)。
- **コンテキスト長** (`bench/cli.py`)
  - `--context-window`(既定32768)を追加し、Ollama `num_ctx` へ渡す。
- **記録**
  - `results/<group>/run-config.json` を出力。各 `metadata.json` に `run_config` を追加。
  - `summary.csv` / `summary.md` にagent status、turns、token数、所要時間を追加。
- `config/run.yaml`: `max_no_tool_turns`、`context_guard_tokens`、`thinking`、`thinking_overrides` を追加、`benchmark_version` 0.1.1。
- `README.md`: 終了条件とthinking方針を追記。
- `tests/test_runner.py`: 終了条件3種と `--think` の単体テストを追加(計11件)。

### 実測で確認したOllamaの `think` 挙動(Ollama 0.32.13)

| model | 未指定 | `false` | `true` | `"low"` |
|---|---|---|---|---|
| gpt-oss:20b | 思考あり | **無視(思考あり)** | 思考あり | 思考短縮 |
| qwen3.6:35b-a3b(-coding-nvfp4) | 思考あり(長い) | 思考なし | 思考あり | `true` 扱い |
| north-mini-code-1.0 | 思考あり | 思考なし | 思考あり | `true` 扱い |

## 0.1.0 — 配布時点

配布物そのまま。ローカルでの変更なし。
