from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List repository files below an optional relative directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 repository file with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1, "default": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Regex search across UTF-8 repository files.",
            "parameters": {
                "type": "object",
                "properties": {"pattern": {"type": "string"}, "path": {"type": "string", "default": "."}},
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or replace one UTF-8 repository file. Parent directories are created.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_text",
            "description": "Replace one exact text occurrence in a UTF-8 repository file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_check",
            "description": "Run a benchmark-controlled check: syntax, compose-config, or public-tests.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "enum": ["syntax", "compose-config", "public-tests"]}},
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Finish the implementation attempt.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "required": ["summary"],
                "additionalProperties": False,
            },
        },
    },
]


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    tool["function"]["name"]: tool["function"]["parameters"] for tool in TOOL_DEFINITIONS
}


def validate_arguments(name: str, arguments: dict[str, Any]) -> str | None:
    """Reject calls that do not match the declared schema so the model can self-correct.

    Silently ignoring unknown keys (e.g. line_start instead of start_line) made the model
    believe its request was honored while it received something else.
    """
    schema = TOOL_SCHEMAS.get(name)
    if schema is None:
        return f"unknown tool {name}"
    properties = schema.get("properties", {})
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        return (
            f"unknown argument(s) for {name}: {', '.join(unknown)}. "
            f"Accepted: {', '.join(properties)}"
        )
    missing = [key for key in schema.get("required", []) if key not in arguments]
    if missing:
        return f"missing required argument(s) for {name}: {', '.join(missing)}"
    for key, value in arguments.items():
        if value is None:  # treat an explicit null as "not provided"
            continue
        spec = properties[key]
        expected = spec.get("type")
        if expected == "string" and not isinstance(value, str):
            return f"argument {key} must be a string"
        if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            return f"argument {key} must be an integer"
        if "enum" in spec and value not in spec["enum"]:
            return f"argument {key} must be one of: {', '.join(spec['enum'])}"
        if "minimum" in spec and isinstance(value, int) and value < spec["minimum"]:
            return f"argument {key} must be >= {spec['minimum']}"
    return None


BUILDKIT_LINE = re.compile(r"^#\d+ (?:\d+\.\d+ )?")
NOISE_PATTERNS = (
    re.compile(r"^\s*(Container|Volume|Network|Image)\s+\S+\s+\S+\s*$"),  # compose progress
    re.compile(r"^\$ docker "),                                          # echoed docker commands
    re.compile(r"^\s*$"),
)
ERROR_HINT = re.compile(r"error|Error|ERROR|FAILED|Traceback|exit code", re.ASCII)


def condense_check_output(output: str) -> str:
    """Drop docker build / compose progress lines so the check result is the pytest or
    migration output, not thousands of characters of image layer noise. Buildkit lines are
    kept only when they carry an error, with their step/timestamp prefix removed."""
    kept: list[str] = []
    for line in output.splitlines():
        if BUILDKIT_LINE.match(line):
            if ERROR_HINT.search(line):
                kept.append(BUILDKIT_LINE.sub("", line))
            continue
        if any(pattern.match(line) for pattern in NOISE_PATTERNS):
            continue
        kept.append(line)
    return "\n".join(kept)


