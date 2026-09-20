"""CANON's bounded grammar: section discovery, `- Label: body` bullets, link extraction."""

from __future__ import annotations

import pytest

from hiwaga_mcp.errors import ContextRoutingError, ReasonCode
from hiwaga_mcp.models.context import SourceClassification
from hiwaga_mcp.services.context_routing import ROUTING_SECTIONS, parse_canon_document

CANONICAL = "## Canonical sources"
SUPPORTING = "## Supporting references"
HISTORICAL = "## Exploratory Prototype A — frozen findings and history"


def _minimal(
    canonical: str = "- A: [A](a.md)\n",
    supporting: str = "- B: [B](b.md)\n",
    historical: str = "- C: [C](c.md)\n",
) -> str:
    return f"{CANONICAL}\n\n{canonical}\n{SUPPORTING}\n\n{supporting}\n{HISTORICAL}\n\n{historical}\n"


def _refused(text: str, problem: str) -> ContextRoutingError:
    with pytest.raises(ContextRoutingError) as info:
        parse_canon_document(text)
    assert info.value.code is ReasonCode.CONTEXT_ROUTING_INVALID
    assert info.value.details["problem"] == problem
    return info.value


# --- section discovery --------------------------------------------------------


def test_all_three_known_routing_sections_are_parsed() -> None:
    doc = parse_canon_document(_minimal())
    assert set(doc.sections) == set(ROUTING_SECTIONS)
    assert [b.label for b in doc.sections["Canonical sources"]] == ["A"]
    assert [b.label for b in doc.sections["Supporting references"]] == ["B"]
    assert [b.label for b in doc.sections["Exploratory Prototype A — frozen findings and history"]] == ["C"]


def test_unknown_h2_sections_are_ignored() -> None:
    text = _minimal() + "\n## Historical and provisional material\n\n- Not routed: [x](x.md)\n"
    text += "\n## Current planning boundary\n\n- Also not routed: [y](y.md)\n"
    doc = parse_canon_document(text)
    assert set(doc.sections) == set(ROUTING_SECTIONS)


@pytest.mark.parametrize("missing_section", list(ROUTING_SECTIONS))
def test_a_missing_required_section_is_a_routing_error(missing_section: str) -> None:
    parts = {CANONICAL: "- A: [A](a.md)\n", SUPPORTING: "- B: [B](b.md)\n", HISTORICAL: "- C: [C](c.md)\n"}
    heading = f"## {missing_section}"
    text = "".join(f"{h}\n\n{body}\n" for h, body in parts.items() if h != heading)
    error = _refused(text, "missing_routing_section")
    assert missing_section in error.details["missing_sections"]


def test_a_renamed_required_section_is_a_routing_error() -> None:
    text = _minimal().replace(CANONICAL, "## Canon sources (renamed)")
    error = _refused(text, "missing_routing_section")
    assert "Canonical sources" in error.details["missing_sections"]


def test_a_duplicated_required_section_is_a_routing_error() -> None:
    text = _minimal() + f"\n{CANONICAL}\n\n- D: [D](d.md)\n"
    error = _refused(text, "duplicate_section")
    assert error.details["section"] == "Canonical sources"


def test_h1_and_h3_do_not_start_or_end_a_routing_section() -> None:
    text = (
        f"# Title\n{CANONICAL}\n\n- A: [A](a.md)\n### Sub\n- B: [B](b.md)\n"
        f"{SUPPORTING}\n\n- C: [C](c.md)\n{HISTORICAL}\n\n- D: [D](d.md)\n"
    )
    doc = parse_canon_document(text)
    labels = [b.label for b in doc.sections["Canonical sources"]]
    assert labels == ["A", "B"]


def test_an_empty_document_has_no_routing_sections() -> None:
    error = _refused("", "missing_routing_section")
    assert set(error.details["missing_sections"]) == set(ROUTING_SECTIONS)


# --- bullet grammar ------------------------------------------------------------


