#!/usr/bin/env bash
# Round 2: the 6 candidates that passed the speed screening (SCREENING.md), each at its
# vendor-recommended sampling values ("本番で使う値" table in SCREENING.md), thinking on where the
# model has it, 64K context (nemotron: 48K, it spills to CPU at 64K).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-$HOME/.pyenv/versions/3.12.14/bin/python}"
EXTRA=("$@")

run() { # model think ctx maxout sampling-args...
  local model="$1" think="$2" ctx="$3" maxout="$4"; shift 4
  echo "=== $model (think=$think ctx=$ctx maxout=$maxout $*) ==="
  "$PY" -m bench.cli run --adapter ollama --model "$model" --think "$think" \
    --context-window "$ctx" --max-output-tokens "$maxout" "$@" --all-controlled ${EXTRA[@]+"${EXTRA[@]}"}
}

# Laguna XS 2.1: Modelfile has no PARAMETERs; official temp 1.0 / top_k 20 / top_p 1.0, thinking on
run laguna-xs-2.1:q4_K_M                  on  65536 24576 --temperature 1.0 --top-k 20 --top-p 1.0
# Ornith 1.5: official general temp 0.6 / top_p 0.95 / top_k 20, thinking on
run ornith:35b-q4_K_M                     on  65536 24576 --temperature 0.6 --top-p 0.95 --top-k 20
# Qwen3-Coder: non-thinking; official temp 0.7 / top_p 0.8 / top_k 20 / repetition_penalty 1.05
run qwen3-coder:30b-a3b-q4_K_M            off 65536 24576 --temperature 0.7 --top-p 0.8 --top-k 20 --repeat-penalty 1.05
# Gemma 4 26B-A4B: official temp 1.0 / top_p 0.95 / top_k 64, thinking on
run gemma4:26b-a4b-it-q4_K_M              on  65536 24576 --temperature 1.0 --top-p 0.95 --top-k 64
# Nemotron 3.5 Lightning: official temp 1.0 / top_p 0.95, reasoning on; 48K (64K spills to CPU)
run nemotron-3.5-lightning:30b-a3b-q4_K_M on  49152 16384 --temperature 1.0 --top-p 0.95
# GLM-4.7-Flash: official coding/agentic values temp 0.7 / top_p 1.0, thinking on
run glm-4.7-flash:q4_K_M                  on  65536 24576 --temperature 0.7 --top-p 1.0
