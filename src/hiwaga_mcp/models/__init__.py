"""Typed domain models and bounded vocabularies for hiwaga-mcp."""

from __future__ import annotations

from hiwaga_mcp.models.authority import AuthorityResolution, AuthorityResult, AuthorityUse
from hiwaga_mcp.models.common import ErrorDetail
from hiwaga_mcp.models.diagnostics import ConfigurationStatus, ServerInfoResult
from hiwaga_mcp.models.gates import GateDecision
from hiwaga_mcp.models.model_gate import (
    MatchedRule,
    ModelGateReasonCode,
    ModelGateResult,
    TaskClass,
)
from hiwaga_mcp.models.preflight import (
    PreflightOperation,
    PreflightReasonCode,
    PreflightRequest,
    PreflightResult,
    ProjectStateSummary,
    TargetPreflightResult,
)
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
    "MatchedRule",
    "ModelGateReasonCode",
    "ModelGateResult",
    "PreflightOperation",
    "PreflightReasonCode",
    "PreflightRequest",
    "PreflightResult",
    "ProjectStateResult",
    "ProjectStateSummary",
    "ProofClass",
    "RepositoryIdentityReport",
    "RepositoryIdentityStatus",
    "SentinelCheck",
    "SentinelKind",
    "ServerInfoResult",
    "TargetPreflightResult",
    "TaskClass",
    "VerificationStatus",
]
