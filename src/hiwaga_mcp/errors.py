"""Stable reason codes and the exception types that carry them.

Every deterministic failure in this package carries a stable machine-readable
reason code. Reason codes are an interface: consumers branch on them, so they
are defined here and nowhere else.

This module deliberately imports nothing from `hiwaga_mcp.models` so that the
model layer can depend on these codes without a cycle. The structured rendering
of an error lives in `hiwaga_mcp.models.common.ErrorDetail`.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ReasonCode(str, Enum):
    """Stable, machine-consumable failure identifiers.

    Only codes this corridor actually raises are defined. Later corridors add
    their own codes alongside the behaviour that emits them.
    """

    CONFIGURATION_INVALID = "HIWAGA_CONFIGURATION_INVALID"
    REPOSITORY_IDENTITY_INVALID = "HIWAGA_REPOSITORY_IDENTITY_INVALID"
    TARGET_OUTSIDE_REPOSITORY = "HIWAGA_TARGET_OUTSIDE_REPOSITORY"
    PROGRESS_DOCUMENT_INVALID = "HIWAGA_PROGRESS_DOCUMENT_INVALID"
    PROJECT_STATE_UNAVAILABLE = "HIWAGA_PROJECT_STATE_UNAVAILABLE"
    ASSET_AUTHORITY_INVALID = "HIWAGA_ASSET_AUTHORITY_INVALID"
    WORKER_POLICY_INVALID = "HIWAGA_WORKER_POLICY_INVALID"


class HiwagaError(Exception):
    """Base class for deterministic HIWAGA control-plane failures.

    Carries a stable reason code alongside a human-readable explanation, plus
    optional structured detail. Subclasses bind the code.
    """

    code: ReasonCode

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})


class ConfigurationError(HiwagaError):
    """`HIWAGA_REPO_ROOT` is absent, unusable, or does not name a directory."""

    code = ReasonCode.CONFIGURATION_INVALID


class RepositoryIdentityError(HiwagaError):
    """The configured root is not a valid HIWAGA checkout."""

    code = ReasonCode.REPOSITORY_IDENTITY_INVALID


class TargetOutsideRepositoryError(HiwagaError):
    """A supplied path resolves outside the verified repository root."""

    code = ReasonCode.TARGET_OUTSIDE_REPOSITORY


class ProgressDocumentError(HiwagaError):
    """The progress ledger is missing, unreadable, empty, or has no current block."""

    code = ReasonCode.PROGRESS_DOCUMENT_INVALID


class ProjectStateUnavailableError(HiwagaError):
    """Repository state could not be established well enough to report it."""

    code = ReasonCode.PROJECT_STATE_UNAVAILABLE


class AssetAuthorityError(HiwagaError):
    """The asset-authority manifest is missing, malformed, or cannot be trusted."""

    code = ReasonCode.ASSET_AUTHORITY_INVALID


class WorkerPolicyError(HiwagaError):
    """The canonical worker policy is missing, malformed, or internally inconsistent."""

    code = ReasonCode.WORKER_POLICY_INVALID


__all__ = [
    "AssetAuthorityError",
    "ConfigurationError",
    "HiwagaError",
    "ProgressDocumentError",
    "ProjectStateUnavailableError",
    "ReasonCode",
    "RepositoryIdentityError",
    "TargetOutsideRepositoryError",
    "WorkerPolicyError",
]
