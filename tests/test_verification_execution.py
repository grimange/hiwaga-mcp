"""Real subprocess execution: status classification, cleanup, bounding, containment.

These tests launch actual processes. Every one uses a throwaway fixture
repository and a fixture verifier script; none touches a real HIWAGA checkout,
and none starts Godot or Blender.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import time
from pathlib import Path
from typing import Any

import anyio
import pytest

from hiwaga_mcp.errors import (
    ReasonCode,
    UnknownVerifierError,
    UnsupportedVerifyModeError,
    VerifierRegistryError,
)
from hiwaga_mcp.models.verification import ArtifactKind, ProofClass, VerificationStatus
from hiwaga_mcp.services.runtime_state import repository_state_key, resolve_state_root
from hiwaga_mcp.services.verification import (
    STDERR_LOG_NAME,
    STDOUT_LOG_NAME,
    TAIL_CHARACTERS,
    run_verification,
)

from .conftest import (
    fixture_registry,
    init_git_repo,
    install_fixture_verifiers,
    install_repo_python,
    make_hiwaga_repo,
    registry_text,
    run_git,
)


def verify(root: Path, verifier: str = "structural", mode: str | None = None, registry: Any = None) -> Any:
    """Run one verification to completion and return its typed result."""

    async def body() -> Any:
        return await run_verification(
            root, verifier, mode, registry_text=registry_text(registry) if registry else registry_text()
        )

    return anyio.run(body)


# --- PASS --------------------------------------------------------------------


def test_successful_verifier_is_a_pass(verify_repo: Path) -> None:
    result = verify(verify_repo)
    assert result.status is VerificationStatus.PASS
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.proof_class is ProofClass.STRUCTURAL


def test_pass_reports_the_repository_it_ran_against(verify_repo: Path) -> None:
    result = verify(verify_repo)
    assert result.repository_root == str(verify_repo.resolve())
    assert result.repository == verify_repo.name


def test_pass_captures_both_streams(verify_repo: Path) -> None:
    result = verify(verify_repo)
    assert "structural check ok" in result.stdout_tail
    assert "a warning" in result.stderr_tail


def test_pass_records_a_duration(verify_repo: Path) -> None:
    assert verify(verify_repo).duration_ms >= 0


def test_default_mode_is_used_when_the_caller_omits_one(verify_repo: Path) -> None:
    assert verify(verify_repo, "structural", None).mode == "default"


def test_pass_does_not_assert_operator_acceptance(verify_repo: Path) -> None:
    """A PASS is machine proof, and says so."""
    result = verify(verify_repo)
    assert any("not operator acceptance" in limitation for limitation in result.limitations)
    payload = result.model_dump(mode="json")
    for invented in ("animation_accepted", "visual_quality_passed", "gameplay_good", "approved"):
        assert invented not in payload


# --- FAIL --------------------------------------------------------------------


def test_failing_verifier_is_a_fail_not_an_execution_error(verify_repo: Path) -> None:
    """The single most important contract: a found defect is a domain result."""
    result = verify(verify_repo, "failing")
    assert result.status is VerificationStatus.FAIL
    assert result.exit_code == 1
    assert result.timed_out is False


def test_fail_preserves_the_verifier_output(verify_repo: Path) -> None:
    result = verify(verify_repo, "failing")
    assert "checking invariant" in result.stdout_tail
    assert "invariant does not hold" in result.stderr_tail


def test_fail_explains_itself_as_a_verification_failure(verify_repo: Path) -> None:
    assert "verification failure" in verify(verify_repo, "failing").reason


@pytest.mark.parametrize("code", [1, 2, 3, 42, 127])
def test_any_nonzero_exit_is_a_fail(verify_repo: Path, code: int) -> None:
    (verify_repo / "tools" / "coded.py").write_text(f"raise SystemExit({code})\n", encoding="utf-8")
    registry = fixture_registry()
    registry["verifiers"]["structural"]["script"] = "tools/coded.py"
    result = verify(verify_repo, registry=registry)
    assert result.status is VerificationStatus.FAIL
    assert result.exit_code == code


# --- TIMEOUT -----------------------------------------------------------------


def test_slow_verifier_times_out(verify_repo: Path) -> None:
    result = verify(verify_repo, "slow")
    assert result.status is VerificationStatus.TIMEOUT
    assert result.timed_out is True


def test_timeout_terminates_within_a_bounded_window(verify_repo: Path) -> None:
    """A one-second deadline does not wait for the verifier's own hour-long sleep."""
    started = time.monotonic()
    verify(verify_repo, "slow")
    assert time.monotonic() - started < 30


