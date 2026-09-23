# ベンダー推奨のサンプリング設定と thinking 方針の根拠

作成: 2026-09-21
目的: ベンチマークの cohort を「thinking off + temperature 0」から「各モデルのベンダー推奨設定 + thinking on」へ切り替える判断の根拠を残す。
関連: `CHANGELOG.md`、`NOTES.md`

## 結論

- Ollama の Modelfile に焼き込まれた `PARAMETER` 値は、各ベンダーの公式 model card の推奨値と **1 つ残らず一致**する。Ollama 独自の値ではない。
- 3 ベンダーとも thinking を既定 on とし、Cohere は「on で最も良く動く」と明記。Qwen は greedy decoding(temperature 0)を**明示的に禁止**している。
- したがって「thinking off + temperature 0」は、3 ベンダーが「こうしないでくれ」と書いている条件であり、「実用できるモデルを知る」目的には不適。

## 1. ローカルで確認した Ollama Modelfile の既定値

`ollama show --modelfile <model>` の `PARAMETER` 行(2026-09-21、Ollama 0.32.13):

| model | temperature | top_p | top_k | min_p | presence_penalty | repeat_penalty |
|---|---:|---:|---:|---:|---:|---:|
| qwen3.6:35b-a3b-coding-nvfp4 | 0.6 | 0.95 | 20 | 0 | 0 | 1 |
| qwen3.6:35b-a3b | 1.0 | 0.95 | 20 | 0 | 1.5 | 1 |
| north-mini-code-1.0:latest | 1.0 | 0.95 | — | — | — | — |
| gpt-oss:20b | 1.0 | — | — | — | — | — |

## 2. ベンダー公式 model card の記述

### Qwen3.6-35B-A3B(Alibaba / Qwen)

出典: https://huggingface.co/Qwen/Qwen3.6-35B-A3B

> Thinking mode for general tasks: `temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=1.5, repetition_penalty=1.0`
> Thinking mode for precise coding tasks: `temperature=0.6, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=0.0, repetition_penalty=1.0`
> Non-thinking (instruct) mode: `temperature=0.7, top_p=0.80, top_k=20, min_p=0.0, presence_penalty=1.5, repetition_penalty=1.0`
> The model operates in thinking mode by default, generating reasoning content before final responses.
> An output length of 32,768 tokens is recommended for most queries.
> For preserving thinking capabilities in long-horizon tasks, a context length of at least 128K tokens is advised.

- `coding-nvfp4` の Modelfile は「precise coding」の値、無印 `35b-a3b` は「general」の値になっている。

### Qwen3 系共通の greedy decoding 警告

出典: https://huggingface.co/Qwen/Qwen3-32B (Best Practices)

> For thinking mode: Use `Temperature=0.6`, `TopP=0.95`, `TopK=20`, and `MinP=0`.
> **DO NOT use greedy decoding**, as it can lead to performance degradation and endless repetitions.
> For non-thinking mode: Use `Temperature=0.7`, `TopP=0.8`, `TopK=20`, and `MinP=0`.

- 本ベンチの temperature 0 run で観測した「`run_check("syntax")` を 24 回連続」「同一内容の `alembic/env.py` を 8 回連続で書く」は、この警告どおりの現象(`CHANGELOG.md` 0.1.6、0.1.7 検証 run、4 周目)。

### gpt-oss-20b(OpenAI)

出典: https://github.com/openai/gpt-oss 、 https://huggingface.co/openai/gpt-oss-20b

> We recommend sampling with `temperature=1.0` and `top_p=1.0`.
> (reasoning effort は) low, medium, high に調整可能。

