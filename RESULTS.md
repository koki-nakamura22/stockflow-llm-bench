# ベンチマーク結果: cohort "practical settings"

実行日: 2026-09-21〜22
ハーネス: 0.2.1(glm-4.7-flash のみ 0.2.2 で再走)。変更履歴は `CHANGELOG.md`
環境: Apple M5 / 32GB、Ollama 0.32.13(`OLLAMA_FLASH_ATTENTION=1`、`OLLAMA_KV_CACHE_TYPE=q8_0`)、Rancher Desktop(docker 29.5.3)
設定の根拠: `VENDOR_SETTINGS.md` / 速度スクリーニング: `SCREENING.md` / ハーネスの構造: `ARCHITECTURE.md`

実施は 2 ラウンド。**Round 1** = 手持ちの 3 モデル、**Round 2** = 候補 9 モデルのうち速度スクリーニングを通った 6 モデル。合計 **9 モデル / 54 run**。

## 全モデルの結果一覧(Round 1 + Round 2、Index 降順)

| Model | ラウンド | A00 | C01 | C02 | C03 | C04 | C05 | **Index** | Ctrl | Health | finish | 所要 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **ornith:35b**(Qwen3.5-35B-A3B ベースの fine-tune) | 2 | **100** | 100 | 9 | 100 | 100 | 0 | **77.1** | 61.8 | 95.8 | 4/6 | 84 分 |
| laguna-xs-2.1(33B-A3B) | 2 | 0 | 0 | **80** | 100 | 45 | **100** | 39.0 | 65.0 | 95.8 | 1/6 | 104 分 |
| gemma4:26b-a4b | 2 | 0 | 25 | 0 | 100 | 100 | **100** | 39.0 | 65.0 | 95.0 | 3/6 | 99 分 |
| qwen3.6:35b-a3b(Q4_K_M) | 1 | 0 | 70 | 0 | 100 | 100 | 0 | 32.4 | 54.0 | 95.8 | **6/6** | 45 分 |
| gpt-oss:20b | 1 | 0 | 100 | 0 | 100 | 25 | 0 | 27.0 | 45.0 | 91.7 | 0/6 | 86 分 |
| qwen3-coder:30b-a3b(非推論) | 2 | 0 | 25 | 25 | 75 | 100 | 0 | 27.0 | 45.0 | 98.3 | **6/6** | **40 分** |
| nemotron-3.5-lightning(48K) | 2 | 0 | 0 | 9 | 100 | 45 | 56 | 25.2 | 42.0 | 94.2 | 0/6 | 69 分 |
| glm-4.7-flash(0.2.2 で再走) | 2 | 0 | 0 | 9 | 100 | 0 | 48 | 18.8 | 31.4 | 98.3 | 4/6 | 171 分 |
| north-mini-code-1.0 | 1 | 0 | 45 | 0 | 100 | 0 | 0 | 17.4 | 29.0 | 90.8 | 1/6 | 142 分 |

finish = `finish` tool を呼んで自発終了した課題数 / 6。用語の定義は「用語: 課題 ID とスコアの読み方」を参照。

### ベンチにかけなかった候補(速度足切り、`SCREENING.md`)

| Model | 種別 | 64K 条件の生成速度 | 理由 |
|---|---|---:|---|
| qwen3.8:27b | dense 27.3B | 4.6 tok/s | 本番 1 モデルで 3〜5 時間かかる見込み。MTP 版(`27b-mtp-q4_K_M`)なら再考の余地 |
| muse-glimmer:30b | dense 27.9B | 4.7 tok/s | 同上。DFlash 版でも公式値 1.8× = 約 8.5 tok/s で足切り(15)に届かない見込み |
| devstral-small-2:24b | dense 24.0B、非推論 | 5.7 tok/s | 同上 |

