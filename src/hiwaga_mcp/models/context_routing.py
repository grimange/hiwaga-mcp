"""The packaged domain → CANON-label routing mapping schema.

The only fact about context routing that `docs/CANON.md` cannot supply on its
own is *which* CANON bullet labels answer which `ContextDomain`. This module is
the strict schema for that one small, packaged mapping. It deliberately holds
nothing else: no paths, no titles, no status classifications, no notes — CANON
remains the sole authority for all of that.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from hiwaga_mcp.models.context import ContextDomain


class LabelRef(BaseModel):
    """One mapped CANON bullet label.

    `section` is an optional, explicitly authored annotation for the rare case
    where routing authority names an internal document section for this source
    (for example the Vertical Slice acceptance gate). It is never derived by
    parsing a bullet's prose at runtime.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: StrictStr
    section: StrictStr | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_a_bare_label_string(cls, value: object) -> object:
        return {"label": value} if isinstance(value, str) else value

    @field_validator("label")
    @classmethod
    def _label_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be empty")
        return value

    @field_validator("section")
    @classmethod
    def _section_is_not_blank_when_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("section must not be empty when present")
        return value


class DomainRouting(BaseModel):
    """The CANON labels that answer one `ContextDomain`, grouped by the CANON section they must come from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical: list[LabelRef] = Field(
        default_factory=list, description="Labels expected in CANON's `## Canonical sources`."
    )
    supporting: list[LabelRef] = Field(
        default_factory=list, description="Labels expected in CANON's `## Supporting references`."
    )
    historical: list[LabelRef] = Field(
        default_factory=list, description="Labels expected in CANON's Exploratory Prototype A section."
    )

    @model_validator(mode="after")
    def _no_label_repeated_within_the_domain(self) -> DomainRouting:
        seen: set[str] = set()
        for ref in (*self.canonical, *self.supporting, *self.historical):
            if ref.label in seen:
                raise ValueError(f"label {ref.label!r} is mapped more than once for this domain")
            seen.add(ref.label)
        return self


class ContextRoutingMapping(BaseModel):
    """`context_routing.json`: for every context domain, the CANON labels that answer it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: StrictInt
    domains: dict[ContextDomain, DomainRouting]

    @model_validator(mode="after")
    def _every_domain_is_present(self) -> ContextRoutingMapping:
        missing = sorted(domain.value for domain in ContextDomain if domain not in self.domains)
        if missing:
            raise ValueError(f"missing a routing entry for domain(s): {', '.join(missing)}")
        return self


__all__ = ["ContextRoutingMapping", "DomainRouting", "LabelRef"]
