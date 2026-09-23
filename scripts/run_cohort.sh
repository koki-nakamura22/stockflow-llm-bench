#!/usr/bin/env bash
# Run the "practical settings" cohort: every model at its vendor-recommended sampling values with
# thinking on and a 64K context. Values and their sources: VENDOR_SETTINGS.md
#
# Usage: scripts/run_cohort.sh [extra bench.cli args, e.g. --task A00]
# Requires: Ollama with OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 (64K must fit on GPU),
#           docker on PATH, Python 3.11+ as $PY (default: pyenv 3.12.14).
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-$HOME/.pyenv/versions/3.12.14/bin/python}"
CTX="${CTX:-65536}"
MAXOUT="${MAXOUT:-24576}"   # one turn must hold a full deliberation; thinking restarts if cut off
EXTRA=("$@")

run() { # model think sampling-args...
  local model="$1" think="$2"; shift 2
  echo "=== $model (think=$think $*) ==="
  "$PY" -m bench.cli run --adapter ollama --model "$model" --think "$think" \
    --context-window "$CTX" --max-output-tokens "$MAXOUT" "$@" --all-controlled ${EXTRA[@]+"${EXTRA[@]}"}
}

# Qwen3.6-35B-A3B "precise coding" values. Only the Q4_K_M tag is run: under identical settings the
# nvfp4 tag alone degenerates (indentation self-amplification, 136 leading spaces; see CHANGELOG
# "nvfp4 vs Q4_K_M"). Re-enable it here if a newer Ollama fixes nvfp4 on Metal.
QWEN_CODING=(--temperature 0.6 --top-p 0.95 --top-k 20 --min-p 0 --presence-penalty 0 --repeat-penalty 1)
run qwen3.6:35b-a3b              on "${QWEN_CODING[@]}"
# run qwen3.6:35b-a3b-coding-nvfp4 on "${QWEN_CODING[@]}"   # excluded 2026-09-21
# Cohere North Mini Code: recommended temperature=1.0, top_p=0.95, thinking on
run north-mini-code-1.0:latest   on --temperature 1.0 --top-p 0.95
# OpenAI gpt-oss: recommended temperature=1.0, top_p=1.0; reasoning effort medium (cannot be off)
run gpt-oss:20b                  medium --temperature 1.0 --top-p 1.0
