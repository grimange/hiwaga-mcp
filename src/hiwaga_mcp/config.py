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


__all__ = ["REPO_ROOT_ENV_VAR", "ServerConfig", "load_config"]
