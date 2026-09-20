"""Repository identity models.

These describe whether a configured root is a valid HIWAGA checkout. They do
not describe project progress or state; that vocabulary lives in
`hiwaga_mcp.models.state`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from hiwaga_mcp.models.common import ErrorDetail


class SentinelKind(str, Enum):
    """What a required authority sentinel must be on disk."""

    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class SentinelCheck(BaseModel):
    """The observed state of one required authority sentinel."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="Repository-relative sentinel path.")
    kind: SentinelKind = Field(description="Required on-disk kind for this sentinel.")
    present: bool = Field(description="True when the sentinel exists with the required kind.")


class RepositoryIdentityStatus(str, Enum):
    """Whether the configured root satisfies HIWAGA structural authority."""

    VALID = "VALID"
    INVALID = "INVALID"


class RepositoryIdentityReport(BaseModel):
    """Deterministic result of validating a configured root.

    Identity is established by the agreed structural sentinels, not by a clone
    path or a Git remote name.
    """

    model_config = ConfigDict(frozen=True)

    status: RepositoryIdentityStatus = Field(description="Overall identity verdict.")
    repo_root: str = Field(description="Canonicalized root that was inspected.")
    exists: bool = Field(description="True when the configured root exists on disk.")
    is_directory: bool = Field(description="True when the configured root is a directory.")
    sentinels: list[SentinelCheck] = Field(description="Per-sentinel observations, in required order.")
    missing_sentinels: list[str] = Field(description="Repository-relative paths of absent sentinels.")
    error: ErrorDetail | None = Field(
        default=None,
        description="Populated when status is INVALID; absent when VALID.",
    )


__all__ = [
    "RepositoryIdentityReport",
    "RepositoryIdentityStatus",
    "SentinelCheck",
    "SentinelKind",
]
