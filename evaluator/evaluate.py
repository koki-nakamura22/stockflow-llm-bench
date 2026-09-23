from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVALUATOR = ROOT / "evaluator"
SCORING = json.loads((EVALUATOR / "scoring.json").read_text(encoding="utf-8"))


def run(command: list[str], log, cwd: Path | None = None, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    log.write(f"$ {' '.join(command)}\n")
    log.flush()
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    log.write(result.stdout)
    log.write(f"\n[exit={result.returncode}]\n")
    log.flush()
    return result


def project_name(workspace: Path, task: str) -> str:
    raw = f"sfb-{task.lower()}-{workspace.name.lower()}"
    return re.sub(r"[^a-z0-9_-]", "-", raw)[-50:]


def code_health(workspace: Path) -> dict[str, Any]:
    python_files = [
        path
        for path in workspace.rglob("*.py")
        if not any(part in {".venv", "alembic", "tests", "public-tests"} for part in path.parts)
    ]
    syntax_errors = 0
    max_complexity = 0
    oversized_functions = 0
    oversized_modules = 0
    for path in python_files:
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError):
            syntax_errors += 1
            continue
        if len(source.splitlines()) > 500:
            oversized_modules += 1
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                end = getattr(node, "end_lineno", node.lineno)
                if end - node.lineno + 1 > 120:
                    oversized_functions += 1
                complexity = 1 + sum(
                    isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.Match))
                    for child in ast.walk(node)
                )
                max_complexity = max(max_complexity, complexity)
    syntax_score = max(0, 30 - 30 * syntax_errors)
    complexity_score = 30 if max_complexity <= 10 else 20 if max_complexity <= 15 else 10 if max_complexity <= 20 else 0
    size_score = max(0, 20 - 5 * oversized_functions - 3 * oversized_modules)
    forbidden = [
        path
        for path in workspace.rglob("*")
        if path.is_file()
        and (path.name in {".env", "id_rsa"} or ".venv" in path.parts or path.suffix in {".db", ".sqlite"})
    ]
    hygiene_score = 20 if not forbidden else 0
    total = syntax_score + complexity_score + size_score + hygiene_score
    return {
        "score": float(total),
        "max_score": 100.0,
        "metrics": {
            "python_files": len(python_files),
            "syntax_errors": syntax_errors,
            "max_complexity": max_complexity,
            "oversized_functions": oversized_functions,
            "oversized_modules": oversized_modules,
            "forbidden_artifacts": [str(path.relative_to(workspace)) for path in forbidden],
        },
    }


def parse_junit(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    outcomes: dict[str, bool] = {}
    for case in root.iter("testcase"):
        name = case.attrib.get("name", "")
        failed = case.find("failure") is not None or case.find("error") is not None
        skipped = case.find("skipped") is not None
        outcomes[name] = not failed and not skipped
    return outcomes


def capability(task: str, outcomes: dict[str, bool]) -> dict[str, Any]:
    weights: dict[str, float] = SCORING[task]
    items = [
        {"id": name, "points": points, "passed": bool(outcomes.get(name)), "score": points if outcomes.get(name) else 0}
        for name, points in weights.items()
    ]
    score = sum(item["score"] for item in items)
    return {"score": score, "max_score": 100, "items": items}


def evaluate(workspace: Path, task: str, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    log_path = output / "test-output.log"
    junit_path = output / "pytest.xml"
    project = project_name(workspace, task)
    compose = ["docker", "compose", "-p", project, "-f", str(workspace / "compose.yaml")]
    started = time.monotonic()
    status = "completed"
    error: str | None = None
    with log_path.open("w", encoding="utf-8") as log:
        try:
            build = run(["docker", "build", "-t", "stockflow-bench-evaluator:0.1", str(EVALUATOR)], log)
            if build.returncode != 0:
                raise RuntimeError("evaluator image build failed")
            if run(compose + ["up", "-d", "--build", "db"], log, timeout=1200).returncode != 0:
                raise RuntimeError("database startup failed")
            migration_command = ["make", "migrate-expand"] if task == "C05" else ["alembic", "upgrade", "head"]
            # --build: the app image name is shared across runs (project name derives from the
            # workspace dir name), so a stale image from an earlier run would otherwise be reused.
            if run(compose + ["run", "--build", "--rm", "app"] + migration_command, log, timeout=1200).returncode != 0:
                raise RuntimeError("migration failed")
            if run(compose + ["up", "-d", "--build", "app"], log, timeout=1200).returncode != 0:
                raise RuntimeError("application startup failed")
            network_result = run(
                [
                    "docker",
                    "network",
                    "ls",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--format",
                    "{{.Name}}",
                ],
                log,
            )
            networks = [line.strip() for line in network_result.stdout.splitlines() if line.strip()]
            if not networks:
                raise RuntimeError("compose network not found")
            test_files = ["/evaluator/tests/test_a00.py"]
            if task != "A00":
                test_files.append(f"/evaluator/tests/test_{task.lower()}.py")
            command = [
                "docker",
                "run",
                "--rm",
                "--network",
                networks[0],
                "-e",
                "BASE_URL=http://app:8000",
                "-e",
                "EVALUATOR_DATABASE_URL=postgresql://stockflow:stockflow@db:5432/stockflow",
                "-e",
                f"TASK_ID={task}",
                "-v",
                f"{EVALUATOR / 'tests'}:/evaluator/tests:ro",
                "-v",
                f"{workspace}:/submission:ro",
                "-v",
                f"{output}:/output",
                "stockflow-bench-evaluator:0.1",
                "-q",
                *test_files,
                "--junitxml=/output/pytest.xml",
            ]
            run(command, log, timeout=1800)
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            status = "error"
            error = str(exc)
        finally:
            try:
                run(compose + ["down", "-v", "--rmi", "local", "--remove-orphans"], log, timeout=300)
            except Exception as cleanup_error:
                log.write(f"cleanup error: {cleanup_error}\n")
    outcomes = parse_junit(junit_path)
    result = {
        "schema_version": "1.0",
        "task_id": task,
        "status": status,
        "error": error,
        "capability": capability(task, outcomes),
        "code_health": code_health(workspace),
        "tests": {"outcomes": outcomes, "passed": sum(outcomes.values()), "total": len(outcomes)},
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    (output / "evaluator-result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--task", choices=sorted(SCORING), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if shutil.which("docker") is None:
        print("docker is required", file=sys.stderr)
        return 2
    result = evaluate(args.workspace.resolve(), args.task, args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

