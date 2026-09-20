"""Controlled execution of registered verifiers.

Two steps, deliberately separated so the first can be inspected without running
anything:

1. `build_execution_plan` turns a registry entry plus the validated repository
   root into a fully resolved `ExecutionPlan`. Every path it produces has been
   through the repository containment boundary.
2. `execute_plan` runs that plan as a subprocess and classifies the outcome.

There is no shell anywhere in this module. Processes are launched with an argv
vector through `asyncio.create_subprocess_exec`, in their own session so a
timeout can terminate the whole process group rather than orphaning children.

The caller contributes a verifier id and a mode name and nothing else. The
executable, arguments, working directory, timeout, environment, and proof class
all come from the trusted registry and server configuration.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from pathlib import Path

from hiwaga_mcp.models.verification import (
    ArtifactKind,
    ExecutionPlan,
    VerificationArtifact,
    VerificationResult,
    VerificationStatus,
)
from hiwaga_mcp.models.verification_registry import (
    RUN_DIRECTORY_TOKEN,
    ExecutableStrategy,
    VerifierDefinition,
    VerifierMode,
)
from hiwaga_mcp.services.repository import resolve_within_repository
from hiwaga_mcp.services.verification_registry import load_verifier_registry, select_verifier

#: Where controlled runtime state lives, relative to the HIWAGA root. Ignored
#: scratch: nothing here is tracked evidence, and nothing is promoted from it.
SCRATCH_DIRECTORY = ".hiwaga-mcp"
RUNS_DIRECTORY = f"{SCRATCH_DIRECTORY}/runs"

STDOUT_LOG_NAME = "stdout.log"
STDERR_LOG_NAME = "stderr.log"

#: How much of each stream comes back in the MCP result. The complete stream is
#: always on disk; this only bounds what a verifier can spend in response tokens.
TAIL_CHARACTERS = 2000

#: Upper bound on artifacts enumerated from a run directory.
MAX_ARTIFACTS = 50

#: Seconds a terminated process gets to exit before it is killed outright.
TERMINATION_GRACE_SECONDS = 5.0

#: Ambient variables a verifier inherits. An allowlist, not a denylist: anything
#: not named here (GIT_DIR, GIT_WORK_TREE, PYTHONPATH, PYTHONHOME, and every
#: other authority-changing variable) simply never reaches the child.
INHERITED_ENVIRONMENT = ("PATH", "HOME", "LANG", "TZ")
INHERITED_ENVIRONMENT_PREFIXES = ("LC_",)

#: Fixed entries this server always sets. Suppressing bytecode keeps a verifier
#: from leaving `__pycache__` directories in the operator's checkout.
FIXED_ENVIRONMENT = {"PYTHONDONTWRITEBYTECODE": "1"}

_ACCEPTANCE_LIMITATION = (
    "Machine verification is not operator acceptance: a PASS means the verifier's own assertions held, "
    "not that a human reviewed or approved the result."
)


def new_run_id() -> str:
    """A collision-free, filesystem-safe identifier for one invocation.

    Random rather than derived: no caller-supplied text reaches a path segment,
    and correctness does not depend on the clock.
    """
    return uuid.uuid4().hex


def build_environment(definition: VerifierDefinition) -> dict[str, str]:
    """The complete environment the child receives.

    Built from nothing: allowlisted ambient values, this server's fixed entries,
    then the registry's static entries. The caller supplies none of it.
    """
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in INHERITED_ENVIRONMENT or name.startswith(INHERITED_ENVIRONMENT_PREFIXES)
    }
    environment.update(FIXED_ENVIRONMENT)
    environment.update(definition.environment)
    return environment


#: Where `REPO_PYTHON` looks, relative to the repository root.
REPO_PYTHON_DIRECTORY = ".venv/bin"
REPO_PYTHON_NAME = "python"


def resolve_executable(repo_root: Path, strategy: ExecutableStrategy) -> Path:
    """Resolve an executable strategy to a concrete path inside the repository.

    The path is produced by the strategy, never by the caller: no registry entry
    and no tool argument can name an interpreter.

    The *directory* holding the interpreter goes through containment, so a
    `.venv` symlinked at another checkout is refused. The interpreter entry
    itself is deliberately not symlink-resolved: in every ordinary virtualenv
    `.venv/bin/python` is a link to the system interpreter, and following it
    would reject every real checkout.

    Raises:
        TargetOutsideRepositoryError: the interpreter directory escapes the root.
    """
    if strategy is ExecutableStrategy.REPO_PYTHON:
        directory = resolve_within_repository(repo_root, REPO_PYTHON_DIRECTORY)
        return directory / REPO_PYTHON_NAME
    # Unreachable while the strategy enum has one member; keeps the mapping total.
    raise AssertionError(f"unhandled executable strategy: {strategy}")  # pragma: no cover


def build_execution_plan(
    repo_root: Path,
    verifier: str,
    definition: VerifierDefinition,
    mode_name: str,
    mode: VerifierMode,
    *,
    run_id: str | None = None,
) -> ExecutionPlan:
    """Resolve a registry entry into the exact invocation that will run.

    Every repository path — interpreter, script, working directory, run
    directory — goes through `resolve_within_repository`, so a registry that
    escaped schema validation still cannot reach outside the checkout.

    Raises:
        TargetOutsideRepositoryError: a registry path escapes the repository.
    """
    root = repo_root.expanduser().resolve()
    identifier = run_id or new_run_id()

    executable = resolve_executable(root, definition.executable)
    script = resolve_within_repository(root, definition.script)
    cwd = resolve_within_repository(root, definition.working_directory)
    run_directory = resolve_within_repository(root, f"{RUNS_DIRECTORY}/{identifier}")

    argv = [str(executable), str(script)]
    argv += [arg.replace(RUN_DIRECTORY_TOKEN, str(run_directory)) for arg in mode.args]

    return ExecutionPlan(
        verifier=verifier,
        mode=mode_name,
        proof_class=definition.proof_class,
        executable=executable,
        argv=argv,
        cwd=cwd,
        timeout_seconds=definition.timeout_seconds,
        run_id=identifier,
        run_directory=run_directory,
        environment=build_environment(definition),
    )


def _signal_process_group(process: asyncio.subprocess.Process, number: int) -> None:
    """Signal the child's whole process group, falling back to the child alone."""
    try:
        os.killpg(os.getpgid(process.pid), number)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.send_signal(number)
        except (ProcessLookupError, OSError):
            pass


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """Stop the process group and reap it, escalating if it ignores SIGTERM."""
    _signal_process_group(process, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=TERMINATION_GRACE_SECONDS)
        return
    except asyncio.TimeoutError:
        pass
    _signal_process_group(process, signal.SIGKILL)
    await process.wait()


