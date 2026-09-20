"""Asset-authority models for `hiwaga_authority`.

Two layers: the typed view of `art-source/ASSET_AUTHORITY.json` (validated on
load), and the flat result a caller receives. Manifest vocabularies such as
`status` are kept as the strings the manifest declares; only values this
control plane derives itself (resolution, permitted/forbidden uses) are enums.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class AuthorityResolution(str, Enum):
    """How a target relates to the asset registry.

    `UNRESOLVED` and `CONFLICT` are normal domain results, not failures.
    """

    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"
    CONFLICT = "CONFLICT"


class AuthorityUse(str, Enum):
    """Uses this control plane derives from explicit manifest fields.

    The mapping lives in `hiwaga_mcp.services.authority` and is deliberately
    small: only constraints HIWAGA's asset-authority contract states outright.
    """

    HISTORICAL_REFERENCE = "HISTORICAL_REFERENCE"
    TECHNICAL_REFERENCE = "TECHNICAL_REFERENCE"
    AUTHORING_DERIVATION = "AUTHORING_DERIVATION"
    DUPLICATE_SUPERSEDED_SOURCE = "DUPLICATE_SUPERSEDED_SOURCE"
    LINK_SUPERSEDED_SOURCE = "LINK_SUPERSEDED_SOURCE"
    RESHAPE_SUPERSEDED_SOURCE = "RESHAPE_SUPERSEDED_SOURCE"
    REUSE_SUPERSEDED_TOPOLOGY = "REUSE_SUPERSEDED_TOPOLOGY"


class AssetAuthorityEntry(BaseModel):
    """One asset in the manifest: only the fields authority decisions use.

    Values are validated strictly (`"true"` is not a boolean). Fields the
    manifest carries beyond these are ignored, not preserved.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    status: StrictStr | None = None
    visual_authority: StrictBool | None = None
    runtime_active: StrictBool | None = None
    runtime_required_temporarily: StrictBool | None = None
    authoring_reuse: StrictStr | None = None
    creation_mode: StrictStr | None = None
    replacement: StrictStr | None = None

    # Repository-relative paths.
    source_path: StrictStr | None = None
    runtime_path: StrictStr | None = None
    motion_proof_path: StrictStr | None = None

    # Paths relative to `source_path`.
    static_form_source: StrictStr | None = None
    rig_proof_source: StrictStr | None = None
    motion_source: StrictStr | None = None
    representative_pose_reference_source: StrictStr | None = None


class AssetAuthorityManifest(BaseModel):
    """`art-source/ASSET_AUTHORITY.json`, keyed by machine asset identity."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    schema_version: StrictInt
    assets: dict[StrictStr, AssetAuthorityEntry]


class AuthorityResult(BaseModel):
    """Asset authority that applies to one repository target."""

    model_config = ConfigDict(frozen=True)

    repository: str = Field(description="Repository identity label; present only after identity validation.")
    repository_root: str = Field(description="Canonicalized root of the configured checkout.")
    target: str = Field(description="The target exactly as supplied.")
    resolved_target: str = Field(
        description="Canonical repository-relative POSIX path of the target ('.' for the root itself)."
    )

    resolution: AuthorityResolution = Field(description="RESOLVED, UNRESOLVED, or CONFLICT.")
    asset_id: str | None = Field(description="Manifest key of the owning asset; null unless RESOLVED.")
    matched_asset_ids: list[str] = Field(
        description="Every asset that owns the target, sorted; more than one means CONFLICT."
    )

    status: str | None = Field(description="Manifest `status`, verbatim, if declared.")
    visual_authority: bool | None = Field(description="Manifest `visual_authority`, if declared.")
    runtime_active: bool | None = Field(description="Manifest `runtime_active`, if declared.")
    runtime_required_temporarily: bool | None = Field(
        description="Manifest `runtime_required_temporarily`, if declared."
    )
    creation_mode: str | None = Field(description="Manifest `creation_mode`, verbatim, if declared.")
    authoring_reuse: str | None = Field(description="Manifest `authoring_reuse`, verbatim, if declared.")

    source_path: str | None = Field(description="Manifest `source_path`, verbatim, if declared.")
    runtime_path: str | None = Field(description="Manifest `runtime_path`, verbatim, if declared.")

    allowed_uses: list[AuthorityUse] = Field(
        description="Uses derived from explicit manifest fields; empty when none are established."
    )
    forbidden_uses: list[AuthorityUse] = Field(
        description="Uses derived from explicit manifest fields; empty when none are established."
    )

    replacement: str | None = Field(description="Manifest `replacement`, verbatim, if declared.")

    limitations: list[str] = Field(description="Deterministic notes on what this result does not establish.")


__all__ = [
    "AssetAuthorityEntry",
    "AssetAuthorityManifest",
    "AuthorityResolution",
    "AuthorityResult",
    "AuthorityUse",
]