def test_label_extraction_splits_on_the_first_colon_space() -> None:
    doc = parse_canon_document(_minimal(canonical="- My Label: the rest: with a second colon\n"))
    bullet = doc.sections["Canonical sources"][0]
    assert bullet.label == "My Label"
    assert bullet.text == "My Label: the rest: with a second colon"


def test_a_line_without_a_leading_dash_space_is_not_a_bullet() -> None:
    text = _minimal(canonical="Just prose, not a bullet: [x](x.md)\n- A: [A](a.md)\n")
    doc = parse_canon_document(text)
    assert [b.label for b in doc.sections["Canonical sources"]] == ["A"]


def test_a_line_with_no_colon_space_is_not_a_bullet() -> None:
    text = _minimal(canonical="- no colon here at all\n- A: [A](a.md)\n")
    doc = parse_canon_document(text)
    assert [b.label for b in doc.sections["Canonical sources"]] == ["A"]


def test_prose_before_the_link_inside_a_bullet_body_is_tolerated() -> None:
    body = "- Vertical-slice acceptance: the acceptance gate in section 111. See [evidence](evidence/x/).\n"
    doc = parse_canon_document(_minimal(canonical=body))
    bullet = doc.sections["Canonical sources"][0]
    assert bullet.links == (("evidence", "evidence/x/"),)
    assert "the acceptance gate in section 111" in bullet.text


def test_multiple_links_in_one_bullet_preserve_document_order() -> None:
    body = "- Multi: the [first](a.md) then the [second](b.md) and the [third](c.md).\n"
    doc = parse_canon_document(_minimal(canonical=body))
    assert doc.sections["Canonical sources"][0].links == (
        ("first", "a.md"),
        ("second", "b.md"),
        ("third", "c.md"),
    )


def test_a_bullet_with_no_link_is_parsed_with_an_empty_link_tuple() -> None:
    doc = parse_canon_document(_minimal(canonical="- No link here: just prose.\n"))
    assert doc.sections["Canonical sources"][0].links == ()


def test_bullet_text_is_the_complete_label_and_body_verbatim() -> None:
    body = "- Core architecture: [Core](technical/core.md) — `FOUNDATION`. Subordinate to canon.\n"
    doc = parse_canon_document(_minimal(canonical=body))
    assert doc.sections["Canonical sources"][0].text == (
        "Core architecture: [Core](technical/core.md) — `FOUNDATION`. Subordinate to canon."
    )


# --- link target percent-decoding (extraction only; resolution is context.py's job) ---


@pytest.mark.parametrize(
    ("encoded", "decoded_fragment"),
    [
        ("HIWAGA%20Doc.md", "HIWAGA Doc.md"),
        ("HIWAGA%20%E2%80%94%20Doc.md", "HIWAGA — Doc.md"),
        ("Doc%2C%20Part%20Two.md", "Doc, Part Two.md"),
    ],
)
def test_percent_encoded_targets_are_extracted_raw_for_later_decoding(
    encoded: str, decoded_fragment: str
) -> None:
    from urllib.parse import unquote

    doc = parse_canon_document(_minimal(canonical=f"- Encoded: [Doc]({encoded})\n"))
    (raw_target,) = [target for _, target in doc.sections["Canonical sources"][0].links]
    assert raw_target == encoded
    assert unquote(raw_target) == decoded_fragment


# --- classification is derived from section membership only -------------------


def test_classification_comes_from_section_membership_not_from_bullet_prose() -> None:
    """A bullet under Canonical sources that reads SUPPORTING in its own prose is still CANONICAL."""
    body = "- Example: [Doc](doc.md) — SUPPORTING / directional / not canon.\n"
    doc = parse_canon_document(_minimal(canonical=body))
    bullet = doc.sections["Canonical sources"][0]
    # parse_canon_document does not itself assign classification (that is
    # context.py's job via ROUTING_SECTIONS); this proves the section->
    # classification table is fixed independently of any bullet's own prose.
    assert ROUTING_SECTIONS["Canonical sources"] is SourceClassification.CANONICAL
    assert "SUPPORTING" in bullet.text  # the contradictory prose survives verbatim
