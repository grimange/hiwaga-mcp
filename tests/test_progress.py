"""Progress-ledger parser: pure text in, typed block out. No repository needed."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiwaga_mcp.errors import ProgressDocumentError, ReasonCode, TargetOutsideRepositoryError
from hiwaga_mcp.models.state import AmbiguityGate
from hiwaga_mcp.services.progress import (
    detect_operator_requirement,
    parse_current_block,
    read_current_progress_block,
)

from .conftest import VALID_PROGRESS, make_hiwaga_repo, write_progress


def _block(body: str, heading: str = "Current"):
    return parse_current_block(f"## {heading}\n\n{body}\n")


# --- block selection ---------------------------------------------------------


def test_first_h2_block_is_the_current_block() -> None:
    block = parse_current_block(VALID_PROGRESS)
    assert block.heading == "Current Block Title — 2026-09-20"
    assert block.phase == "REPRESENTATIVE_GAMEPLAY_PROTOTYPING."


def test_later_historical_blocks_do_not_contaminate_current_state() -> None:
    block = parse_current_block(VALID_PROGRESS)
    # The older block declares Status, TARGET_AMBIGUOUS, an OLD next step, and an
    # operator review; none of that may reach the current block.
    assert block.status is None
    assert block.ambiguity_gate is AmbiguityGate.TARGET_CLEAR
    assert block.next_bounded_step is not None and "OLD" not in block.next_bounded_step
    assert "OLD" not in (block.phase or "")
    assert block.operator_required is False


def test_heading_is_preserved_verbatim_without_its_marker() -> None:
    assert _block("- **Phase:** P", heading="Player V2 — Pose Lab P0 complete — 2026-09-20").heading == (
        "Player V2 — Pose Lab P0 complete — 2026-09-20"
    )


def test_closing_hashes_are_not_part_of_the_heading() -> None:
    assert parse_current_block("## Title ##\n- **Phase:** P\n").heading == "Title"


def test_preamble_before_the_first_h2_is_ignored() -> None:
    text = "# Ledger\n\nPhase: PREAMBLE_PHASE\n\n## Block\n- **Phase:** BLOCK_PHASE\n"
    assert parse_current_block(text).phase == "BLOCK_PHASE"


def test_h1_and_h3_do_not_start_or_end_the_current_block() -> None:
    text = "# H1\n## Block\n- **Phase:** P\n### Sub\n- **Status:** S\n## Next\n- **Status:** NOT_THIS\n"
    block = parse_current_block(text)
    assert block.heading == "Block"
    assert block.phase == "P"
    assert block.status == "S"


def test_h2_inside_a_code_fence_does_not_end_the_block() -> None:
    text = "## Block\n- **Phase:** P\n\n```\n## not a heading\n```\n\n- **Status:** S\n## Next\n"
    block = parse_current_block(text)
    assert block.heading == "Block"
    assert block.status == "S"


def test_empty_document_is_refused() -> None:
    for text in ("", "   \n\n\t\n"):
        with pytest.raises(ProgressDocumentError) as info:
            parse_current_block(text)
        assert info.value.code is ReasonCode.PROGRESS_DOCUMENT_INVALID
        assert info.value.details["problem"] == "empty"


def test_document_without_an_h2_has_no_current_block() -> None:
    with pytest.raises(ProgressDocumentError) as info:
        parse_current_block("# Title\n\nPhase: X\n### Not an H2\n")
    assert info.value.details["problem"] == "no_current_block"


# --- supported fields --------------------------------------------------------


def test_recognized_fields_are_parsed() -> None:
    block = parse_current_block(VALID_PROGRESS)
    assert block.current_focus is not None
    assert block.current_focus.startswith("`CURRENT_FOCUS_TOKEN__NEXT_READY`.")
    assert block.success_condition == "the route is followed unaided."
    assert block.next_bounded_step == "`NEXT_STEP_TOKEN` — implement it."


@pytest.mark.parametrize(
    "line",
    [
        "- **Phase:** VALUE",
        "* **Phase:** VALUE",
        "**Phase:** VALUE",
        "- **Phase**: VALUE",
        "Phase: VALUE",
        "- Phase: VALUE",
        "1. **Phase:** VALUE",
        "- **PHASE:**   VALUE  ",
    ],
)
def test_label_layouts_are_tolerated(line: str) -> None:
    assert _block(line).phase == "VALUE"


def test_plain_label_keeps_inline_markdown_in_the_value() -> None:
    block = _block("Phase: **HIWAGA CORE FOUNDATION** — `ACTIVE`")
    assert block.phase == "**HIWAGA CORE FOUNDATION** — `ACTIVE`"


def test_indented_wrapped_values_are_joined() -> None:
    block = _block("- **Design Question:** can the player\n  follow the route\n  from Home?\n- **Phase:** P")
    assert block.design_question == "can the player follow the route from Home?"
    assert block.phase == "P"


def test_lazy_wrapped_plain_values_are_joined() -> None:
    block = _block("Phase: first part\nsecond part\nStatus: S")
    assert block.phase == "first part second part"
    assert block.status == "S"


def test_value_starting_on_the_next_line_is_read() -> None:
    assert _block("- **Success Condition:**\n  the value is here").success_condition == "the value is here"


def test_blank_line_ends_a_wrapped_value() -> None:
    block = _block("- **Phase:** P\n  more\n\n  detached paragraph")
    assert block.phase == "P more"


def test_unknown_field_ends_a_wrapped_value_and_is_not_absorbed() -> None:
    block = _block("- **Phase:** P\n- **Authority:** something else\n- **Status:** S")
    assert block.phase == "P"
    assert block.status == "S"


def test_unindented_unknown_label_ends_a_plain_value() -> None:
    assert _block("Phase: P\nLast Corridor: SOMETHING").phase == "P"


def test_unknown_labels_and_prose_are_not_classified_as_state() -> None:
    block = _block(
        "Notes: Status: not a field\nThe next bounded step: is mentioned in prose.\n- **Evidence:** e"
    )
    assert block.status is None
    assert block.next_bounded_step is None


def test_missing_optional_fields_are_none() -> None:
    block = _block("- **Phase:** P")
    assert block.phase == "P"
    for name in (
        "current_focus",
        "status",
        "design_question",
        "player_goal",
        "success_condition",
        "ambiguity_gate",
        "next_bounded_step",
    ):
        assert getattr(block, name) is None, name
    assert block.operator_required is False


def test_block_with_no_supported_fields_is_reported_not_guessed() -> None:
    block = _block("Just prose about nothing in particular.")
    assert block.phase is None
    assert any("No supported progress fields" in note for note in block.limitations)


def test_first_declaration_of_a_repeated_field_wins_and_is_reported() -> None:
    block = _block("- **Phase:** FIRST\n- **Phase:** SECOND")
    assert block.phase == "FIRST"
    assert any("more than once" in note for note in block.limitations)


def test_crlf_line_endings_are_tolerated() -> None:
    block = parse_current_block("## Block\r\n- **Phase:** P\r\n- **Status:** S\r\n")
    assert (block.phase, block.status) == ("P", "S")


# --- combined labels: never split -------------------------------------------


def test_current_focus_status_is_one_unsplit_value() -> None:
    block = _block("- **Current Focus / Status:** `TOKEN__READY`. Ambiguity gate `TARGET_CLEAR`; more prose.")
    assert block.current_focus == "`TOKEN__READY`. Ambiguity gate `TARGET_CLEAR`; more prose."
    assert block.status is None
    assert any("Current Focus / Status" in note and "not split" in note for note in block.limitations)


def test_design_question_player_goal_is_one_unsplit_value() -> None:
    block = _block("- **Design Question / Player Goal:** can the player follow the route?")
    assert block.design_question == "can the player follow the route?"
    assert block.player_goal is None
    assert any("Design Question / Player Goal" in note for note in block.limitations)


def test_separately_declared_second_part_is_not_reported_as_unsplit() -> None:
    block = _block("- **Current Focus / Status:** COMBINED\n- **Status:** SEPARATE")
    assert block.current_focus == "COMBINED"
    assert block.status == "SEPARATE"
    assert not any("not split" in note for note in block.limitations)


def test_distinct_labels_populate_distinct_fields() -> None:
    block = _block("- **Current Focus:** F\n- **Status:** S\n- **Design Question:** Q\n- **Player Goal:** G")
    fields = (block.current_focus, block.status, block.design_question, block.player_goal)
    assert fields == ("F", "S", "Q", "G")
    assert block.limitations == ()


@pytest.mark.parametrize(
    "label",
    [
        "Next Bounded Step",
        "Next AI Goal / Next Bounded Step",
        "Next Bounded Step / Next Human Goal",
        "Next Human Goal / Next Bounded Step",
    ],
)
def test_next_step_label_family_reports_the_whole_value(label: str) -> None:
    assert _block(f"- **{label}:** THE VALUE").next_bounded_step == "THE VALUE"


def test_next_human_goal_alone_is_not_a_next_bounded_step() -> None:
    block = _block("- **Next Human Goal:** operator plays it")
    assert block.next_bounded_step is None
    assert block.next_human_goal == "operator plays it"


# --- ambiguity gate ----------------------------------------------------------


@pytest.mark.parametrize("gate", list(AmbiguityGate))
def test_each_established_gate_value_is_recognized(gate: AmbiguityGate) -> None:
    assert _block(f"- **Ambiguity Gate:** `{gate.value}`").ambiguity_gate is gate


def test_gate_label_is_case_insensitive_and_tolerates_trailing_prose() -> None:
    block = _block("- **Ambiguity gate:** `TARGET_PARTIALLY_CONSTRAINED`. Rooter precedent applies.")
    assert block.ambiguity_gate is AmbiguityGate.TARGET_PARTIALLY_CONSTRAINED


def test_absent_gate_is_none_never_target_clear() -> None:
    block = _block("- **Phase:** P")
    assert block.ambiguity_gate is None


@pytest.mark.parametrize("gate", list(AmbiguityGate))
def test_inline_only_canonical_token_is_recognized(gate: AmbiguityGate) -> None:
    block = _block(f"- **Current Focus / Status:** `X`. Ambiguity gate `{gate.value}`; more.")
    assert block.ambiguity_gate is gate
    assert not any("ambiguity" in note.lower() for note in block.limitations)


def test_inline_token_is_found_in_any_recognized_field() -> None:
    block = _block("- **Phase:** P\n- **Next Bounded Step:** gate is TARGET_PARTIALLY_CONSTRAINED here")
    assert block.ambiguity_gate is AmbiguityGate.TARGET_PARTIALLY_CONSTRAINED


def test_no_canonical_token_anywhere_is_none_without_a_note() -> None:
    block = _block("- **Current Focus / Status:** `X`. Clear target, partially constrained, ambiguous task.")
    assert block.ambiguity_gate is None
    assert not any("mbiguity" in note for note in block.limitations)


def test_gate_synonyms_and_near_tokens_are_not_gate_values() -> None:
    for text in ("target clear", "TARGET_CLEARLY", "target_clear", "XTARGET_AMBIGUOUS", "TARGET-CLEAR"):
        assert _block(f"- **Status:** {text}").ambiguity_gate is None, text


def test_repeated_identical_inline_token_is_not_a_conflict() -> None:
    block = _block("- **Status:** TARGET_CLEAR here\n- **Next Bounded Step:** TARGET_CLEAR, TARGET_CLEAR")
    assert block.ambiguity_gate is AmbiguityGate.TARGET_CLEAR
    assert not any("mbiguity" in note for note in block.limitations)


def test_conflicting_inline_tokens_are_none_with_a_limitation() -> None:
    block = _block("- **Status:** TARGET_CLEAR here\n- **Next Bounded Step:** but TARGET_AMBIGUOUS there")
    assert block.ambiguity_gate is None
    assert any(
        "several ambiguity gates" in note and "TARGET_AMBIGUOUS" in note and "TARGET_CLEAR" in note
        for note in block.limitations
    )


def test_explicit_gate_with_the_same_inline_token_uses_that_gate() -> None:
    block = _block("- **Ambiguity Gate:** TARGET_CLEAR\n- **Status:** ok, TARGET_CLEAR")
    assert block.ambiguity_gate is AmbiguityGate.TARGET_CLEAR
    assert not any("mbiguity" in note for note in block.limitations)


def test_explicit_gate_ignores_inline_text_that_is_not_a_canonical_token() -> None:
    block = _block("- **Ambiguity Gate:** TARGET_CLEAR\n- **Status:** the target is ambiguous")
    assert block.ambiguity_gate is AmbiguityGate.TARGET_CLEAR


def test_explicit_gate_with_a_conflicting_inline_token_is_none_with_a_limitation() -> None:
    block = _block("- **Ambiguity Gate:** TARGET_CLEAR\n- **Status:** but TARGET_AMBIGUOUS")
    assert block.ambiguity_gate is None
    assert any("declares TARGET_CLEAR" in note and "TARGET_AMBIGUOUS" in note for note in block.limitations)


def test_unrecognized_explicit_gate_is_not_rescued_by_an_inline_token() -> None:
    block = _block("- **Ambiguity Gate:** MAYBE\n- **Status:** TARGET_CLEAR")
    assert block.ambiguity_gate is None
    assert any("none of the recognized gate values" in note for note in block.limitations)


def test_historical_only_canonical_token_does_not_affect_the_current_gate() -> None:
    text = (
        "## Current\n- **Phase:** P\n\n"
        "## Older\n- **Ambiguity Gate:** TARGET_AMBIGUOUS\n- **Status:** TARGET_CLEAR"
    )
    block = parse_current_block(text)
    assert block.ambiguity_gate is None
    assert block.limitations == ()


def test_historical_token_cannot_conflict_with_the_current_explicit_gate() -> None:
    text = "## Current\n- **Ambiguity Gate:** TARGET_CLEAR\n\n## Older\n- **Status:** TARGET_AMBIGUOUS\n"
    block = parse_current_block(text)
    assert block.ambiguity_gate is AmbiguityGate.TARGET_CLEAR
    assert block.limitations == ()


def test_unrecognized_gate_value_is_none_and_reported() -> None:
    block = _block("- **Ambiguity Gate:** MAYBE_CLEAR")
    assert block.ambiguity_gate is None
    assert any("none of the recognized gate values" in note for note in block.limitations)


def test_conflicting_gate_values_are_none_and_reported() -> None:
    block = _block("- **Ambiguity Gate:** TARGET_CLEAR or TARGET_AMBIGUOUS")
    assert block.ambiguity_gate is None
    assert any("several gates" in note for note in block.limitations)


# --- operator requirement ----------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "`HIWAGA_X__OPERATOR_REVIEW_READY`",
        "operator review",
        "Human review of the outing",
        "human/operator review",
        "**ONE HUMAN/OPERATOR INTEGRATED OUTING**",
        "operator playtest",
        "Operator acceptance is pending",
        "OPERATOR VISUAL ACCEPTANCE PENDING",
        "one operator outing",
        # action-oriented forms
        "operator runs the native review",
        "Operator run the native review",
        "operator performs the integrated outing",
        "operator performs review of the build",
        "operator plays the verified proof",
        "Operator play the candidate",
        "human reviews the candidate",
        "human performs the focused review",
        "`STATE__READY`. Then the OPERATOR RUNS THE NATIVE REVIEW (states 03-08).",
    ],
)
def test_explicit_operator_wording_is_detected(text: str) -> None:
    assert detect_operator_requirement(text) is True


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "implement the prototype in Godot",
        "No operator action required first.",
        "No operator review is required.",
        "without operator acceptance",
        "operator review not required",
        "operator review is not needed",
        "The operator experientially accepted the outing.",
        "Whole motion remains NOT OPERATOR ACCEPTED.",
        "operatoring review",
        # negated / not-an-explicit-requirement forms
        "No human review is required.",
        "Operator action is not required.",
        "No operator action required before next step.",
        "Do not have the operator run the review.",
        "operator does not run the native review",
        # incidental words without an explicit human/operator subject + action
        "native review harness",
        "run the native review",
        "the player plays the build",
        "play test harness",
        "acceptance criteria are listed",
        "review the candidate",
        "reviews are automated",
        "operator facing review tool",
        "the human readable review report",
        "the operator ran the review",
        "human reviewed the candidate",
        "operators run things",
    ],
)
def test_absent_or_negated_operator_wording_is_not_detected(text: str | None) -> None:
    assert detect_operator_requirement(text) is False


def test_operator_required_comes_from_the_current_block_fields() -> None:
    assert _block("- **Next Bounded Step:** ONE operator playtest.").operator_required is True
    assert _block("- **Current Focus / Status:** `X__OPERATOR_REVIEW_READY`.").operator_required is True
    assert _block("- **Next Human Goal:** operator review of the build").operator_required is True


def test_operator_wording_outside_the_scanned_fields_is_ignored() -> None:
    block = _block("- **Evidence:** operator review happened\n- **Next Bounded Step:** implement it")
    assert block.operator_required is False


@pytest.mark.parametrize(
    "text",
    [
        "No automatic Astra run. Operator runs the native review.",
        "No project-level reassessment; operator plays the outing.",
        "Do not begin cutover, human reviews the candidate.",
        "No operator review required. Operator runs the native review.",
    ],
)
def test_negation_in_another_clause_does_not_suppress_a_positive_requirement(text: str) -> None:
    assert detect_operator_requirement(text) is True


def test_operator_action_in_next_bounded_step_and_status_is_detected_at_block_level() -> None:
    assert _block("- **Next Bounded Step:** operator runs the native review").operator_required is True
    assert _block("- **Status:** `X`. Human performs the focused review.").operator_required is True
    assert _block("- **Next Human Goal:** operator plays the verified proof").operator_required is True


def test_negated_operator_wording_at_block_level_stays_false_without_a_note() -> None:
    block = _block("- **Next Bounded Step:** implement it. No operator review required.")
    assert block.operator_required is False
    assert not any("contradictory" in note for note in block.limitations)


def test_contradictory_operator_wording_is_true_and_reported() -> None:
    block = _block(
        "- **Status:** No operator review required.\n"
        "- **Next Bounded Step:** operator runs the native review."
    )
    assert block.operator_required is True
    assert any("contradictory" in note for note in block.limitations)


def test_operator_action_wording_outside_the_scanned_fields_or_in_history_is_ignored() -> None:
    block = _block("- **Evidence:** operator runs the native review\n- **Next Bounded Step:** implement it")
    assert block.operator_required is False
    history = "## Current\n- **Phase:** P\n\n## Older\n- **Status:** operator runs the review\n"
    historical = parse_current_block(history)
    assert historical.operator_required is False


def test_operator_required_is_false_when_nothing_explicit_is_declared() -> None:
    assert parse_current_block(VALID_PROGRESS).operator_required is False


# --- reading from a repository ----------------------------------------------


def test_read_current_progress_block_reads_the_fixture_ledger(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    write_progress(root, VALID_PROGRESS)
    assert read_current_progress_block(root).heading == "Current Block Title — 2026-09-20"


def test_missing_ledger_is_refused(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga", omit=("docs/progress/HIWAGA_PROGRESS.md",))
    with pytest.raises(ProgressDocumentError) as info:
        read_current_progress_block(root)
    assert info.value.details["problem"] == "missing"


def test_non_utf8_ledger_is_refused(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    (root / "docs/progress/HIWAGA_PROGRESS.md").write_bytes(b"## Block\n\xff\xfe\n")
    with pytest.raises(ProgressDocumentError) as info:
        read_current_progress_block(root)
    assert info.value.details["problem"] == "not_utf8"


def test_ledger_symlinked_outside_the_repository_is_not_read(tmp_path: Path, outside_dir: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga", omit=("docs/progress/HIWAGA_PROGRESS.md",))
    (outside_dir / "secret.md").write_text("## Outside\n- **Phase:** LEAKED\n", encoding="utf-8")
    (root / "docs/progress").mkdir(parents=True)
    (root / "docs/progress/HIWAGA_PROGRESS.md").symlink_to(outside_dir / "secret.md")
    with pytest.raises(TargetOutsideRepositoryError):
        read_current_progress_block(root)


def test_utf8_bom_is_tolerated(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    (root / "docs/progress/HIWAGA_PROGRESS.md").write_bytes(b"\xef\xbb\xbf## Block\n- **Phase:** P\n")
    block = read_current_progress_block(root)
    assert (block.heading, block.phase) == ("Block", "P")
