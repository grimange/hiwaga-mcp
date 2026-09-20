"""Verification vocabulary.

These enums keep machine proof and human acceptance separate. `ProofClass`
describes what kind of evidence a verifier can produce; it never asserts that
an operator accepted the result.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class VerificationStatus(str, Enum):
    """Outcome of an allowlisted verifier execution.

    A `FAIL` is a successful execution that found a defect, and is structured
    domain output rather than an MCP protocol error. `EXECUTION_ERROR` means
    the verifier could not run at all.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class ProofClass(str, Enum):
    """The strength and kind of evidence a verification produced.

    None of these values implies operator visual acceptance.
    """

    STRUCTURAL = "STRUCTURAL"
    HEADLESS = "HEADLESS"
    NATIVE_RENDERED = "NATIVE_RENDERED"


class ArtifactKind(str, Enum):
    """What a produced artifact is on disk."""

    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class VerificationArtifact(BaseModel):
    """A file the verifier produced inside its own controlled run directory.

    Only the run directory is enumerated. The repository is never scanned for
    files a verifier may have touched elsewhere.
    """

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="Repository-relative path of the artifact.")
    kind: ArtifactKind = Field(description="Whether the artifact is a file or a directory.")
    size_bytes: int = Field(description="Size in bytes; 0 for a directory.")


class ExecutionPlan(BaseModel):
    """The fully resolved, trusted invocation, fixed before anything runs.

    Every field comes from the registry, the validated repository root, and the
    generated run directory. Nothing here is caller-supplied, which is why tests
    inspect this model as the execution boundary.

    This is internal: it is never returned to an MCP caller.
    """

    model_config = ConfigDict(frozen=True)

    verifier: str = Field(description="Registered verifier id.")
    mode: str = Field(description="Declared mode being run.")
    proof_class: ProofClass = Field(description="Proof class declared by the registry.")
    executable: Path = Field(description="Absolute interpreter path resolved from the strategy.")
    argv: list[str] = Field(description="Full argument vector, argv[0] being the executable.")
    cwd: Path = Field(description="Absolute working directory, proven inside the repository.")
    timeout_seconds: int = Field(description="Hard deadline from the registry.")
    run_id: str = Field(description="Identifier of this invocation's run directory.")
    run_directory: Path = Field(description="Absolute run directory for logs and artifacts.")
    environment: dict[str, str] = Field(description="The complete environment the child receives.")


class VerificationResult(BaseModel):
    """The outcome of one controlled verifier execution.

    `status` describes the verification, never the MCP call. A FAIL, TIMEOUT, or
    EXECUTION_ERROR is a successful tool call carrying a real result; invalid
    requests are raised as tool errors instead and never appear here.

    Nothing in this model expresses operator acceptance. A PASS means the
    verifier's own machine assertions held, not that a human approved anything.
    """

    model_config = ConfigDict(frozen=True)

    repository: str = Field(description="Name of the validated HIWAGA checkout.")
    repository_root: str = Field(description="Absolute validated repository root.")

    verifier: str = Field(description="Registered verifier id that ran.")
    mode: str = Field(description="Declared mode that ran.")
    proof_class: ProofClass = Field(description="Proof class from the registry, not the caller.")

    status: VerificationStatus = Field(description="PASS, FAIL, TIMEOUT, or EXECUTION_ERROR.")
    exit_code: int | None = Field(
        default=None,
        description="Child exit code; negative means terminated by that signal. Null if never launched.",
    )
    timed_out: bool = Field(description="True when the deadline terminated the process.")
    duration_ms: int = Field(description="Wall-clock duration of the execution attempt.")

    run_id: str = Field(description="Identifier of this invocation.")
    run_directory: str = Field(description="Repository-relative run directory.")

    stdout_log: str = Field(description="Repository-relative path of the complete stdout log.")
    stderr_log: str = Field(description="Repository-relative path of the complete stderr log.")

    stdout_tail: str = Field(description="Bounded tail of stdout; the full log is on disk.")
    stderr_tail: str = Field(description="Bounded tail of stderr; the full log is on disk.")
    stdout_bytes: int = Field(description="Complete stdout size on disk, in bytes.")
    stderr_bytes: int = Field(description="Complete stderr size on disk, in bytes.")
    output_truncated: bool = Field(description="True when a tail omits part of that stream.")

    artifacts: list[VerificationArtifact] = Field(description="Files found in the run directory.")
    artifacts_truncated: bool = Field(description="True when more artifacts exist than are listed.")

    reason: str = Field(description="Human-readable explanation of the status.")
    limitations: list[str] = Field(description="What this execution deterministically did not establish.")


__all__ = [
    "ArtifactKind",
    "ExecutionPlan",
    "ProofClass",
    "VerificationArtifact",
    "VerificationResult",
    "VerificationStatus",
]
