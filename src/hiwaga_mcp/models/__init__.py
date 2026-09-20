"""Typed domain models and bounded vocabularies for hiwaga-mcp."""

from __future__ import annotations

from hiwaga_mcp.models.authority import AuthorityResolution, AuthorityResult, AuthorityUse
from hiwaga_mcp.models.common import ErrorDetail
from hiwaga_mcp.models.diagnostics import ConfigurationStatus, ServerInfoResult
from hiwaga_mcp.models.gates import GateDecision
from hiwaga_mcp.models.project import (
    RepositoryIdentityReport,
    RepositoryIdentityStatus,
    SentinelCheck,
    SentinelKind,
)
from hiwaga_mcp.models.state import AmbiguityGate, GitState, ProjectStateResult
from hiwaga_mcp.models.verification import ProofClass, VerificationStatus

__all__ = [
    "AmbiguityGate",
    "AuthorityResolution",
    "AuthorityResult",
    "AuthorityUse",
    "ConfigurationStatus",
    "ErrorDetail",
    "GateDecision",
    "GitState",
    "ProjectStateResult",
    "ProofClass",
    "RepositoryIdentityReport",
    "RepositoryIdentityStatus",
    "SentinelCheck",
    "SentinelKind",
    "ServerInfoResult",
    "VerificationStatus",
]
