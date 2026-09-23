from __future__ import annotations

import argparse
import ast
import json
import shutil
import sys
from pathlib import Path

from bench.adapters import THINK_CHOICES, make_adapter
from bench.workflow import ROOT, TASKS, run_group


def preflight() -> tuple[bool, dict]:
    scoring = json.loads((ROOT / "evaluator" / "scoring.json").read_text(encoding="utf-8"))
    discovered_tests: set[str] = set()
    for test_file in (ROOT / "evaluator" / "tests").glob("test_*.py"):
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
        discovered_tests.update(
            node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    scoring_names = {name for task in scoring.values() for name in task}
    checks = {
        "python": sys.version,
        "git": shutil.which("git") is not None,
        "docker": shutil.which("docker") is not None,
        "compose_file": (ROOT / "reference" / "base" / "compose.yaml").is_file(),
        "tasks": {task: (ROOT / "tasks" / f"{task}.md").is_file() for task in TASKS},
        "scores": {task: sum(scoring.get(task, {}).values()) for task in TASKS},
        "missing_scored_tests": sorted(scoring_names - discovered_tests),
    }
    valid = (
        checks["git"]
        and checks["docker"]
        and checks["compose_file"]
        and all(checks["tasks"].values())
        and all(value == 100 for value in checks["scores"].values())
        and not checks["missing_scored_tests"]
    )
    return valid, checks


def common_adapter(parser: argparse.ArgumentParser, model_required: bool) -> None:
    parser.add_argument("--adapter", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--base-url")
    parser.add_argument("--model", required=model_required)
    parser.add_argument("--api-key-env")
    parser.add_argument(
        "--request-timeout", type=int, default=2400,
        help="seconds per model request; must cover --max-output-tokens at the model's slowest "
        "long-context speed (24K tokens at 15 tok/s is 27 min) (default: 2400)",
    )
    parser.add_argument(
        "--max-output-tokens", type=int, default=24576,
        help="cap on one turn's generation (Ollama num_predict / OpenAI max_tokens); the context "
        "guard reserves this much headroom. Thinking models restart their reasoning from scratch "
        "when a turn is cut off, so this must hold one full deliberation (default: 24576)",
    )
    parser.add_argument(
        "--think", choices=THINK_CHOICES, default="on",
        help="Ollama thinking mode. gpt-oss ignores 'off'/'on' and takes low/medium/high; use 'medium' there. (default: on)",
    )
    sampling = parser.add_argument_group(
        "sampling",
        "Sent only when given; otherwise the model's Modelfile default applies. Every value used is "
        "recorded in run-config.json. See VENDOR_SETTINGS.md for the per-model cohort values.",
    )
    sampling.add_argument("--temperature", type=float)
    sampling.add_argument("--top-p", type=float)
    sampling.add_argument("--top-k", type=int)
    sampling.add_argument("--min-p", type=float)
    sampling.add_argument("--presence-penalty", type=float)
    sampling.add_argument("--repeat-penalty", type=float)
    sampling.add_argument("--seed", type=int, help="fix the sampler seed (not sent unless given)")
    parser.add_argument("--context-window", type=int, default=32768, help="num_ctx for Ollama")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stockflow-bench")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight")
    models = sub.add_parser("models")
    common_adapter(models, model_required=False)
    run = sub.add_parser("run")
    common_adapter(run, model_required=True)
    run.add_argument("--task", choices=TASKS, default="A00")
    run.add_argument("--all-controlled", action="store_true")
    run.add_argument("--include-self", action="store_true")
    run.add_argument("--max-turns", type=int, default=40)
    run.add_argument(
        "--context-guard", type=int, default=None,
        help="stop with context_exceeded once the next prompt is estimated above this many tokens "
        "(default: context window minus --max-output-tokens)",
    )
    run.add_argument(
        "--max-no-tool-turns", type=int, default=3,
        help="stop with no_tool_call after this many consecutive replies without a tool call",
    )
    run.add_argument(
        "--max-repeated-calls", type=int, default=8,
        help="stop with repeated_call after this many consecutive identical tool calls with identical results",
    )
    run.add_argument("--no-evaluate", action="store_true")
    run.add_argument("--results", type=Path, default=ROOT / "results")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "preflight":
        valid, checks = preflight()
        print(json.dumps({"valid": valid, "checks": checks}, ensure_ascii=False, indent=2))
        return 0 if valid else 1
    sampling = {
        "temperature": args.temperature,
        "top_p": args.top_p,
        "top_k": args.top_k,
        "min_p": args.min_p,
        "presence_penalty": args.presence_penalty,
        "repeat_penalty": args.repeat_penalty,
        "seed": args.seed,
    }
    adapter = make_adapter(
        args.adapter, args.model or "unused", args.base_url, args.request_timeout, args.api_key_env,
        think=args.think, context_window=args.context_window, max_output_tokens=args.max_output_tokens,
        sampling=sampling,
    )
    if args.command == "models":
        print("\n".join(adapter.list_models()))
        return 0
    available = adapter.list_models()
    if args.model not in available:
        print(f"model not found: {args.model}\navailable: {', '.join(available)}", file=sys.stderr)
        return 2
    valid, checks = preflight()
    if not args.no_evaluate and not valid:
        print(json.dumps(checks, ensure_ascii=False, indent=2), file=sys.stderr)
        print("preflight failed; use --no-evaluate only if you intentionally want generation without Docker evaluation", file=sys.stderr)
        return 2
    tasks = TASKS if args.all_controlled else [args.task]
    context_guard = (
        args.context_guard if args.context_guard is not None
        else args.context_window - args.max_output_tokens
    )
    group = run_group(
        adapter,
        args.model,
        tasks,
        args.include_self,
        args.max_turns,
        not args.no_evaluate,
        args.results.resolve(),
        run_config={
            "adapter": args.adapter,
            "think": args.think,
            "sampling": {key: value for key, value in sampling.items() if value is not None},
            "context_window": args.context_window,
            "max_output_tokens": args.max_output_tokens,
            "request_timeout_seconds": args.request_timeout,
            "context_guard_tokens": context_guard,
            "max_no_tool_turns": args.max_no_tool_turns,
            "max_repeated_calls": args.max_repeated_calls,
            "max_turns": args.max_turns,
        },
    )
    print(group)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
