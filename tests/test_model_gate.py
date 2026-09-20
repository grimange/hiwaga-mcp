"""`hiwaga_model_gate` decision logic: trusted identity, exact matching, and the four outcomes."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import hiwaga_mcp
from hiwaga_mcp.config import MODEL_ENV_VAR, WORKER_ENV_VAR, WorkerIdentity, load_worker_identity
from hiwaga_mcp.errors import ReasonCode, WorkerPolicyError
from hiwaga_mcp.models.gates import GateDecision
from hiwaga_mcp.models.model_gate import ModelGateReasonCode, ModelGateResult, TaskClass
from hiwaga_mcp.services.model_gate import (
    evaluate_model_gate,
    normalize_identity,
    parse_worker_policy,
    run_model_gate,
)

from .conftest import fixture_worker_policy, worker_policy_text

D = GateDecision
C = ModelGateReasonCode
T = TaskClass

POLICY = parse_worker_policy(worker_policy_text())


def gate(task_class: T, worker: str | None, model: str | None) -> ModelGateResult:
    return evaluate_model_gate(task_class, POLICY, WorkerIdentity(worker=worker, model=model))


def outcome(result: ModelGateResult) -> tuple[D, C]:
    return result.decision, result.reason_code


# --- ALLOW / DENY ------------------------------------------------------------


def test_an_authorized_worker_and_model_is_allowed() -> None:
    result = gate(T.BOUNDED_IMPLEMENTATION, "codex", "model-A")
    assert outcome(result) == (D.ALLOW, C.ALLOWED)
    assert (result.worker, result.model) == ("codex", "model-A")
    assert result.matched_rule is not None
    assert (result.matched_rule.worker, result.matched_rule.models) == ("codex", ["model-A"])
    assert result.matched_rule.human_required is False
    assert result.policy_schema_version == 1


def test_a_known_wrong_worker_is_denied_not_ambiguous() -> None:
    result = gate(T.BOUNDED_IMPLEMENTATION, "claude-code", "model-A")
    assert outcome(result) == (D.DENY, C.WORKER_DENIED)
    assert result.allowed_workers == ["codex"]
    assert result.matched_rule is not None and result.matched_rule.worker is None


def test_a_known_wrong_model_is_denied() -> None:
    result = gate(T.BOUNDED_IMPLEMENTATION, "codex", "model-B")
    assert outcome(result) == (D.DENY, C.MODEL_DENIED)
    assert result.matched_rule is not None
    assert (result.matched_rule.worker, result.matched_rule.models) == ("codex", ["model-A"])
    assert "model-A" in result.reason


@pytest.mark.parametrize(
    ("worker", "model", "expected"),
    [
        ("codex", "model-A", (D.ALLOW, C.ALLOWED)),
        ("codex", "model-B", (D.ALLOW, C.ALLOWED)),
        ("claude-code", "model-C", (D.ALLOW, C.ALLOWED)),
        ("claude-code", "model-A", (D.DENY, C.MODEL_DENIED)),  # model-A belongs to codex, not claude-code
        ("codex", "model-C", (D.DENY, C.MODEL_DENIED)),
        ("other", "model-A", (D.DENY, C.WORKER_DENIED)),
    ],
)
def test_worker_and_model_are_matched_as_a_pair(worker: str, model: str, expected: tuple[D, C]) -> None:
    assert outcome(gate(T.EVIDENCE_AUDIT, worker, model)) == expected


def test_allowed_workers_and_models_describe_the_class_without_ranking() -> None:
    result = gate(T.EVIDENCE_AUDIT, "codex", "model-A")
    assert result.allowed_workers == ["codex", "claude-code"]
    assert result.allowed_models == ["model-A", "model-B", "model-C"]


def test_the_result_carries_no_ranking_recommendation_effort_or_cost_fields() -> None:
    assert set(ModelGateResult.model_fields) == {
        "task_class",
        "decision",
        "worker",
        "model",
        "policy_schema_version",
        "matched_rule",
        "allowed_workers",
        "allowed_models",
        "reason_code",
        "reason",
        "limitations",
    }


# --- trusted identity --------------------------------------------------------


@pytest.mark.parametrize(
    ("worker", "model", "missing"),
    [
        (None, None, "HIWAGA_AI_WORKER and HIWAGA_AI_MODEL"),
        (None, "model-A", "HIWAGA_AI_WORKER"),
        ("codex", None, "HIWAGA_AI_MODEL"),
        ("   ", "model-A", "HIWAGA_AI_WORKER"),
        ("codex", "   ", "HIWAGA_AI_MODEL"),
        ("", "model-A", "HIWAGA_AI_WORKER"),
        ("codex", "\t\n", "HIWAGA_AI_MODEL"),
    ],
)
def test_missing_or_blank_identity_is_ambiguity_not_denial(
    worker: str | None, model: str | None, missing: str
) -> None:
    result = gate(T.BOUNDED_IMPLEMENTATION, worker, model)
    assert outcome(result) == (D.AMBIGUITY, C.IDENTITY_UNAVAILABLE)
    assert missing in result.reason


def test_a_partly_configured_wrong_worker_is_still_ambiguity_because_identity_is_incomplete() -> None:
    assert gate(T.BOUNDED_IMPLEMENTATION, "claude-code", None).decision is D.AMBIGUITY


def test_the_result_reports_the_identity_it_matched_or_null() -> None:
    absent = gate(T.BOUNDED_IMPLEMENTATION, None, None)
    assert (absent.worker, absent.model) == (None, None)
    partial = gate(T.BOUNDED_IMPLEMENTATION, "  Codex ", None)
    assert (partial.worker, partial.model) == ("codex", None)


def test_identity_normalization_trims_both_and_lowercases_only_the_worker() -> None:
    assert normalize_identity(WorkerIdentity(worker="  Codex\n", model="  Model-A ")) == ("codex", "Model-A")
    assert normalize_identity(WorkerIdentity()) == (None, None)
    assert normalize_identity(WorkerIdentity(worker="", model=" ")) == (None, None)


def test_identity_is_read_only_from_the_two_canonical_variables() -> None:
    env = {
        WORKER_ENV_VAR: " Codex ",
        MODEL_ENV_VAR: "model-A",
        "HIWAGA_MODEL": "x",
        "CLAUDE_MODEL": "y",
        "MODEL": "z",
        "HIWAGA_AI_EFFORT": "high",
        "CODEX_MODEL": "w",
    }
    assert load_worker_identity(env) == WorkerIdentity(worker=" Codex ", model="model-A")
    assert load_worker_identity({"HIWAGA_MODEL": "x", "CLAUDE_MODEL": "y"}) == WorkerIdentity()


def test_the_process_environment_is_read_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(WORKER_ENV_VAR, "codex")
    monkeypatch.setenv(MODEL_ENV_VAR, "model-A")
    assert load_worker_identity() == WorkerIdentity(worker="codex", model="model-A")
    monkeypatch.delenv(WORKER_ENV_VAR)
    monkeypatch.delenv(MODEL_ENV_VAR)
    assert load_worker_identity() == WorkerIdentity()


# --- exact matching ----------------------------------------------------------


@pytest.mark.parametrize(
    "model",
    ["model-A-plus", "x-model-A", "MODEL-A", "model-a", "model-", "model", "model-A2", "model_A", "Model-A"],
)
def test_models_match_exactly_and_case_sensitively(model: str) -> None:
    assert outcome(gate(T.BOUNDED_IMPLEMENTATION, "codex", model)) == (D.DENY, C.MODEL_DENIED)


@pytest.mark.parametrize(
    "worker",
    ["claude", "anthropic", "cc", "claude_code", "codex-cli", "xcodex", "codex2", "openai", "co", "code"],
)
def test_workers_match_exactly_and_aliases_are_not_guessed(worker: str) -> None:
    assert outcome(gate(T.BOUNDED_IMPLEMENTATION, worker, "model-A")) == (D.DENY, C.WORKER_DENIED)


@pytest.mark.parametrize("worker", ["codex", "CODEX", "Codex", "  codex  ", "\tcodex\n"])
def test_the_worker_is_trimmed_and_lowercased_before_matching(worker: str) -> None:
    assert outcome(gate(T.BOUNDED_IMPLEMENTATION, worker, "model-A")) == (D.ALLOW, C.ALLOWED)


def test_the_model_is_trimmed_but_never_case_folded() -> None:
    assert gate(T.BOUNDED_IMPLEMENTATION, "codex", "  model-A\n").decision is D.ALLOW
    assert gate(T.BOUNDED_IMPLEMENTATION, "codex", "MODEL-A").decision is D.DENY


def test_a_newer_model_is_not_inherited_from_an_older_one() -> None:
    policy = parse_worker_policy(
        '{"schema_version": 1, "task_classes": {"BOUNDED_IMPLEMENTATION":'
        ' {"allowed": [{"worker": "codex", "models": ["gpt-5.6-luna"]}]}}}'
    )
    for newer in ("gpt-5.7-luna", "gpt-6-luna", "gpt-5.6-luna-2", "gpt-5.6-sol"):
        result = evaluate_model_gate(T.BOUNDED_IMPLEMENTATION, policy, WorkerIdentity("codex", newer))
        assert outcome(result) == (D.DENY, C.MODEL_DENIED), newer


# --- undefined policy --------------------------------------------------------


@pytest.mark.parametrize("task_class", [T.BUG_DIAGNOSIS, T.HIGH_COMPLEXITY_CONVERGENCE, T.RELEASE_REVIEW])
def test_a_class_with_no_rule_is_ambiguity_policy_undefined(task_class: T) -> None:
    result = gate(task_class, "codex", "model-A")
    assert outcome(result) == (D.AMBIGUITY, C.POLICY_UNDEFINED)
    assert result.matched_rule is None
    assert result.allowed_workers == [] and result.allowed_models == []


def test_undefined_policy_is_reported_even_when_identity_is_missing() -> None:
    assert outcome(gate(T.BUG_DIAGNOSIS, None, None)) == (D.AMBIGUITY, C.POLICY_UNDEFINED)


def test_there_is_no_fallback_between_task_classes() -> None:
    # BOUNDED_IMPLEMENTATION authorizes codex/model-A; that grants nothing to an undefined class.
    assert gate(T.BOUNDED_IMPLEMENTATION, "codex", "model-A").decision is D.ALLOW
    assert gate(T.HIGH_COMPLEXITY_CONVERGENCE, "codex", "model-A").decision is D.AMBIGUITY


def test_an_empty_but_valid_policy_makes_every_class_undefined_not_invalid() -> None:
    policy = parse_worker_policy('{"schema_version": 1, "task_classes": {}}')
    for task_class in T:
        result = evaluate_model_gate(task_class, policy, WorkerIdentity("codex", "model-A"))
        assert outcome(result) == (D.AMBIGUITY, C.POLICY_UNDEFINED)


# --- human-only --------------------------------------------------------------


@pytest.mark.parametrize(
    ("worker", "model"),
    [
        ("codex", "model-A"),  # an identity that is authorized elsewhere
        ("claude-code", "model-C"),
        ("nobody", "nothing"),  # an unauthorized identity
        (None, None),  # no identity at all
        ("codex", None),
    ],
)
def test_a_human_only_class_is_human_required_whatever_the_identity(
    worker: str | None, model: str | None
) -> None:
    result = gate(T.OPERATOR_REVIEW, worker, model)
    assert outcome(result) == (D.HUMAN_REQUIRED, C.HUMAN_REQUIRED)
    assert result.matched_rule is not None and result.matched_rule.human_required is True
    assert result.allowed_workers == [] and result.allowed_models == []


def test_a_human_only_result_still_reports_the_configured_identity_or_null() -> None:
    assert (
        gate(T.OPERATOR_REVIEW, "codex", "model-A").worker,
        gate(T.OPERATOR_REVIEW, "codex", "model-A").model,
    ) == (
        "codex",
        "model-A",
    )
    absent = gate(T.OPERATOR_REVIEW, None, None)
    assert (absent.worker, absent.model) == (None, None)


# --- invalid policy is an error, never an outcome ---------------------------


def test_an_invalid_policy_raises_instead_of_producing_a_decision() -> None:
    with pytest.raises(WorkerPolicyError) as info:
        run_model_gate(T.BOUNDED_IMPLEMENTATION, WorkerIdentity("codex", "model-A"), policy_text="{ nope")
    assert info.value.code is ReasonCode.WORKER_POLICY_INVALID


def test_invalid_and_undefined_are_distinct() -> None:
    identity = WorkerIdentity("codex", "model-A")
    undefined = run_model_gate(T.BUG_DIAGNOSIS, identity, policy_text=worker_policy_text())
    assert undefined.reason_code is C.POLICY_UNDEFINED
    contradictory = fixture_worker_policy()
    contradictory["task_classes"]["OPERATOR_REVIEW"]["allowed"] = [{"worker": "codex", "models": ["m"]}]
    with pytest.raises(WorkerPolicyError):
        run_model_gate(T.BUG_DIAGNOSIS, identity, policy_text=worker_policy_text(contradictory))


def test_run_model_gate_uses_the_packaged_policy_by_default() -> None:
    allowed = run_model_gate(T.BOUNDED_IMPLEMENTATION, WorkerIdentity("codex", "gpt-5.6-luna"))
    assert outcome(allowed) == (D.ALLOW, C.ALLOWED)
    assert outcome(run_model_gate(T.OPERATOR_REVIEW, WorkerIdentity())) == (
        D.HUMAN_REQUIRED,
        C.HUMAN_REQUIRED,
    )


# --- independence ------------------------------------------------------------

FORBIDDEN_DEPENDENCIES = {
    "hiwaga_mcp.services.preflight",
    "hiwaga_mcp.services.project_state",
    "hiwaga_mcp.services.authority",
    "hiwaga_mcp.services.progress",
    "hiwaga_mcp.services.git_state",
    "hiwaga_mcp.services.repository",
    "hiwaga_mcp.models.preflight",
    "hiwaga_mcp.models.state",
    "hiwaga_mcp.models.authority",
}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


@pytest.mark.parametrize("relative", ["services/model_gate.py", "models/model_gate.py"])
def test_model_gate_does_not_depend_on_preflight_project_state_authority_or_the_repository(
    relative: str,
) -> None:
    imports = _imports(Path(hiwaga_mcp.__file__).parent / relative)
    assert not imports & FORBIDDEN_DEPENDENCIES, imports & FORBIDDEN_DEPENDENCIES


def test_the_gate_needs_no_repository_and_reads_no_client_hook_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)  # an empty directory: no .codex/, no .claude/, no HIWAGA checkout
    assert not (tmp_path / ".codex").exists() and not (tmp_path / ".claude").exists()
    result = run_model_gate(T.BOUNDED_IMPLEMENTATION, WorkerIdentity("codex", "gpt-5.6-sol"))
    assert result.decision is D.ALLOW


def test_the_gate_source_names_no_client_hook_policy_file() -> None:
    text = (Path(hiwaga_mcp.__file__).parent / "services/model_gate.py").read_text(encoding="utf-8")
    assert ".codex" not in text and ".claude" not in text and "model-policy" not in text
