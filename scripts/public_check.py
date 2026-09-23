from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    print(f"$ {' '.join(command)}")
    print(result.stdout)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    suffix = re.sub(r"[^a-z0-9]", "-", workspace.name.lower())[-30:]
    project = f"sfb-public-{suffix}"
    compose = ["docker", "compose", "-p", project, "-f", str(workspace / "compose.yaml")]
    try:
        if run(["docker", "build", "-t", "stockflow-bench-evaluator:0.1", str(ROOT / "evaluator")]).returncode:
            return 1
        if run(compose + ["up", "-d", "--build", "db"]).returncode:
            return 1
        makefile = (workspace / "Makefile").read_text(encoding="utf-8") if (workspace / "Makefile").exists() else ""
        migrate = ["make", "migrate-expand"] if "migrate-expand" in makefile else ["alembic", "upgrade", "head"]
        # --build so files written after an earlier check are picked up (image name is per project).
        if run(compose + ["run", "--build", "--rm", "app"] + migrate).returncode:
            return 1
        if run(compose + ["up", "-d", "--build", "app"]).returncode:
            return 1
        network = run(
            [
                "docker", "network", "ls", "--filter", f"label=com.docker.compose.project={project}",
                "--format", "{{.Name}}",
            ]
        ).stdout.strip().splitlines()[0]
        command = [
            "docker", "run", "--rm", "--network", network,
            "-e", "BASE_URL=http://app:8000",
            "-v", f"{ROOT / 'public-tests'}:/public-tests:ro",
            # Short tracebacks and no cache plugin: the default long tracebacks walk through
            # requests/urllib3 internals and, with the read-only mount, add cache warnings,
            # pushing the summary line past the model-facing size cap.
            "stockflow-bench-evaluator:0.1", "-q", "--tb=short", "-p", "no:cacheprovider", "/public-tests",
        ]
        return run(command, timeout=1800).returncode
    except (OSError, subprocess.TimeoutExpired, IndexError) as exc:
        print(f"public check error: {exc}", file=sys.stderr)
        return 2
    finally:
        try:
            run(compose + ["down", "-v", "--rmi", "local", "--remove-orphans"], timeout=300)
        except Exception as exc:
            print(f"cleanup error: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

