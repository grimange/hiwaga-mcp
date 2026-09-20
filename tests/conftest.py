"""Shared fixtures.

Every test runs against a throwaway fixture repository under pytest's tmp_path.
No test reads, writes, or otherwise touches the operator's live HIWAGA checkout.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from hiwaga_mcp.models.project import SentinelKind
from hiwaga_mcp.services.repository import REQUIRED_SENTINELS


def make_hiwaga_repo(root: Path, *, omit: tuple[str, ...] = ()) -> Path:
    """Create a minimal structure satisfying HIWAGA identity sentinels.

    Args:
        root: Directory to populate. Created if absent.
        omit: Repository-relative sentinel paths to deliberately leave out.
    """
    root.mkdir(parents=True, exist_ok=True)
    for relative, kind in REQUIRED_SENTINELS:
        if relative in omit:
            continue
        target = root / relative
        if kind is SentinelKind.DIRECTORY:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"fixture sentinel: {relative}\n", encoding="utf-8")
    return root


VALID_PROGRESS = """\
# HIWAGA Progress

Preamble prose that is not part of any block.

## Current Block Title — 2026-09-20

- **Phase:** REPRESENTATIVE_GAMEPLAY_PROTOTYPING.
- **Current Focus / Status:** `CURRENT_FOCUS_TOKEN__NEXT_READY`.
  Wrapped continuation of the focus value.
- **Design Question / Player Goal:** can the player follow the route?
- **Success Condition:** the route is followed unaided.
- **Ambiguity Gate:** TARGET_CLEAR, including precedent.
- **Next Bounded Step:** `NEXT_STEP_TOKEN` — implement it.

## Older Block — 2026-09-19

- **Phase:** OLD_PHASE
- **Status:** OLD_STATUS
- **Ambiguity Gate:** TARGET_AMBIGUOUS
- **Next Bounded Step:** OLD_NEXT_STEP with operator review.
"""


def write_progress(root: Path, text: str) -> None:
    """Replace the fixture repository's progress ledger."""
    (root / "docs/progress/HIWAGA_PROGRESS.md").write_text(text, encoding="utf-8")


def run_git(root: Path, *args: str) -> str:
    """Run a real Git command in a fixture repository, isolated from user/system config."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    result = subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def init_git_repo(root: Path) -> str:
    """Initialize `root` as a real Git repository on `main` with one commit; return HEAD."""
    run_git(root, "init", "-q", "-b", "main")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "fixture")
    return run_git(root, "rev-parse", "HEAD")


@pytest.fixture
def state_repo(tmp_path: Path) -> Path:
    """A valid fixture HIWAGA checkout: real Git repo, clean, with a valid progress ledger."""
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    write_progress(root, VALID_PROGRESS)
    init_git_repo(root)
    return root


@pytest.fixture
def hiwaga_repo(tmp_path: Path) -> Path:
    """A valid fixture HIWAGA checkout."""
    return make_hiwaga_repo(tmp_path / "hiwaga")


@pytest.fixture
def outside_dir(tmp_path: Path) -> Path:
    """A directory that is a sibling of, and never inside, `hiwaga_repo`."""
    target = tmp_path / "outside"
    target.mkdir(parents=True, exist_ok=True)
    (target / "secret.txt").write_text("outside\n", encoding="utf-8")
    return target
