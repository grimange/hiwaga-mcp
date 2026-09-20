"""Deterministic worker/model gate.

Is the configured AI worker/model permitted for an explicitly supplied task
class? The answer comes from exactly three things: the trusted process identity
(`HIWAGA_AI_WORKER`, `HIWAGA_AI_MODEL`), the canonical packaged policy, and the
task class. Nothing else is consulted: not project state, preflight, asset
authority, the repository, or any client hook policy.

Outcomes:

* human-only rule                       -> HUMAN_REQUIRED (identity is irrelevant)
* no rule for the class                 -> AMBIGUITY (routing is undefined, not forbidden)
* identity not configured               -> AMBIGUITY
* worker not listed for the class       -> DENY
* worker listed, model not listed       -> DENY
* worker and model listed               -> ALLOW

An untrustworthy policy is not an outcome: it raises `WorkerPolicyError`.
Matching is exact. There is no ranking, family inference, or fallback between
task classes.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic import ValidationError

from hiwaga_mcp.config import MODEL_ENV_VAR, WORKER_ENV_VAR, WorkerIdentity
from hiwaga_mcp.errors import WorkerPolicyError
from hiwaga_mcp.models.gates import GateDecision
from hiwaga_mcp.models.model_gate import (
    MatchedRule,
    ModelGateReasonCode,
    ModelGateResult,
    TaskClass,
    TaskClassRule,
    WorkerPolicy,
)

POLICY_PACKAGE = "hiwaga_mcp"
POLICY_RESOURCE = "policy/worker_policy.json"
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

Decision = GateDecision
Code = ModelGateReasonCode

_STANDING_LIMITATION = (
    "The gate decides worker/model membership for the supplied task class only. Identity is the operator's "
    f"{WORKER_ENV_VAR}/{MODEL_ENV_VAR} configuration and is not verified against the actual client; "
    "reasoning effort, project state, asset authority, and preflight are not consulted."
)


class _DuplicateKeyError(ValueError):
    pass


def _invalid(message: str, problem: str, **details: Any) -> WorkerPolicyError:
    return WorkerPolicyError(message, details={"problem": problem, "path": POLICY_RESOURCE, **details})


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise _DuplicateKeyError(f"duplicate JSON keys: {', '.join(duplicated)}")
    return dict(pairs)


def parse_worker_policy(text: str) -> WorkerPolicy:
    """Parse and validate worker-policy text.

    Raises:
        WorkerPolicyError: not JSON, duplicate keys at any level, not an object, a
            missing or unsupported `schema_version`, an unknown key, or a rule that
            is malformed or self-contradictory.
    """
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError as exc:
        raise _invalid(f"The worker policy is ambiguous: {exc}.", "duplicate_keys") from exc
    except ValueError as exc:
        raise _invalid(f"The worker policy is not valid JSON: {exc}", "malformed_json") from exc

    if not isinstance(raw, dict):
        raise _invalid("The worker policy must be a JSON object.", "not_an_object")

    version = raw.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _invalid(
            "The worker policy `schema_version` is missing or not an integer.", "invalid_structure"
        )
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise _invalid(
            f"The worker policy schema_version {version} is not supported "
            f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}).",
            "unsupported_schema_version",
            schema_version=version,
        )

    try:
        return WorkerPolicy.model_validate(raw)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
        raise _invalid(
            f"The worker policy has an invalid structure: {'; '.join(problems[:5])}",
            "invalid_structure",
            errors=problems[:10],
        ) from exc


def _packaged_policy_text() -> str:
    resource = resources.files(POLICY_PACKAGE).joinpath(POLICY_RESOURCE)
    try:
        return resource.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise _invalid("The packaged worker policy is missing.", "missing") from exc
    except UnicodeDecodeError as exc:
        raise _invalid("The packaged worker policy is not valid UTF-8.", "not_utf8") from exc
    except OSError as exc:
        raise _invalid(f"The packaged worker policy could not be read: {exc}", "unreadable") from exc


def load_worker_policy(text: str | None = None) -> WorkerPolicy:
    """Load the canonical worker policy: `text` if given (a server-construction seam), else the package's."""
    return parse_worker_policy(_packaged_policy_text() if text is None else text)