def test_timeout_states_that_nothing_was_established(verify_repo: Path) -> None:
    result = verify(verify_repo, "slow")
    assert "deadline" in result.reason
    assert any("proves nothing" in limitation for limitation in result.limitations)


def test_timeout_still_captures_output_produced_before_the_deadline(verify_repo: Path) -> None:
    assert "starting long work" in verify(verify_repo, "slow").stdout_tail


def test_timeout_reaps_the_child(verify_repo: Path) -> None:
    """No zombie is left behind: the process is waited on, not merely signalled."""
    result = verify(verify_repo, "slow")
    assert result.timed_out is True
    assert result.exit_code is not None


def test_timeout_cleans_up_descendant_processes(verify_repo: Path) -> None:
    """A verifier's grandchildren die with it, because the whole group is signalled."""
    result = verify(verify_repo, "spawner")
    assert result.status is VerificationStatus.TIMEOUT

    marker = Path(result.run_directory) / "child.pid"
    assert marker.exists(), "the fixture grandchild never started"

    # The grandchild rewrites the marker every 50ms while alive. If the process
    # group was cleaned up, the file stops changing.
    first = marker.read_text()
    time.sleep(1.0)
    assert marker.read_text() == first, "a descendant survived the timeout"


# --- EXECUTION_ERROR ---------------------------------------------------------


def test_missing_interpreter_is_an_execution_error(tmp_path: Path) -> None:
    """A valid request whose resolved interpreter cannot launch is not a tool error."""
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    (root / ".venv" / "bin").mkdir(parents=True)  # directory exists, interpreter does not
    install_fixture_verifiers(root)

    result = verify(root)
    assert result.status is VerificationStatus.EXECUTION_ERROR
    assert result.timed_out is False
    assert "could not be executed" in result.reason


def test_missing_script_is_reported_by_the_interpreter(verify_repo: Path) -> None:
    """The interpreter launches and reports the missing script: a verifier-level failure."""
    registry = fixture_registry()
    registry["verifiers"]["structural"]["script"] = "tools/absent.py"
    result = verify(verify_repo, registry=registry)
    assert result.status is VerificationStatus.FAIL
    assert result.exit_code not in (0, None)


def test_abnormal_signal_exit_is_an_execution_error(verify_repo: Path) -> None:
    """Killed by a signal is not a verifier verdict, so it is never a FAIL."""
    registry = fixture_registry()
    registry["verifiers"]["structural"]["script"] = "tools/abnormal_exit.py"
    result = verify(verify_repo, registry=registry)
    assert result.status is VerificationStatus.EXECUTION_ERROR
    assert result.exit_code == -signal.SIGKILL
    assert "terminated by signal" in result.reason


def test_missing_working_directory_is_an_execution_error(verify_repo: Path) -> None:
    registry = fixture_registry()
    registry["verifiers"]["structural"]["working_directory"] = "does/not/exist"
    result = verify(verify_repo, registry=registry)
    assert result.status is VerificationStatus.EXECUTION_ERROR


# --- invalid requests are tool-level failures, not statuses -------------------


def test_unknown_verifier_raises_rather_than_returning_a_status(verify_repo: Path) -> None:
    with pytest.raises(UnknownVerifierError) as excinfo:
        verify(verify_repo, "does-not-exist")
    assert excinfo.value.code is ReasonCode.UNKNOWN_VERIFIER


def test_unsupported_mode_raises_rather_than_returning_a_status(verify_repo: Path) -> None:
    with pytest.raises(UnsupportedVerifyModeError) as excinfo:
        verify(verify_repo, "structural", "native")
    assert excinfo.value.code is ReasonCode.UNSUPPORTED_VERIFY_MODE


