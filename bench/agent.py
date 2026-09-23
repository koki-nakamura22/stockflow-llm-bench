from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from bench.adapters import Adapter
from bench.tools import TOOL_DEFINITIONS, RepositoryTools

SYSTEM_PROMPT = """You are a software implementation agent working in an isolated repository.
Use only the provided tools. Read the repository and task, implement the task, run available
public checks, and finish without asking questions. Never access paths outside the workspace,
external networks, hidden tests, evaluators, other runs, or host configuration. Do not modify
benchmark-owned tests or runner files. If a check fails, inspect the result and continue within
the remaining budget. End by calling finish with a concise summary and checks run."""


MALFORMED_TOOL_CALL_MARKERS = (
    "error parsing tool call",          # Ollama, gpt-oss Harmony parser
    "mismatched arg_key and arg_value", # Ollama, GLM parser
    "failed to parse tool call",
    "invalid tool call",
)


def is_malformed_tool_call_error(error: str) -> bool:
    lowered = error.lower()
    return "http 500" in lowered and any(marker in lowered for marker in MALFORMED_TOOL_CALL_MARKERS)


def estimate_tokens(text: str) -> int:
    # Rough upper-bound estimate for text not yet reported by the endpoint (code ~3 chars/token).
    return len(text) // 3 + 1


def parse_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("tool arguments must be an object")


class AgentRunner:
    def __init__(
        self,
        adapter: Adapter,
        tools: RepositoryTools,
        transcript_path: Path,
        max_turns: int = 40,
        max_output_chars: int = 250_000,
        context_guard_tokens: int = 40_960,
        max_no_tool_turns: int = 3,
        max_repeated_calls: int = 8,
    ) -> None:
        self.adapter = adapter
        self.tools = tools
        self.transcript_path = transcript_path
        self.max_turns = max_turns
        self.max_output_chars = max_output_chars
        self.context_guard_tokens = context_guard_tokens
        self.max_no_tool_turns = max_no_tool_turns
        self.max_repeated_calls = max_repeated_calls

    def record(self, event: dict[str, Any]) -> None:
        with self.transcript_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def run(self, task_prompt: str) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt},
        ]
        prompt_tokens = 0
        completion_tokens = 0
        output_chars = 0
        last_prompt_tokens = 0
        estimated_next_prompt = 0
        no_tool_streak = 0
        turns_used = 0
        last_call: tuple[str, str, str] | None = None  # (name, arguments json, result)
        repeat_streak = 0
        started = time.monotonic()
        status = "max_turns"
        error = None
        for turn in range(1, self.max_turns + 1):
            if estimated_next_prompt > self.context_guard_tokens:
                status = "context_exceeded"
                self.record({
                    "type": "context_exceeded", "turn": turn,
                    "last_prompt_tokens": last_prompt_tokens,
                    "estimated_next_prompt_tokens": estimated_next_prompt,
                    "limit": self.context_guard_tokens,
                })
                break
            try:
                reply = self.adapter.chat(messages, TOOL_DEFINITIONS)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if is_malformed_tool_call_error(error):
                    # The model emitted a tool call the server could not parse (Ollama answers
                    # HTTP 500 for that). An OpenAI-compatible server would return it as plain
                    # text, which the loop nudges; treat it the same instead of killing the run.
                    turns_used = turn
                    no_tool_streak += 1
                    self.record({"type": "malformed_tool_call", "turn": turn, "error": error[:500], "streak": no_tool_streak})
                    if no_tool_streak >= self.max_no_tool_turns:
                        status = "no_tool_call"
                        break
                    nudge = (
                        "Your last tool call could not be parsed by the server. Emit it again as a "
                        "single valid tool call whose arguments match the tool schema exactly."
                    )
                    messages.append({"role": "user", "content": nudge})
                    estimated_next_prompt += estimate_tokens(nudge)
                    error = None
                    continue
                status = "model_error"
                self.record({"type": "model_error", "turn": turn, "error": error})
                break
            turns_used = turn
            prompt_tokens += reply.prompt_tokens or 0
            completion_tokens += reply.completion_tokens or 0
            last_prompt_tokens = reply.prompt_tokens or last_prompt_tokens
            estimated_next_prompt = last_prompt_tokens + (reply.completion_tokens or 0)
            message = reply.message
            output_chars += len(json.dumps(message, ensure_ascii=False))
            self.record({"type": "assistant", "turn": turn, "message": message, "usage": {
                "prompt_tokens": reply.prompt_tokens,
                "completion_tokens": reply.completion_tokens,
            }})
            if output_chars > self.max_output_chars:
                status = "output_limit"
                break
            assistant_message = {"role": "assistant", **message}
            messages.append(assistant_message)
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                # Only the finish tool ends a run; a text-only reply is nudged, not accepted.
                no_tool_streak += 1
                if no_tool_streak >= self.max_no_tool_turns:
                    status = "no_tool_call"
                    self.record({"type": "no_tool_call", "turn": turn, "streak": no_tool_streak})
                    break
                nudge = "Continue implementing using the tools, or call finish when complete."
                messages.append({"role": "user", "content": nudge})
                estimated_next_prompt += estimate_tokens(nudge)
                continue
            no_tool_streak = 0
            for index, call in enumerate(tool_calls):
                function = call.get("function", {})
                name = function.get("name", "")
                call_id = call.get("id") or f"turn-{turn}-tool-{index}"
                try:
                    arguments = parse_arguments(function.get("arguments", {}))
                    result = self.tools.execute(name, arguments)
                except Exception as exc:
                    arguments = {}
                    result = f"error: {type(exc).__name__}: {exc}"
                # Degenerate-loop guard: the same call with the same result, over and over, cannot
                # make progress. Say so after a few repeats and stop the run after many.
                signature = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False), result)
                repeat_streak = repeat_streak + 1 if signature == last_call else 1
                last_call = signature
                if repeat_streak >= 3:
                    result += (
                        f"\n\nnotice: this is the same call as the previous {repeat_streak - 1} call(s) and the "
                        "result has not changed. Repeating it will not change anything; edit files "
                        "to address the result, or call finish."
                    )
                self.record(
                    {"type": "tool", "turn": turn, "id": call_id, "name": name, "arguments": arguments, "result": result}
                )
                messages.append({"role": "tool", "tool_call_id": call_id, "content": result})
                estimated_next_prompt += estimate_tokens(result)
                if self.tools.finished:
                    status = "completed"
                    break
                if repeat_streak >= self.max_repeated_calls:
                    status = "repeated_call"
                    self.record({"type": "repeated_call", "turn": turn, "name": name, "streak": repeat_streak})
                    break
            if self.tools.finished or status == "repeated_call":
                break
        return {
            "status": status,
            "error": error,
            "summary": self.tools.summary,
            "turns": turns_used,
            "last_prompt_tokens": last_prompt_tokens or None,
            "prompt_tokens": prompt_tokens or None,
            "completion_tokens": completion_tokens or None,
            "duration_seconds": round(time.monotonic() - started, 3),
        }

