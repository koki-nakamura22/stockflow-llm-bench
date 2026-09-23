from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from bench.adapters import ModelReply, OllamaAdapter, think_value
from bench.agent import AgentRunner
from bench.cli import main as cli_main
from bench.tools import RepositoryTools, condense_check_output
from bench.workflow import run_group


class ScriptedAdapter:
    def __init__(self) -> None:
        self.index = 0
        self.replies = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "1",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": {"path": "stockflow/generated.py", "content": "VALUE = 1\n"},
                        },
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "2",
                        "type": "function",
                        "function": {"name": "finish", "arguments": {"summary": "done"}},
                    }
                ],
            },
        ]

    def chat(self, messages, tools):
        reply = self.replies[self.index]
        self.index += 1
        return ModelReply(reply, {"message": reply}, 10, 5)

    def list_models(self):
        return ["scripted"]


class ReplyListAdapter:
    """Replays fixed assistant messages with configurable token usage."""

    def __init__(self, replies, prompt_tokens=10, completion_tokens=5) -> None:
        self.replies = replies
        self.index = 0
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.seen_messages = []

    def chat(self, messages, tools):
        self.seen_messages.append(list(messages))
        reply = self.replies[min(self.index, len(self.replies) - 1)]
        self.index += 1
        return ModelReply(reply, {"message": reply}, self.prompt_tokens, self.completion_tokens)

    def list_models(self):
        return ["scripted"]


def text_reply(content: str) -> dict:
    return {"role": "assistant", "content": content}


def finish_reply() -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "f", "type": "function", "function": {"name": "finish", "arguments": {"summary": "done"}}}],
    }


class OllamaHandler(BaseHTTPRequestHandler):
    calls = 0

    def log_message(self, format, *args):
        return

    def send_json(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self.send_json({"models": [{"name": "mock-local"}]})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        json.loads(self.rfile.read(length))
        OllamaHandler.calls += 1
        if OllamaHandler.calls == 1:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "write_file",
                        "arguments": {"path": "stockflow/from_http.py", "content": "OK = True\n"},
                    }
                }],
            }
        else:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {"name": "finish", "arguments": {"summary": "done"}}
                }],
            }
        self.send_json({"message": message, "prompt_eval_count": 10, "eval_count": 5})


class OpenAIHandler(OllamaHandler):
    calls = 0

    def do_GET(self):
        if self.path == "/v1/models":
            self.send_json({"data": [{"id": "mock-openai"}]})
            return
        self.send_error(404)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        json.loads(self.rfile.read(length))
        OpenAIHandler.calls += 1
        if OpenAIHandler.calls == 1:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": json.dumps(
                            {"path": "stockflow/from_openai.py", "content": "OK = True\n"}
                        ),
                    },
                }],
            }
        else:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": "call-2",
                    "type": "function",
                    "function": {
                        "name": "finish",
                        "arguments": json.dumps({"summary": "done"}),
                    },
                }],
            }
        self.send_json({
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        })


