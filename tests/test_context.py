"""`get_context`: routing resolution, classification, historical isolation, fail-closed behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hiwaga_mcp.errors import (
    ContextRoutingError,
    ReasonCode,
    RepositoryIdentityError,
    TargetOutsideRepositoryError,
)
from hiwaga_mcp.models.context import ContextDomain, SourceClassification
from hiwaga_mcp.services import authority as authority_module
from hiwaga_mcp.services import context as context_module
from hiwaga_mcp.services.context import get_context

from .conftest import (
    context_routing_mapping_text,
    fixture_context_routing_mapping,
    install_fixture_canon_links,
    make_hiwaga_repo,
    write_canon,
)

D = ContextDomain
C = SourceClassification


_USE_FIXTURE_MAPPING = object()


def route(root: Path, domain: D, mapping: Any = _USE_FIXTURE_MAPPING) -> Any:
    """Route against the fixture mapping by default; pass `mapping=None` to use the packaged one."""
    if mapping is _USE_FIXTURE_MAPPING:
        mapping = fixture_context_routing_mapping()
    text = context_routing_mapping_text(mapping) if mapping is not None else None
    return get_context(root, domain, mapping_text=text)


def paths(sources: list[Any]) -> list[str]:
    return [s.path for s in sources]


# --- every domain --------------------------------------------------------------


def test_project_routes_canon_itself_and_full_project_state(context_repo: Path) -> None:
    result = route(context_repo, D.PROJECT)
    assert paths(result.canonical_sources) == ["docs/CANON.md"]
    (canon_source,) = result.canonical_sources
    assert canon_source.classification is C.CURRENT_STATE
    assert canon_source.exists is True
    assert result.supporting_sources == [] and result.historical_sources == []
    assert result.project_state is not None
    assert result.routing_document == "docs/CANON.md"


def test_gameplay_routes_canonical_and_supporting(context_repo: Path) -> None:
    result = route(context_repo, D.GAMEPLAY)
    assert paths(result.canonical_sources) == ["docs/FIXTURE_GAME_IDENTITY.md"]
    assert result.canonical_sources[0].classification is C.CANONICAL
    assert paths(result.supporting_sources) == ["docs/FIXTURE_CAMPAIGN.md"]
    assert result.historical_sources == []


def test_world_lore_routes_only_the_consolidated_bible(context_repo: Path) -> None:
    result = route(context_repo, D.WORLD_LORE)
    assert paths(result.canonical_sources) == ["docs/lore/FIXTURE_WORLD_LORE.md"]
    assert result.supporting_sources == [] and result.historical_sources == []


def test_visual_identity_routes_the_provisional_canonical_source(context_repo: Path) -> None:
    result = route(context_repo, D.VISUAL_IDENTITY)
    (source,) = result.canonical_sources
    assert source.path == "docs/FIXTURE_VISUAL_IDENTITY.md"
    assert source.classification is C.CANONICAL
    assert "provisional" in source.note


def test_core_architecture_is_canonical_less_supporting_only(context_repo: Path) -> None:
    result = route(context_repo, D.CORE_ARCHITECTURE)
    assert result.canonical_sources == []
    assert set(paths(result.supporting_sources)) >= {
        "docs/technical/fixture-development-environment.md",
        "docs/FIXTURE_ENGINE_EVALUATION.md",
        "docs/technical/FIXTURE_CORE_ARCHITECTURE.md",
    }


def test_progression_is_canonical_less_supporting_only(context_repo: Path) -> None:
    result = route(context_repo, D.PROGRESSION)
    assert result.canonical_sources == []
    assert paths(result.supporting_sources) == [
        "docs/design/FIXTURE_PROGRESSION.md",
        "docs/design/FIXTURE_P1_CONTRACT.md",
    ]


def test_representative_gameplay_is_canonical_less_supporting_only(context_repo: Path) -> None:
    result = route(context_repo, D.REPRESENTATIVE_GAMEPLAY)
    assert result.canonical_sources == []
    assert paths(result.supporting_sources) == [
        "docs/design/FIXTURE_RGF_CONTRACT.md",
        "docs/design/FIXTURE_MOTION_LANGUAGE.md",
    ]


def test_asset_authority_is_canonical_less_supporting_only(context_repo: Path) -> None:
    result = route(context_repo, D.ASSET_AUTHORITY)
    assert result.canonical_sources == []
    assert paths(result.supporting_sources) == ["docs/technical/FIXTURE_ASSET_AUTHORITY.md"]
    assert any("ASSET_AUTHORITY.json" in note for note in result.limitations)


def test_verification_separates_active_and_historical_sources(context_repo: Path) -> None:
    result = route(context_repo, D.VERIFICATION)
    assert paths(result.supporting_sources) == ["docs/technical/FIXTURE_EVIDENCE_STANDARD.md"]
    historical_paths = paths(result.historical_sources)
    assert "docs/technical/FIXTURE_CAPTURE_CLAIM.md" in historical_paths
    assert all(s.classification is C.PROTOTYPE_A for s in result.historical_sources)


# --- canonical-less domains report a limitation, not an error -----------------


@pytest.mark.parametrize(
    "domain",
    [D.CORE_ARCHITECTURE, D.PROGRESSION, D.REPRESENTATIVE_GAMEPLAY, D.ASSET_AUTHORITY, D.VERIFICATION],
)
def test_canonical_less_domains_are_not_errors(context_repo: Path, domain: D) -> None:
    result = route(context_repo, domain)
    assert result.canonical_sources == []
    assert any("no canonical source" in note for note in result.limitations)


def test_project_never_gets_the_canonical_less_limitation(context_repo: Path) -> None:
    result = route(context_repo, D.PROJECT)
    assert not any("no canonical source" in note for note in result.limitations)


# --- the Vertical Slice special case (the highest-value regression) -----------


def test_evidence_never_appears_as_vertical_slice_canonical_or_supporting(context_repo: Path) -> None:
    result = route(context_repo, D.VERTICAL_SLICE)
    assert "docs/evidence/fixture-vertical-slice" not in paths(result.canonical_sources)
    assert "docs/evidence/fixture-vertical-slice" not in paths(result.supporting_sources)
    assert "docs/evidence/fixture-vertical-slice" in paths(result.historical_sources)


def test_vertical_slice_canonical_source_carries_the_acceptance_section(context_repo: Path) -> None:
    result = route(context_repo, D.VERTICAL_SLICE)
    (source,) = result.canonical_sources
    assert source.path == "docs/FIXTURE_VERTICAL_SLICE_SPEC.md"
    assert source.classification is C.CANONICAL
    assert source.section == "42. Fixture Acceptance Gate"


def test_vertical_slice_historical_source_classification_is_prototype_a(context_repo: Path) -> None:
    result = route(context_repo, D.VERTICAL_SLICE)
    assert all(s.classification is C.PROTOTYPE_A for s in result.historical_sources)


def test_vertical_slice_acceptance_decoy_bullet_contributes_nothing(context_repo: Path) -> None:
    """The `Vertical-slice acceptance` CANON bullet is deliberately unmapped; it must not leak in."""
    result = route(context_repo, D.VERTICAL_SLICE)
    all_notes = "".join(
        s.note for s in (*result.canonical_sources, *result.supporting_sources, *result.historical_sources)
    )
    assert "Ambiguous classification example" not in all_notes


def test_the_same_path_in_two_sections_is_returned_twice_not_deduplicated(context_repo: Path) -> None:
    """`docs/progress/HIWAGA_PROGRESS.md` and the evidence dir both come from one historical bullet."""
    result = route(context_repo, D.VERTICAL_SLICE)
    historical_paths = paths(result.historical_sources)
    assert historical_paths == ["docs/evidence/fixture-vertical-slice", "docs/progress/HIWAGA_PROGRESS.md"]
    assert len(historical_paths) == len(
        set(historical_paths)
    )  # not literally duplicated, but not merged either


# --- historical isolation (every domain) --------------------------------------


@pytest.mark.parametrize("domain", list(ContextDomain))
def test_prototype_a_never_contaminates_canonical_or_supporting(context_repo: Path, domain: D) -> None:
    result = route(context_repo, domain)
    for source in (*result.canonical_sources, *result.supporting_sources):
        assert source.classification is not C.PROTOTYPE_A


# --- missing sources -----------------------------------------------------------


def test_missing_supporting_source_is_a_structured_limitation_not_an_error(context_repo: Path) -> None:
    result = route(context_repo, D.CORE_ARCHITECTURE)
    ghost = next(s for s in result.supporting_sources if s.path == "docs/design/FIXTURE_GHOST.md")
    assert ghost.exists is False
    assert ghost.size_bytes is None
    assert any("FIXTURE_GHOST.md" in note and "does not exist" in note for note in result.limitations)


def test_missing_historical_source_is_a_structured_limitation_not_an_error(context_repo: Path) -> None:
    result = route(context_repo, D.VERIFICATION)
    ghost = next(s for s in result.historical_sources if s.path == "docs/design/FIXTURE_GHOST_HISTORY.md")
    assert ghost.exists is False
    assert any("FIXTURE_GHOST_HISTORY.md" in note for note in result.limitations)


def test_missing_canonical_source_fails_closed(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    write_canon(root)
    install_fixture_canon_links(root)
    (root / "docs/FIXTURE_GAME_IDENTITY.md").unlink()  # the GAMEPLAY canonical source
    with pytest.raises(ContextRoutingError) as info:
        route(root, D.GAMEPLAY)
    assert info.value.code is ReasonCode.CONTEXT_ROUTING_INVALID
    assert info.value.details["problem"] == "missing_canonical_source"


# --- directory links -------------------------------------------------------


def test_a_routed_directory_exists_true_and_size_bytes_null(context_repo: Path) -> None:
    result = route(context_repo, D.VERTICAL_SLICE)
    directory = next(s for s in result.historical_sources if s.path == "docs/evidence/fixture-vertical-slice")
    assert directory.exists is True
    assert directory.size_bytes is None


# --- mapped label drift --------------------------------------------------------


def test_a_mapped_label_absent_from_canon_fails_closed(context_repo: Path) -> None:
    mapping = fixture_context_routing_mapping()
    mapping["domains"]["GAMEPLAY"]["canonical"] = ["A label that no longer exists"]
    with pytest.raises(ContextRoutingError) as info:
        route(context_repo, D.GAMEPLAY, mapping)
    assert info.value.details["problem"] == "mapped_label_not_found"
    assert info.value.details["domain"] == "GAMEPLAY"


def test_a_mapped_label_in_the_wrong_category_fails_closed(context_repo: Path) -> None:
    """A supporting-section label mapped as canonical does not silently resolve."""
    mapping = fixture_context_routing_mapping()
    mapping["domains"]["GAMEPLAY"]["canonical"] = ["Core architecture"]  # a real label, wrong section
    with pytest.raises(ContextRoutingError) as info:
        route(context_repo, D.GAMEPLAY, mapping)
    assert info.value.details["problem"] == "mapped_label_not_found"


# --- CANON structural failures propagate ---------------------------------------


def test_missing_canon_document_is_a_routing_error(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga", omit=("docs/CANON.md",))
    with pytest.raises(RepositoryIdentityError):
        # CANON.md is an identity sentinel: its absence fails identity first.
        route(root, D.PROJECT)


def test_malformed_canon_structure_is_a_routing_error(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    write_canon(root, "# Title\n\nno routing sections at all\n")
    with pytest.raises(ContextRoutingError) as info:
        route(root, D.PROJECT)
    assert info.value.details["problem"] == "missing_routing_section"


def test_invalid_mapping_is_a_routing_error(context_repo: Path) -> None:
    with pytest.raises(ContextRoutingError) as info:
        get_context(context_repo, D.PROJECT, mapping_text="{ not json")
    assert info.value.code is ReasonCode.CONTEXT_ROUTING_INVALID


# --- containment ----------------------------------------------------------


def test_a_canon_link_escaping_the_repository_is_a_containment_error(
    tmp_path: Path, outside_dir: Path
) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    (outside_dir / "secret.md").write_text("# secret\n", encoding="utf-8")
    # CANON links resolve relative to `docs/`, so escaping to `outside_dir` (a
    # sibling of the repository root) takes one `..` to leave `docs/` plus one
    # more to leave the repository root itself.
    text = (
        "## Canonical sources\n\n- Game identity and gameplay design: [Escape](../../outside/secret.md)\n"
        "\n## Supporting references\n\n- x: [x](x.md)\n"
        "\n## Exploratory Prototype A — frozen findings and history\n\n- y: [y](y.md)\n"
    )
    write_canon(root, text)
    with pytest.raises(TargetOutsideRepositoryError):
        route(root, D.GAMEPLAY)


# --- ordering ---------------------------------------------------------------


def test_source_order_follows_mapping_label_order_then_link_order_in_each_bullet(context_repo: Path) -> None:
    result = route(context_repo, D.CORE_ARCHITECTURE)
    # mapping order: "Technical foundation reference" (2 links), then "Core
    # architecture" (1 link), then "Missing supporting source".
    assert paths(result.supporting_sources) == [
        "docs/technical/fixture-development-environment.md",
        "docs/FIXTURE_ENGINE_EVALUATION.md",
        "docs/technical/FIXTURE_CORE_ARCHITECTURE.md",
        "docs/design/FIXTURE_GHOST.md",
    ]


def test_reordering_the_mapping_labels_reorders_the_result(context_repo: Path) -> None:
    mapping = fixture_context_routing_mapping()
    mapping["domains"]["PROGRESSION"]["supporting"] = list(
        reversed(mapping["domains"]["PROGRESSION"]["supporting"])
    )
    result = route(context_repo, D.PROGRESSION, mapping)
    assert paths(result.supporting_sources) == [
        "docs/design/FIXTURE_P1_CONTRACT.md",
        "docs/design/FIXTURE_PROGRESSION.md",
    ]


# --- verbatim titles, labels, notes --------------------------------------------


def test_title_is_the_markdown_link_text_verbatim(context_repo: Path) -> None:
    result = route(context_repo, D.CORE_ARCHITECTURE)
    titles = {s.path: s.title for s in result.supporting_sources}
    assert titles["docs/technical/fixture-development-environment.md"] == "fixture dev environment"
    assert titles["docs/FIXTURE_ENGINE_EVALUATION.md"] == "Fixture Engine Evaluation"


def test_label_is_the_canon_bullet_label_verbatim(context_repo: Path) -> None:
    result = route(context_repo, D.CORE_ARCHITECTURE)
    labels = {s.label for s in result.supporting_sources}
    assert "Technical foundation reference" in labels


def test_note_is_the_complete_bullet_text_and_shared_across_a_multi_link_bullet(context_repo: Path) -> None:
    result = route(context_repo, D.CORE_ARCHITECTURE)
    first, second = result.supporting_sources[0], result.supporting_sources[1]
    assert first.note == second.note
    assert "DIRECTIONAL" in first.note


# --- project-state reuse and authority separation ------------------------------


def test_project_calls_get_project_state_exactly_once(
    context_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = context_module.get_project_state

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(context_module, "get_project_state", counting)
    route(context_repo, D.PROJECT)
    assert len(calls) == 1


@pytest.mark.parametrize("domain", [d for d in ContextDomain if d is not ContextDomain.PROJECT])
def test_non_project_domains_never_call_get_project_state(
    context_repo: Path, monkeypatch: pytest.MonkeyPatch, domain: D
) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("get_project_state must not be called for a non-PROJECT domain")

    monkeypatch.setattr(context_module, "get_project_state", fail)
    route(context_repo, domain)  # must not raise


@pytest.mark.parametrize("domain", list(ContextDomain))
def test_no_domain_calls_the_authority_service(
    context_repo: Path, monkeypatch: pytest.MonkeyPatch, domain: D
) -> None:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("hiwaga_context must never call the authority service")

    monkeypatch.setattr(authority_module, "resolve_authority", fail)
    monkeypatch.setattr(authority_module, "resolve_authorities", fail)
    route(context_repo, domain)  # must not raise


def test_context_service_does_not_import_the_authority_service() -> None:
    import ast
    from pathlib import Path as P

    source = P(context_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        f"{node.module}.{alias.name}" if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        for alias in (node.names if isinstance(node, (ast.Import, ast.ImportFrom)) else [])
    }
    assert not any("authority" in name for name in imported)


# --- no document bodies / token bounding ---------------------------------------


def test_result_never_carries_document_bodies(context_repo: Path) -> None:
    result = route(context_repo, D.REPRESENTATIVE_GAMEPLAY)
    payload = result.model_dump_json()
    assert "Fixture RGF Contract\n" not in payload  # the fixture file's own H1 content
    assert len(payload) < 20_000


def test_the_result_names_the_validated_repository(context_repo: Path) -> None:
    result = route(context_repo, D.GAMEPLAY)
    assert result.repository == "HIWAGA"
    assert result.repository_root == str(context_repo.resolve())


def test_context_does_not_modify_the_repository(context_repo: Path) -> None:
    from .conftest import run_git

    before = run_git(context_repo, "status", "--porcelain=v1", "--untracked-files=all")
    for domain in ContextDomain:
        route(context_repo, domain)
    after = run_git(context_repo, "status", "--porcelain=v1", "--untracked-files=all")
    assert before == after == ""
