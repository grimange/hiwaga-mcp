"""The packaged domain→CANON-label routing mapping: strict parsing, and the packaged seed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import hiwaga_mcp
from hiwaga_mcp.errors import ContextRoutingError, ReasonCode
from hiwaga_mcp.models.context import ContextDomain
from hiwaga_mcp.services.context_routing import load_context_routing_mapping, parse_context_routing_mapping

from .conftest import fixture_context_routing_mapping


def _refused(mapping: Any, problem: str) -> ContextRoutingError:
    text = mapping if isinstance(mapping, str) else json.dumps(mapping)
    with pytest.raises(ContextRoutingError) as info:
        parse_context_routing_mapping(text)
    assert info.value.code is ReasonCode.CONTEXT_ROUTING_INVALID
    assert info.value.details["problem"] == problem
    return info.value


def _base() -> dict[str, Any]:
    """A minimal, fully-populated mapping: every domain present, none carrying labels."""
    return {"schema_version": 1, "domains": {d.value: {} for d in ContextDomain}}


# --- schema version ------------------------------------------------------------


def test_the_fixture_mapping_parses_and_is_typed() -> None:
    mapping = parse_context_routing_mapping(json.dumps(fixture_context_routing_mapping()))
    assert mapping.schema_version == 1
    routing = mapping.domains[ContextDomain.VERTICAL_SLICE]
    assert routing.canonical[0].label == "Vertical slice"
    assert routing.canonical[0].section == "42. Fixture Acceptance Gate"
    assert routing.historical[0].label == "Milestone evidence and ledger"


@pytest.mark.parametrize("version", [0, 2, 99, -1])
def test_unsupported_schema_version_is_refused(version: int) -> None:
    mapping = _base()
    mapping["schema_version"] = version
    error = _refused(mapping, "unsupported_schema_version")
    assert error.details["schema_version"] == version


@pytest.mark.parametrize("version", ['"1"', "true", "1.0", "null"])
def test_schema_version_must_be_an_integer(version: str) -> None:
    _refused(f'{{"schema_version": {version}, "domains": {{}}}}', "invalid_structure")


def test_missing_schema_version_is_refused() -> None:
    _refused('{"domains": {}}', "invalid_structure")


# --- JSON well-formedness -------------------------------------------------------


@pytest.mark.parametrize("text", ["", "{", "not json", '{"schema_version": 1,}', "[1,"])
def test_malformed_json_is_refused(text: str) -> None:
    _refused(text, "malformed_json")


@pytest.mark.parametrize("text", ["[]", '"x"', "1", "null"])
def test_non_object_top_level_is_refused(text: str) -> None:
    _refused(text, "not_an_object")


def test_duplicate_top_level_keys_are_refused() -> None:
    _refused('{"schema_version": 1, "schema_version": 1, "domains": {}}', "duplicate_keys")


def test_duplicate_domain_keys_are_refused() -> None:
    text = '{"schema_version": 1, "domains": {"PROJECT": {}, "PROJECT": {}}}'
    _refused(text, "duplicate_keys")


def test_duplicate_label_within_one_category_is_refused() -> None:
    mapping = _base()
    mapping["domains"]["GAMEPLAY"] = {"canonical": ["A", "A"]}
    _refused(mapping, "invalid_structure")


# --- structure -------------------------------------------------------------


def test_missing_domains_is_refused() -> None:
    _refused('{"schema_version": 1}', "invalid_structure")


@pytest.mark.parametrize("value", ["[]", '"x"', "null", "3"])
def test_non_object_domains_is_refused(value: str) -> None:
    _refused(f'{{"schema_version": 1, "domains": {value}}}', "invalid_structure")


def test_an_unknown_domain_key_is_refused() -> None:
    mapping = _base()
    mapping["domains"]["PLAYER"] = {}
    _refused(mapping, "invalid_structure")


@pytest.mark.parametrize("domain", ["gameplay", "Gameplay", "GENERAL", "OTHER", "AUTO", ""])
def test_case_or_vocabulary_variants_of_a_domain_are_refused(domain: str) -> None:
    mapping = _base()
    mapping["domains"][domain] = {}
    _refused(mapping, "invalid_structure")


@pytest.mark.parametrize("domain", [d.value for d in ContextDomain])
def test_a_missing_domain_entry_is_refused(domain: str) -> None:
    mapping = _base()
    del mapping["domains"][domain]
    error = _refused(mapping, "invalid_structure")
    assert domain in error.message


def test_an_empty_label_is_refused() -> None:
    mapping = _base()
    mapping["domains"]["GAMEPLAY"] = {"canonical": [""]}
    _refused(mapping, "invalid_structure")


@pytest.mark.parametrize("label", ["   ", "\t"])
def test_a_blank_label_is_refused(label: str) -> None:
    mapping = _base()
    mapping["domains"]["GAMEPLAY"] = {"canonical": [label]}
    _refused(mapping, "invalid_structure")


def test_a_label_repeated_across_categories_of_one_domain_is_refused() -> None:
    mapping = _base()
    mapping["domains"]["GAMEPLAY"] = {"canonical": ["Same label"], "supporting": ["Same label"]}
    _refused(mapping, "invalid_structure")


def test_the_same_label_may_appear_in_different_domains() -> None:
    mapping = _base()
    mapping["domains"]["GAMEPLAY"] = {"canonical": ["Shared label"]}
    mapping["domains"]["WORLD_LORE"] = {"canonical": ["Shared label"]}
    parsed = parse_context_routing_mapping(json.dumps(mapping))
    assert parsed.domains[ContextDomain.GAMEPLAY].canonical[0].label == "Shared label"
    assert parsed.domains[ContextDomain.WORLD_LORE].canonical[0].label == "Shared label"


def test_an_unknown_top_level_field_is_refused() -> None:
    mapping = _base()
    mapping["extra"] = True
    _refused(mapping, "invalid_structure")


def test_an_unknown_domain_routing_field_is_refused() -> None:
    mapping = _base()
    mapping["domains"]["GAMEPLAY"] = {"canonical": [], "prototype_a": []}
    _refused(mapping, "invalid_structure")


def test_an_unknown_label_ref_field_is_refused() -> None:
    mapping = _base()
    mapping["domains"]["VERTICAL_SLICE"] = {"canonical": [{"label": "X", "note": "extra"}]}
    _refused(mapping, "invalid_structure")


def test_a_blank_section_annotation_is_refused() -> None:
    mapping = _base()
    mapping["domains"]["VERTICAL_SLICE"] = {"canonical": [{"label": "X", "section": "   "}]}
    _refused(mapping, "invalid_structure")


def test_a_bare_string_and_an_object_form_are_both_accepted() -> None:
    mapping = _base()
    mapping["domains"]["VERTICAL_SLICE"] = {
        "canonical": ["Plain label", {"label": "Annotated label", "section": "9"}]
    }
    parsed = parse_context_routing_mapping(json.dumps(mapping))
    refs = parsed.domains[ContextDomain.VERTICAL_SLICE].canonical
    assert (refs[0].label, refs[0].section) == ("Plain label", None)
    assert (refs[1].label, refs[1].section) == ("Annotated label", "9")


def test_absent_categories_default_to_empty_lists() -> None:
    parsed = parse_context_routing_mapping(json.dumps(_base()))
    routing = parsed.domains[ContextDomain.PROJECT]
    assert routing.canonical == [] and routing.supporting == [] and routing.historical == []


# --- the packaged canonical mapping ------------------------------------------


def test_the_packaged_mapping_loads_and_is_valid() -> None:
    mapping = load_context_routing_mapping()
    assert mapping.schema_version == 1
    assert set(mapping.domains) == set(ContextDomain)


def test_the_packaged_mapping_file_is_where_the_loader_expects_it() -> None:
    assert (Path(hiwaga_mcp.__file__).parent / "policy/context_routing.json").is_file()


def test_the_packaged_mapping_routes_the_six_synced_representative_gameplay_documents() -> None:
    labels = {
        ref.label
        for ref in load_context_routing_mapping().domains[ContextDomain.REPRESENTATIVE_GAMEPLAY].supporting
    }
    for expected in (
        "Player V2 motion language",
        "Player V2 animation timing authority",
        "Player V2 motion acceptance matrix",
        "Animation pose-lab contract",
        "Representative player visual target",
        "Representative environment form target",
    ):
        assert expected in labels


def test_the_packaged_mapping_gives_vertical_slice_a_section_annotated_canonical_entry() -> None:
    routing = load_context_routing_mapping().domains[ContextDomain.VERTICAL_SLICE]
    assert routing.canonical[0].label == "Vertical slice"
    assert routing.canonical[0].section is not None and "111" in routing.canonical[0].section
    assert "Vertical-slice acceptance" not in {ref.label for ref in routing.canonical}


def test_the_packaged_mapping_does_not_route_evidence_directly_as_vertical_slice_canonical() -> None:
    routing = load_context_routing_mapping().domains[ContextDomain.VERTICAL_SLICE]
    canonical_labels = {ref.label for ref in routing.canonical}
    assert "Milestone evidence and ledger" not in canonical_labels
    assert "Milestone evidence and ledger" in {ref.label for ref in routing.historical}


@pytest.mark.parametrize(
    "domain",
    ["CORE_ARCHITECTURE", "PROGRESSION", "REPRESENTATIVE_GAMEPLAY", "ASSET_AUTHORITY", "VERIFICATION"],
)
def test_the_packaged_mapping_declares_no_canonical_labels_for_canonical_less_domains(domain: str) -> None:
    routing = load_context_routing_mapping().domains[ContextDomain(domain)]
    assert routing.canonical == []
