"""Deterministic HIWAGA context routing.

`get_context` answers exactly one question: given an explicit `ContextDomain`,
which repository sources does `docs/CANON.md` currently route for it? It is a
routing interface, not a search engine — every result comes from CANON's own
bounded grammar plus the packaged domain→label mapping, never from ranking,
keyword matching, or interpreting a source's own status prose.

Composition, not reimplementation: this module calls the existing project-state
service for `PROJECT` and nothing else. It never calls the asset-authority
service (`hiwaga_context` answers "which documents govern asset authority?";
`hiwaga_authority` answers "which registered authority applies to this path?"),
never calls preflight or the model gate, and never executes anything.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from hiwaga_mcp.errors import ContextRoutingError
from hiwaga_mcp.models.context import ContextDomain, ContextResult, ContextSource, SourceClassification
from hiwaga_mcp.models.context_routing import DomainRouting, LabelRef
from hiwaga_mcp.services.context_routing import (
    CANON_DIRECTORY,
    CANON_DOCUMENT_PATH,
    CanonBullet,
    CanonDocument,
    load_context_routing_mapping,
    read_canon_document,
)
from hiwaga_mcp.services.project_state import REPOSITORY_LABEL, get_project_state
from hiwaga_mcp.services.repository import require_valid_repository, resolve_within_repository

#: Which CANON section a category's labels must be found in, and the
#: classification every source resolved from that category carries. Fixed by
#: section membership only (never by a bullet's own status prose).
_CATEGORY_SECTIONS: tuple[tuple[str, str, SourceClassification], ...] = (
    ("canonical", "Canonical sources", SourceClassification.CANONICAL),
    ("supporting", "Supporting references", SourceClassification.SUPPORTING),
    ("historical", "Exploratory Prototype A — frozen findings and history", SourceClassification.PROTOTYPE_A),
)

_STANDING_LIMITATION = (
    "hiwaga_context reports routing metadata only — paths, titles, and CANON's own status text — from "
    "docs/CANON.md and the packaged domain mapping. It returns no document bodies, excerpts, or summaries, "
    "and performs no search, ranking, or asset-authority resolution."
)

_WORLD_LORE_HISTORICAL_LIMITATION = (
    "CANON's historical/provisional class rule covers earlier docs/lore/ material as a whole "
    "(superseded by the consolidated World & Lore Bible when it evolved); those files are not "
    "individually enumerated by this routing."
)

_ASSET_AUTHORITY_MACHINE_FILE_LIMITATION = (
    "CANON names art-source/ASSET_AUTHORITY.json as the machine-readable counterpart to the routed "
    "document above only as inline text, not as a Markdown link, so it is not returned as a separate "
    "routed source here."
)


def _invalid(message: str, problem: str, **details: object) -> ContextRoutingError:
    return ContextRoutingError(message, details={"problem": problem, **details})


def _resolve_source(
    root: Path,
    bullet: CanonBullet,
    link_text: str,
    raw_target: str,
    classification: SourceClassification,
    section: str | None,
) -> ContextSource:
    """Resolve one Markdown link out of a bullet into a containment-checked `ContextSource`.

    Raises:
        TargetOutsideRepositoryError: the link resolves outside the repository.
    """
    target = unquote(raw_target.split("#", 1)[0])
    resolved = resolve_within_repository(root, f"{CANON_DIRECTORY}/{target}")
    is_file = resolved.is_file()
    is_dir = not is_file and resolved.is_dir()
    return ContextSource(
        path=resolved.relative_to(root).as_posix(),
        title=link_text,
        label=bullet.label,
        classification=classification,
        section=section,
        note=bullet.text,
        exists=is_file or is_dir,
        size_bytes=resolved.stat().st_size if is_file else None,
    )


def _resolve_category(
    root: Path,
    canon: CanonDocument,
    refs: list[LabelRef],
    section_name: str,
    classification: SourceClassification,
    domain: ContextDomain,
    *,
    fail_closed: bool,
) -> tuple[list[ContextSource], list[str]]:
    """Resolve one mapping category (canonical/supporting/historical) for `domain`.

    Raises:
        ContextRoutingError: a mapped label no longer names a bullet in
            `section_name` (routing drift), or `fail_closed` and a resolved
            source does not exist on disk.
        TargetOutsideRepositoryError: a resolved link escapes the repository.
    """
    bullets_by_label = {bullet.label: bullet for bullet in canon.sections[section_name]}
    sources: list[ContextSource] = []
    limitations: list[str] = []

    for ref in refs:
        bullet = bullets_by_label.get(ref.label)
        if bullet is None:
            raise _invalid(
                f"The context routing mapping routes {domain.value} to CANON label {ref.label!r} in "
                f"{section_name!r}, but no such bullet exists there anymore.",
                "mapped_label_not_found",
                domain=domain.value,
                section=section_name,
                label=ref.label,
            )
        if not bullet.links:
            limitations.append(
                f"CANON bullet {ref.label!r} in {section_name!r} names no Markdown link, so it "
                "contributes no routed source."
            )
            continue
        for link_text, raw_target in bullet.links:
            source = _resolve_source(root, bullet, link_text, raw_target, classification, ref.section)
            if not source.exists:
                if fail_closed:
                    raise _invalid(
                        f"The routed source {source.path!r} for CANON label {ref.label!r} does not exist; "
                        "current canonical routing authority is broken.",
                        "missing_canonical_source",
                        domain=domain.value,
                        label=ref.label,
                        path=source.path,
                    )
                limitations.append(
                    f"Routed source {source.path!r} (label {ref.label!r}) does not exist on disk."
                )
            sources.append(source)

    return sources, limitations


def _canon_self_source(root: Path) -> ContextSource:
    """The `PROJECT`-domain special case: CANON is not a document it routes, it is the routing index."""
    resolved = resolve_within_repository(root, CANON_DOCUMENT_PATH)
    return ContextSource(
        path=CANON_DOCUMENT_PATH,
        title="HIWAGA Canon and Source-of-Truth Index",
        label="PROJECT routing index",
        classification=SourceClassification.CURRENT_STATE,
        section=None,
        note=(
            "docs/CANON.md is the domain-routing authority hiwaga_context resolves every other "
            "domain's sources from; it is not itself routed by a CANON bullet."
        ),
        exists=resolved.is_file(),
        size_bytes=resolved.stat().st_size if resolved.is_file() else None,
    )


def get_context(repo_root: Path, domain: ContextDomain, *, mapping_text: str | None = None) -> ContextResult:
    """Route `domain` to the repository sources CANON currently governs or supports it with.

    Raises:
        RepositoryIdentityError: `repo_root` is not a valid HIWAGA checkout.
        ContextRoutingError: CANON's routing structure, the packaged mapping, a
            mapped label, or a canonical source cannot be trusted.
        TargetOutsideRepositoryError: a routed link escapes the repository.
    """
    root = require_valid_repository(repo_root)
    canon = read_canon_document(root)
    mapping = load_context_routing_mapping(mapping_text)
    routing: DomainRouting = mapping.domains[domain]

    limitations: list[str] = []
    resolved: dict[str, list[ContextSource]] = {}
    for category, section_name, classification in _CATEGORY_SECTIONS:
        sources, category_limitations = _resolve_category(
            root,
            canon,
            getattr(routing, category),
            section_name,
            classification,
            domain,
            fail_closed=(category == "canonical"),
        )
        resolved[category] = sources
        limitations.extend(category_limitations)

    project_state = None
    canonical_sources = resolved["canonical"]
    if domain is ContextDomain.PROJECT:
        project_state = get_project_state(root)
        canonical_sources = [_canon_self_source(root), *canonical_sources]
    elif not canonical_sources:
        limitations.append(
            f"CANON defines supporting/current development sources for {domain.value} but no "
            "canonical source; this is a valid repository fact, not a routing failure."
        )

    if domain is ContextDomain.WORLD_LORE:
        limitations.append(_WORLD_LORE_HISTORICAL_LIMITATION)
    if domain is ContextDomain.ASSET_AUTHORITY:
        limitations.append(_ASSET_AUTHORITY_MACHINE_FILE_LIMITATION)

    limitations.append(_STANDING_LIMITATION)

    return ContextResult(
        repository=REPOSITORY_LABEL,
        repository_root=str(root),
        domain=domain,
        canonical_sources=canonical_sources,
        supporting_sources=resolved["supporting"],
        historical_sources=resolved["historical"],
        project_state=project_state,
        routing_document=CANON_DOCUMENT_PATH,
        limitations=limitations,
    )


__all__ = ["get_context"]