- 足切り基準は「64K 条件の生成 15 tok/s 以上」。dense 24〜28B は 100% GPU に載っていても 5 tok/s 前後で、MoE(A3B/A4B)の 7〜10 分の 1。
- さらに別枠で `qwen3.6:35b-a3b-coding-nvfp4` を**生成品質の問題**で除外している(後述の節)。

## 成果物とログの置き場所

モデルが実際に書いたコードは全 run 分が残っている(18 run group / 98 run の workspace、計 7MB)。パスはリポジトリルートからの相対。

```
results/<run group>/
├── run-config.json               実際に使った設定(think / sampling / context / 上限)
├── summary.{json,csv,md}         その run group の集計
└── runs/<model>/<track>/<task>/
    ├── workspace/                ★ モデルが書いたコードそのもの(git リポジトリ、baseline commit 付き)
    ├── submission.patch          baseline からの差分。これ 1 つで成果物を再現できる
    ├── transcript.jsonl          全ターンの会話・tool 呼び出し・結果・トークン数
    ├── prompt.md                 モデルに渡した課題文
    ├── metadata.json             スコア、agent status、turn 数、トークン数、run_config
    ├── evaluator-result.json     hidden test のテスト別 pass/fail と配点 ※Public 版には非同梱
    ├── pytest.xml                同上(JUnit 形式) ※Public 版には非同梱
    ├── test-output.log           Docker 評価の生ログ ※Public 版には非同梱
    └── evaluator-console.log     ※Public 版には非同梱
```

`<track>` は A00 が `zero_to_one`、C01〜C05 が `controlled_cold_change`。
`git -C <workspace> status --short` で「モデルが書いた / 変更したファイル」だけが一覧できる。

| Model | run group(相対パス) |
|---|---|
| ornith:35b | `results/20260922T020250505689Z-ornith-35b-q4_K_M/` |
| laguna-xs-2.1 | `results/20260922T001538744335Z-laguna-xs-2.1-q4_K_M/` |
| gemma4:26b-a4b | `results/20260922T041008933196Z-gemma4-26b-a4b-it-q4_K_M/` |
| qwen3.6:35b-a3b(Round 1) | `results/20260921T125743899479Z-qwen3.6-35b-a3b/` |
| gpt-oss:20b(Round 1) | `results/20260921T161104580146Z-gpt-oss-20b/` |
| qwen3-coder:30b-a3b | `results/20260922T032815288311Z-qwen3-coder-30b-a3b-q4_K_M/` |
| nemotron-3.5-lightning | `results/20260922T055110237564Z-nemotron-3.5-lightning-30b-a3b-q4_K_M/` |
| glm-4.7-flash(0.2.2 再走) | `results/20260922T094641447940Z-glm-4.7-flash-q4_K_M/` |
| north-mini-code-1.0 | `results/20260921T134631626585Z-north-mini-code-1.0-latest/` |

参考(本表の集計には使っていない run):

| 用途 | run group(相対パス) |
|---|---|
| nvfp4 の除外根拠(同条件比較) | `results/20260921T101916568217Z-qwen3.6-35b-a3b-coding-nvfp4/` |
| 揺らぎ比較の 1 回目(qwen3.6、上限 8K) | `results/20260921T114955347212Z-qwen3.6-35b-a3b/` |
| glm-4.7-flash の 0.2.1 run(timeout 多発) | `results/20260922T070249937023Z-glm-4.7-flash-q4_K_M/` |
| ハーネス慣らし(旧 cohort 0.1.x、モデル比較には使わない) | `results/` の 2026-09-21 の gpt-oss / nvfp4 各 run group |

## 用語: 課題 ID とスコアの読み方

### 課題(すべて題材は StockFlow Mini = マルチテナント注文・在庫管理 API。FastAPI / SQLAlchemy 2 / Alembic / PostgreSQL 16)

