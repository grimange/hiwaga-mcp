"""The execution plan is the boundary: what runs is fixed before anything runs.

Every field of the plan comes from the registry, the validated repository root,
and the generated run directory. These tests assert exactly that, and that a
caller has no route to change any of it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hiwaga_mcp.errors import (
    ReasonCode,
    TargetOutsideRepositoryError,
    UnknownVerifierError,
    UnsupportedVerifyModeError,
)
from hiwaga_mcp.models.verification import ProofClass
from hiwaga_mcp.models.verification_registry import ExecutableStrategy
from hiwaga_mcp.services.verification import (
    FIXED_ENVIRONMENT,
    INHERITED_ENVIRONMENT,
    RUNS_DIRECTORY,
    build_environment,
    build_execution_plan,
    new_run_id,
    resolve_executable,
)
from hiwaga_mcp.services.verification_registry import parse_verifier_registry, select_verifier

from .conftest import fixture_registry, make_hiwaga_repo, registry_text


def plan_for(root: Path, verifier: str = "structural", mode: str | None = None, registry: Any = None) -> Any:
    """Resolve `verifier`/`mode` against a registry and build its execution plan."""
    parsed = parse_verifier_registry(registry_text(registry) if registry else registry_text())
    verifier_id, definition, mode_name, entry = select_verifier(parsed, verifier, mode)
    return build_execution_plan(root, verifier_id, definition, mode_name, entry)


# --- executable selection ----------------------------------------------------


def test_repo_python_resolves_inside_the_repository(verify_repo: Path) -> None:
    executable = resolve_executable(verify_repo, ExecutableStrategy.REPO_PYTHON)
    assert executable == verify_repo.resolve() / ".venv/bin/python"


def test_venv_interpreter_symlinked_to_the_system_python_is_accepted(verify_repo: Path) -> None:
    """Every ordinary virtualenv links `.venv/bin/python` at the system interpreter."""
    interpreter = verify_repo / ".venv/bin/python"
    assert interpreter.is_symlink()
    assert not str(interpreter.resolve()).startswith(str(verify_repo.resolve()))
    assert resolve_executable(verify_repo, ExecutableStrategy.REPO_PYTHON) == interpreter


def test_plan_uses_the_repository_interpreter(verify_repo: Path) -> None:
    plan = plan_for(verify_repo)
    assert plan.executable == verify_repo.resolve() / ".venv/bin/python"
    assert plan.argv[0] == str(plan.executable)


def test_venv_directory_symlinked_outside_the_repository_is_rejected(
    tmp_path: Path, outside_dir: Path
) -> None:
    """A `.venv` pointed at another checkout is an escape, and is refused."""
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    (outside_dir / "bin").mkdir(parents=True, exist_ok=True)
    (root / ".venv").symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(TargetOutsideRepositoryError) as excinfo:
        resolve_executable(root, ExecutableStrategy.REPO_PYTHON)
    assert excinfo.value.code is ReasonCode.TARGET_OUTSIDE_REPOSITORY


# --- argv construction -------------------------------------------------------


def test_argv_is_interpreter_then_script_then_fixed_mode_args(verify_repo: Path) -> None:
    plan = plan_for(verify_repo, "structural", "with_output")
    assert plan.argv[0] == str(verify_repo.resolve() / ".venv/bin/python")
    assert plan.argv[1] == str((verify_repo / "tools/pass.py").resolve())
    assert plan.argv[2] == "--out"
    assert plan.argv[3] == str(plan.run_directory)
    assert len(plan.argv) == 4


def test_mode_without_args_produces_exactly_two_argv_entries(verify_repo: Path) -> None:
    plan = plan_for(verify_repo, "structural", "default")
    assert len(plan.argv) == 2


def test_each_mode_contributes_its_own_arguments(verify_repo: Path) -> None:
    assert plan_for(verify_repo, "structural", "default").argv[2:] == []
    with_output = plan_for(verify_repo, "structural", "with_output")
    assert with_output.argv[2:] == ["--out", str(with_output.run_directory)]


def test_run_directory_token_is_the_only_substitution(verify_repo: Path) -> None:
    plan = plan_for(verify_repo, "structural", "with_output")
    assert "{run_directory}" not in " ".join(plan.argv)
    assert "{" not in plan.argv[3]


def test_argv_entries_are_separate_values_never_a_command_string(verify_repo: Path) -> None:
    """No argv entry is a concatenation of several shell words."""
    plan = plan_for(verify_repo, "structural", "with_output")
    for entry in plan.argv:
        assert not any(token in entry for token in ("|", ";", "&&", "$(", "`", "\n"))
    assert " " not in plan.argv[2]


def test_argv_is_a_list_of_strings(verify_repo: Path) -> None:
    plan = plan_for(verify_repo)
    assert isinstance(plan.argv, list)
    assert all(isinstance(entry, str) for entry in plan.argv)


# --- working directory, timeout, proof class ---------------------------------


def test_working_directory_is_contained_and_absolute(verify_repo: Path) -> None:
    plan = plan_for(verify_repo)
    assert plan.cwd == verify_repo.resolve()
    assert plan.cwd.is_absolute()


def test_declared_working_directory_is_honoured(verify_repo: Path) -> None:
    registry = fixture_registry()
    registry["verifiers"]["structural"]["working_directory"] = "tools"
    assert plan_for(verify_repo, registry=registry).cwd == (verify_repo / "tools").resolve()


def test_escaping_working_directory_is_rejected_at_plan_time(verify_repo: Path) -> None:
    """Even if a registry evaded schema checks, containment still refuses it."""
    parsed = parse_verifier_registry(registry_text())
    verifier_id, definition, mode_name, entry = select_verifier(parsed, "structural", "default")
    escaped = definition.model_copy(update={"working_directory": "../outside"})
    with pytest.raises(TargetOutsideRepositoryError):
        build_execution_plan(verify_repo, verifier_id, escaped, mode_name, entry)


def test_escaping_script_is_rejected_at_plan_time(verify_repo: Path) -> None:
    parsed = parse_verifier_registry(registry_text())
    verifier_id, definition, mode_name, entry = select_verifier(parsed, "structural", "default")
    escaped = definition.model_copy(update={"script": "../../etc/passwd"})
    with pytest.raises(TargetOutsideRepositoryError):
        build_execution_plan(verify_repo, verifier_id, escaped, mode_name, entry)


def test_symlinked_script_escaping_the_repository_is_rejected(verify_repo: Path, outside_dir: Path) -> None:
    external = outside_dir / "evil.py"
    external.write_text("print('pwned')\n", encoding="utf-8")
    (verify_repo / "tools" / "linked.py").symlink_to(external)
    registry = fixture_registry()
    registry["verifiers"]["structural"]["script"] = "tools/linked.py"
    with pytest.raises(TargetOutsideRepositoryError):
        plan_for(verify_repo, registry=registry)


def test_timeout_comes_from_the_registry(verify_repo: Path) -> None:
    assert plan_for(verify_repo, "structural").timeout_seconds == 30
    assert plan_for(verify_repo, "slow").timeout_seconds == 1


def test_proof_class_comes_from_the_registry(verify_repo: Path) -> None:
    assert plan_for(verify_repo, "structural").proof_class is ProofClass.STRUCTURAL
    assert plan_for(verify_repo, "slow").proof_class is ProofClass.HEADLESS


def test_caller_cannot_claim_a_different_proof_class(verify_repo: Path) -> None:
    """A mode name never influences the declared proof class."""
    assert plan_for(verify_repo, "structural", "with_output").proof_class is ProofClass.STRUCTURAL


# --- run directory -----------------------------------------------------------


def test_run_directory_is_inside_the_ignored_scratch_tree(verify_repo: Path) -> None:
    plan = plan_for(verify_repo)
    relative = plan.run_directory.relative_to(verify_repo.resolve())
    assert str(relative).startswith(RUNS_DIRECTORY)
    assert relative.parent == Path(RUNS_DIRECTORY)


def test_each_plan_gets_its_own_run_directory(verify_repo: Path) -> None:
    first, second = plan_for(verify_repo), plan_for(verify_repo)
    assert first.run_id != second.run_id
    assert first.run_directory != second.run_directory


def test_run_id_is_filesystem_safe_and_carries_no_caller_text(verify_repo: Path) -> None:
    run_id = new_run_id()
    assert run_id.isalnum()
    assert "/" not in run_id and "." not in run_id
    assert len(run_id) >= 16


def test_explicit_run_id_is_honoured(verify_repo: Path) -> None:
    parsed = parse_verifier_registry(registry_text())
    verifier_id, definition, mode_name, entry = select_verifier(parsed, "structural", "default")
    plan = build_execution_plan(verify_repo, verifier_id, definition, mode_name, entry, run_id="fixed")
    assert plan.run_id == "fixed"
    assert plan.run_directory.name == "fixed"


# --- the caller cannot alter the plan ----------------------------------------


def test_caller_cannot_inject_arguments_through_the_verifier_name(verify_repo: Path) -> None:
    parsed = parse_verifier_registry(registry_text())
    for attempt in ("structural --unsafe", "structural;rm -rf /", "structural\nfailing"):
        with pytest.raises(UnknownVerifierError):
            select_verifier(parsed, attempt, "default")


def test_caller_cannot_inject_arguments_through_the_mode_name(verify_repo: Path) -> None:
    parsed = parse_verifier_registry(registry_text())
    for attempt in ("default --out /etc", "default;id", "../default"):
        with pytest.raises(UnsupportedVerifyModeError):
            select_verifier(parsed, "structural", attempt)


def test_plan_is_immutable(verify_repo: Path) -> None:
    plan = plan_for(verify_repo)
    with pytest.raises(ValidationError):
        plan.timeout_seconds = 9999  # type: ignore[misc]


# --- environment -------------------------------------------------------------


def test_environment_is_built_from_an_allowlist(verify_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", "/elsewhere/.git")
    monkeypatch.setenv("PYTHONPATH", "/injected")
    monkeypatch.setenv("SOME_SECRET_TOKEN", "hunter2")
    plan = plan_for(verify_repo)
    assert "GIT_DIR" not in plan.environment
    assert "PYTHONPATH" not in plan.environment
    assert "SOME_SECRET_TOKEN" not in plan.environment


def test_benign_environment_is_preserved(verify_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("HOME", "/home/fixture")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    plan = plan_for(verify_repo)
    assert plan.environment["PATH"] == "/usr/bin:/bin"
    assert plan.environment["HOME"] == "/home/fixture"
    assert plan.environment["LC_ALL"] == "C.UTF-8"


def test_fixed_entries_are_always_set(verify_repo: Path) -> None:
    assert plan_for(verify_repo).environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert FIXED_ENVIRONMENT["PYTHONDONTWRITEBYTECODE"] == "1"


def test_registry_environment_is_applied(verify_repo: Path) -> None:
    registry = fixture_registry()
    registry["verifiers"]["structural"]["environment"] = {"HIWAGA_FIXTURE": "yes"}
    assert plan_for(verify_repo, registry=registry).environment["HIWAGA_FIXTURE"] == "yes"


def test_inherited_allowlist_is_narrow() -> None:
    assert set(INHERITED_ENVIRONMENT) == {"PATH", "HOME", "LANG", "TZ"}


def test_build_environment_ignores_unlisted_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONHOME", "/injected")
    monkeypatch.setenv("GIT_WORK_TREE", "/elsewhere")
    parsed = parse_verifier_registry(registry_text())
    environment = build_environment(parsed.verifiers["structural"])
    assert "PYTHONHOME" not in environment
    assert "GIT_WORK_TREE" not in environment
