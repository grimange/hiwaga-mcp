"""Read-only Git facts for the configured HIWAGA checkout.

Uses argv-based subprocess calls only. Inspection never writes to the
repository: `GIT_OPTIONAL_LOCKS=0` stops `git status` from refreshing the
index, and the environment is an allowlist so an ambient `GIT_DIR` or
`GIT_WORK_TREE` cannot redirect Git away from the configured root.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hiwaga_mcp.errors import ProjectStateUnavailableError
from hiwaga_mcp.models.state import GitState

GIT_TIMEOUT_SECONDS = 30.0
_INHERITED_ENV = ("PATH", "HOME", "XDG_CONFIG_HOME")
_BRANCH_REF_PREFIX = "refs/heads/"


def _git_env(repo_root: Path) -> dict[str, str]:
    env = {name: os.environ[name] for name in _INHERITED_ENV if name in os.environ}
    env["LC_ALL"] = "C"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Git must not discover a repository above the configured root.
    env["GIT_CEILING_DIRECTORIES"] = str(repo_root.parent)
    return env


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            env=_git_env(repo_root),
            capture_output=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise ProjectStateUnavailableError(
            "The `git` executable was not found; repository state cannot be established.",
            details={"problem": "git_not_found", "command": ["git", *args]},
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProjectStateUnavailableError(
            f"`git {' '.join(args)}` did not finish within {GIT_TIMEOUT_SECONDS:g}s.",
            details={"problem": "git_timeout", "command": ["git", *args]},
        ) from exc
    except OSError as exc:
        raise ProjectStateUnavailableError(
            f"`git {' '.join(args)}` could not be executed: {exc}",
            details={"problem": "git_not_executable", "command": ["git", *args]},
        ) from exc


def _failed(
    args: tuple[str, ...], result: subprocess.CompletedProcess[bytes]
) -> ProjectStateUnavailableError:
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    return ProjectStateUnavailableError(
        f"`git {' '.join(args)}` failed (exit {result.returncode}): {stderr or 'no diagnostic output'}",
        details={
            "problem": "git_command_failed",
            "command": ["git", *args],
            "exit_code": result.returncode,
            "stderr": stderr,
        },
    )


def read_git_state(repo_root: Path) -> GitState:
    """Establish branch, HEAD, and worktree state for `repo_root`.

    Raises:
        ProjectStateUnavailableError: Git is unavailable, `repo_root` is not a
            usable repository, or HEAD has no commit. Carries
            `HIWAGA_PROJECT_STATE_UNAVAILABLE`; no partial state is returned.
    """
    root = repo_root.resolve()

    head_args = ("rev-parse", "--verify", "HEAD^{commit}")
    head_result = _run_git(root, *head_args)
    if head_result.returncode != 0:
        raise _failed(head_args, head_result)
    head = head_result.stdout.decode("utf-8", errors="replace").strip()
    if len(head) < 40 or any(c not in "0123456789abcdef" for c in head):
        raise ProjectStateUnavailableError(
            f"`git rev-parse` did not return a full commit SHA: {head!r}",
            details={"problem": "unexpected_head_output", "output": head},
        )

    # Exit 1 with --quiet means HEAD is not a symbolic ref, i.e. detached.
    branch_args = ("symbolic-ref", "--quiet", "HEAD")
    branch_result = _run_git(root, *branch_args)
    branch: str | None
    if branch_result.returncode == 0:
        ref = branch_result.stdout.decode("utf-8", errors="replace").strip()
        if not ref.startswith(_BRANCH_REF_PREFIX):
            raise ProjectStateUnavailableError(
                f"HEAD points at an unexpected ref: {ref!r}",
                details={"problem": "unexpected_head_ref", "ref": ref},
            )
        branch = ref[len(_BRANCH_REF_PREFIX) :]
    elif branch_result.returncode == 1:
        branch = None
    else:
        raise _failed(branch_args, branch_result)

    # `-z --no-renames` yields exactly one NUL-terminated record per entry, and
    # `--untracked-files=all` counts each untracked file rather than its directory.
    status_args = ("status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all")
    status_result = _run_git(root, *status_args)
    if status_result.returncode != 0:
        raise _failed(status_args, status_result)
    change_count = len([record for record in status_result.stdout.split(b"\0") if record])

    return GitState(
        branch=branch,
        head=head,
        detached_head=branch is None,
        worktree_clean=change_count == 0,
        worktree_change_count=change_count,
    )


__all__ = ["GIT_TIMEOUT_SECONDS", "read_git_state"]
