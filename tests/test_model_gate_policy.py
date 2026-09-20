"""Canonical worker policy: strict typed parsing, the packaged seed, and packaging."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import hiwaga_mcp
from hiwaga_mcp.errors import ReasonCode, WorkerPolicyError
from hiwaga_mcp.models.model_gate import TaskClass
from hiwaga_mcp.services.model_gate import load_worker_policy, parse_worker_policy

from .conftest import fixture_worker_policy, worker_policy_text

REPO_ROOT = Path(__file__).resolve().parents[1]


def _refused(text: str, problem: str) -> WorkerPolicyError:
    with pytest.raises(WorkerPolicyError) as info:
        parse_worker_policy(text)
    assert info.value.code is ReasonCode.WORKER_POLICY_INVALID
    assert info.value.details["problem"] == problem
    return info.value


def _with_class(rule: Any, name: str = "BOUNDED_IMPLEMENTATION") -> str:
    return json.dumps({"schema_version": 1, "task_classes": {name: rule}})


def _ai(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"allowed": list(entries)}


# --- schema version ----------------------------------------------------------


def test_schema_version_1_is_accepted_and_typed() -> None:
    policy = parse_worker_policy(worker_policy_text())
    assert policy.schema_version == 1
    rule = policy.task_classes[TaskClass.BOUNDED_IMPLEMENTATION]
    assert rule.human_required is False
    assert rule.allowed[0].worker == "codex" and rule.allowed[0].models == ["model-A"]


@pytest.mark.parametrize("version", [0, 2, 99, -1])
def test_unsupported_schema_version_is_refused(version: int) -> None:
    error = _refused(
        json.dumps({"schema_version": version, "task_classes": {}}), "unsupported_schema_version"
    )
    assert error.details["schema_version"] == version


@pytest.mark.parametrize("version", ['"1"', "true", "1.0", "null"])
def test_schema_version_must_be_an_integer(version: str) -> None:
    _refused(f'{{"schema_version": {version}, "task_classes": {{}}}}', "invalid_structure")


def test_missing_schema_version_is_refused() -> None:
    _refused('{"task_classes": {}}', "invalid_structure")


# --- JSON well-formedness ----------------------------------------------------


@pytest.mark.parametrize("text", ["", "{", "not json", '{"schema_version": 1,}', "[1,"])
def test_malformed_json_is_refused(text: str) -> None:
    _refused(text, "malformed_json")


@pytest.mark.parametrize("text", ["[]", '"x"', "1", "null"])
def test_non_object_top_level_is_refused(text: str) -> None:
    _refused(text, "not_an_object")


@pytest.mark.parametrize(
    "text",
    [
        '{"schema_version": 1, "schema_version": 1, "task_classes": {}}',
        '{"schema_version": 1, "task_classes": {}, "task_classes": {}}',
        '{"schema_version": 1, "task_classes": {"OPERATOR_REVIEW": {"human_required": true},'
        ' "OPERATOR_REVIEW": {"human_required": true}}}',
        '{"schema_version": 1, "task_classes": {"OPERATOR_REVIEW": {"human_required": true,'
        ' "human_required": true}}}',
        '{"schema_version": 1, "task_classes": {"BOUNDED_IMPLEMENTATION": {"allowed":'
        ' [{"worker": "codex", "worker": "codex", "models": ["m"]}]}}}',
    ],
)
def test_duplicate_json_keys_are_refused_at_every_level(text: str) -> None:
    error = _refused(text, "duplicate_keys")
    assert "duplicate JSON keys" in error.message


# --- structure ---------------------------------------------------------------


def test_missing_task_classes_is_refused() -> None:
    _refused('{"schema_version": 1}', "invalid_structure")


@pytest.mark.parametrize("value", ["[]", '"x"', "null", "3"])
def test_non_object_task_classes_is_refused(value: str) -> None:
    _refused(f'{{"schema_version": 1, "task_classes": {value}}}', "invalid_structure")


def test_an_empty_task_class_map_is_a_valid_policy() -> None:
    assert parse_worker_policy('{"schema_version": 1, "task_classes": {}}').task_classes == {}


@pytest.mark.parametrize(
    "key",
    [
        "bounded_implementation",
        "GENERAL",
        "OTHER",
        "AUTO",
        "UNKNOWN",
        "",
        "BOUNDED-IMPLEMENTATION",
        " EVIDENCE_AUDIT",
    ],
)
def test_invalid_task_class_keys_are_refused(key: str) -> None:
    error = _refused(_with_class({"human_required": True}, key), "invalid_structure")
    assert "task_classes" in error.message


@pytest.mark.parametrize(
    "rule",
    [
        "just a string",
        [],
        None,
        5,
        {"human_required": "true"},
        {"human_required": 1},
        {"allowed": "codex"},
        {"allowed": ["codex"]},
        {"allowed": [{"worker": 5, "models": ["m"]}]},
        {"allowed": [{"worker": "codex", "models": "m"}]},
        {"allowed": [{"worker": "codex", "models": [5]}]},
        {"allowed": [{"worker": "codex"}]},
        {"allowed": [{"models": ["m"]}]},
    ],
)
def test_malformed_rules_are_refused(rule: Any) -> None:
    _refused(_with_class(rule), "invalid_structure")


# --- the two rule kinds ------------------------------------------------------


def test_a_human_required_rule_is_accepted() -> None:
    rule = parse_worker_policy(_with_class({"human_required": True}, "OPERATOR_REVIEW")).task_classes[
        TaskClass.OPERATOR_REVIEW
    ]
    assert rule.human_required is True and rule.allowed == []


def test_an_ai_allowed_rule_with_several_workers_is_accepted() -> None:
    rule = parse_worker_policy(worker_policy_text()).task_classes[TaskClass.EVIDENCE_AUDIT]
    assert [(e.worker, e.models) for e in rule.allowed] == [
        ("codex", ["model-A", "model-B"]),
        ("claude-code", ["model-C"]),
    ]


def test_explicit_human_required_false_with_allowed_workers_is_accepted() -> None:
    rule = _with_class({"human_required": False, "allowed": [{"worker": "codex", "models": ["m"]}]})
    assert parse_worker_policy(rule).task_classes[TaskClass.BOUNDED_IMPLEMENTATION].human_required is False


def test_human_required_together_with_allowed_workers_is_refused() -> None:
    rule = {"human_required": True, "allowed": [{"worker": "codex", "models": ["m"]}]}
    error = _refused(_with_class(rule), "invalid_structure")
    assert "human_required" in error.message


@pytest.mark.parametrize(
    "rule", [{}, {"human_required": False}, {"allowed": []}, {"human_required": False, "allowed": []}]
)
def test_a_rule_that_establishes_nothing_is_refused(rule: dict[str, Any]) -> None:
    error = _refused(_with_class(rule), "invalid_structure")
    assert "omit the class" in error.message


# --- worker and model strings ------------------------------------------------


@pytest.mark.parametrize("worker", ["", "   ", "\t"])
def test_empty_worker_is_refused(worker: str) -> None:
    _refused(_with_class(_ai({"worker": worker, "models": ["m"]})), "invalid_structure")


@pytest.mark.parametrize("model", ["", "   ", "\n"])
def test_empty_model_is_refused(model: str) -> None:
    _refused(_with_class(_ai({"worker": "codex", "models": [model]})), "invalid_structure")


def test_an_empty_model_list_is_refused() -> None:
    _refused(_with_class(_ai({"worker": "codex", "models": []})), "invalid_structure")


@pytest.mark.parametrize("worker", [" codex", "codex ", "Codex", "CLAUDE-CODE"])
def test_workers_must_be_canonical_lowercase_and_trimmed(worker: str) -> None:
    _refused(_with_class(_ai({"worker": worker, "models": ["m"]})), "invalid_structure")


@pytest.mark.parametrize("model", [" model-A", "model-A ", "\tmodel-A"])
def test_models_must_be_trimmed(model: str) -> None:
    _refused(_with_class(_ai({"worker": "codex", "models": [model]})), "invalid_structure")


def test_model_ids_keep_their_case() -> None:
    policy = parse_worker_policy(_with_class(_ai({"worker": "codex", "models": ["Model-A", "model-a"]})))
    assert policy.task_classes[TaskClass.BOUNDED_IMPLEMENTATION].allowed[0].models == ["Model-A", "model-a"]


# --- duplicate / contradictory entries --------------------------------------


def test_the_same_worker_listed_twice_in_a_class_is_refused_even_when_identical() -> None:
    for models in (["m"], ["other"]):
        rule = _ai({"worker": "codex", "models": ["m"]}, {"worker": "codex", "models": models})
        error = _refused(_with_class(rule), "invalid_structure")
        assert "same worker more than once" in error.message


def test_a_repeated_model_within_one_worker_entry_is_refused() -> None:
    error = _refused(_with_class(_ai({"worker": "codex", "models": ["m", "m"]})), "invalid_structure")
    assert "repeat" in error.message


# --- unknown keys are refused, not ignored ----------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(denied=[]),
        lambda p: p.update(cost_warning={"enabled": True}),
        lambda p: p.update({"$schema": "x"}),
        lambda p: p["task_classes"]["BOUNDED_IMPLEMENTATION"].update(denied_models=["m"]),
        lambda p: p["task_classes"]["BOUNDED_IMPLEMENTATION"].update(reasoning_effort="medium"),
        lambda p: p["task_classes"]["BOUNDED_IMPLEMENTATION"]["allowed"][0].update(effort="high"),
        lambda p: p["task_classes"]["OPERATOR_REVIEW"].update(note="x"),
    ],
)
def test_unknown_keys_are_refused_because_an_ignored_key_could_change_who_is_authorized(
    mutate: Any,
) -> None:
    policy = fixture_worker_policy()
    mutate(policy)
    _refused(json.dumps(policy), "invalid_structure")


# --- the packaged canonical policy ------------------------------------------

SEEDED = {
    "EVIDENCE_AUDIT": {"codex": ["gpt-5.6-sol"]},
    "BOUNDED_IMPLEMENTATION": {"codex": ["gpt-5.6-luna", "gpt-5.6-sol"]},
    "EXECUTION_BOUNDARY_CHANGE": {"codex": ["gpt-5.6-sol"]},
    "RELEASE_REVIEW": {"codex": ["gpt-5.6-luna", "gpt-5.6-sol"]},
}


def test_the_packaged_policy_loads_and_is_valid() -> None:
    policy = load_worker_policy()
    assert policy.schema_version == 1


def test_the_packaged_policy_seeds_exactly_the_established_rules() -> None:
    policy = load_worker_policy()
    ai = {
        cls.value: {entry.worker: entry.models for entry in rule.allowed}
        for cls, rule in policy.task_classes.items()
        if not rule.human_required
    }
    assert ai == SEEDED


def test_operator_review_is_human_required_in_the_packaged_policy() -> None:
    rule = load_worker_policy().task_classes[TaskClass.OPERATOR_REVIEW]
    assert rule.human_required is True and rule.allowed == []


def test_task_classes_without_established_routing_are_left_undefined() -> None:
    defined = set(load_worker_policy().task_classes)
    assert TaskClass.BUG_DIAGNOSIS not in defined
    assert TaskClass.HIGH_COMPLEXITY_CONVERGENCE not in defined


def test_no_claude_routing_or_denied_model_is_invented_in_the_packaged_policy() -> None:
    text = (Path(hiwaga_mcp.__file__).parent / "policy/worker_policy.json").read_text(encoding="utf-8")
    assert "claude" not in text.lower()
    assert "astra" not in text.lower()
    assert "effort" not in text.lower() and "cost" not in text.lower()


def test_the_packaged_policy_file_is_where_the_loader_expects_it() -> None:
    assert (Path(hiwaga_mcp.__file__).parent / "policy/worker_policy.json").is_file()


def test_the_task_class_vocabulary_is_exactly_the_p0_set() -> None:
    assert {c.value for c in TaskClass} == {
        "EVIDENCE_AUDIT",
        "BUG_DIAGNOSIS",
        "BOUNDED_IMPLEMENTATION",
        "EXECUTION_BOUNDARY_CHANGE",
        "RELEASE_REVIEW",
        "HIGH_COMPLEXITY_CONVERGENCE",
        "OPERATOR_REVIEW",
    }


def test_packaging_declares_the_policy_as_package_data() -> None:
    """The JSON must be declared as package data so an installed (non-editable) copy still has it.

    A real wheel build needs setuptools, which this environment's virtualenv does not carry, so the
    declaration is checked statically and the built wheel is proven separately by hand.
    """
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    table = pyproject.split("[tool.setuptools.package-data]", 1)
    assert len(table) == 2, "pyproject.toml must declare [tool.setuptools.package-data]"
    section = table[1].split("\n[", 1)[0]
    assert re.search(r'hiwaga_mcp\s*=\s*\[[^\]]*"policy/\*\.json"', section)
    matched = sorted((REPO_ROOT / "src/hiwaga_mcp").glob("policy/*.json"))
    assert [path.name for path in matched] == ["worker_policy.json"]
