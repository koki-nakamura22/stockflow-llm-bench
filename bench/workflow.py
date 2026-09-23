from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.adapters import Adapter
from bench.agent import AgentRunner
from bench.tools import RepositoryTools

ROOT = Path(__file__).resolve().parents[1]
TASKS = ["A00", "C01", "C02", "C03", "C04", "C05"]
DEFAULT_RUN_CONFIG: dict[str, Any] = {
    "adapter": None,
    "think": None,
    "sampling": {},
    "context_window": 32768,
    "max_output_tokens": 24576,
    "request_timeout_seconds": 2400,
    "context_guard_tokens": 40960,
    "max_no_tool_turns": 3,
    "max_repeated_calls": 8,
    "max_turns": 40,
}


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")[:80] or "model"


def hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def git(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_NAME": "Benchmark", "GIT_AUTHOR_EMAIL": "benchmark@localhost",
                "GIT_COMMITTER_NAME": "Benchmark", "GIT_COMMITTER_EMAIL": "benchmark@localhost"})
    return subprocess.run(
        ["git", *command], cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )


def prepare_workspace(source: Path, destination: Path) -> str:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(".git", "benchmark-tests", "__pycache__", ".pytest_cache"),
    )
    shutil.copytree(ROOT / "public-tests", destination / "benchmark-tests")
    public_hash = hash_tree(destination / "benchmark-tests")
    git(["init", "-q"], destination)
    git(["add", "."], destination)
    commit = git(["commit", "-q", "-m", "benchmark baseline"], destination)
    if commit.returncode != 0:
        raise RuntimeError(f"could not create baseline commit: {commit.stdout}")
    return public_hash


def save_patch(workspace: Path, path: Path) -> None:
    git(["add", "-N", "."], workspace)
    result = git(["diff", "--binary", "HEAD"], workspace)
    path.write_text(result.stdout, encoding="utf-8")


def evaluate(workspace: Path, task: str, run_dir: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "evaluator" / "evaluate.py"),
            "--workspace", str(workspace),
            "--task", task,
            "--output", str(run_dir),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    (run_dir / "evaluator-console.log").write_text(result.stdout, encoding="utf-8")
    result_path = run_dir / "evaluator-result.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    return {
        "status": "error",
        "error": result.stdout[-4000:],
        "capability": {"score": 0, "max_score": 100},
        "code_health": {"score": 0, "max_score": 100},
    }


