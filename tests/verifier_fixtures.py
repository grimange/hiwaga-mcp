"""Deterministic fixture verifiers and registries for execution tests.

Every script here is self-contained: no HIWAGA source, no network, no Godot.
They exist so each execution outcome — PASS, FAIL, TIMEOUT, EXECUTION_ERROR,
oversized output, orphaned children, environment leakage — can be provoked
exactly and cheaply.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PASS_SCRIPT = """\
import sys
from pathlib import Path

print("structural check ok")
print("a warning", file=sys.stderr)
if len(sys.argv) > 2 and sys.argv[1] == "--out":
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text('{"passed": true}\\n')
    (out / "nested").mkdir(exist_ok=True)
    (out / "nested" / "detail.txt").write_text("detail\\n")
raise SystemExit(0)
"""

FAIL_SCRIPT = """\
import sys

print("checking invariant")
print("AssertionError: invariant does not hold", file=sys.stderr)
raise SystemExit(1)
"""

SLOW_SCRIPT = """\
import time

print("starting long work", flush=True)
time.sleep(3600)
raise SystemExit(0)
"""

#: Spawns a grandchild that writes a heartbeat file forever. If the deadline
#: only killed the direct child, the heartbeat would keep advancing.
SPAWN_SCRIPT = """\
import subprocess
import sys
import time
from pathlib import Path

marker = Path(sys.argv[1])
marker.parent.mkdir(parents=True, exist_ok=True)
child = subprocess.Popen([sys.executable, "-c", CHILD, str(marker)])
print(child.pid, flush=True)
time.sleep(3600)
"""

CHILD_SOURCE = """\
import sys, time
from pathlib import Path
target = Path(sys.argv[1])
count = 0
while True:
    count += 1
    target.write_text(str(count))
    time.sleep(0.05)
"""

NOISY_SCRIPT = """\
import sys

line = "x" * 200
for index in range(400):
    print(f"{index:04d} {line}")
for index in range(400):
    print(f"{index:04d} {line}", file=sys.stderr)
raise SystemExit(0)
"""

ENVIRONMENT_SCRIPT = """\
import json
import os

print(json.dumps(dict(os.environ)))
raise SystemExit(0)
"""

#: Named to avoid shadowing a stdlib module: the script directory leads sys.path,
#: so a fixture called signal.py would break `import signal` for every verifier.
ABNORMAL_EXIT_SCRIPT = """\
import os
import signal

os.kill(os.getpid(), signal.SIGKILL)
"""

MUTATE_SCRIPT = """\
import sys
from pathlib import Path

Path(sys.argv[1]).write_text("mutated by a verifier\\n")
raise SystemExit(0)
"""


def _spawn_script() -> str:
    """`SPAWN_SCRIPT` with the grandchild's source embedded as a literal."""
    return SPAWN_SCRIPT.replace("CHILD", repr(CHILD_SOURCE), 1)


FIXTURE_VERIFIERS: dict[str, str] = {
    "pass.py": PASS_SCRIPT,
    "fail.py": FAIL_SCRIPT,
    "slow.py": SLOW_SCRIPT,
    "spawn.py": _spawn_script(),
    "noisy.py": NOISY_SCRIPT,
    "environment.py": ENVIRONMENT_SCRIPT,
    "abnormal_exit.py": ABNORMAL_EXIT_SCRIPT,
    "mutate.py": MUTATE_SCRIPT,
}


def fixture_registry() -> dict[str, Any]:
    """A fresh registry covering every execution outcome; tests mutate their own copy."""
    return {
        "schema_version": 1,
        "verifiers": {
            "structural": {
                "proof_class": "STRUCTURAL",
                "executable": "REPO_PYTHON",
                "script": "tools/pass.py",
                "working_directory": ".",
                "timeout_seconds": 30,
                "default_mode": "default",
                "modes": {
                    "default": {"args": []},
                    "with_output": {"args": ["--out", "{run_directory}"]},
                },
            },
            "failing": {
                "proof_class": "STRUCTURAL",
                "executable": "REPO_PYTHON",
                "script": "tools/fail.py",
                "timeout_seconds": 30,
                "default_mode": "default",
                "modes": {"default": {"args": []}},
            },
            "slow": {
                "proof_class": "HEADLESS",
                "executable": "REPO_PYTHON",
                "script": "tools/slow.py",
                "timeout_seconds": 1,
                "default_mode": "default",
                "modes": {"default": {"args": []}},
            },
            "noisy": {
                "proof_class": "STRUCTURAL",
                "executable": "REPO_PYTHON",
                "script": "tools/noisy.py",
                "timeout_seconds": 30,
                "default_mode": "default",
                "modes": {"default": {"args": []}},
            },
            "spawner": {
                "proof_class": "HEADLESS",
                "executable": "REPO_PYTHON",
                "script": "tools/spawn.py",
                "timeout_seconds": 1,
                "default_mode": "default",
                "modes": {"default": {"args": ["{run_directory}/child.pid"]}},
            },
        },
    }


def registry_text(registry: dict[str, Any] | None = None) -> str:
    """Serialize `registry` (default: the fixture registry) as registry-file text."""
    return json.dumps(fixture_registry() if registry is None else registry, indent=2)


def install_repo_python(root: Path) -> Path:
    """Symlink the running interpreter to `<root>/.venv/bin/python`, where REPO_PYTHON looks."""
    target = root / ".venv" / "bin" / "python"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.symlink_to(Path(sys.executable).resolve())
    return target


def install_fixture_verifiers(root: Path) -> None:
    """Write every fixture verifier script into `<root>/tools/`."""
    tools = root / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    for name, body in FIXTURE_VERIFIERS.items():
        (tools / name).write_text(body, encoding="utf-8")
