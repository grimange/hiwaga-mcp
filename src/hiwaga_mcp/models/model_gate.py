"""Worker/model gate models for `hiwaga_model_gate`.

Two layers: the typed canonical worker policy (validated on load, unknown keys
refused because an ignored key could silently change who is authorized) and the
flat result a caller receives.

Matching is exact membership. Nothing here ranks models, infers families, or
recommends one.
"""

from __future__ import annotations

from enum import Enum

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from hiwaga_mcp.models.gates import GateDecision


class TaskClass(str, Enum):
    """The closed set of task classes the gate routes.

    The caller supplies exactly one; it is never inferred from text. There is
    deliberately no catch-all class.
    """

    EVIDENCE_AUDIT = "EVIDENCE_AUDIT"
    BUG_DIAGNOSIS = "BUG_DIAGNOSIS"
    BOUNDED_IMPLEMENTATION = "BOUNDED_IMPLEMENTATION"
    EXECUTION_BOUNDARY_CHANGE = "EXECUTION_BOUNDARY_CHANGE"
    RELEASE_REVIEW = "RELEASE_REVIEW"
    HIGH_COMPLEXITY_CONVERGENCE = "HIGH_COMPLEXITY_CONVERGENCE"
    OPERATOR_REVIEW = "OPERATOR_REVIEW"


class ModelGateReasonCode(str, Enum):
    """Stable reason codes for model-gate decisions.

    Ordinary domain outcomes, not tool errors, and separate from the failure
    codes in `hiwaga_mcp.errors.ReasonCode`.
    """

    ALLOWED = "HIWAGA_MODEL_GATE_ALLOWED"
    WORKER_DENIED = "HIWAGA_MODEL_GATE_WORKER_DENIED"
    MODEL_DENIED = "HIWAGA_MODEL_GATE_MODEL_DENIED"
    IDENTITY_UNAVAILABLE = "HIWAGA_MODEL_GATE_IDENTITY_UNAVAILABLE"
    POLICY_UNDEFINED = "HIWAGA_MODEL_GATE_POLICY_UNDEFINED"
    HUMAN_REQUIRED = "HIWAGA_MODEL_GATE_HUMAN_REQUIRED"


def _canonical_string(value: str, what: str) -> str:
    if not value.strip():
        raise ValueError(f"{what} must not be empty")
    if value != value.strip():
        raise ValueError(f"{what} must not have surrounding whitespace: {value!r}")
    return value


class AllowedWorker(BaseModel):
    """One worker and the exact model ids it may use for a task class."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    worker: StrictStr
    models: list[StrictStr]

    @field_validator("worker")
    @classmethod
    def _worker_is_canonical(cls, value: str) -> str:
        _canonical_string(value, "worker")
        if value != value.lower():
            raise ValueError(f"worker ids are lowercase; got {value!r}")
        return value

    @field_validator("models")
    @classmethod
    def _models_are_canonical_and_unique(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("models must list at least one model id")
        for model in value:
            _canonical_string(model, "model")
        if len(set(value)) != len(value):
            raise ValueError("models must not repeat a model id")
        return value


class TaskClassRule(BaseModel):
    """What a task class requires: a human, or one of the listed workers/models."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    human_required: StrictBool = False
    allowed: list[AllowedWorker] = Field(default_factory=list)

    @model_validator(mode="after")
    def _establishes_exactly_one_requirement(self) -> TaskClassRule:
        if self.human_required and self.allowed:
            raise ValueError("a human_required rule must not also list allowed workers")
        if not self.human_required and not self.allowed:
            raise ValueError(
                "a rule must set human_required=true or list allowed workers; omit the class instead"
            )
        workers = [entry.worker for entry in self.allowed]
        if len(set(workers)) != len(workers):
            raise ValueError("allowed lists the same worker more than once")
        return self


class WorkerPolicy(BaseModel):
    """`worker_policy.json`: per task class, who may do it. Classes are independent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: StrictInt
    task_classes: dict[TaskClass, TaskClassRule]


class MatchedRule(BaseModel):
    """The compact slice of policy the decision rested on."""

    model_config = ConfigDict(frozen=True)

    task_class: TaskClass = Field(description="The task class whose rule was consulted.")
    human_required: bool = Field(description="True when the rule requires a human.")
    worker: str | None = Field(
        description="The policy entry for the configured worker; null when none applies."
    )
    models: list[str] = Field(description="Exact model ids that entry allows; empty when none applies.")


class ModelGateResult(BaseModel):
    """Whether the configured worker/model may take the requested task class."""

    model_config = ConfigDict(frozen=True)

    task_class: TaskClass = Field(description="The task class that was evaluated.")
    decision: GateDecision = Field(description="ALLOW, DENY, AMBIGUITY, or HUMAN_REQUIRED.")

    worker: str | None = Field(
        description="Configured worker as matched (trimmed, lowercased); null when not configured."
    )
    model: str | None = Field(description="Configured model as matched (trimmed); null when not configured.")

    policy_schema_version: int = Field(description="Schema version of the canonical worker policy used.")

    matched_rule: MatchedRule | None = Field(description="Rule consulted; null when the class has no rule.")
    allowed_workers: list[str] = Field(
        description="Workers the policy allows for this class, in policy order."
    )
    allowed_models: list[str] = Field(
        description="Every model id the policy allows for this class across its workers, in policy order."
    )

    reason_code: ModelGateReasonCode = Field(description="Stable reason for the decision.")
    reason: str = Field(description="Human-readable explanation of the decision.")

    limitations: list[str] = Field(
        description="Deterministic notes on what this decision does not establish."
    )


__all__ = [
    "AllowedWorker",
    "MatchedRule",
    "ModelGateReasonCode",
    "ModelGateResult",
    "TaskClass",
    "TaskClassRule",
    "WorkerPolicy",
]