def _tail(path: Path) -> tuple[str, int, bool]:
    """`(bounded tail, complete size in bytes, whether the tail omits anything)`."""
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            # Read a little more than the limit so multi-byte characters at the
            # cut survive decoding; the text is trimmed to the limit after.
            if size > TAIL_CHARACTERS * 4:
                handle.seek(-TAIL_CHARACTERS * 4, os.SEEK_END)
            raw = handle.read()
    except OSError:
        return "", 0, False
    text = raw.decode("utf-8", errors="replace")
    if len(text) > TAIL_CHARACTERS:
        return text[-TAIL_CHARACTERS:], size, True
    return text, size, len(text.encode("utf-8")) < size


def _artifacts(run_directory: Path, repo_root: Path) -> tuple[list[VerificationArtifact], bool]:
    """Enumerate what the verifier left in its own run directory.

    Only this directory is inspected. The repository is never scanned for files
    a verifier may have modified elsewhere.
    """
    logs = {STDOUT_LOG_NAME, STDERR_LOG_NAME}
    found: list[VerificationArtifact] = []
    try:
        candidates = sorted(run_directory.rglob("*"), key=lambda path: str(path))
    except OSError:  # pragma: no cover - run directory disappeared under us
        return [], False

    for path in candidates:
        if path.parent == run_directory and path.name in logs:
            continue
        try:
            is_dir = path.is_dir()
            size = 0 if is_dir else path.stat().st_size
        except OSError:  # pragma: no cover - race with the verifier
            continue
        found.append(
            VerificationArtifact(
                path=str(path.relative_to(repo_root)),
                kind=ArtifactKind.DIRECTORY if is_dir else ArtifactKind.FILE,
                size_bytes=size,
            )
        )
    return found[:MAX_ARTIFACTS], len(found) > MAX_ARTIFACTS


def _classify(
    exit_code: int | None, timed_out: bool, launch_error: str | None
) -> tuple[VerificationStatus, str]:
    """Map a completed execution attempt onto the verification vocabulary."""
    if launch_error is not None:
        return (
            VerificationStatus.EXECUTION_ERROR,
            f"The verifier could not be executed: {launch_error}",
        )
    if timed_out:
        return (
            VerificationStatus.TIMEOUT,
            "The verifier exceeded its configured deadline and its process group was terminated. "
            "No verification outcome was established.",
        )
    if exit_code == 0:
        return (
            VerificationStatus.PASS,
            "The verifier ran to completion and reported success.",
        )
    if exit_code is not None and exit_code < 0:
        # Negative is asyncio's encoding of "killed by signal N", and no
        # verifier failure convention produces it.
        return (
            VerificationStatus.EXECUTION_ERROR,
            f"The verifier was terminated by signal {abs(exit_code)} before reporting a result.",
        )
    return (
        VerificationStatus.FAIL,
        f"The verifier ran to completion and reported a verification failure (exit code {exit_code}).",
    )