class ToolsTest(unittest.TestCase):
    def test_path_escape_and_protected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            tools = RepositoryTools(workspace, root)
            self.assertIn("error", tools.execute("write_file", {"path": "../escape", "content": "x"}))
            self.assertIn("error", tools.execute("write_file", {"path": "/../escape", "content": "x"}))
            self.assertIn(
                "read-only",
                tools.execute("write_file", {"path": "compose.yaml", "content": "services: {}"}),
            )

    def test_root_path_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            (workspace / "pkg").mkdir(parents=True)
            (workspace / "pkg" / "a.py").write_text("A = 1\n")
            tools = RepositoryTools(workspace, root)
            expected = tools.execute("list_files", {"path": "."})
            self.assertEqual(expected, "pkg/a.py")
            for alias in ("", "/", None):
                self.assertEqual(tools.execute("list_files", {"path": alias}), expected, repr(alias))
            self.assertEqual(tools.execute("read_file", {"path": "/pkg/a.py"}), "1: A = 1")

    def test_write_file_reports_plainly_without_diff_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            tools = RepositoryTools(workspace, root)
            created = tools.execute("write_file", {"path": "pkg/a.py", "content": "A = 1\nB = 2\n"})
            self.assertEqual(created, "created pkg/a.py (2 lines)")
            replaced = tools.execute("write_file", {"path": "pkg/a.py", "content": "A = 3\n"})
            self.assertEqual(replaced, "replaced pkg/a.py (1 lines)")
            self.assertNotIn("+", created + replaced)

    def test_unknown_or_invalid_arguments_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "a.py").write_text("x\ny\nz\n")
            tools = RepositoryTools(workspace, root)
            result = tools.execute("read_file", {"path": "a.py", "line_start": 2, "line_end": 3})
            self.assertTrue(result.startswith("error: unknown argument(s) for read_file: line_end, line_start"))
            self.assertIn("Accepted: path, start_line, end_line", result)
            self.assertEqual(tools.execute("read_file", {"path": "a.py", "start_line": 2, "end_line": 3}), "2: y\n3: z")
            self.assertIn("missing required", tools.execute("read_file", {}))
            self.assertIn("must be an integer", tools.execute("read_file", {"path": "a.py", "start_line": "2"}))
            self.assertIn("must be one of", tools.execute("run_check", {"name": "lint"}))
            self.assertEqual(tools.execute("list_files", {"path": None}), "a.py")

    def test_syntax_check_reports_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            (workspace / "stockflow").mkdir(parents=True)
            (workspace / "benchmark-tests").mkdir()
            (workspace / "benchmark-tests" / "bad.py").write_text("def (:\n")  # benchmark-owned, ignored
            (workspace / "stockflow" / "ok.py").write_text("x = 1\n")
            tools = RepositoryTools(workspace, root)
            self.assertEqual(tools.execute("run_check", {"name": "syntax"}), "syntax: pass (1 files)")
            (workspace / "stockflow" / "bad.py").write_text("def f():\n    x = 1\n  y = 2\n")
            result = tools.execute("run_check", {"name": "syntax"})
            self.assertTrue(result.startswith("syntax: fail (1 error(s) in 2 files)"))
            self.assertIn("stockflow/bad.py:3:", result)
            self.assertIn("unindent", result)
            self.assertIn("    y = 2", result)

    def test_condense_check_output_keeps_errors_drops_progress(self) -> None:
        raw = "\n".join([
            "$ docker compose -p x up -d --build db",
            "#7 [3/4] COPY . /app",
            "#7 DONE 0.1s",
            "#9 1.227       error: Multiple top-level packages discovered",
            " Container sfb-db-1 Healthy ",
            " Image sfb-app Built ",
            "",
            "FAILED: Path doesn't exist: '/app/alembic'.",
            "2 passed, 1 failed",
        ])
        self.assertEqual(
            condense_check_output(raw).splitlines(),
            [
                "      error: Multiple top-level packages discovered",
                "FAILED: Path doesn't exist: '/app/alembic'.",
                "2 passed, 1 failed",
            ],
        )

    def test_agent_tool_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            (workspace / "stockflow").mkdir(parents=True)
            transcript = root / "transcript.jsonl"
            runner = AgentRunner(
                ScriptedAdapter(), RepositoryTools(workspace, root), transcript, max_turns=4
            )
            result = runner.run("implement")
            self.assertEqual(result["status"], "completed")
            self.assertEqual((workspace / "stockflow" / "generated.py").read_text(), "VALUE = 1\n")
            self.assertEqual(len(transcript.read_text().splitlines()), 4)


