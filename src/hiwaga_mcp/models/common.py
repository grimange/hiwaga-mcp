"""Structured error representation shared by every HIWAGA tool output."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hiwaga_mcp.errors import HiwagaError, ReasonCode


class ErrorDetail(BaseModel):
    """A failure expressed as a stable code plus a human explanation.

    Important status is never carried by prose alone: `code` is the field a
    consumer branches on, and `message` exists for the operator reading it.
    """

    model_config = ConfigDict(frozen=True)

    code: ReasonCode = Field(description="Stable machine-consumable reason code.")
    message: str = Field(description="Human-readable explanation of the failure.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured supporting detail for the failure.",
    )

    @classmethod
    def from_error(cls, error: HiwagaError) -> ErrorDetail:
        """Render a raised `HiwagaError` as structured output."""
        return cls(code=error.code, message=error.message, details=error.details)


__all__ = ["ErrorDetail"]
