"""Where this server's own runtime state lives — never inside the HIWAGA checkout.

`hiwaga_verify` needs somewhere to write run logs and artifacts. That state
belongs to `hiwaga-mcp`, not to the repository it inspects: a HIWAGA checkout
should never need a `.gitignore` entry or any other awareness of this server to
stay clean. This module resolves an external, XDG-based state root and derives
a stable per-repository namespace under it.

Three responsibilities, each pure (no filesystem I/O, no directory creation):

1. `resolve_state_root` — the external root all of this server's state lives
   under: `$XDG_STATE_HOME/hiwaga-mcp`, or `~/.local/state/hiwaga-mcp`.
2. `repository_state_key` — a stable, deterministic namespace per canonical
   repository root, so two checkouts never collide and one checkout is always
   consistent regardless of its branch or worktree state.
3. `resolve_run_directory` — combines the two into one run's directory.

Callers create directories lazily, at the point they actually write to them;
nothing here creates anything. This intentionally does not reuse
`hiwaga_mcp.services.repository`'s containment primitive: that primitive proves
a path is *inside* the validated HIWAGA root, which is the opposite of what an
external state root must be. Safety here instead comes from every path
component being either produced internally (the repository key, an
XDG-anchored root) or checked against a small explicit character set (the run
id).
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Mapping
from pathlib import Path

from hiwaga_mcp.errors import RuntimeStateError

#: Directory name this server's state lives under, inside the resolved state home.
STATE_APP_NAME = "hiwaga-mcp"

#: The XDG variable consulted for the state home. Not `HIWAGA_MCP_STATE_ROOT` or
#: any other bespoke variable: normal operation needs no configuration at all.
STATE_HOME_ENV_VAR = "XDG_STATE_HOME"

#: XDG fallback when the variable is unset, blank, or not absolute.
DEFAULT_STATE_HOME_RELATIVE = Path(".local") / "state"

#: Path segments between the state root and a run: `<root>/repositories/<key>/runs/<run-id>`.
REPOSITORIES_SEGMENT = "repositories"
RUNS_SEGMENT = "runs"

#: Hex characters of the SHA-256 digest kept as the repository key. Short enough
#: for a readable directory name, long enough (96 bits) that two real HIWAGA
#: checkouts on one machine will never collide by chance.
REPOSITORY_KEY_LENGTH = 24

_SAFE_COMPONENT_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z")


def _safe_component(value: str, field: str) -> str:
    """A value trusted as exactly one path segment: no separator, no traversal, no empty string.

    Defence in depth: today's only caller of `resolve_run_directory` is
    `new_run_id()` (a `uuid4().hex`), which already satisfies this, and no MCP
    tool argument reaches this function. This still refuses to build a path
    from anything else, so that guarantee cannot silently erode later.
    """
    if not _SAFE_COMPONENT_RE.fullmatch(value):
        raise RuntimeStateError(
            f"{field} {value!r} is not a safe single path component.",
            details={"problem": "unsafe_path_component", "field": field, "value": value},
        )
    return value


def resolve_state_root(env: Mapping[str, str] | None = None) -> Path:
    """The external root this server's own state lives under.

    Resolution, in order:

    1. `XDG_STATE_HOME`, if set to a non-blank, absolute path. A relative value
       (including a bare `~...`, since tilde expansion is intentionally not
       supported here) does not satisfy XDG's own absolute-path requirement and
       is treated as unset, falling through to (2), rather than being silently
       anchored to the current working directory.
    2. `<HOME>/.local/state`, where `HOME` must itself be absolute.

    `env` is a construction-time seam for deterministic tests (mirroring
    `hiwaga_mcp.config.load_config`); real operation reads `os.environ`.

    Raises:
        RuntimeStateError: neither source yields a usable absolute directory.
            Carries `HIWAGA_RUNTIME_STATE_UNAVAILABLE`. There is no fallback
            into the HIWAGA repository.
    """
    source = os.environ if env is None else env

    xdg_state_home = source.get(STATE_HOME_ENV_VAR)
    if xdg_state_home is not None and xdg_state_home.strip():
        candidate = Path(xdg_state_home.strip())
        if candidate.is_absolute():
            return (candidate / STATE_APP_NAME).resolve()

    home = source.get("HOME")
    if home is None or not home.strip():
        raise RuntimeStateError(
            f"Neither {STATE_HOME_ENV_VAR} nor HOME names a usable directory, so no local "
            "runtime-state root can be established.",
            details={"problem": "no_home", "xdg_state_home": xdg_state_home},
        )
    home_dir = Path(home.strip())
    if not home_dir.is_absolute():
        raise RuntimeStateError(
            f"HOME is not an absolute path ({home!r}), so no local runtime-state root can be established.",
            details={"problem": "home_not_absolute", "home": home},
        )
    return (home_dir / DEFAULT_STATE_HOME_RELATIVE / STATE_APP_NAME).resolve()


def repository_state_key(repo_root: Path) -> str:
    """A stable namespace key for `repo_root`, independent of branch, HEAD, or worktree state.

    Deterministic: the same canonical root always yields the same key, and two
    distinct canonical roots practically never collide. The key is derived
    solely from the canonical absolute path string — not the basename, not any
    Git state — so a repository's identity on disk is what is namespaced.
    """
    canonical = repo_root.expanduser().resolve()
    digest = hashlib.sha256(str(canonical).encode("utf-8")).hexdigest()
    return digest[:REPOSITORY_KEY_LENGTH]


def resolve_run_directory(repo_root: Path, run_id: str, *, env: Mapping[str, str] | None = None) -> Path:
    """The absolute external directory for one verifier run of `repo_root`.

    Shape: `<state root>/repositories/<repository key>/runs/<run id>`. Pure
    path computation; nothing is created here or by `repository_state_key` or
    `resolve_state_root`; a caller creates the directory lazily when it is
    actually about to write to it.

    Raises:
        RuntimeStateError: `run_id` is not a safe single path component, or the
            state root cannot be established (see `resolve_state_root`).
    """
    key = _safe_component(repository_state_key(repo_root), "repository key")
    safe_run_id = _safe_component(run_id, "run_id")
    return resolve_state_root(env) / REPOSITORIES_SEGMENT / key / RUNS_SEGMENT / safe_run_id


__all__ = [
    "DEFAULT_STATE_HOME_RELATIVE",
    "REPOSITORIES_SEGMENT",
    "REPOSITORY_KEY_LENGTH",
    "RUNS_SEGMENT",
    "STATE_APP_NAME",
    "STATE_HOME_ENV_VAR",
    "repository_state_key",
    "resolve_run_directory",
    "resolve_state_root",
]
