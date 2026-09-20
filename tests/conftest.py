"""Shared fixtures.

Every test runs against a throwaway fixture repository under pytest's tmp_path.
No test reads, writes, or otherwise touches the operator's live HIWAGA checkout.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from hiwaga_mcp.models.project import SentinelKind
from hiwaga_mcp.services.repository import REQUIRED_SENTINELS

from .context_fixtures import (
    FIXTURE_CANON_TEXT,
    context_routing_mapping_text,
    fixture_context_routing_mapping,
    install_fixture_canon_links,
    write_canon,
)
from .verifier_fixtures import (
    FIXTURE_VERIFIERS,
    fixture_registry,
    install_fixture_verifiers,
    install_repo_python,
    registry_text,
)

__all__ = [
    "FIXTURE_CANON_TEXT",
    "FIXTURE_VERIFIERS",
    "context_routing_mapping_text",
    "fixture_context_routing_mapping",
    "fixture_registry",
    "install_fixture_canon_links",
    "install_fixture_verifiers",
    "install_repo_python",
    "registry_text",
    "write_canon",
]


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


def fixture_manifest() -> dict[str, Any]:
    """A fresh minimal asset-authority manifest; tests mutate their own copy."""
    return {
        "schema_version": 1,
        "assets": {
            "old_thing": {
                "status": "superseded",
                "visual_authority": False,
                "runtime_required_temporarily": False,
                "authoring_reuse": "reference_only",
                "source_path": "art-source/_superseded/old_thing",
                "runtime_path": "game/assets/old_thing_proof",
            },
            "solo": {
                "status": "some_future_status",
                "runtime_path": "game/assets/solo/solo.glb",
                "source_path": "art-source/solo/solo.blend",
                "unmodelled_additive_field": "tolerated",
            },
            "fresh": {
                "status": "active_rebuild_target",
                "creation_mode": "from_scratch",
                "visual_authority": True,
                "runtime_active": True,
                "runtime_required_temporarily": False,
                "source_path": "art-source/fresh",
                "static_form_source": "fresh_static.blend",
                "motion_source": "motion/fresh_motion.blend",
                "motion_proof_path": "game/proofs/fresh/field.tscn",
            },
            "fresh_old": {"source_path": "art-source/fresh_old"},
        },
    }


def write_manifest(root: Path, manifest: dict[str, Any] | str) -> None:
    """Replace the fixture repository's asset-authority manifest."""
    text = manifest if isinstance(manifest, str) else json.dumps(manifest, indent=2)
    (root / "art-source/ASSET_AUTHORITY.json").write_text(text, encoding="utf-8")


@pytest.fixture
def authority_repo(tmp_path: Path) -> Path:
    """A valid fixture HIWAGA checkout carrying `fixture_manifest()` (no Git needed)."""
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    write_manifest(root, fixture_manifest())
    return root


def fixture_worker_policy() -> dict[str, Any]:
    """A fresh minimal worker policy: single-worker, multi-worker, and human-only classes."""
    return {
        "schema_version": 1,
        "task_classes": {
            "BOUNDED_IMPLEMENTATION": {"allowed": [{"worker": "codex", "models": ["model-A"]}]},
            "EVIDENCE_AUDIT": {
                "allowed": [
                    {"worker": "codex", "models": ["model-A", "model-B"]},
                    {"worker": "claude-code", "models": ["model-C"]},
                ]
            },
            "OPERATOR_REVIEW": {"human_required": True},
        },
    }


def worker_policy_text(policy: dict[str, Any] | None = None) -> str:
    """Serialize `policy` (default: the fixture policy) as policy-file text."""
    return json.dumps(fixture_worker_policy() if policy is None else policy, indent=2)


def preflight_manifest() -> dict[str, Any]:
    """`fixture_manifest()` plus assets that exercise conflict and status-only cases."""
    manifest = fixture_manifest()
    manifest["assets"]["legacy"] = {"status": "superseded", "source_path": "art-source/legacy"}
    manifest["assets"]["dup_a"] = {"source_path": "art-source/dup"}
    manifest["assets"]["dup_b"] = {"source_path": "art-source/dup"}
    return manifest


def progress_text(gate: str | None = None, *, operator: bool = False) -> str:
    """A one-block ledger declaring an optional ambiguity gate and optional operator step."""
    lines = ["## Preflight fixture block", ""]
    if gate:
        lines.append(f"- **Ambiguity Gate:** {gate}")
    step = "operator runs the native review." if operator else "implement the next step."
    lines.append(f"- **Next Bounded Step:** {step}")
    return "\n".join(lines) + "\n"


def set_project_state(root: Path, gate: str | None = None, *, operator: bool = False) -> None:
    """Rewrite the ledger so `hiwaga_project_state` reports the given gate/operator state."""
    write_progress(root, progress_text(gate, operator=operator))


@pytest.fixture
def preflight_repo(tmp_path: Path) -> Path:
    """A fixture checkout with a real Git repo, a valid ledger (no gate, no operator step), and assets."""
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    write_manifest(root, preflight_manifest())
    set_project_state(root)
    init_git_repo(root)
    return root


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


@pytest.fixture(autouse=True)
def _isolated_runtime_state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Every test gets its own `XDG_STATE_HOME`, so the suite never touches the operator's real state.

    `hiwaga_verify` now writes outside whatever repository it inspects, so a
    test that does not isolate this would otherwise pollute the real
    `~/.local/state/hiwaga-mcp` on the machine running the suite. This applies
    even to tests that never call verify: it is cheap, and it means no test can
    accidentally regress the isolation by omission.
    """
    state_home = tmp_path / "xdg-state-home"
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))
    return state_home


@pytest.fixture
def outside_dir(tmp_path: Path) -> Path:
    """A directory that is a sibling of, and never inside, `hiwaga_repo`."""
    target = tmp_path / "outside"
    target.mkdir(parents=True, exist_ok=True)
    (target / "secret.txt").write_text("outside\n", encoding="utf-8")
    return target


@pytest.fixture
def verify_repo(tmp_path: Path) -> Path:
    """A valid fixture checkout carrying a repo interpreter and the fixture verifiers.

    Self-contained: it borrows the running interpreter by symlink but touches no
    real HIWAGA checkout and needs no Git.
    """
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    install_repo_python(root)
    install_fixture_verifiers(root)
    return root


@pytest.fixture
def context_repo(tmp_path: Path) -> Path:
    """A valid fixture checkout carrying `FIXTURE_CANON_TEXT`, the files it links to, a real
    Git repo, and a valid progress block, so every domain including PROJECT can be routed.

    Two links are deliberately left dangling (`FIXTURE_GHOST*`) to exercise
    missing-supporting/missing-historical routing without a tool error.
    """
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    write_canon(root)
    install_fixture_canon_links(root)
    write_progress(root, VALID_PROGRESS)
    init_git_repo(root)
    return root