async def execute_plan(plan: ExecutionPlan, repo_root: Path) -> VerificationResult:
    """Run a resolved plan and classify the outcome.

    A verifier that runs and fails, times out, or cannot launch all produce a
    result, never an exception: those are verification outcomes. Only an invalid
    request or untrustworthy configuration raises, and that happens before here.
    """
    root = repo_root.expanduser().resolve()
    stdout_log = plan.run_directory / STDOUT_LOG_NAME
    stderr_log = plan.run_directory / STDERR_LOG_NAME

    exit_code: int | None = None
    timed_out = False
    launch_error: str | None = None
    started = time.monotonic()

    try:
        plan.run_directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        launch_error = f"the run directory could not be created: {exc}"
    else:
        try:
            with stdout_log.open("wb") as out_handle, stderr_log.open("wb") as err_handle:
                process = await asyncio.create_subprocess_exec(
                    plan.argv[0],
                    *plan.argv[1:],
                    cwd=str(plan.cwd),
                    env=plan.environment,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=out_handle,
                    stderr=err_handle,
                    # Its own session, so a deadline terminates the verifier and
                    # everything it spawned rather than orphaning children.
                    start_new_session=True,
                )
                try:
                    exit_code = await asyncio.wait_for(process.wait(), timeout=plan.timeout_seconds)
                except asyncio.TimeoutError:
                    timed_out = True
                    await _terminate(process)
                    exit_code = process.returncode
        except (OSError, ValueError) as exc:
            launch_error = str(exc)

    duration_ms = int((time.monotonic() - started) * 1000)
    status, reason = _classify(exit_code, timed_out, launch_error)

    stdout_tail, stdout_bytes, stdout_cut = _tail(stdout_log)
    stderr_tail, stderr_bytes, stderr_cut = _tail(stderr_log)
    artifacts, artifacts_truncated = _artifacts(plan.run_directory, root)

    limitations = [_ACCEPTANCE_LIMITATION]
    if status is VerificationStatus.TIMEOUT:
        limitations.append(
            "The verifier was terminated mid-run, so its output is partial and proves nothing "
            "about the state it was checking."
        )
    if stdout_cut or stderr_cut:
        limitations.append(
            f"Captured output exceeds the {TAIL_CHARACTERS}-character tail returned here; "
            "the complete logs are in the run directory."
        )

    return VerificationResult(
        repository=root.name,
        repository_root=str(root),
        verifier=plan.verifier,
        mode=plan.mode,
        proof_class=plan.proof_class,
        status=status,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_ms=duration_ms,
        run_id=plan.run_id,
        run_directory=str(plan.run_directory.relative_to(root)),
        stdout_log=str(stdout_log.relative_to(root)),
        stderr_log=str(stderr_log.relative_to(root)),
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        output_truncated=stdout_cut or stderr_cut,
        artifacts=artifacts,
        artifacts_truncated=artifacts_truncated,
        reason=reason,
        limitations=limitations,
    )


async def run_verification(
    repo_root: Path, verifier: str, mode: str | None = None, *, registry_text: str | None = None
) -> VerificationResult:
    """Look a verifier up in the canonical registry and execute it.

    This function deliberately consults nothing else. It does not call preflight
    or the model gate: whether development may proceed, and whether a worker is
    authorized, are separate questions an external planner composes. Verify owns
    safe execution only.

    Raises:
        VerifierRegistryError: the registry is missing or untrustworthy.
        UnknownVerifierError: no such registered verifier.
        UnsupportedVerifyModeError: the verifier does not declare that mode.
        TargetOutsideRepositoryError: a registry path escapes the repository.
    """
    registry = load_verifier_registry(registry_text)
    verifier_id, definition, mode_name, mode_entry = select_verifier(registry, verifier, mode)
    plan = build_execution_plan(repo_root, verifier_id, definition, mode_name, mode_entry)
    return await execute_plan(plan, repo_root)


__all__ = [
    "FIXED_ENVIRONMENT",
    "SCRATCH_DIRECTORY",
    "INHERITED_ENVIRONMENT",
    "MAX_ARTIFACTS",
    "RUNS_DIRECTORY",
    "TAIL_CHARACTERS",
    "build_environment",
    "build_execution_plan",
    "execute_plan",
    "new_run_id",
    "resolve_executable",
    "run_verification",
]