| ID | Track | 開始点 | 内容 | 配点の内訳 |
|---|---|---|---|---|
| **A00** | Zero-to-One | 空のスケルトン(`platform-skeleton/`) | 商品・注文・キャンセル API を 0 から実装。tenant 分離、明細の価格 snapshot、重複明細の合算、在庫減算と注文作成の単一 transaction、在庫不足時の完全 rollback、同時注文で在庫を負にしない | 新規 6 テスト = 100 点 |
| **C01** | Controlled Cold Change | 基準実装(`reference/base/`) | 注文一覧に cursor ページング。重複なし、改ざん cursor の拒否、filter、tenant 境界 | 新規 75 + A00 regression 25 |
| **C02** | 同上 | 同上 | 冪等性キー(`Idempotency-Key`)。replay で同一レスポンス・在庫減算は 1 回だけ、conflict 検出、tenant scope、同一キーの同時リクエスト | 新規 75 + regression 25 |
| **C03** | 同上 | 同上 | 注文の状態遷移(confirm / ship / cancel)。禁止遷移の拒否、競合遷移で 1 つだけ成功 | 新規 75 + regression 25 |
| **C04** | 同上 | 同上 | outbox パターン。domain transaction と同一 transaction で event 行を作る、失敗時は event を残さない、worker module | 新規 75 + regression 25 |
| **C05** | 同上 | 同上 | rolling migration(expand / contract)。税 10% を `subtotal_amount` / `tax_amount` / `total_amount` に拡張、`make migrate-expand` は旧 app を壊さない、backfill、再実行で二重加算しない | 新規 75 + regression 25 |

- **regression 25 点**は C01〜C05 共通で、A00 の 6 テストを再実行したもの。**変更で既存機能を壊すと、新規テストが全部通っても最大 25 点しか残らない**。逆に app が起動しなければ 0 点。
- Track の記号(A / B / C)は仕様書の定義(A=空から、B=共通の基準実装から、C=自分の A00 成果物から)。本実装では `C01`〜`C05` の既定実行は仕様書の **Track B**(全モデル共通の基準実装から)に当たる。`C` は "Change(変更課題)" の意味。自分の成果物に適用する Track C は `--include-self` を付けたときだけ走る(今回は未実施)。

### スコア

- **Capability**(表の A00〜C05 の数値): hidden test の pass に応じた 0〜100 点。課題ごとに満点 100。
- **Index**(Primary Capability Index)= `0.4 × A00 + 0.6 × (C01〜C05 の平均)`。仕様書が定める主要順位で、Code Health や速度は含めない。
- **Ctrl**(Controlled mean)= C01〜C05 の平均。
- **Code Health**: 構文エラー、最大 cyclomatic complexity、巨大な関数 / モジュール、成果物への不要ファイル混入を静的に採点(0〜100)。順位には使わない。
- **finish**: モデルが `finish` tool を呼んで自発的に終了した課題数 / 6。残りは turn 上限・context guard・エラーによる打ち切り(`ARCHITECTURE.md` の終了条件を参照)。

## 実行条件

| 項目 | 値 |
|---|---|
| thinking | on(gpt-oss は `medium`。off 不可、low は課題を放棄する) |
| sampling | 各ベンダー推奨値。qwen: temp 0.6 / top_p 0.95 / top_k 20 / min_p 0 / presence 0(precise coding)、north-mini: temp 1.0 / top_p 0.95、gpt-oss: temp 1.0 / top_p 1.0 |
| context | 65,536(context guard 40,960) |
| 1 turn の生成上限 | 24,576 tokens |
| turn 上限 | 40 |
| 試行 | 各モデル 1 回(Pass@1)。再現性は下記「揺らぎ」を参照 |

実際に使った値は各 run group の `run-config.json` に記録されている。

## Round 1(2026-09-21、手持ち 3 モデル)

