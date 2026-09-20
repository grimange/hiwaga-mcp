"""Loading and lookup for the canonical verifier registry.

The registry is the execution allowlist, so it is validated strictly and
trusted wholly or not at all. A registry that fails validation does not
degrade to "run the entries that parsed": it raises, and nothing executes.

Registry definitions are read only from the packaged JSON resource. Prose
documents in the HIWAGA checkout — AGENTS.md, README.md, the progress ledger,
Codex or Claude configuration — are never consulted at runtime.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from pydantic import ValidationError

from hiwaga_mcp.errors import (
    UnknownVerifierError,
    UnsupportedVerifyModeError,
    VerifierRegistryError,
)
from hiwaga_mcp.models.verification_registry import (
    VerifierDefinition,
    VerifierMode,
    VerifierRegistry,
)

REGISTRY_PACKAGE = "hiwaga_mcp"
REGISTRY_RESOURCE = "policy/verifier_registry.json"
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})


class _DuplicateKeyError(ValueError):
    pass


def _invalid(message: str, problem: str, **details: Any) -> VerifierRegistryError:
    return VerifierRegistryError(message, details={"problem": problem, "path": REGISTRY_RESOURCE, **details})


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise _DuplicateKeyError(f"duplicate JSON keys: {', '.join(duplicated)}")
    return dict(pairs)


def parse_verifier_registry(text: str) -> VerifierRegistry:
    """Parse and validate verifier-registry text.

    Raises:
        VerifierRegistryError: not JSON, duplicate keys at any level, not an
            object, a missing or unsupported `schema_version`, a missing or
            non-object `verifiers` map, an unknown key anywhere, or any verifier
            that is malformed (unknown proof class or executable strategy,
            non-positive timeout, empty mode map, escaping script or working
            directory, unsupported argument placeholder, undeclared default mode).
    """
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError as exc:
        raise _invalid(f"The verifier registry is ambiguous: {exc}.", "duplicate_keys") from exc
    except ValueError as exc:
        raise _invalid(f"The verifier registry is not valid JSON: {exc}", "malformed_json") from exc

    if not isinstance(raw, dict):
        raise _invalid("The verifier registry must be a JSON object.", "not_an_object")

    version = raw.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _invalid(
            "The verifier registry `schema_version` is missing or not an integer.", "invalid_structure"
        )
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise _invalid(
            f"The verifier registry schema_version {version} is not supported "
            f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}).",
            "unsupported_schema_version",
            schema_version=version,
        )

    if "verifiers" not in raw:
        raise _invalid("The verifier registry declares no `verifiers` map.", "invalid_structure")
    if not isinstance(raw["verifiers"], dict):
        raise _invalid("The verifier registry `verifiers` must be a JSON object.", "invalid_structure")

    try:
        return VerifierRegistry.model_validate(raw)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
        raise _invalid(
            f"The verifier registry has an invalid structure: {'; '.join(problems[:5])}",
            "invalid_structure",
            errors=problems[:10],
        ) from exc


def _packaged_registry_text() -> str:
    resource = resources.files(REGISTRY_PACKAGE).joinpath(REGISTRY_RESOURCE)
    try:
        return resource.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise _invalid("The packaged verifier registry is missing.", "missing") from exc
    except UnicodeDecodeError as exc:
        raise _invalid("The packaged verifier registry is not valid UTF-8.", "not_utf8") from exc
    except OSError as exc:
        raise _invalid(f"The packaged verifier registry could not be read: {exc}", "unreadable") from exc


def load_verifier_registry(text: str | None = None) -> VerifierRegistry:
    """Load the canonical registry: `text` if given (a server-construction seam), else the package's."""
    return parse_verifier_registry(_packaged_registry_text() if text is None else text)


def select_verifier(
    registry: VerifierRegistry, verifier: str, mode: str | None
) -> tuple[str, VerifierDefinition, str, VerifierMode]:
    """Resolve a caller's `(verifier, mode)` selection against the registry.

    An unknown verifier or mode is an invalid request, not a verification
    outcome, so both raise rather than returning a status.

    Returns:
        `(verifier_id, definition, mode_name, mode)`.

    Raises:
        UnknownVerifierError: no such registered verifier.
        UnsupportedVerifyModeError: the verifier does not declare that mode, or
            the mode was omitted and the verifier declares no default.
    """
    selected = verifier.strip()
    definition = registry.verifiers.get(selected)
    if definition is None:
        known = ", ".join(sorted(registry.verifiers)) or "none"
        raise UnknownVerifierError(
            f"No verifier {verifier!r} is registered (registered: {known}).",
            details={"verifier": verifier, "registered_verifiers": sorted(registry.verifiers)},
        )

    declared = sorted(definition.modes)
    if mode is None or not mode.strip():
        if definition.default_mode is None:
            raise UnsupportedVerifyModeError(
                f"Verifier {selected!r} declares no default mode; supply one of: {', '.join(declared)}.",
                details={"verifier": selected, "mode": mode, "supported_modes": declared},
            )
        chosen = definition.default_mode
    else:
        chosen = mode.strip()

    entry = definition.modes.get(chosen)
    if entry is None:
        raise UnsupportedVerifyModeError(
            f"Verifier {selected!r} does not support mode {chosen!r} (supported: {', '.join(declared)}).",
            details={"verifier": selected, "mode": chosen, "supported_modes": declared},
        )
    return selected, definition, chosen, entry


__all__ = [
    "REGISTRY_RESOURCE",
    "SUPPORTED_SCHEMA_VERSIONS",
    "load_verifier_registry",
    "parse_verifier_registry",
    "select_verifier",
]
