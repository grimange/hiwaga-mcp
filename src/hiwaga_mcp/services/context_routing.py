"""The bounded grammar over `docs/CANON.md`, and the packaged domain→label mapping.

Two independent, deterministic parsers, deliberately kept apart from the
per-domain resolution logic in `hiwaga_mcp.services.context`:

1. `read_canon_document` / `parse_canon_document` read only the three routing
   sections the accepted routing audit established as reliable, and extract
   each `- Label: body` bullet's label and Markdown links. Nothing outside
   that grammar is interpreted: status prose, provisional markers, and
   `PROTOTYPE_A` tokens are never parsed into machine values here.
2. `load_context_routing_mapping` / `parse_context_routing_mapping` load and
   strictly validate the packaged `context_routing.json` — the one fact CANON
   cannot supply on its own (which labels answer which domain).

Neither function checks a mapped label against CANON's actual bullets; that
cross-check is `hiwaga_mcp.services.context`'s job, once it has both.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hiwaga_mcp.errors import ContextRoutingError
from hiwaga_mcp.models.context import SourceClassification
from hiwaga_mcp.models.context_routing import ContextRoutingMapping
from hiwaga_mcp.services.repository import resolve_within_repository

CANON_DOCUMENT_PATH = "docs/CANON.md"
CANON_DIRECTORY = str(Path(CANON_DOCUMENT_PATH).parent)  # "docs" — links in CANON are relative to this

ROUTING_MAPPING_PACKAGE = "hiwaga_mcp"
ROUTING_MAPPING_RESOURCE = "policy/context_routing.json"
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

#: Exact H2 heading text of the three sections that supply routing bullets, and
#: the classification every bullet drawn from that section carries. Any other
#: H2 — `Historical and provisional material`, `Current planning boundary`, or
#: a future one — is ignored, never routed.
ROUTING_SECTIONS: dict[str, SourceClassification] = {
    "Canonical sources": SourceClassification.CANONICAL,
    "Supporting references": SourceClassification.SUPPORTING,
    "Exploratory Prototype A — frozen findings and history": SourceClassification.PROTOTYPE_A,
}

_H2_RE = re.compile(r"^ {0,3}##[ \t]+(?P<text>\S.*?)[ \t]*$")
_BULLET_RE = re.compile(r"^- (?P<rest>\S.*)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


@dataclass(frozen=True)
class CanonBullet:
    """One parsed `- Label: body` line from a known routing section, verbatim."""

    label: str
    text: str  # "Label: body", exactly as written after "- "
    links: tuple[tuple[str, str], ...]  # (link text, raw target), in document order


@dataclass(frozen=True)
class CanonDocument:
    """The three known routing sections of `docs/CANON.md`, parsed and nothing else."""

    sections: dict[str, tuple[CanonBullet, ...]]


class _DuplicateKeyError(ValueError):
    pass


def _invalid(message: str, problem: str, **details: Any) -> ContextRoutingError:
    return ContextRoutingError(message, details={"problem": problem, **details})


def _parse_bullet(line: str) -> CanonBullet | None:
    """Parse one `- Label: body` line. Returns None for any line that does not match."""
    match = _BULLET_RE.match(line)
    if match is None:
        return None
    rest = match.group("rest")
    separator = rest.find(": ")
    if separator == -1:
        return None
    label = rest[:separator].strip()
    if not label:
        return None
    return CanonBullet(label=label, text=rest.strip(), links=tuple(_LINK_RE.findall(rest)))


def parse_canon_document(text: str) -> CanonDocument:
    """Parse the three known routing sections out of CANON text.

    A `- ` line inside a known section that does not match `Label: body` is
    silently skipped, not an error by itself: it only becomes one if a mapped
    label later fails to resolve against what was actually parsed (see
    `hiwaga_mcp.services.context`).

    Raises:
        ContextRoutingError: a required routing section is missing, renamed, or
            declared more than once. Carries `HIWAGA_CONTEXT_ROUTING_INVALID`.
    """
    sections: dict[str, list[CanonBullet]] = {}
    current: str | None = None

    for line in text.splitlines():
        heading = _H2_RE.match(line)
        if heading:
            name = heading.group("text").strip()
            current = name if name in ROUTING_SECTIONS else None
            if current is not None:
                if current in sections:
                    raise _invalid(
                        f"{CANON_DOCUMENT_PATH} declares the routing section {current!r} more than once.",
                        "duplicate_section",
                        section=current,
                    )
                sections[current] = []
            continue
        if current is not None:
            bullet = _parse_bullet(line)
            if bullet is not None:
                sections[current].append(bullet)

    missing = [name for name in ROUTING_SECTIONS if name not in sections]
    if missing:
        raise _invalid(
            f"{CANON_DOCUMENT_PATH} is missing required routing section(s): {', '.join(missing)}.",
            "missing_routing_section",
            missing_sections=missing,
        )

    return CanonDocument(sections={name: tuple(bullets) for name, bullets in sections.items()})


def read_canon_document(repo_root: Path) -> CanonDocument:
    """Read and parse `docs/CANON.md` from `repo_root`.

    Raises:
        ContextRoutingError: the document is missing, unreadable, not UTF-8, or
            structurally invalid.
        TargetOutsideRepositoryError: the document resolves outside the repository.
    """
    path = resolve_within_repository(repo_root, CANON_DOCUMENT_PATH)
    if not path.is_file():
        raise _invalid(f"{CANON_DOCUMENT_PATH} does not exist in the configured repository.", "missing")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _invalid(f"{CANON_DOCUMENT_PATH} is not valid UTF-8.", "not_utf8") from exc
    except OSError as exc:
        raise _invalid(f"{CANON_DOCUMENT_PATH} could not be read: {exc}", "unreadable") from exc
    return parse_canon_document(text)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    duplicated = sorted({key for key in keys if keys.count(key) > 1})
    if duplicated:
        raise _DuplicateKeyError(f"duplicate JSON keys: {', '.join(duplicated)}")
    return dict(pairs)


def parse_context_routing_mapping(text: str) -> ContextRoutingMapping:
    """Parse and validate the packaged domain→CANON-label mapping.

    Validates the mapping's own structure only; it does not check a mapped
    label against CANON's actual bullets (see `hiwaga_mcp.services.context`).

    Raises:
        ContextRoutingError: not JSON, duplicate keys at any level, not an
            object, a missing or unsupported `schema_version`, an unknown
            domain key, a missing domain, an empty or repeated label, or any
            other structural violation.
    """
    try:
        raw = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
    except _DuplicateKeyError as exc:
        raise _invalid(f"The context routing mapping is ambiguous: {exc}.", "duplicate_keys") from exc
    except ValueError as exc:
        raise _invalid(f"The context routing mapping is not valid JSON: {exc}", "malformed_json") from exc

    if not isinstance(raw, dict):
        raise _invalid("The context routing mapping must be a JSON object.", "not_an_object")

    version = raw.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _invalid(
            "The context routing mapping `schema_version` is missing or not an integer.", "invalid_structure"
        )
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise _invalid(
            f"The context routing mapping schema_version {version} is not supported "
            f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}).",
            "unsupported_schema_version",
            schema_version=version,
        )

    try:
        return ContextRoutingMapping.model_validate(raw)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()]
        raise _invalid(
            f"The context routing mapping has an invalid structure: {'; '.join(problems[:5])}",
            "invalid_structure",
            errors=problems[:10],
        ) from exc


def _packaged_mapping_text() -> str:
    resource = resources.files(ROUTING_MAPPING_PACKAGE).joinpath(ROUTING_MAPPING_RESOURCE)
    try:
        return resource.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise _invalid("The packaged context routing mapping is missing.", "missing") from exc
    except UnicodeDecodeError as exc:
        raise _invalid("The packaged context routing mapping is not valid UTF-8.", "not_utf8") from exc
    except OSError as exc:
        raise _invalid(
            f"The packaged context routing mapping could not be read: {exc}", "unreadable"
        ) from exc


def load_context_routing_mapping(text: str | None = None) -> ContextRoutingMapping:
    """Load the canonical mapping: `text` if given (a server-construction seam), else the package's."""
    return parse_context_routing_mapping(_packaged_mapping_text() if text is None else text)


__all__ = [
    "CANON_DIRECTORY",
    "CANON_DOCUMENT_PATH",
    "ROUTING_MAPPING_RESOURCE",
    "ROUTING_SECTIONS",
    "SUPPORTED_SCHEMA_VERSIONS",
    "CanonBullet",
    "CanonDocument",
    "load_context_routing_mapping",
    "parse_canon_document",
    "parse_context_routing_mapping",
    "read_canon_document",
]
