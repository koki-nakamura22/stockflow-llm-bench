# 候補モデルの速度スクリーニング(2026-09-22)

目的: 候補 9 モデルを本番ベンチマーク(6 課題、1 モデル 1〜2.5 時間)にかけるか、速度で足切りする。
環境: Apple M5 / 32GB、Ollama 0.32.13(`OLLAMA_FLASH_ATTENTION=1`、`OLLAMA_KV_CACHE_TYPE=q8_0`)、llmfit 1.1.10。
生データ: `screening-2026-09-22.json`

## 計測方法

- 量子化は全部 **Q4_K_M**(nvfp4 は `RESULTS.md` のとおり除外。MTP / DFlash 版は素の Q4_K_M で足切りしてから別途)
- **llmfit bench**(`llmfit bench <model> --provider ollama --runs 3`): 短い prompt・既定 context のベストケース tok/s と TTFT
- **64K 条件**(本番と同じ): `num_ctx=65536` で読み込み、`ollama ps` で GPU 搭載率を確認、約 5K トークンの prompt で pp(prompt 処理)/ tg(生成)tok/s を計測
- capabilities は `ollama show`(ハーネスは `tools` 必須)

## 結果

| 優先 | Ollama tag | arch | params | thinking | llmfit tok/s(短) | 64K GPU | pp 64K | **tg 64K** | 判定 |
|---:|---|---|---:|---|---:|---|---:|---:|---|
| 1 | `qwen3.8:27b-q4_K_M` | qwen35(dense) | 27.3B | on | 6.7 | 18 GB 100% | 105 | **4.6** | かけない(遅すぎ) |
| 2 | `ornith:35b-q4_K_M` | qwen35moe | 34.7B | on | 30.4 | 22 GB 100% | 663 | **40.0** | かける |
| 3 | `muse-glimmer:30b-q4_K_M` | muse-glimmer(dense) | 27.9B | on | 5.2 | 17 GB 100% | 80 | **4.7** | かけない(遅すぎ) |
| 4 | `laguna-xs-2.1:q4_K_M` | laguna(MoE) | 33.4B | on | 36.4 | 20 GB 100% | 571 | **46.5** | かける |
| 5 | `devstral-small-2:24b-instruct-2512-q4_K_M` | mistral3(dense) | 24.0B | なし | 5.7 | 20 GB 100% | 115 | **5.7** | かけない(遅すぎ) |
| 6 | `glm-4.7-flash:q4_K_M` | glm4moelite | 29.9B | on | 25.4 | 20 GB 100% | 249 | **20.6** | かける(境界) |
| 7 | `gemma4:26b-a4b-it-q4_K_M` | gemma4(MoE) | 25.8B | on | 26.0 | 17 GB 100% | 553 | **34.7** | かける |
| 8 | `nemotron-3.5-lightning:30b-a3b-q4_K_M` | nemotron_h_moe | 32.9B | on | 28.3 | 26 GB **3% CPU** | 591 | 31.6 | かける(**48K** で 25 GB 100% GPU、tg 24.5) |
| 9 | `qwen3-coder:30b-a3b-q4_K_M` | qwen3moe | 30.5B | なし | 40.2 | 21 GB 100% | 459 | **36.7** | かける |

参考(現行): `qwen3.6:35b-a3b` Q4_K_M は 64K・FA 有りで llmfit 43.5 tok/s。本番 6 課題は 45 分。

## 足切り基準

1. `tools` 対応 — 9 本とも OK
2. 64K で 100% GPU — nemotron のみ 3% CPU 溢れ。48K なら収まる(25 GB)ので 48K で運用
3. **64K 条件の tg ≥ 15 tok/s** — 本番の壁時間は「出力トークン ÷ tg」が支配的。現行 qwen(実効 18.8 tok/s)で 45 分なので、5 tok/s 台だと **1 モデル 3〜5 時間**、40 turn の課題は 1 課題で 1 時間を超える

## 所見