def test_invalid_registry_raises_rather_than_returning_a_status(verify_repo: Path) -> None:
    async def body() -> Any:
        return await run_verification(verify_repo, "structural", None, registry_text="{broken")

    with pytest.raises(VerifierRegistryError) as excinfo:
        anyio.run(body)
    assert excinfo.value.code is ReasonCode.VERIFIER_REGISTRY_INVALID


def test_nothing_executes_when_the_registry_is_invalid(verify_repo: Path) -> None:
    """A malformed registry is never partially trusted."""
    registry = fixture_registry()
    registry["verifiers"]["poison"] = {"proof_class": "STRUCTURAL"}

    async def body() -> Any:
        return await run_verification(verify_repo, "structural", None, registry_text=json.dumps(registry))

    with pytest.raises(VerifierRegistryError):
        anyio.run(body)
    assert not (verify_repo / ".hiwaga-mcp").exists()
    key = repository_state_key(verify_repo)
    assert not (resolve_state_root() / "repositories" / key).exists()


# --- run directory, logs, artifacts ------------------------------------------


def test_logs_are_written_under_the_external_state_root(verify_repo: Path) -> None:
    result = verify(verify_repo)
    key = repository_state_key(verify_repo)
    expected_run_directory = resolve_state_root() / "repositories" / key / "runs" / result.run_id
    assert Path(result.run_directory) == expected_run_directory
    assert Path(result.stdout_log).is_file()
    assert Path(result.stderr_log).is_file()


def test_reported_paths_are_absolute_and_outside_the_repository(verify_repo: Path) -> None:
    result = verify(verify_repo)
    for reported in (result.run_directory, result.stdout_log, result.stderr_log):
        assert Path(reported).is_absolute()
        assert verify_repo.resolve() not in Path(reported).parents
        assert Path(reported) != verify_repo.resolve()
    assert result.stdout_log.endswith(STDOUT_LOG_NAME)
    assert result.stderr_log.endswith(STDERR_LOG_NAME)


def test_each_run_gets_its_own_directory(verify_repo: Path) -> None:
    first, second = verify(verify_repo), verify(verify_repo)
    assert first.run_id != second.run_id
    assert first.run_directory != second.run_directory
    assert Path(first.run_directory).is_dir()
    assert Path(second.run_directory).is_dir()


def test_complete_output_is_on_disk_even_when_the_tail_is_bounded(verify_repo: Path) -> None:
    result = verify(verify_repo, "noisy")
    assert result.status is VerificationStatus.PASS
    assert result.stdout_bytes > TAIL_CHARACTERS
    assert result.stderr_bytes > TAIL_CHARACTERS
    assert Path(result.stdout_log).stat().st_size == result.stdout_bytes


def test_response_output_is_bounded(verify_repo: Path) -> None:
    """A verbose verifier cannot consume unbounded MCP response tokens."""
    result = verify(verify_repo, "noisy")
    assert len(result.stdout_tail) <= TAIL_CHARACTERS
    assert len(result.stderr_tail) <= TAIL_CHARACTERS
    assert result.output_truncated is True
    assert any("tail" in limitation for limitation in result.limitations)


def test_bounded_tail_keeps_the_end_of_the_stream(verify_repo: Path) -> None:
    """The tail is the most recent output, which is where a failure reports itself."""
    result = verify(verify_repo, "noisy")
    assert "0399" in result.stdout_tail
    assert "0000 " not in result.stdout_tail


def test_small_output_is_not_marked_truncated(verify_repo: Path) -> None:
    result = verify(verify_repo)
    assert result.output_truncated is False


def test_artifacts_are_enumerated_from_the_run_directory(verify_repo: Path) -> None:
    result = verify(verify_repo, "structural", "with_output")
    paths = {artifact.path for artifact in result.artifacts}
    assert f"{result.run_directory}/report.json" in paths
    assert f"{result.run_directory}/nested/detail.txt" in paths


