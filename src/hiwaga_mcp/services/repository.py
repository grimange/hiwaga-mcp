"""Repository identity validation and the path containment primitive.

Two responsibilities, both deterministic and both prerequisites for every later
authority and verification corridor:

1. Decide whether a configured root is a valid HIWAGA checkout, using the
   agreed structural sentinels rather than a clone path or a Git remote.
2. Resolve a caller-supplied path strictly inside that root, rejecting
   traversal, external absolute paths, and symlink escape.

This module deliberately provides no general file reading. It is the internal
safety primitive that keeps later tools contained.
"""

from __future__ import annotations

from pathlib import Path

from hiwaga_mcp.errors import ReasonCode, TargetOutsideRepositoryError
from hiwaga_mcp.models.common import ErrorDetail
from hiwaga_mcp.models.project import (
    RepositoryIdentityReport,
    RepositoryIdentityStatus,
    SentinelCheck,
    SentinelKind,
)

# Structural authority for a HIWAGA checkout. Order is significant only for
# stable, readable reporting.
REQUIRED_SENTINELS: tuple[tuple[str, SentinelKind], ...] = (
    (".git", SentinelKind.DIRECTORY),
    ("game/project.godot", SentinelKind.FILE),
    ("docs/CANON.md", SentinelKind.FILE),
    ("docs/progress/HIWAGA_PROGRESS.md", SentinelKind.FILE),
    ("art-source/ASSET_AUTHORITY.json", SentinelKind.FILE),
)


def _sentinel_present(root: Path, relative: str, kind: SentinelKind) -> bool:
    target = root / relative
    if kind is SentinelKind.DIRECTORY:
        return target.is_dir()
    return target.is_file()


def validate_repository_identity(repo_root: Path) -> RepositoryIdentityReport:
    """Report whether `repo_root` is a valid HIWAGA checkout.

    Returns a verdict rather than raising, so diagnostics can describe an
    invalid checkout instead of failing opaquely. The report always carries
    `HIWAGA_REPOSITORY_IDENTITY_INVALID` in `error` when the status is INVALID.
    """
    root = repo_root.expanduser().resolve()
    exists = root.exists()
    is_directory = root.is_dir()

    if not is_directory:
        problem = "does_not_exist" if not exists else "not_a_directory"
        message = (
            f"Configured HIWAGA root does not exist: {root}"
            if not exists
            else f"Configured HIWAGA root is not a directory: {root}"
        )
        # Sentinels cannot be meaningfully inspected under a non-directory.
        sentinels = [
            SentinelCheck(path=relative, kind=kind, present=False) for relative, kind in REQUIRED_SENTINELS
        ]
        return RepositoryIdentityReport(
            status=RepositoryIdentityStatus.INVALID,
            repo_root=str(root),
            exists=exists,
            is_directory=is_directory,
            sentinels=sentinels,
            missing_sentinels=[relative for relative, _ in REQUIRED_SENTINELS],
            error=ErrorDetail(
                code=ReasonCode.REPOSITORY_IDENTITY_INVALID,
                message=message,
                details={"repo_root": str(root), "problem": problem},
            ),
        )

    sentinels = [
        SentinelCheck(path=relative, kind=kind, present=_sentinel_present(root, relative, kind))
        for relative, kind in REQUIRED_SENTINELS
    ]
    missing = [check.path for check in sentinels if not check.present]

    if missing:
        return RepositoryIdentityReport(
            status=RepositoryIdentityStatus.INVALID,
            repo_root=str(root),
            exists=exists,
            is_directory=is_directory,
            sentinels=sentinels,
            missing_sentinels=missing,
            error=ErrorDetail(
                code=ReasonCode.REPOSITORY_IDENTITY_INVALID,
                message=(
                    f"Configured root {root} is missing required HIWAGA authority "
                    f"sentinels: {', '.join(missing)}"
                ),
                details={
                    "repo_root": str(root),
                    "problem": "missing_sentinels",
                    "missing_sentinels": missing,
                },
            ),
        )

    return RepositoryIdentityReport(
        status=RepositoryIdentityStatus.VALID,
        repo_root=str(root),
        exists=exists,
        is_directory=is_directory,
        sentinels=sentinels,
        missing_sentinels=[],
        error=None,
    )


def resolve_within_repository(repo_root: Path, target: str | Path) -> Path:
    """Resolve `target` to an absolute path proven to sit inside `repo_root`.

    A relative target is interpreted against the root. An absolute target is
    accepted only if it resolves inside the root. Symlinks are followed before
    the containment check, so a link pointing outside the repository is
    rejected rather than followed.

    Returns:
        The canonical absolute path. The path is not required to exist.

    Raises:
        TargetOutsideRepositoryError: the target escapes the root, or is
            otherwise unusable as a repository-contained path. Carries
            `HIWAGA_TARGET_OUTSIDE_REPOSITORY`.
    """
    root = repo_root.expanduser().resolve()
    raw = str(target)

    if "\x00" in raw:
        raise TargetOutsideRepositoryError(
            "Target path contains a null byte and cannot be contained.",
            details={"repo_root": str(root), "target": raw, "problem": "null_byte"},
        )

    if not raw.strip():
        raise TargetOutsideRepositoryError(
            "Target path is empty.",
            details={"repo_root": str(root), "target": raw, "problem": "empty"},
        )

    candidate = Path(raw)
    if candidate.is_absolute():
        combined = candidate
    else:
        # `expanduser` is deliberately NOT applied to a relative target: a
        # leading `~` must stay a literal repository-relative name.
        combined = root / candidate

    try:
        resolved = combined.resolve()
    except OSError as exc:  # pragma: no cover - platform dependent
        raise TargetOutsideRepositoryError(
            f"Target path could not be resolved: {exc}",
            details={"repo_root": str(root), "target": raw, "problem": "unresolvable"},
        ) from exc

    if resolved != root and root not in resolved.parents:
        raise TargetOutsideRepositoryError(
            f"Target path resolves outside the HIWAGA repository: {resolved}",
            details={
                "repo_root": str(root),
                "target": raw,
                "resolved_path": str(resolved),
                "problem": "outside_repository",
            },
        )

    return resolved


__all__ = [
    "REQUIRED_SENTINELS",
    "resolve_within_repository",
    "validate_repository_identity",
]