| Model | A00 | C01 | C02 | C03 | C04 | C05 | **Index** | Ctrl mean | Code Health | 所要 | 出力 tok | 実効 tok/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **qwen3.6:35b-a3b**(Q4_K_M) | 0 | 70 | 0 | 100 | 100 | 0 | **32.4** | 54.0 | 95.8 | 45 分 | 50,927 | 18.8 |
| gpt-oss:20b | 0 | 100 | 0 | 100 | 25 | 0 | 27.0 | 45.0 | 91.7 | 86 分 | 82,872 | 16.0 |
| north-mini-code-1.0 | 0 | 45 | 0 | 100 | 0 | 0 | 17.4 | 29.0 | 90.8 | 142 分 | 123,316 | 14.5 |

- Index = 0.4 × A00 + 0.6 × (C01〜C05 の平均)。Code Health は順位に含めない。
- 実効 tok/s = 出力トークン ÷ 壁時間(tool 実行・Docker build の待ちを含む)。
- run group は「成果物とログの置き場所」の表を参照。

### 課題ごとの終了状態

| Model | A00 | C01 | C02 | C03 | C04 | C05 |
|---|---|---|---|---|---|---|
| qwen Q4_K_M | finish | finish | finish | finish | finish | finish |
| gpt-oss | max_turns | ctx_exceeded | max_turns | max_turns | **model_error**(下記) | max_turns |
| north-mini | ctx_exceeded | max_turns | finish | max_turns | max_turns | ctx_exceeded |

## 所見

### 全体

> 以下は Round 1 の 3 モデルだけを見た時点の所見。A00 / C02 / C05 についての「無理」という結論は Round 2 で覆っている(「Round 2 の所見」と「結論」を参照)。

- **A00(0→1 実装)は 3 モデルとも 0 点。** 全員が「ほぼ動くもの」まで書くが、最後の 1 つ(実行時エラー、migration の不備、SyntaxError)を残して app が起動しない。起動しなければ 6 テスト全部落ちるので 0 点になる。このクラスのローカルモデルに、40 turn で FastAPI + SQLAlchemy + Alembic + PostgreSQL のシステムを無人で 0 から立ち上げさせるのは、現時点では無理がある。
- **C02(冪等性キー)と C05(expand/contract migration)は 3 モデルとも 0 点。** 同時実行や旧 schema 互換のような「実システム固有の制約」は、変更課題でも歯が立たない。
- **C03(状態遷移)は 3 モデルとも 100 点。** enum の遷移規則を追加する程度の変更は安定して通る。
- 「起動しない = 0 点」の採点は厳しいが、実運用での「壊れたコードを push した」に相当するので妥当。部分点が欲しい場合は evaluator の設計を変える話になる。

### qwen3.6:35b-a3b(Q4_K_M)— 最有力

- 唯一、**6 課題すべてで `finish` tool を呼んで自発的に終了**した。ターンやコンテキストを使い切らず、「読む → 書く → チェック → 終える」のループが最も整っている。
- 最速(45 分)。tool の使い方も洗練されている(複数ファイルを 1 ターンで並列 read、`run_check` を適切に挟む)。
- 弱点: 変更課題でも app を起動不能にする変更を入れることがある(C02 / C05)。前の run(8K 上限)では C05 が 100 点だったので、実力はあるが安定しない。

### gpt-oss:20b

- C01 は満点だが、**6 課題中 4 課題で 40 turn を使い切る**。細かい `replace_text` を繰り返し、完成に至らない。
- C04 の `model_error` は Ollama 側の問題: モデルが壊れた tool call JSON を出し、Ollama の Harmony パーサが HTTP 500 で request 全体を失敗させた。OpenAI 互換サーバーなら本文として返るだけなので、ハーネスで吸収すべき(0.2.2 で対応予定)。この 1 件がなければ C04 はもう少し進んだ可能性がある。
- gpt-oss は thinking を off にできず、`low` では課題を放棄する(`CHANGELOG.md` 0.1.3)。`medium` で 1 turn 7〜9 分考えることがあり、それが所要時間に出ている。

### north-mini-code-1.0