class TerminationTest(unittest.TestCase):
    def make_runner(self, adapter, **kwargs):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        workspace = root / "workspace"
        (workspace / "stockflow").mkdir(parents=True)
        return AgentRunner(adapter, RepositoryTools(workspace, root), root / "transcript.jsonl", **kwargs)

    def test_text_only_reply_is_nudged_not_completed(self) -> None:
        adapter = ReplyListAdapter([text_reply("Let me look at the files first."), finish_reply()])
        result = self.make_runner(adapter, max_turns=5).run("implement")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["turns"], 2)
        self.assertEqual(result["summary"], "done")
        nudges = [m for m in adapter.seen_messages[1] if m["role"] == "user"]
        self.assertEqual(len(nudges), 2)  # task prompt + nudge

    def test_consecutive_text_replies_stop_with_no_tool_call(self) -> None:
        adapter = ReplyListAdapter([text_reply("thinking out loud")])
        result = self.make_runner(adapter, max_turns=10, max_no_tool_turns=3).run("implement")
        self.assertEqual(result["status"], "no_tool_call")
        self.assertEqual(result["turns"], 3)
        self.assertEqual(result["summary"], "")

    def test_context_guard_stops_before_next_request(self) -> None:
        adapter = ReplyListAdapter([text_reply("still going")], prompt_tokens=29_000, completion_tokens=1_500)
        result = self.make_runner(adapter, max_turns=10, context_guard_tokens=30_000).run("implement")
        self.assertEqual(result["status"], "context_exceeded")
        self.assertEqual(result["turns"], 1)
        self.assertEqual(result["last_prompt_tokens"], 29_000)
        self.assertEqual(len(adapter.seen_messages), 1)


    def test_repeated_identical_calls_are_flagged_then_stopped(self) -> None:
        check = {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c", "type": "function", "function": {"name": "run_check", "arguments": {"name": "syntax"}}}],
        }
        adapter = ReplyListAdapter([check])
        runner = self.make_runner(adapter, max_turns=20, max_repeated_calls=5)
        result = runner.run("implement")
        self.assertEqual(result["status"], "repeated_call")
        self.assertEqual(result["turns"], 5)
        tool_results = [m["content"] for m in adapter.seen_messages[-1] if m["role"] == "tool"]
        self.assertNotIn("notice:", tool_results[0])
        self.assertNotIn("notice:", tool_results[1])
        self.assertIn("same call as the previous 2 call(s)", tool_results[2])

    def test_repeat_streak_resets_when_call_changes(self) -> None:
        check = {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "c", "type": "function", "function": {"name": "run_check", "arguments": {"name": "syntax"}}}],
        }
        listing = {
            "role": "assistant", "content": "",
            "tool_calls": [{"id": "l", "type": "function", "function": {"name": "list_files", "arguments": {}}}],
        }
        adapter = ReplyListAdapter([check, check, listing, check, check, finish_reply()])
        result = self.make_runner(adapter, max_turns=20, max_repeated_calls=3).run("implement")
        self.assertEqual(result["status"], "completed")


    def test_malformed_tool_call_500_is_nudged_not_fatal(self) -> None:
        class FlakyAdapter(ReplyListAdapter):
            def __init__(self):
                super().__init__([finish_reply()])
                self.calls = 0
            def chat(self, messages, tools):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError('HTTP 500 from model endpoint: {"error":"error parsing tool call: raw=..."}')
                if self.calls == 2:
                    raise RuntimeError('HTTP 500 from model endpoint: {"error":"mismatched arg_key and arg_value counts: 1 keys, 2 values"}')
                return super().chat(messages, tools)
        adapter = FlakyAdapter()
        result = self.make_runner(adapter, max_turns=6).run("implement")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["turns"], 3)
        nudges = [m for m in adapter.seen_messages[-1] if m["role"] == "user" and "could not be parsed" in m["content"]]
        self.assertEqual(len(nudges), 2)

    def test_other_endpoint_errors_are_still_fatal(self) -> None:
        class DeadAdapter(ReplyListAdapter):
            def chat(self, messages, tools):
                raise RuntimeError("model endpoint unavailable: connection refused")
        result = self.make_runner(DeadAdapter([]), max_turns=3).run("implement")
        self.assertEqual(result["status"], "model_error")