class RepositoryTools:
    def __init__(self, workspace: Path, root: Path) -> None:
        self.workspace = workspace.resolve()
        self.root = root.resolve()
        self.finished = False
        self.summary = ""

    def safe_path(self, relative: str | None) -> Path:
        # Models commonly pass "" or "/" for the repository root; treat both as workspace-relative.
        relative = (relative or "").lstrip("/") or "."
        if "\x00" in relative:
            raise ValueError("invalid path")
        candidate = (self.workspace / relative).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise ValueError("path escapes workspace")
        return candidate

    def execute(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            validation = validate_arguments(name, arguments)
            if validation:
                return f"error: {validation}"
            if name == "list_files":
                return self.list_files(arguments.get("path", "."))
            if name == "read_file":
                return self.read_file(
                    arguments["path"], arguments.get("start_line", 1), arguments.get("end_line")
                )
            if name == "search_text":
                return self.search_text(arguments["pattern"], arguments.get("path", "."))
            if name == "write_file":
                return self.write_file(arguments["path"], arguments["content"])
            if name == "replace_text":
                return self.replace_text(arguments["path"], arguments["old"], arguments["new"])
            if name == "run_check":
                return self.run_check(arguments["name"])
            if name == "finish":
                self.finished = True
                self.summary = arguments["summary"]
                return "finished"
            return f"error: unknown tool {name}"
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"

    def syntax_check(self) -> str:
        """Parse every submission .py file and report each SyntaxError with file, line and source.

        compileall only printed errors to the runner's stdout, so the model saw "syntax: fail"
        with nothing to act on and repeated the same check until its turn budget ran out.
        """
        errors: list[str] = []
        checked = 0
        for path in sorted(self.workspace.rglob("*.py")):
            if any(part in {".git", "benchmark-tests", "__pycache__"} for part in path.parts):
                continue
            checked += 1
            relative = path.relative_to(self.workspace)
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(relative))
            except SyntaxError as exc:
                line = (exc.text or "").rstrip()
                errors.append(f"{relative}:{exc.lineno}:{exc.offset or 0}: {exc.msg}\n    {line}")
            except UnicodeDecodeError as exc:
                errors.append(f"{relative}: not valid UTF-8 ({exc.reason})")
        if errors:
            return f"syntax: fail ({len(errors)} error(s) in {checked} files)\n" + "\n".join(errors)
        return f"syntax: pass ({checked} files)"

    def list_files(self, relative: str) -> str:
        base = self.safe_path(relative)
        if not base.exists():
            return "error: path does not exist"
        files = []
        for path in sorted(base.rglob("*")):
            if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
                files.append(str(path.relative_to(self.workspace)))
                if len(files) >= 500:
                    files.append("... truncated ...")
                    break
        return "\n".join(files)

    def read_file(self, relative: str, start_line: int, end_line: int | None) -> str:
        path = self.safe_path(relative)
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        end = min(end_line or (start_line + 399), len(lines))
        selected = lines[max(0, start_line - 1) : end]
        return "\n".join(f"{number}: {line}" for number, line in enumerate(selected, start_line))

    def search_text(self, pattern: str, relative: str) -> str:
        regex = re.compile(pattern)
        base = self.safe_path(relative)
        matches: list[str] = []
        paths = [base] if base.is_file() else base.rglob("*")
        for path in paths:
            if not path.is_file() or ".git" in path.parts:
                continue
            try:
                for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"{path.relative_to(self.workspace)}:{number}:{line}")
                        if len(matches) >= 200:
                            return "\n".join(matches + ["... truncated ..."])
            except UnicodeDecodeError:
                continue
        return "\n".join(matches)

    def write_file(self, relative: str, content: str) -> str:
        path = self.safe_path(relative)
        if (
            ".git" in path.parts
            or "benchmark-tests" in path.parts
            or path.name in {"compose.yaml", "Dockerfile"}
        ):
            raise ValueError("benchmark-owned path is read-only")
        if len(content.encode("utf-8")) > 1_000_000:
            raise ValueError("file exceeds 1 MB")
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(content, encoding="utf-8")
        # Plain confirmation only: a diff preview led models to quote "+"/"-" prefixed lines
        # back into replace_text, which then never matched.
        action = "replaced" if existed else "created"
        return f"{action} {relative} ({len(content.splitlines())} lines)"

    def replace_text(self, relative: str, old: str, new: str) -> str:
        path = self.safe_path(relative)
        if (
            ".git" in path.parts
            or "benchmark-tests" in path.parts
            or path.name in {"compose.yaml", "Dockerfile"}
        ):
            raise ValueError("benchmark-owned path is read-only")
        content = path.read_text(encoding="utf-8")
        count = content.count(old)
        if count != 1:
            raise ValueError(f"expected exactly one occurrence, found {count}")
        path.write_text(content.replace(old, new), encoding="utf-8")
        return f"replaced text in {relative}"

    def run_check(self, name: str) -> str:
        if name == "syntax":
            return self.syntax_check()
        if name == "compose-config":
            result = subprocess.run(
                ["docker", "compose", "-f", str(self.workspace / "compose.yaml"), "config"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )
            return f"exit={result.returncode}\n{result.stdout[-8000:]}"
        if name == "public-tests":
            result = subprocess.run(
                [
                    os.fspath(Path(os.sys.executable)),
                    os.fspath(self.root / "scripts" / "public_check.py"),
                    "--workspace",
                    os.fspath(self.workspace),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=1800,
                check=False,
            )
            return f"exit={result.returncode}\n{condense_check_output(result.stdout)[-12000:]}"
        raise ValueError(f"unknown check {name}")
