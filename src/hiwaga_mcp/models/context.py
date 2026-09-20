"""Public routing vocabulary and result models for `hiwaga_context`.

This is a routing interface, not a search or summarization tool: every field
here is either a repository fact (a path, whether it exists, its size) or text
carried verbatim from `docs/CANON.md` (a title, a label, a note). Nothing here
ranks, excerpts, or interprets a source's own status prose.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from hiwaga_mcp.models.state import ProjectStateResult


class ContextDomain(str, Enum):
    """The closed set of context domains `hiwaga_context` routes.

    Established by the accepted routing audit and the CANON structure it
    synchronized against. The caller supplies exactly one; there is no
    catch-all, and none is inferred from free text.
    """

    PROJECT = "PROJECT"
    GAMEPLAY = "GAMEPLAY"
    WORLD_LORE = "WORLD_LORE"
    VISUAL_IDENTITY = "VISUAL_IDENTITY"
    VERTICAL_SLICE = "VERTICAL_SLICE"
    CORE_ARCHITECTURE = "CORE_ARCHITECTURE"
    PROGRESSION = "PROGRESSION"
    REPRESENTATIVE_GAMEPLAY = "REPRESENTATIVE_GAMEPLAY"
    ASSET_AUTHORITY = "ASSET_AUTHORITY"
    VERIFICATION = "VERIFICATION"


class SourceClassification(str, Enum):
    """How a routed source relates to current authority.

    Derived solely from which CANON routing section a source's bullet lives
    in — never from that bullet's own status prose, which is preserved
    verbatim in `ContextSource.note` instead. `CURRENT_STATE` is not derived
    from any CANON section; it marks the one `PROJECT`-domain source that is
    the routing index itself (`docs/CANON.md`), not a document CANON routes.
    """

    CANONICAL = "CANONICAL"
    SUPPORTING = "SUPPORTING"
    PROTOTYPE_A = "PROTOTYPE_A"
    CURRENT_STATE = "CURRENT_STATE"


class ContextSource(BaseModel):
    """One repository source CANON currently routes for a domain."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="Repository-relative path of the source; a file or a directory.")
    title: str = Field(description="CANON's own Markdown link text for this source, verbatim.")
    label: str = Field(description="The CANON bullet label this source was routed from, verbatim.")
    classification: SourceClassification = Field(
        description="Derived from which CANON routing section the bullet lives in."
    )
    section: str | None = Field(
        description=(
            "An internal document section this source names, only where routing authority "
            "explicitly identifies one (e.g. an acceptance-gate section number); null otherwise. "
            "No excerpt of that section is returned."
        )
    )
    note: str = Field(description="The complete CANON routing bullet text this source came from, verbatim.")
    exists: bool = Field(description="True when the path exists on disk, as a file or a directory.")
    size_bytes: int | None = Field(description="File size in bytes; null for a directory or a missing path.")


class ContextResult(BaseModel):
    """Which repository sources currently govern or support one context domain."""

    model_config = ConfigDict(frozen=True)

    repository: str = Field(description="Repository identity label; present only after identity validation.")
    repository_root: str = Field(description="Canonicalized root of the configured checkout.")
    domain: ContextDomain = Field(description="The context domain that was routed.")

    canonical_sources: list[ContextSource] = Field(
        description="Sources from CANON's `## Canonical sources`; empty when the domain has none."
    )
    supporting_sources: list[ContextSource] = Field(
        description="Sources from CANON's `## Supporting references`."
    )
    historical_sources: list[ContextSource] = Field(
        description="Sources from CANON's Exploratory Prototype A section; never canonical or supporting."
    )

    project_state: ProjectStateResult | None = Field(
        description="The full current project state; populated only for the PROJECT domain."
    )

    routing_document: str = Field(
        description="Repository-relative path of the routing authority (docs/CANON.md)."
    )
    limitations: list[str] = Field(description="Deterministic notes on what this routing does not establish.")


__all__ = ["ContextDomain", "ContextResult", "ContextSource", "SourceClassification"]
