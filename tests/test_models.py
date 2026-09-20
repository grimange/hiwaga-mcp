"""Bounded vocabularies serialize as their stable string values."""

from __future__ import annotations

from hiwaga_mcp.errors import HiwagaError, ReasonCode
from hiwaga_mcp.models.common import ErrorDetail
from hiwaga_mcp.models.gates import GateDecision
from hiwaga_mcp.models.verification import ProofClass, VerificationStatus


def test_gate_decision_vocabulary_is_exact() -> None:
    assert {member.value for member in GateDecision} == {
        "ALLOW",
        "DENY",
        "AMBIGUITY",
        "HUMAN_REQUIRED",
    }


def test_verification_status_vocabulary_is_exact() -> None:
    assert {member.value for member in VerificationStatus} == {
        "PASS",
        "FAIL",
        "TIMEOUT",
        "EXECUTION_ERROR",
    }


def test_proof_class_vocabulary_is_exact() -> None:
    assert {member.value for member in ProofClass} == {
        "STRUCTURAL",
        "HEADLESS",
        "NATIVE_RENDERED",
    }


def test_reason_codes_are_prefixed_and_stable() -> None:
    assert {member.value for member in ReasonCode} == {
        "HIWAGA_CONFIGURATION_INVALID",
        "HIWAGA_REPOSITORY_IDENTITY_INVALID",
        "HIWAGA_TARGET_OUTSIDE_REPOSITORY",
        "HIWAGA_PROGRESS_DOCUMENT_INVALID",
        "HIWAGA_PROJECT_STATE_UNAVAILABLE",
        "HIWAGA_ASSET_AUTHORITY_INVALID",
        "HIWAGA_WORKER_POLICY_INVALID",
    }


def test_error_detail_serializes_the_code_as_its_stable_string() -> None:
    detail = ErrorDetail(
        code=ReasonCode.TARGET_OUTSIDE_REPOSITORY,
        message="escaped",
        details={"problem": "outside_repository"},
    )
    assert detail.model_dump(mode="json") == {
        "code": "HIWAGA_TARGET_OUTSIDE_REPOSITORY",
        "message": "escaped",
        "details": {"problem": "outside_repository"},
    }


def test_error_detail_defaults_details_to_empty() -> None:
    detail = ErrorDetail(code=ReasonCode.CONFIGURATION_INVALID, message="unset")
    assert detail.details == {}


def test_error_detail_round_trips_a_raised_error() -> None:
    class Boom(HiwagaError):
        code = ReasonCode.CONFIGURATION_INVALID

    detail = ErrorDetail.from_error(Boom("bad root", details={"problem": "empty"}))
    assert detail.code is ReasonCode.CONFIGURATION_INVALID
    assert detail.message == "bad root"
    assert detail.details == {"problem": "empty"}


def test_enum_schema_constrains_values() -> None:
    schema = ErrorDetail.model_json_schema()
    code_enum = schema["$defs"]["ReasonCode"]["enum"]
    assert "HIWAGA_REPOSITORY_IDENTITY_INVALID" in code_enum