- 最も遅く(142 分)、最もトークンを使い(123K)、最も低い。探索(`list_files` 11 回、`read_file` 19 回)が多く、実装にたどり着くのが遅い。
- C03 は 100 点だが 40 turn 使い切り(他モデルは 10 turn 前後で `finish`)。「できるが効率が悪い」。
- Cohere の推奨は thinking on + temp 1.0 で、そのとおりに動かしている。

### 揺らぎ(同条件での再実行)

Pass@1 の単発値には幅がある。qwen Q4_K_M を同条件(0.2.0 設定)で 2 回回した結果:

| run | A00 | C01 | C02 | C03 | C04 | C05 | Index |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 回目(上限 8K) | 0 | 45 | 9 | 100 | 100 | 100 | 42.5 |
| 2 回目(上限 24K、本番) | 0 | 70 | 0 | 100 | 100 | 0 | 32.4 |

C05 が 100 ↔ 0 で振れる。**Index で ±10 程度は同じモデルの揺らぎの範囲**と見るべきで、gpt-oss(27.0)と qwen(32.4)の差はこの幅に収まる。順位を確定させるには各モデル 3 回以上が必要(Cohere は 3 seed の平均を採っている)。temperature 0 でも揺らぐことは旧 cohort で確認済み(`CHANGELOG.md` 0.1.7 検証 run)。

## 除外したモデル: qwen3.6:35b-a3b-coding-nvfp4 は使い物にならなかった

`qwen3.6:35b-a3b-coding-nvfp4`(nvfp4 量子化、21GB)は速度が Q4_K_M の約 2 倍(tg 40 vs 26 tok/s)で当初は本命だったが、**コード生成が壊れる**ため cohort から外した。

根拠(`CHANGELOG.md`「nvfp4 vs Q4_K_M 切り分け」、run group `…T101916568217Z-qwen3.6-35b-a3b-coding-nvfp4`):

- Q4_K_M と**同じ重み・同じ sampling・同じ thinking・同じ 64K**で A00 を実行したところ、nvfp4 だけが `stockflow/models.py` を **35 回書き直し**、`__tablename__` の前のインデントが 4 → 7 → 61 → **136 スペース**と自己増幅した。thinking には「同じ間違いを繰り返している、今度こそ正しく書く」と毎回書いてあるのに、生成が直らない。`run_check` は一度も呼ばず 40 turn を使い切った。
- 同条件の Q4_K_M は 14 回の write が 9 ファイルに分散、`run_check` 11 回、最大インデント 16 スペースで正常。
- 旧 cohort(thinking off、temp 0)でも nvfp4 だけが「unindent does not match」の SyntaxError を繰り返し出していた(A00、C02 で確認)。
- C02 / C05 では 3 turn 連続で 8K トークンの thinking を出し切って行動せず(堂々巡り)。同条件の Q4_K_M は 6 課題すべて `finish` に到達。
- 結果: nvfp4 Index 28.0(A00 0 / C01 70 / C02 9 / C03 96 / C04 58 / C05 0)、68 分。Q4_K_M は Index 42.5、50 分。**tok/s で 2 倍速くてもループで溶かし、結局遅い。**

小さな変更課題(C01 / C03 / C04)では普通に動くので「常に壊れる」わけではないが、長いファイルを丸ごと書く・長く考える場面で空白などの連続トークンの分布が崩れる。4bit 浮動小数点量子化(nvfp4)が特定のトークン分布を粗くする症状として説明がつき、整数量子化の Q4_K_M で出ないことと整合する。「たまに壊れる」はコーディングエージェントとしては「使えない」と同義なので除外した。Ollama の nvfp4 実装(Metal)が更新されたら、A00 を 1 本回すだけで再評価できる(`scripts/run_cohort.sh` のコメントアウト行を戻す)。

## Round 2(2026-09-22): スクリーニング通過 6 モデル

`SCREENING.md` で速度足切りを通った 6 モデルを、それぞれのベンダー推奨設定で実行(`scripts/run_cohort_round2.sh`)。ハーネス 0.2.1(glm のみ 0.2.2 で再走)。