class ThinkOptionTest(unittest.TestCase):
    def test_think_mapping(self) -> None:
        self.assertIsNone(think_value(None))
        self.assertIsNone(think_value("default"))
        self.assertIs(think_value("off"), False)
        self.assertIs(think_value("on"), True)
        self.assertEqual(think_value("low"), "low")
        with self.assertRaises(ValueError):
            think_value("maybe")

    def test_ollama_payload_carries_think_and_num_ctx(self) -> None:
        captured = {}

        def fake_request(url, payload, headers, timeout):
            captured.update(payload)
            return {"message": {"role": "assistant", "content": ""}, "prompt_eval_count": 1, "eval_count": 1}

        adapter = OllamaAdapter("m", think="off", context_window=4096)
        with patch("bench.adapters.request_json", fake_request):
            adapter.chat([{"role": "user", "content": "hi"}], [])
        self.assertIs(captured["think"], False)
        self.assertEqual(captured["options"]["num_ctx"], 4096)
        self.assertEqual(captured["options"]["num_predict"], 24576)
        # No sampling given: nothing sent, so the Modelfile default applies.
        self.assertNotIn("temperature", captured["options"])
        self.assertNotIn("seed", captured["options"])

        captured.clear()
        adapter = OllamaAdapter(
            "m", think="on", sampling={"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0,
                                       "presence_penalty": 0, "seed": None, "bogus": 1},
        )
        with patch("bench.adapters.request_json", fake_request):
            adapter.chat([{"role": "user", "content": "hi"}], [])
        self.assertIs(captured["think"], True)
        self.assertEqual(captured["options"]["temperature"], 0.6)
        self.assertEqual(captured["options"]["top_k"], 20)
        self.assertEqual(captured["options"]["min_p"], 0)
        self.assertNotIn("seed", captured["options"])
        self.assertNotIn("bogus", captured["options"])

        captured.clear()
        adapter = OllamaAdapter("m", think="default")
        with patch("bench.adapters.request_json", fake_request):
            adapter.chat([{"role": "user", "content": "hi"}], [])
        self.assertNotIn("think", captured)


class ScoringTest(unittest.TestCase):
    def test_all_tasks_sum_to_100(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scoring = json.loads((root / "evaluator" / "scoring.json").read_text())
        self.assertEqual(set(scoring), {"A00", "C01", "C02", "C03", "C04", "C05"})
        for task, values in scoring.items():
            self.assertEqual(sum(values.values()), 100, task)

    def test_generation_only_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            group = run_group(
                ScriptedAdapter(),
                "scripted",
                ["A00"],
                include_self=False,
                max_turns=4,
                evaluate_submission=False,
                results_root=Path(temporary),
            )
            summary = json.loads((group / "summary.json").read_text())
            self.assertEqual(len(summary["runs"]), 1)
            self.assertEqual(summary["runs"][0]["evaluator_status"], "not_evaluated")
            self.assertTrue((group / "summary.md").is_file())
            self.assertTrue(
                (group / "runs" / "scripted" / "zero_to_one" / "A00" / "submission.patch").is_file()
            )

    def test_ollama_cli_generation_only(self) -> None:
        OllamaHandler.calls = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), OllamaHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                argv = [
                    "stockflow-bench", "run", "--adapter", "ollama",
                    "--base-url", f"http://127.0.0.1:{server.server_port}",
                    "--model", "mock-local", "--task", "A00", "--max-turns", "4",
                    "--think", "medium", "--temperature", "0.6", "--top-p", "0.95", "--top-k", "20",
                    "--no-evaluate", "--results", temporary,
                ]
                with patch.object(sys, "argv", argv):
                    self.assertEqual(cli_main(), 0)
                summaries = list(Path(temporary).glob("*/summary.json"))
                self.assertEqual(len(summaries), 1)
                summary = json.loads(summaries[0].read_text())
                self.assertEqual(summary["runs"][0]["agent"]["status"], "completed")
                config = json.loads((summaries[0].parent / "run-config.json").read_text())
                self.assertEqual(config["think"], "medium")
                self.assertEqual(config["sampling"], {"temperature": 0.6, "top_p": 0.95, "top_k": 20})
                self.assertEqual(config["context_guard_tokens"], 32768 - 24576)
        finally:
            server.shutdown()
            server.server_close()

    def test_openai_cli_generation_only(self) -> None:
        OpenAIHandler.calls = 0
        server = ThreadingHTTPServer(("127.0.0.1", 0), OpenAIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                argv = [
                    "stockflow-bench", "run", "--adapter", "openai",
                    "--base-url", f"http://127.0.0.1:{server.server_port}/v1",
                    "--model", "mock-openai", "--task", "A00", "--max-turns", "4",
                    "--no-evaluate", "--results", temporary,
                ]
                with patch.object(sys, "argv", argv):
                    self.assertEqual(cli_main(), 0)
                summaries = list(Path(temporary).glob("*/summary.json"))
                self.assertEqual(len(summaries), 1)
                summary = json.loads(summaries[0].read_text())
                self.assertEqual(summary["runs"][0]["agent"]["status"], "completed")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