def test_artifact_metadata_is_typed(verify_repo: Path) -> None:
    result = verify(verify_repo, "structural", "with_output")
    report = next(a for a in result.artifacts if a.path.endswith("report.json"))
    assert report.kind is ArtifactKind.FILE
    assert report.size_bytes > 0
    nested = next(a for a in result.artifacts if a.path.endswith("nested"))
    assert nested.kind is ArtifactKind.DIRECTORY
    assert nested.size_bytes == 0


def test_logs_are_not_listed_as_artifacts(verify_repo: Path) -> None:
    result = verify(verify_repo, "structural", "with_output")
    names = {Path(artifact.path).name for artifact in result.artifacts}
    assert STDOUT_LOG_NAME not in names
    assert STDERR_LOG_NAME not in names


def test_no_artifacts_when_the_verifier_writes_nothing(verify_repo: Path) -> None:
    assert verify(verify_repo, "structural", "default").artifacts == []


def test_the_repository_is_never_scanned_for_artifacts(verify_repo: Path) -> None:
    """Files outside the run directory are not promoted into the result."""
    (verify_repo / "game" / "stray.txt").write_text("not an artifact\n", encoding="utf-8")
    result = verify(verify_repo, "structural", "with_output")
    assert all(artifact.path.startswith(result.run_directory) for artifact in result.artifacts)
    assert all(not artifact.path.startswith(str(verify_repo.resolve())) for artifact in result.artifacts)


# --- environment -------------------------------------------------------------


def _environment_seen_by_verifier(root: Path) -> dict[str, str]:
    registry = fixture_registry()
    registry["verifiers"]["structural"]["script"] = "tools/environment.py"
    result = verify(root, registry=registry)
    assert result.status is VerificationStatus.PASS
    return json.loads(Path(result.stdout_log).read_text())


def test_dangerous_ambient_variables_do_not_reach_the_verifier(
    verify_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_DIR", "/elsewhere/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/elsewhere")
    monkeypatch.setenv("PYTHONPATH", "/injected")
    monkeypatch.setenv("PYTHONHOME", "/injected")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "hunter2")

    seen = _environment_seen_by_verifier(verify_repo)
    for leaked in ("GIT_DIR", "GIT_WORK_TREE", "PYTHONPATH", "PYTHONHOME", "AWS_SECRET_ACCESS_KEY"):
        assert leaked not in seen