def _configured(value: str | None) -> str | None:
    """The trimmed value, or None when absent, empty, or whitespace-only."""
    if value is None or not value.strip():
        return None
    return value.strip()


def normalize_identity(identity: WorkerIdentity) -> tuple[str | None, str | None]:
    """`(worker, model)` as matched: worker trimmed and lowercased, model trimmed only (case-sensitive)."""
    worker = _configured(identity.worker)
    return (worker.lower() if worker else None), _configured(identity.model)


def _decide(
    task_class: TaskClass, rule: TaskClassRule | None, worker: str | None, model: str | None
) -> tuple[Decision, Code, str, MatchedRule | None]:
    if rule is None:
        return (
            Decision.AMBIGUITY,
            Code.POLICY_UNDEFINED,
            f"The worker policy defines no rule for {task_class.value}, so routing is undefined.",
            None,
        )

    if rule.human_required:
        return (
            Decision.HUMAN_REQUIRED,
            Code.HUMAN_REQUIRED,
            f"{task_class.value} is a human-only task class; no AI worker/model is authorized for it.",
            MatchedRule(task_class=task_class, human_required=True, worker=None, models=[]),
        )

    unmatched = MatchedRule(task_class=task_class, human_required=False, worker=None, models=[])

    missing = [name for name, value in ((WORKER_ENV_VAR, worker), (MODEL_ENV_VAR, model)) if value is None]
    if missing:
        return (
            Decision.AMBIGUITY,
            Code.IDENTITY_UNAVAILABLE,
            f"Worker/model identity is not configured ({' and '.join(missing)} unset or empty).",
            unmatched,
        )

    entry = next((candidate for candidate in rule.allowed if candidate.worker == worker), None)
    if entry is None:
        allowed = ", ".join(candidate.worker for candidate in rule.allowed)
        return (
            Decision.DENY,
            Code.WORKER_DENIED,
            f"Worker {worker!r} is not authorized for {task_class.value} (authorized: {allowed}).",
            unmatched,
        )

    matched = MatchedRule(
        task_class=task_class, human_required=False, worker=entry.worker, models=entry.models
    )
    if model not in entry.models:
        return (
            Decision.DENY,
            Code.MODEL_DENIED,
            f"Model {model!r} is not authorized for worker {worker!r} on {task_class.value} "
            f"(authorized: {', '.join(entry.models)}).",
            matched,
        )
    return (
        Decision.ALLOW,
        Code.ALLOWED,
        f"Worker {worker!r} with model {model!r} is authorized for {task_class.value}.",
        matched,
    )


def evaluate_model_gate(
    task_class: TaskClass, policy: WorkerPolicy, identity: WorkerIdentity
) -> ModelGateResult:
    """Apply `policy` to `identity` for `task_class`. Pure: no I/O, no other tools."""
    rule = policy.task_classes.get(task_class)
    worker, model = normalize_identity(identity)
    decision, code, reason, matched = _decide(task_class, rule, worker, model)

    allowed_workers: list[str] = []
    allowed_models: list[str] = []
    for entry in rule.allowed if rule else []:
        allowed_workers.append(entry.worker)
        allowed_models.extend(m for m in entry.models if m not in allowed_models)

    return ModelGateResult(
        task_class=task_class,
        decision=decision,
        worker=worker,
        model=model,
        policy_schema_version=policy.schema_version,
        matched_rule=matched,
        allowed_workers=allowed_workers,
        allowed_models=allowed_models,
        reason_code=code,
        reason=reason,
        limitations=[_STANDING_LIMITATION],
    )


def run_model_gate(
    task_class: TaskClass, identity: WorkerIdentity, *, policy_text: str | None = None
) -> ModelGateResult:
    """Load the canonical policy and evaluate `task_class` for the configured `identity`.

    Raises:
        WorkerPolicyError: the policy is missing, malformed, or self-contradictory.
    """
    return evaluate_model_gate(task_class, load_worker_policy(policy_text), identity)


__all__ = [
    "POLICY_RESOURCE",
    "SUPPORTED_SCHEMA_VERSIONS",
    "evaluate_model_gate",
    "load_worker_policy",
    "normalize_identity",
    "parse_worker_policy",
    "run_model_gate",
]