- **dense 24〜28B は一律 5 tok/s 前後**(qwen3.8、muse-glimmer、devstral)。100% GPU に乗っていても遅く、16K context でも変わらない(qwen3.8 で 4.4)。M5 の Metal で dense をこのサイズで回すのは帯域律速で、MoE(A3B/A4B)との差は 7〜10 倍
- SWE-bench Pro で最有力だった qwen3.8:27b は、この環境では速度で落ちる。**MTP 版(`qwen3.8:27b-mtp-q4_K_M`)と muse-glimmer の DFlash 版(`30b-q4_K_M-dflash`)は投機的デコードで dense の tg を上げる可能性がある**ので、これらだけ追加で速度を測る価値がある(品質は変わらない設計なので、速度が 15 tok/s に届けば「かける」に戻せる)
- ornith は architecture が `qwen35moe` = Qwen3.5-35B-A3B ベースの fine-tune(表の「開発元不明」の補足)
- devstral-small-2 と qwen3-coder は `thinking` なし(非推論モデル)。cohort の「thinking on」は適用できないので、そのまま推奨 sampling で回す
- glm-4.7-flash は MoE なのに 20 tok/s と他の半分。境界だが 1 モデル 1.5〜2 時間程度なので「かける」

## 判定

**かける(6)**: ornith、laguna-xs-2.1、qwen3-coder、gemma4 26b-a4b、nemotron-3.5-lightning(48K)、glm-4.7-flash
**かけない(3)**: qwen3.8:27b、muse-glimmer:30b、devstral-small-2 — ただし MTP / DFlash 版の速度次第で再考

各モデルのベンダー推奨 sampling は本番前に `VENDOR_SETTINGS.md` と同じ手順で確認する(`ollama show --modelfile` + model card)。

## 各モデルの公式推奨構成(2026-09-22 調査)

Ollama の Modelfile 値(`ollama show --modelfile`)と、ベンダー公式 model card の記述を突き合わせた。「本番で使う値」は、コーディング / エージェント用途の推奨があればそれを優先し、無ければ一般推奨値。

| Ollama tag | Modelfile の値 | 公式推奨(出典) | thinking | 本番で使う値 |
|---|---|---|---|---|
| `qwen3.8:27b-q4_K_M` | temp 1.0 / top_p 0.95 / top_k 20 / min_p 0 / presence 0 | thinking: temp 1.0 / top_p 0.95 / top_k 20 / min_p 0 / presence 0。non-thinking: temp 0.7 / top_p 0.8 / presence 1.5。`reasoning_effort` は xhigh(既定)/ medium / low。エージェント用途は出力を大きく取れ(reasoning 最大 262K) | 既定 on | Modelfile どおり。速度で除外中 |
| `ornith:35b-q4_K_M` | temp 0.6 / top_p 0.95 / top_k 20 + **system prompt 付き**("You are Ornith, an open-source agentic coding assistant. Think step by step…") | 一般: temp 0.6 / top_p 0.95 / top_k 20。ベンチ再現: temp 1.0 / top_p 0.95(OpenHands、256K)。ベースは Qwen3.5 + Gemma4 の継続事前学習 | 既定 on(`<think>` ブロック) | **temp 0.6 / top_p 0.95 / top_k 20**。Modelfile の system prompt はハーネスの system prompt と競合するので注意(下記) |
| `muse-glimmer:30b-q4_K_M` | temp 1.0 / top_k 64 / top_p 0.95 | temp 1.0 / top_p 0.95 / top_k 64。reasoning strength は system prompt に `Reasoning strength: high` 等で指定、コーディング / エージェントは high か xhigh 推奨。DFlash で M5 Max 1.8×(26.6 → 50.2 tok/s) | system prompt で制御 | Modelfile どおり + `Reasoning strength: high`。速度で除外中(DFlash 版は要計測) |
| `laguna-xs-2.1:q4_K_M` | **PARAMETER 無し**(Ollama 既定 temp 0.8 / top_p 0.9 / top_k 40 になる) | **temp 1.0 / top_k 20 / top_p 1.0**、thinking on、256K。全ベンチをこの値で実行(Harbor harness、最大 500 step)。過去ターンの reasoning を履歴に残すこと | 既定 on(`enable_thinking`) | **temp 1.0 / top_k 20 / top_p 1.0 を CLI で明示**(Modelfile に無いので必須) |
| `devstral-small-2:24b-instruct-2512-q4_K_M` | temp 0.15 | **temp 0.15**。`CHAT_SYSTEM_PROMPT.txt` を system prompt に使う(エージェント用)。256K。Mistral Vibe / OpenHands 等で使う想定 | **なし**(非推論) | temp 0.15。速度で除外中 |
| `glm-4.7-flash:q4_K_M` | temp 1.0 / top_p 0.95 / min_p 0.01 | 既定: temp 1.0 / top_p 0.95。**コーディング / エージェント: temp 0.7 / top_p 1.0 / max_new_tokens 16384**(SWE-bench 59.2 はこの値) | "Preserved Thinking" あり | **temp 0.7 / top_p 1.0**(コーディング推奨値) |
| `gemma4:26b-a4b-it-q4_K_M` | temp 1.0 / top_k 64 / top_p 0.95 | temp 1.0 / top_p 0.95 / top_k 64。thinking は system prompt 先頭の `<|think|>` トークンで有効化。256K | トークンで制御(Ollama は `think` field で対応) | Modelfile どおり、think on |
| `nemotron-3.5-lightning:30b-a3b-q4_K_M` | temp 1.0 / top_p 0.95 / **draft_num_predict 2**(MTP 自己投機デコードが既定で有効) | temp 1.0 / top_p 0.95。reasoning は `enable_thinking` で制御、既定 on。MTP 層内蔵、外部 drafter(DSpark / DFlash)あり。SWE-bench 51.56 は BF16 | 既定 on | Modelfile どおり、**48K**(64K は 3% CPU 溢れ) |
| `qwen3-coder:30b-a3b-q4_K_M` | temp 0.7 / top_p 0.8 / top_k 20 / repeat_penalty 1.05 | **temp 0.7 / top_p 0.8 / top_k 20 / repetition_penalty 1.05**、出力 65,536 推奨、256K | **なし**(非推論専用) | Modelfile どおり |