スコアは冒頭の「全モデルの結果一覧」にまとめてある。

### 所見

- **ornith:35b が A00(0→1 実装)を通した唯一のモデル**(100/100)。Index 77.1 は 2 位の倍。C01 / C03 / C04 も満点で、落としたのは C02(冪等性、9)と C05(migration、0)だけ。architecture は `qwen35moe` = Qwen3.5-35B-A3B の fine-tune で、Modelfile に "agentic coding assistant" の system prompt が焼き込まれている(ハーネスの system prompt との合成は未検証、`SCREENING.md` 参照)。
- **これまで全モデルが 0 だった C02(冪等性キー)を laguna が 80 点で突破**。C05(expand/contract migration)も laguna / gemma4 が 100 点。Round 1 で「3 モデルとも 0 点」と書いた 2 課題は、モデルを変えれば解けることが分かった。**「このクラスでは無理」ではなく「Round 1 の 3 モデルでは無理だった」が正しい**。
- 非推論モデル(qwen3-coder)は 6/6 で `finish` に到達し 40 分と最速。点は取れないが挙動は安定。
- glm-4.7-flash は 171 分と最遅。A00 は 24K トークンの thinking ターンが 40 分の request timeout に達して切断(長文脈で約 10 tok/s)。**速度スクリーニングは通ったが、長文脈の thinking で実用速度を割る**。
- nemotron は 48K 運用(64K で CPU 溢れ)のため guard 32K に早く到達し、6 課題中 4 課題が `context_exceeded`。
- A00 を通したのは 9 run 中 1 つだけ、C02 は 2 つ、C05 は 3 つ。課題の難度順は A00 > C02 > C05 > C01 ≈ C04 > C03(C03 は 9 run 中 8 つが満点)。

### ハーネス修正(Round 2 中)

- **0.2.2**: Ollama の tool call パースエラー(HTTP 500)を致命扱いせず nudge に変更(gpt-oss C04、glm A00 turn 4 が該当)。`--request-timeout` 1200 → 2400 秒(ornith A00 が 20 分で切られたため)。詳細は `CHANGELOG.md`。

## 結論: 使い物になりそうなモデルと、その理由

### 相対評価: `ornith:35b`(Q4_K_M)— Round 2 で更新

Round 1 では qwen3.6:35b-a3b(Q4_K_M)を推したが、Round 2 の ornith:35b がそれを明確に上回った。

| | ornith:35b | qwen3.6:35b-a3b | laguna / gemma4 |
|---|---|---|---|
| Index | **77.1** | 32.4 | 39.0 |
| A00(0→1) | **100** | 0 | 0 |
| 満点課題 | 4/6 | 2/6 | 2/6 |
| 所要 | 84 分 | 45 分 | 99〜104 分 |
| 自発終了 | 4/6 | **6/6** | 1〜3/6 |

ornith を推す理由: **唯一 0→1 実装を完走し、変更課題も 4 課題中 3 つで満点**。qwen3.6 は速くて行儀が良い(6/6 で `finish`)が、点が取れない。

旧・相対評価(Round 1 のみの比較)は以下。

### (旧)相対評価: `qwen3.6:35b-a3b`(Q4_K_M)

理由は点数そのものより**振る舞い**にある。

| 観点 | qwen Q4_K_M | gpt-oss:20b | north-mini |
|---|---|---|---|
| 自分で作業を終えられるか | **6/6 で `finish`** | 1/6(残りは turn 切れ・context 切れ・エラー) | 1/6 |
| 所要時間(6 課題) | **45 分** | 86 分 | 142 分 |
| 変更課題の満点数 | 2/5(C03、C04) | 2/5(C01、C03) | 1/5(C03) |
| tool の使い方 | 並列 read、適切な `run_check`、無駄が少ない | `replace_text` の細かい試行錯誤で turn を溶かす | 探索過多(`read_file` 19 回等) |
| Code Health | 95.8 | 91.7 | 90.8 |