def run_one(
    adapter: Adapter,
    model: str,
    group_dir: Path,
    track: str,
    task: str,
    source: Path,
    max_turns: int,
    evaluate_submission: bool,
    run_config: dict[str, Any],
) -> dict[str, Any]:
    run_dir = group_dir / "runs" / slug(model) / track / task
    workspace = run_dir / "workspace"
    run_dir.mkdir(parents=True, exist_ok=True)
    public_hash = prepare_workspace(source, workspace)
    prompt = (ROOT / "tasks" / f"{task}.md").read_text(encoding="utf-8")
    (run_dir / "prompt.md").write_text(prompt, encoding="utf-8")
    tools = RepositoryTools(workspace, ROOT)
    agent = AgentRunner(
        adapter,
        tools,
        run_dir / "transcript.jsonl",
        max_turns=max_turns,
        context_guard_tokens=run_config["context_guard_tokens"],
        max_no_tool_turns=run_config["max_no_tool_turns"],
        max_repeated_calls=run_config["max_repeated_calls"],
    )
    agent_result = agent.run(prompt)
    save_patch(workspace, run_dir / "submission.patch")
    public_unchanged = public_hash == hash_tree(workspace / "benchmark-tests")
    if not public_unchanged:
        evaluator_result: dict[str, Any] = {
            "status": "invalid",
            "error": "benchmark-owned public tests changed",
            "capability": {"score": 0, "max_score": 100},
            "code_health": {"score": None, "max_score": 100},
        }
    elif evaluate_submission:
        evaluator_result = evaluate(workspace, task, run_dir)
    else:
        evaluator_result = {
            "status": "not_evaluated",
            "error": None,
            "capability": {"score": None, "max_score": 100},
            "code_health": {"score": None, "max_score": 100},
        }
    metadata = {
        "model": model,
        "track": track,
        "task": task,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "run_config": run_config,
        "agent": agent_result,
        "public_tests_unchanged": public_unchanged,
        "evaluator_status": evaluator_result.get("status"),
        "capability_score": evaluator_result.get("capability", {}).get("score"),
        "code_health_score": evaluator_result.get("code_health", {}).get("score"),
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {**metadata, "workspace": str(workspace), "run_dir": str(run_dir)}


def write_summary(group_dir: Path, rows: list[dict[str, Any]]) -> None:
    summary = {"schema_version": "1.0", "runs": rows}
    (group_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    fields = [
        "model", "track", "task", "evaluator_status", "capability_score", "code_health_score",
        "agent_status", "turns", "prompt_tokens", "completion_tokens", "duration_seconds",
        "public_tests_unchanged", "run_dir",
    ]
    for row in rows:
        agent = row.get("agent", {})
        row.setdefault("agent_status", agent.get("status"))
        for key in ("turns", "prompt_tokens", "completion_tokens", "duration_seconds"):
            row.setdefault(key, agent.get(key))
    with (group_dir / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Benchmark summary", "",
        "| Model | Track | Task | Status | Capability | Code Health | Agent | Turns | Duration |",
        "|---|---|---|---|---:|---:|---|---:|---:|",
    ]
    for row in rows:
        agent = row.get("agent", {})
        duration = agent.get("duration_seconds")
        lines.append(
            f"| {row['model']} | {row['track']} | {row['task']} | {row['evaluator_status']} | "
            f"{row['capability_score'] if row['capability_score'] is not None else '-'} | "
            f"{row['code_health_score'] if row['code_health_score'] is not None else '-'} | "
            f"{agent.get('status', '-')} | {agent.get('turns', '-')} | "
            f"{f'{duration / 60:.1f}m' if isinstance(duration, (int, float)) else '-'} |"
        )
    controlled = [row["capability_score"] for row in rows if row["track"] == "controlled_cold_change" and isinstance(row["capability_score"], (int, float))]
    zero = next((row["capability_score"] for row in rows if row["track"] == "zero_to_one"), None)
    if isinstance(zero, (int, float)) and len(controlled) == 5:
        controlled_mean = sum(controlled) / len(controlled)
        primary = 0.4 * zero + 0.6 * controlled_mean
        lines.extend(["", f"Primary Capability Index: **{primary:.2f}**", f"Controlled mean: **{controlled_mean:.2f}**"])
    (group_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_group(
    adapter: Adapter,
    model: str,
    tasks: list[str],
    include_self: bool,
    max_turns: int,
    evaluate_submission: bool,
    results_root: Path,
    run_config: dict[str, Any] | None = None,
) -> Path:
    run_config = {**DEFAULT_RUN_CONFIG, **(run_config or {}), "max_turns": max_turns}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    group_dir = results_root / f"{stamp}-{slug(model)}"
    group_dir.mkdir(parents=True, exist_ok=False)
    (group_dir / "run-config.json").write_text(
        json.dumps({"model": model, **run_config}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows: list[dict[str, Any]] = []
    a00_workspace: Path | None = None
    for task in tasks:
        track = "zero_to_one" if task == "A00" else "controlled_cold_change"
        source = ROOT / "platform-skeleton" if task == "A00" else ROOT / "reference" / "base"
        row = run_one(
            adapter, model, group_dir, track, task, source, max_turns, evaluate_submission, run_config
        )
        rows.append(row)
        write_summary(group_dir, rows)
        if task == "A00":
            a00_workspace = Path(row["workspace"])
    if include_self and a00_workspace is not None:
        for task in [task for task in tasks if task != "A00"]:
            row = run_one(
                adapter,
                model,
                group_dir,
                "self_cold_change",
                task,
                a00_workspace,
                max_turns,
                evaluate_submission,
                run_config,
            )
            rows.append(row)
            write_summary(group_dir, rows)
    return group_dir