def test_required_benign_variables_are_preserved(verify_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    seen = _environment_seen_by_verifier(verify_repo)
    assert seen["PATH"] == os.environ["PATH"]
    assert seen["HOME"] == os.environ["HOME"]
    assert seen["LANG"] == "en_US.UTF-8"
    assert seen["LC_ALL"] == "C.UTF-8"


def test_bytecode_writing_is_suppressed(verify_repo: Path) -> None:
    """Keeps a verifier from leaving __pycache__ in the operator's checkout."""
    assert _environment_seen_by_verifier(verify_repo)["PYTHONDONTWRITEBYTECODE"] == "1"


def test_registry_environment_reaches_the_verifier(verify_repo: Path) -> None:
    registry = fixture_registry()
    registry["verifiers"]["structural"]["script"] = "tools/environment.py"
    registry["verifiers"]["structural"]["environment"] = {"HIWAGA_FIXTURE_FLAG": "set"}
    result = verify(verify_repo, registry=registry)
    seen = json.loads(Path(result.stdout_log).read_text())
    assert seen["HIWAGA_FIXTURE_FLAG"] == "set"


def test_verifier_runs_in_the_configured_working_directory(verify_repo: Path) -> None:
    (verify_repo / "tools" / "cwd.py").write_text("import os\nprint(os.getcwd())\n", encoding="utf-8")
    registry = fixture_registry()
    registry["verifiers"]["structural"]["script"] = "tools/cwd.py"
    registry["verifiers"]["structural"]["working_directory"] = "game"
    result = verify(verify_repo, registry=registry)
    assert Path(result.stdout_log).read_text().strip() == str((verify_repo / "game").resolve())


# --- read-only repository proof ----------------------------------------------


def _repository_fingerprint(root: Path) -> tuple[str, str, str]:
    """`(HEAD, porcelain status, hash of every tracked file's content)`."""
    head = run_git(root, "rev-parse", "HEAD")
    status = run_git(root, "status", "--porcelain=v1")
    tracked = run_git(root, "ls-files", "-s")
    return head, status, tracked


def test_verification_leaves_git_status_and_the_index_untouched(tmp_path: Path) -> None:
    """The exact proof the corridor exists for: HEAD, status, and the index hash survive a run."""
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    install_repo_python(root)
    install_fixture_verifiers(root)
    init_git_repo(root)  # no `.gitignore` at all: nothing needs to be ignored anymore

    def snapshot() -> tuple[str, str, str]:
        head = run_git(root, "rev-parse", "HEAD")
        status = run_git(root, "status", "--porcelain=v1")
        index_hash = hashlib.sha256((root / ".git" / "index").read_bytes()).hexdigest()
        return head, status, index_hash

    before = snapshot()
    result = verify(root, "structural", "with_output")
    after = snapshot()

    assert result.status is VerificationStatus.PASS
    assert before == after
    assert before[1] == "", "the fixture repository was not clean to begin with"
    assert not (root / ".hiwaga-mcp").exists()


def test_verification_leaves_tracked_source_unchanged(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    install_repo_python(root)
    install_fixture_verifiers(root)
    # No `.hiwaga-mcp/` entry: run state lives outside the repository now, so
    # no ignore configuration is needed to keep this repository's status clean.
    (root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    init_git_repo(root)

    before = _repository_fingerprint(root)
    result = verify(root, "structural", "with_output")
    assert result.status is VerificationStatus.PASS
    after = _repository_fingerprint(root)

    assert before == after, "verification changed the repository"


def test_the_read_only_check_would_notice_a_mutating_verifier(tmp_path: Path) -> None:
    """The fingerprint is not vacuous: a verifier that writes tracked source is caught."""
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    install_repo_python(root)
    install_fixture_verifiers(root)
    (root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    init_git_repo(root)

    registry = fixture_registry()
    registry["verifiers"]["structural"]["script"] = "tools/mutate.py"
    registry["verifiers"]["structural"]["modes"]["default"]["args"] = ["docs/CANON.md"]

    before = _repository_fingerprint(root)
    assert verify(root, registry=registry).status is VerificationStatus.PASS
    assert _repository_fingerprint(root) != before


def test_no_repository_local_state_is_created(verify_repo: Path) -> None:
    """Verification creates nothing at all inside the repository: run state moved out.

    This is the corridor's central regression: `hiwaga_verify` must not require
    or create any `hiwaga-mcp`-owned state inside the target HIWAGA checkout.
    """
    before = set(verify_repo.rglob("*"))
    result = verify(verify_repo, "structural", "with_output")
    after = set(verify_repo.rglob("*"))

    assert after == before, "verification created something inside the repository"
    assert not (verify_repo / ".hiwaga-mcp").exists()

    # The run's actual state landed externally, so the guarantee above is not vacuous.
    assert Path(result.run_directory).is_dir()
    assert verify_repo.resolve() not in Path(result.run_directory).parents


def test_two_repositories_are_isolated_end_to_end(tmp_path: Path) -> None:
    """Two real checkouts, verified for real, land in two separate external namespaces."""
    first = make_hiwaga_repo(tmp_path / "first")
    second = make_hiwaga_repo(tmp_path / "second")
    for root in (first, second):
        install_repo_python(root)
        install_fixture_verifiers(root)

    first_result = verify(first, "structural", "with_output")
    second_result = verify(second, "structural", "with_output")

    first_run = Path(first_result.run_directory)
    second_run = Path(second_result.run_directory)
    assert first_run != second_run
    assert first_run not in second_run.parents
    assert second_run not in first_run.parents
    assert first_run.is_dir() and second_run.is_dir()

    assert repository_state_key(first) != repository_state_key(second)
    for artifact in first_result.artifacts:
        assert not artifact.path.startswith(str(second_run))
    for artifact in second_result.artifacts:
        assert not artifact.path.startswith(str(first_run))

    for root in (first, second):
        assert not (root / ".hiwaga-mcp").exists()