Index(32.4 vs 27.0)の差は揺らぎの範囲内で、点数だけなら gpt-oss と互角。qwen を推す決め手は「**いつ終わるか予測できる**」こと。gpt-oss は 40 turn を使い切るのが常態で、実務では「いつまで経っても終わらない」に見える。north-mini はできる課題でも 10 倍の時間がかかる。

### 絶対評価: Round 2 で上方修正(ただし条件付き)

Round 1 では「0→1 も実システム固有の制約も全滅」だったが、Round 2 で覆った点がある。

- **0→1 実装**: ornith が 100 点。1 モデル 1 回だけなので再現性は未確認だが、「このクラスでは無理」は言えなくなった。
- **実システム固有の制約**: C02(冪等性)は laguna が 80、C05(migration 互換)は laguna / gemma4 が 100。**モデルを選べば解ける**。
- 残る弱点:
  - 同じモデルが全課題を安定して通すことはない(最高の ornith でも C02 は 9、C05 は 0)。
  - **同条件で結果が振れる**(qwen の C05 が 100 ↔ 0)。同じ変更を頼んで、動いたり壊れたりする(「揺らぎ」の節)。
  - **失敗の仕方が「起動しない」**: import 漏れ、SyntaxError、migration の不備。テストで弾けるが、無人運用なら本番を壊す種類の失敗。

### 使いどころがあるとすれば

ornith:35b なら 0→1 実装も 1 回は通った。ただし 1 モデル 1 回の結果であり、**「レビューなしで任せられる」水準ではない**。現実的な使い方は Round 1 の結論と変わらず、**「小さく閉じた変更を、人がレビューする前提で任せる」**。今回で言えば C03(enum 遷移の追加)や C04(outbox の追加)のクラス。条件は:

- 既存コードと既存テストがあること(0→1 ではない)
- 変更が 1〜3 ファイルに収まること
- 結果を必ず人が読む・CI が回ること

「エージェントに任せて放置」の用途ではない。

### 注意点

- この判断は **32GB Mac で動く 20〜35B クラス、Ollama、1 回実行**という条件下のもの。ornith の A00 100 点も 1 回だけの結果で、再現性は未確認。各モデル 3 回回せば順位は変わりうる(Index ±10 の揺らぎ)。
- 課題は意図的に難しく作ってある(仕様書の目的が「実システム固有の制約を扱えるか」)。一般的なコーディングベンチより厳しい。
- gpt-oss の C04 は Ollama の parse error で run が死んだので、gpt-oss はやや不利を受けている(0.2.2 で直す)。

**一言でまとめると(2026-09-22 更新): 相対的には ornith:35b(Q4_K_M)— 0→1 実装を通した唯一のモデルで Index は 2 位の倍。絶対的には依然「レビュー前提」で、同じモデルが全課題を安定して通すことはない。ただし Round 1 で「このクラスでは無理」と書いた冪等性・migration 互換は、laguna / gemma4 が解いたので撤回する。**

## 次に検討すること

1. ~~ハーネス 0.2.2~~(実施済み)
2. **ornith:35b を 3 回実行して A00 100 点の再現性を確認する**(最優先)
3. コンテキスト長の差分実験(`context_exceeded` になった run だけ 96K で再走。手順は `../NOTES.md` の TODO)
4. 各モデル 3 回実行して幅を出す(1 モデル 40 分〜3 時間 × 3)
5. 足切りした dense 3 本の MTP / DFlash 版の速度を測り、15 tok/s に届けばベンチにかける(`SCREENING.md`)
6. `--include-self`(自分の A00 成果物への変更)は、A00 を通せるモデルが出たので実施する価値が出てきた(Round 1 時点では全員 0 点のため見送っていた)
7. より大きいモデル(32GB に収まる範囲では難しい)か、クラウドのオープンモデルとの比較
