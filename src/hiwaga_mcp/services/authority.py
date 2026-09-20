"""Asset authority from `art-source/ASSET_AUTHORITY.json`.

P0 authority is the machine-readable asset registry and nothing else: no prose
documents, READMEs, CANON routing, or progress ledger are consulted. A target is
owned by an asset when its canonical path equals, or sits beneath, one of that
asset's declared paths. Zero owners is `UNRESOLVED`; several is `CONFLICT`; both
are ordinary results. A manifest that cannot be trusted is refused outright,
never partially applied.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hiwaga_mcp.errors import AssetAuthorityError, TargetOutsideRepositoryError
from hiwaga_mcp.models.authority import (
    AssetAuthorityEntry,
    AssetAuthorityManifest,
    AuthorityResolution,
    AuthorityResult,
    AuthorityUse,
)
from hiwaga_mcp.services.project_state import REPOSITORY_LABEL
from hiwaga_mcp.services.repository import require_valid_repository, resolve_within_repository

ASSET_AUTHORITY_PATH = "art-source/ASSET_AUTHORITY.json"
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

# Explicit tables of the only fields treated as paths. No other value is
# inspected for path-like text.
_REPO_RELATIVE_FIELDS = ("source_path", "runtime_path", "motion_proof_path")
_SOURCE_RELATIVE_FIELDS = (
    "static_form_source",
    "rig_proof_source",
    "motion_source",
    "representative_pose_reference_source",
)

# Derived uses. Each rule is driven by one explicit manifest field value and
# states only what HIWAGA's asset-authority contract says outright: superseded
# reference-only assets are for reference, and `FROM SCRATCH` means no
# duplication, append/link, reshaping, or topology reuse from a superseded source.
_REFERENCE_ONLY = ("authoring_reuse", "reference_only")
_REFERENCE_ONLY_ALLOWED = (AuthorityUse.HISTORICAL_REFERENCE, AuthorityUse.TECHNICAL_REFERENCE)
_REFERENCE_ONLY_FORBIDDEN = (AuthorityUse.AUTHORING_DERIVATION,)
_FROM_SCRATCH = ("creation_mode", "from_scratch")
_FROM_SCRATCH_FORBIDDEN = (
    AuthorityUse.DUPLICATE_SUPERSEDED_SOURCE,
    AuthorityUse.LINK_SUPERSEDED_SOURCE,
    AuthorityUse.RESHAPE_SUPERSEDED_SOURCE,
    AuthorityUse.REUSE_SUPERSEDED_TOPOLOGY,
)

_STANDING_LIMITATION = (
    f"Authority is read only from {ASSET_AUTHORITY_PATH}; prose documents, READMEs, CANON, and the "
    "progress ledger are not consulted. Authority status is not a quality or acceptance judgement."
)


class _DuplicateKeyError(ValueError):
    pass


def _invalid(message: str, problem: str, **details: Any) -> AssetAuthorityError:
    return AssetAuthorityError(
        message, details={"problem": problem, "path": ASSET_AUTHORITY_PATH, **details}
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise _DuplicateKeyError(f"duplicate JSON keys: {', '.join(duplicated)}")
    return dict(pairs)


def parse_manifest(text: str) -> AssetAuthorityManifest:
    """Parse and validate manifest text.

    Raises:
        AssetAuthorityError: not JSON, duplicate keys, not an object, a missing or
            unsupported `schema_version`, or a structure that fails validation.
    """
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError as exc:
        raise _invalid(f"{ASSET_AUTHORITY_PATH} is ambiguous: {exc}.", "duplicate_keys") from exc
    except ValueError as exc:
        raise _invalid(f"{ASSET_AUTHORITY_PATH} is not valid JSON: {exc}", "malformed_json") from exc

    if not isinstance(raw, dict):
        raise _invalid(f"{ASSET_AUTHORITY_PATH} must be a JSON object.", "not_an_object")

    version = raw.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _invalid(
            f"{ASSET_AUTHORITY_PATH} `schema_version` is missing or not an integer.", "invalid_structure"
        )
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise _invalid(
            f"{ASSET_AUTHORITY_PATH} schema_version {version} is not supported "
            f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}).",
            "unsupported_schema_version",
            schema_version=version,
        )

    try:
        manifest = AssetAuthorityManifest.model_validate(raw)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
        raise _invalid(
            f"{ASSET_AUTHORITY_PATH} has an invalid structure: {'; '.join(problems[:5])}",
            "invalid_structure",
            errors=problems[:10],
        ) from exc

    blank = [asset_id for asset_id in manifest.assets if not asset_id.strip()]
    if blank:
        raise _invalid(f"{ASSET_AUTHORITY_PATH} contains an empty asset id.", "invalid_structure")
    return manifest


def load_asset_manifest(repo_root: Path) -> AssetAuthorityManifest:
    """Read and validate the manifest of `repo_root` (contained, UTF-8).

    Raises:
        AssetAuthorityError: missing, unreadable, or invalid manifest.
        TargetOutsideRepositoryError: the manifest resolves outside the repository.
    """
    path = resolve_within_repository(repo_root, ASSET_AUTHORITY_PATH)
    if not path.is_file():
        raise _invalid(f"{ASSET_AUTHORITY_PATH} does not exist in the configured repository.", "missing")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _invalid(f"{ASSET_AUTHORITY_PATH} is not valid UTF-8.", "not_utf8") from exc
    except OSError as exc:
        raise _invalid(f"{ASSET_AUTHORITY_PATH} could not be read: {exc}", "unreadable") from exc
    return parse_manifest(text)


def _declared_path(root: Path, asset_id: str, field: str, value: str, *, under: Path | None = None) -> Path:
    """Canonical path for one declared manifest path, or a refusal if it is unusable."""

    def bad(reason: str) -> AssetAuthorityError:
        return _invalid(
            f"Asset `{asset_id}` field `{field}` {reason}.",
            "invalid_path",
            asset_id=asset_id,
            field=field,
            value=value,
        )

    if not value.strip() or "\x00" in value:
        raise bad("is empty or contains a null byte")
    if Path(value).is_absolute():
        raise bad("must be repository-relative, not absolute")

    joined = value if under is None else f"{under.relative_to(root).as_posix()}/{value}"
    try:
        resolved = resolve_within_repository(root, joined)
    except TargetOutsideRepositoryError as exc:
        raise bad("resolves outside the repository") from exc
    if resolved == root:
        raise bad("resolves to the repository root, which would claim every target")
    if under is not None and under not in resolved.parents:
        raise bad(f"must resolve beneath its source_path ({under.relative_to(root).as_posix()})")
    return resolved


def _asset_paths(root: Path, asset_id: str, entry: AssetAuthorityEntry) -> list[Path]:
    """Every canonical path an asset declares, from the explicit path tables only."""
    paths: list[Path] = []
    source_root: Path | None = None

    for field in _REPO_RELATIVE_FIELDS:
        value = getattr(entry, field)
        if value is not None:
            resolved = _declared_path(root, asset_id, field, value)
            paths.append(resolved)
            if field == "source_path":
                source_root = resolved

    for field in _SOURCE_RELATIVE_FIELDS:
        value = getattr(entry, field)
        if value is None:
            continue
        if source_root is None:
            raise _invalid(
                f"Asset `{asset_id}` declares `{field}` but no `source_path` to resolve it against.",
                "invalid_path",
                asset_id=asset_id,
                field=field,
                value=value,
            )
        if source_root.is_file():
            raise _invalid(
                f"Asset `{asset_id}` declares `{field}` relative to a `source_path` that is a file.",
                "invalid_path",
                asset_id=asset_id,
                field=field,
                value=value,
            )
        paths.append(_declared_path(root, asset_id, field, value, under=source_root))
    return paths


def _owns(declared: Path, target: Path) -> bool:
    """True when `target` is `declared` itself or beneath it; a declared file owns only itself."""
    if target == declared:
        return True
    return declared in target.parents and not declared.is_file()


def derive_uses(entry: AssetAuthorityEntry) -> tuple[list[AuthorityUse], list[AuthorityUse]]:
    """Return `(allowed, forbidden)` uses established by explicit manifest fields only."""
    allowed: set[AuthorityUse] = set()
    forbidden: set[AuthorityUse] = set()

    field, value = _REFERENCE_ONLY
    if getattr(entry, field) == value:
        allowed.update(_REFERENCE_ONLY_ALLOWED)
        forbidden.update(_REFERENCE_ONLY_FORBIDDEN)

    field, value = _FROM_SCRATCH
    if getattr(entry, field) == value:
        forbidden.update(_FROM_SCRATCH_FORBIDDEN)

    order = list(AuthorityUse)
    return [u for u in order if u in allowed], [u for u in order if u in forbidden]


def _declared_paths(root: Path, manifest: AssetAuthorityManifest) -> dict[str, list[Path]]:
    """Canonical declared paths per asset. Validates every entry, so a bad one refuses all."""
    return {asset_id: _asset_paths(root, asset_id, entry) for asset_id, entry in manifest.assets.items()}


def _match_assets(declared: dict[str, list[Path]], target: Path) -> list[str]:
    """Sorted ids of every asset owning `target`."""
    return sorted(
        asset_id for asset_id, paths in declared.items() if any(_owns(path, target) for path in paths)
    )


def _result(
    root: Path,
    target: str,
    resolved: Path,
    resolution: AuthorityResolution,
    matched: Sequence[str],
    entry: AssetAuthorityEntry | None,
    limitations: list[str],
) -> AuthorityResult:
    allowed, forbidden = derive_uses(entry) if entry else ([], [])
    return AuthorityResult(
        repository=REPOSITORY_LABEL,
        repository_root=str(root),
        target=target,
        resolved_target=resolved.relative_to(root).as_posix(),
        resolution=resolution,
        asset_id=matched[0] if resolution is AuthorityResolution.RESOLVED else None,
        matched_asset_ids=list(matched),
        status=entry.status if entry else None,
        visual_authority=entry.visual_authority if entry else None,
        runtime_active=entry.runtime_active if entry else None,
        runtime_required_temporarily=entry.runtime_required_temporarily if entry else None,
        creation_mode=entry.creation_mode if entry else None,
        authoring_reuse=entry.authoring_reuse if entry else None,
        source_path=entry.source_path if entry else None,
        runtime_path=entry.runtime_path if entry else None,
        allowed_uses=allowed,
        forbidden_uses=forbidden,
        replacement=entry.replacement if entry else None,
        limitations=[*limitations, _STANDING_LIMITATION],
    )


def resolve_authorities(repo_root: Path, targets: Sequence[str]) -> list[AuthorityResult]:
    """Resolve asset authority for each of `targets`, in order, from one manifest load.

    Identity is checked, every target is contained, the manifest is loaded and
    validated, and declared paths are canonicalized once; each target is then
    matched independently. Any failure refuses the whole batch.

    Raises:
        RepositoryIdentityError: `repo_root` is not a valid HIWAGA checkout.
        TargetOutsideRepositoryError: a target (or the manifest) escapes the repository.
        AssetAuthorityError: the manifest is missing or cannot be trusted.
    """
    root = require_valid_repository(repo_root)
    resolved_targets = [resolve_within_repository(root, target) for target in targets]
    manifest = load_asset_manifest(root)
    declared = _declared_paths(root, manifest)

    results: list[AuthorityResult] = []
    for target, resolved in zip(targets, resolved_targets, strict=True):
        matched = _match_assets(declared, resolved)
        if not matched:
            results.append(
                _result(
                    root,
                    target,
                    resolved,
                    AuthorityResolution.UNRESOLVED,
                    matched,
                    None,
                    ["No asset in the manifest declares a path that owns this target."],
                )
            )
        elif len(matched) > 1:
            results.append(
                _result(
                    root,
                    target,
                    resolved,
                    AuthorityResolution.CONFLICT,
                    matched,
                    None,
                    [
                        f"Multiple assets own this target ({', '.join(matched)}); no owner is chosen "
                        "and no authority fields are reported."
                    ],
                )
            )
        else:
            entry = manifest.assets[matched[0]]
            results.append(_result(root, target, resolved, AuthorityResolution.RESOLVED, matched, entry, []))
    return results


def resolve_authority(repo_root: Path, target: str) -> AuthorityResult:
    """Resolve the asset authority that applies to `target` in `repo_root`.

    `target` is repository-relative (an absolute path is accepted only if it
    resolves inside the repository, per the containment primitive). It need not
    exist: ownership is decided by path relation to the manifest's declared paths.

    Raises:
        RepositoryIdentityError: `repo_root` is not a valid HIWAGA checkout.
        TargetOutsideRepositoryError: `target` (or the manifest) escapes the repository.
        AssetAuthorityError: the manifest is missing or cannot be trusted.
    """
    return resolve_authorities(repo_root, [target])[0]


__all__ = [
    "ASSET_AUTHORITY_PATH",
    "SUPPORTED_SCHEMA_VERSIONS",
    "derive_uses",
    "load_asset_manifest",
    "parse_manifest",
    "resolve_authorities",
    "resolve_authority",
]
