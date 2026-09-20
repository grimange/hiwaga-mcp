"""The verifier registry schema.

The registry is the execution allowlist. Everything that determines *what* runs
— executable, script, arguments, working directory, timeout, proof class — comes
from here, never from the MCP caller. A caller selects only a registered
verifier id and one of its declared modes.

Every model forbids unknown fields. A registry carrying a key this schema does
not model is rejected rather than partially honoured, because an unmodelled key
is exactly where an execution-relevant setting would hide.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from hiwaga_mcp.models.verification import ProofClass

#: The single substitution a mode argument may use. It expands to the absolute
#: path of the run directory this server generated for the invocation. There is
#: no general templating: any other `{...}` token is a registry error.
RUN_DIRECTORY_TOKEN = "{run_directory}"


class ExecutableStrategy(str, Enum):
    """The closed set of interpreters a verifier may be launched with.

    A registry never names an executable path directly. Each strategy resolves
    deterministically against the validated HIWAGA root at execution time.
    """

    #: `<repo_root>/.venv/bin/python` — the HIWAGA checkout's own interpreter.
    REPO_PYTHON = "REPO_PYTHON"


def _reject_unsafe_relative_path(value: str, field: str) -> str:
    """Structurally reject a registry path that cannot be repository-relative.

    This is the cheap schema-time check. The authoritative containment check
    happens against the real root when the execution plan is built.
    """
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    if "\x00" in value:
        raise ValueError(f"{field} must not contain a null byte")
    if value.startswith("/") or value.startswith("~"):
        raise ValueError(f"{field} must be repository-relative, not {value!r}")
    if ".." in value.split("/"):
        raise ValueError(f"{field} must not contain a '..' segment")
    return value


class VerifierMode(BaseModel):
    """One named invocation of a verifier.

    `args` are fixed by the registry and appended after the script. The caller
    contributes no argument and cannot reorder these.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    args: list[str] = Field(default_factory=list, description="Fixed arguments for this mode.")
    description: str | None = Field(default=None, description="What this mode proves.")

    @field_validator("args")
    @classmethod
    def _args_are_plain_values(cls, value: list[str]) -> list[str]:
        for arg in value:
            if "\x00" in arg:
                raise ValueError("arguments must not contain a null byte")
            # Reject any placeholder other than the one supported token, so an
            # unrecognised `{...}` can never reach the command line verbatim.
            for piece in arg.split("{")[1:]:
                token = "{" + piece.split("}")[0] + "}"
                if token != RUN_DIRECTORY_TOKEN:
                    raise ValueError(
                        f"unsupported argument placeholder {token!r} "
                        f"(only {RUN_DIRECTORY_TOKEN!r} is substituted)"
                    )
        return value


class VerifierDefinition(BaseModel):
    """One registered verification operation.

    The proof class is declared here, by the registry. A caller cannot claim
    that a headless verifier produced native rendered evidence.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    proof_class: ProofClass = Field(description="The kind of evidence this verifier can produce.")
    executable: ExecutableStrategy = Field(description="How the interpreter is resolved.")
    script: str = Field(description="Repository-relative script to execute.")
    working_directory: str = Field(default=".", description="Repository-relative working directory.")
    timeout_seconds: StrictInt = Field(
        gt=0,
        description="Hard deadline in seconds; the caller cannot override it.",
    )
    modes: dict[str, VerifierMode] = Field(min_length=1, description="Declared modes, by name.")
    default_mode: str | None = Field(
        default=None,
        description="Mode used when the caller omits one. Absent means a mode is required.",
    )
    description: str | None = Field(default=None, description="What this verifier checks.")
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Fixed environment entries from the trusted registry. Static strings only.",
    )

    @field_validator("script")
    @classmethod
    def _script_is_contained(cls, value: str) -> str:
        return _reject_unsafe_relative_path(value, "script")

    @field_validator("working_directory")
    @classmethod
    def _working_directory_is_contained(cls, value: str) -> str:
        return _reject_unsafe_relative_path(value, "working_directory")

    @field_validator("modes")
    @classmethod
    def _mode_names_are_usable(cls, value: dict[str, VerifierMode]) -> dict[str, VerifierMode]:
        for name in value:
            if not name.strip():
                raise ValueError("mode names must not be empty")
        return value

    @field_validator("environment")
    @classmethod
    def _environment_is_static(cls, value: dict[str, str]) -> dict[str, str]:
        for name, entry in value.items():
            if not name.strip():
                raise ValueError("environment names must not be empty")
            if "\x00" in name or "\x00" in entry:
                raise ValueError("environment entries must not contain a null byte")
        return value

    @model_validator(mode="after")
    def _default_mode_is_declared(self) -> VerifierDefinition:
        if self.default_mode is not None and self.default_mode not in self.modes:
            raise ValueError(f"default_mode {self.default_mode!r} is not a declared mode")
        return self


class VerifierRegistry(BaseModel):
    """The canonical allowlist of verification operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(description="Registry schema version.")
    verifiers: dict[str, VerifierDefinition] = Field(description="Registered verifiers, by id.")

    @field_validator("verifiers")
    @classmethod
    def _ids_are_usable(cls, value: dict[str, VerifierDefinition]) -> dict[str, VerifierDefinition]:
        for name in value:
            if not name.strip():
                raise ValueError("verifier ids must not be empty")
        return value


__all__ = [
    "RUN_DIRECTORY_TOKEN",
    "ExecutableStrategy",
    "VerifierDefinition",
    "VerifierMode",
    "VerifierRegistry",
]
