"""Server configuration.

The MCP operates only against an explicitly configured HIWAGA checkout. There
is no fallback to the current working directory: an unconfigured server reports
that fact rather than guessing at a repository.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from hiwaga_mcp.errors import ConfigurationError

REPO_ROOT_ENV_VAR = "HIWAGA_REPO_ROOT"
WORKER_ENV_VAR = "HIWAGA_AI_WORKER"
MODEL_ENV_VAR = "HIWAGA_AI_MODEL"


@dataclass(frozen=True)
class ServerConfig:
    """Validated server configuration.

    `repo_root` is absolute and canonical (symlinks resolved), and was a
    directory at load time. It is not yet known to be a *HIWAGA* checkout;
    that is `hiwaga_mcp.services.repository` identity validation.
    """

    repo_root: Path


def load_config(env: Mapping[str, str] | None = None) -> ServerConfig:
    """Read and validate configuration from the process environment.

    Raises:
        ConfigurationError: the root is unset, empty, unusable, missing, or is
            not a directory. Carries `HIWAGA_CONFIGURATION_INVALID`.
    """
    source = os.environ if env is None else env
    raw = source.get(REPO_ROOT_ENV_VAR)

    if raw is None:
        raise ConfigurationError(
            f"{REPO_ROOT_ENV_VAR} is not set. Set it to the absolute path of the HIWAGA checkout.",
            details={"env_var": REPO_ROOT_ENV_VAR, "problem": "not_set"},
        )

    if not raw.strip():
        raise ConfigurationError(
            f"{REPO_ROOT_ENV_VAR} is set but empty.",
            details={"env_var": REPO_ROOT_ENV_VAR, "problem": "empty"},
        )

    if "\x00" in raw:
        raise ConfigurationError(
            f"{REPO_ROOT_ENV_VAR} contains a null byte.",
            details={"env_var": REPO_ROOT_ENV_VAR, "problem": "null_byte"},
        )

    try:
        candidate = Path(raw.strip()).expanduser()
        resolved = candidate.resolve()
    except OSError as exc:  # pragma: no cover - platform dependent
        raise ConfigurationError(
            f"{REPO_ROOT_ENV_VAR} could not be resolved to a filesystem path: {exc}",
            details={"env_var": REPO_ROOT_ENV_VAR, "problem": "unresolvable", "configured_value": raw},
        ) from exc

    if not resolved.exists():
        raise ConfigurationError(
            f"{REPO_ROOT_ENV_VAR} points at a path that does not exist: {resolved}",
            details={
                "env_var": REPO_ROOT_ENV_VAR,
                "problem": "does_not_exist",
                "resolved_path": str(resolved),
            },
        )

    if not resolved.is_dir():
        raise ConfigurationError(
            f"{REPO_ROOT_ENV_VAR} points at a path that is not a directory: {resolved}",
            details={
                "env_var": REPO_ROOT_ENV_VAR,
                "problem": "not_a_directory",
                "resolved_path": str(resolved),
            },
        )

    return ServerConfig(repo_root=resolved)


@dataclass(frozen=True)
class WorkerIdentity:
    """The trusted AI worker/model identity, exactly as the process was configured.

    Values are unnormalized and either may be None. Absence is a normal state,
    not a startup failure: only `hiwaga_model_gate` cares, and it reports it.
    """

    worker: str | None = None
    model: str | None = None


def load_worker_identity(env: Mapping[str, str] | None = None) -> WorkerIdentity:
    """Read `HIWAGA_AI_WORKER` / `HIWAGA_AI_MODEL` from the process environment.

    This is the only source of worker identity. Nothing is guessed from the
    process name, the MCP client, or any other variable.
    """
    source = os.environ if env is None else env
    return WorkerIdentity(worker=source.get(WORKER_ENV_VAR), model=source.get(MODEL_ENV_VAR))


__all__ = [
    "MODEL_ENV_VAR",
    "REPO_ROOT_ENV_VAR",
    "WORKER_ENV_VAR",
    "ServerConfig",
    "WorkerIdentity",
    "load_config",
    "load_worker_identity",
]