- reasoning effort の model card 上の既定は medium。gpt-oss は thinking を off にできない(Ollama の `think: false` は無視される。2026-09-21 に実測、`CHANGELOG.md` 0.1.1)。
- `low` では 3 ターン目に「時間が無い」と課題を放棄した(`CHANGELOG.md` 0.1.3 試走 #2)。

### North Mini Code 1.0(Cohere Labs)

出典: https://huggingface.co/CohereLabs/North-Mini-Code-1.0

> We recommend using the following set of sampling parameters for generation: `temperature=1.0`, `top_p=0.95`.
> North Mini Code, similarly as all the other Cohere agent models released to date, supports interleaved thinking and **works best when turned on**. You're strongly encouraged to pass on all the model-generated thinking contents to future agentic steps.
> North-Mini-Code-1.0 supports a context length of 256K & 64K output length.
> We run each benchmark with 3 different seeds and report the average benchmark performance, using temperature=1.0 and top_p=0.95.

- Cohere 自身のベンチマーク手順が「推奨設定 + thinking on + 複数 seed の平均」であり、本ベンチの新 cohort(推奨設定 + 複数回の幅を報告)と同じプロトコル。

## 3. 旧 cohort(thinking off + temperature 0)が model card に反する点

| 旧 cohort | model card の立場 |
|---|---|
| temperature 0(greedy) | Qwen: 明示的に禁止(性能劣化・無限反復) |
| thinking off | Qwen / Cohere: 既定は on。Cohere は「on で最も良く動く」 |
| 32K context | Qwen: 長期タスクは 128K 以上を推奨 |

## 4. 新 cohort(実用条件)— 0.2.0 で実装

| model | think | sampling(CLI で明示) | 出典 |
|---|---|---|---|
| qwen3.6:35b-a3b-coding-nvfp4 | on | temp 0.6 / top_p 0.95 / top_k 20 / min_p 0 / presence 0 / repeat 1 | Qwen "precise coding" |
| qwen3.6:35b-a3b | on | 同上 | Qwen "precise coding"(下記) |
| north-mini-code-1.0 | on | temp 1.0 / top_p 0.95 | Cohere 推奨 |
| gpt-oss:20b | medium | temp 1.0 / top_p 1.0 | OpenAI 推奨。off 不可、low は放棄する |

- **qwen 無印も precise coding 値にする理由**: 課題はコーディングであり、Qwen 自身が「precise coding tasks にはこの値」と指定している。また `coding-nvfp4` タグはテンプレート・system prompt が無印と同一で、Ollama 上の差はサンプリング値と量子化だけ(2026-09-21 に `ollama show --template/--system/--modelfile` で確認。HF の Qwen 公式にも別の coder モデルは存在しない)。両方を同じ値にすれば、2 本の差が **量子化(nvfp4 vs Q4_K_M)だけ**になる。
- **値は Modelfile 既定に任せず CLI で明示する**(`scripts/run_cohort.sh`)。Ollama やモデルの更新で Modelfile 値が変わっても気付けるように、使った値を `results/<group>/run-config.json` に記録する。
- context: **64K**(`OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0`、`launchctl setenv` で設定し Ollama アプリを再起動)。2026-09-21 に 4 モデルとも 64K で 100% GPU を確認(Rancher VM 6GB 稼働中)。Qwen は 128K 以上を推奨するが 32GB では収まらないため、64K が本環境の上限。結果の解釈にこの制約を付記する。
- 再現性: seed は固定せず、同条件で複数回回して幅を報告する。temperature 0 + seed 42 でも MoE + Metal では結果が揺れることを実測済み(`CHANGELOG.md` 0.1.7 検証 run: A00 は 4 周で 4 種類の失敗、C04 は 100 → 58)。Cohere の model card も「3 seed の平均」を採っている。

## 5. 旧 cohort のデータの扱い

`results/` 配下の 2026-09-21 の run(gpt-oss 0.1.4、qwen nvfp4 0.1.5 / 0.1.6 / 0.1.7 / 4 周目途中)は、ハーネスの慣らしと「推奨外設定での挙動」の記録として残す。モデル比較の主データには使わない。

## 追加候補 9 モデルの公式推奨構成

2026-09-22 に調査した 9 モデル(qwen3.8、ornith、muse-glimmer、laguna-xs-2.1、devstral-small-2、glm-4.7-flash、gemma4、nemotron-3.5-lightning、qwen3-coder)の Modelfile 値・公式推奨値・出典は `SCREENING.md` の「各モデルの公式推奨構成」を参照。