### 気づいた点

- **laguna は Modelfile に PARAMETER が無い**。何も渡さないと Ollama の既定(temp 0.8 / top_k 40)で動き、公式推奨(temp 1.0 / top_k 20 / top_p 1.0)とずれる。本ハーネスは値を CLI で明示して `run-config.json` に記録する方式なので問題ないが、「Modelfile 既定に任せる」運用だと踏む
- **ornith は Modelfile に system prompt が焼き込まれている**。ハーネスは自前の system prompt を送るので、Ollama 側でどう合成されるか(置換か連結か)を本番前に 1 回確認する。他モデルと条件を揃えるなら、ハーネスの system prompt が優先されるべき
- **nemotron は Ollama タグの既定で MTP(draft_num_predict 2)が有効**。スクリーニングの 31.6 tok/s はこれ込みの値。他モデルは素の Q4_K_M なので、速度比較としては nemotron が有利な条件になっている(品質には影響しない設計)
- **qwen3.8 の reasoning_effort 既定は xhigh**。Ollama の `think` field が low / medium / high をどう対応させるかは要確認(gpt-oss と同じ扱いになる可能性)
- muse-glimmer の DFlash は M5 Max で 1.8× と公式が言っている。本環境の 4.7 tok/s × 1.8 ≈ 8.5 tok/s で、足切り(15)には届かない見込み。qwen3.8 の MTP 版も同程度の伸びなら同様
- 非推論モデル(devstral、qwen3-coder)は cohort の "thinking on" が適用できない。「ベンダー推奨のまま」で揃える

### 出典

- Qwen3.8-27B: https://huggingface.co/Qwen/Qwen3.8-27B
- Ornith-1.5-35B-A3B: https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B (温度の食い違いは https://huggingface.co/ornith-ai/Ornith-1.5-35B-A3B/discussions/4)
- Muse Glimmer 30B: https://huggingface.co/meta-models/Muse-Glimmer-30B
- Laguna XS 2.1: https://huggingface.co/poolside/Laguna-XS-2.1
- Devstral Small 2: https://huggingface.co/mistralai/Devstral-Small-2-24B-Instruct-2512
- GLM-4.7-Flash: https://huggingface.co/zai-org/GLM-4.7-Flash
- Gemma 4 26B-A4B: https://huggingface.co/google/gemma-4-26b-a4b-it
- Nemotron 3.5 Lightning: https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16
- Qwen3-Coder-30B-A3B: https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct
