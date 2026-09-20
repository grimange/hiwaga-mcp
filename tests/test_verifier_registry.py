"""The verifier registry is the execution allowlist, so it is trusted wholly or not at all."""

from __future__ import annotations

import json
from typing import Any

import pytest

from hiwaga_mcp.errors import (
    ReasonCode,
    UnknownVerifierError,
    UnsupportedVerifyModeError,
    VerifierRegistryError,
)
from hiwaga_mcp.models.verification import ProofClass
from hiwaga_mcp.models.verification_registry import ExecutableStrategy
from hiwaga_mcp.services.verification_registry import (
    REGISTRY_RESOURCE,
    load_verifier_registry,
    parse_verifier_registry,
    select_verifier,
)

from .conftest import fixture_registry, registry_text


def _registry(**changes: Any) -> dict[str, Any]:
    base = fixture_registry()
    base["verifiers"]["structural"].update(changes)
    return base


def _parse(registry: dict[str, Any] | str) -> Any:
    return parse_verifier_registry(registry if isinstance(registry, str) else json.dumps(registry))


def _rejects(registry: dict[str, Any] | str, problem: str | None = None) -> VerifierRegistryError:
    with pytest.raises(VerifierRegistryError) as excinfo:
        _parse(registry)
    assert excinfo.value.code is ReasonCode.VERIFIER_REGISTRY_INVALID
    if problem is not None:
        assert excinfo.value.details["problem"] == problem
    return excinfo.value


# --- schema acceptance -------------------------------------------------------


def test_supported_schema_is_accepted() -> None:
    registry = _parse(fixture_registry())
    assert registry.schema_version == 1
    assert set(registry.verifiers) == {"structural", "failing", "slow", "noisy", "spawner"}


def test_definition_fields_are_typed() -> None:
    definition = _parse(fixture_registry()).verifiers["structural"]
    assert definition.proof_class is ProofClass.STRUCTURAL
    assert definition.executable is ExecutableStrategy.REPO_PYTHON
    assert definition.timeout_seconds == 30
    assert definition.default_mode == "default"


@pytest.mark.parametrize("version", [0, 2, 99, -1, "1", 1.0, True, None])
def test_unsupported_schema_version_is_rejected(version: Any) -> None:
    registry = fixture_registry()
    registry["schema_version"] = version
    _rejects(registry)


def test_missing_schema_version_is_rejected() -> None:
    registry = fixture_registry()
    del registry["schema_version"]
    _rejects(registry, "invalid_structure")


# --- structural rejection ----------------------------------------------------


def test_malformed_json_is_rejected() -> None:
    _rejects("{not json", "malformed_json")


def test_duplicate_json_keys_are_rejected() -> None:
    """An ambiguous registry is never resolved by last-wins."""
    text = '{"schema_version": 1, "verifiers": {}, "verifiers": {"x": {}}}'
    error = _rejects(text, "duplicate_keys")
    assert "verifiers" in error.message


def test_duplicate_nested_keys_are_rejected() -> None:
    text = json.dumps(fixture_registry()).replace(
        '"timeout_seconds": 30', '"timeout_seconds": 30, "timeout_seconds": 9999', 1
    )
    _rejects(text, "duplicate_keys")


@pytest.mark.parametrize("payload", ["[]", '"text"', "12", "null"])
def test_non_object_registry_is_rejected(payload: str) -> None:
    _rejects(payload, "not_an_object")


def test_missing_verifiers_map_is_rejected() -> None:
    _rejects({"schema_version": 1}, "invalid_structure")


@pytest.mark.parametrize("verifiers", [[], "none", 3, None])
def test_non_object_verifiers_map_is_rejected(verifiers: Any) -> None:
    _rejects({"schema_version": 1, "verifiers": verifiers}, "invalid_structure")


def test_empty_verifier_id_is_rejected() -> None:
    registry = fixture_registry()
    registry["verifiers"]["   "] = registry["verifiers"]["structural"]
    _rejects(registry, "invalid_structure")


def test_empty_registry_is_accepted() -> None:
    """No verifiers is a coherent allowlist: it permits nothing."""
    assert _parse({"schema_version": 1, "verifiers": {}}).verifiers == {}


# --- verifier definition rejection -------------------------------------------


def test_malformed_verifier_is_rejected() -> None:
    _rejects({"schema_version": 1, "verifiers": {"broken": "not-an-object"}}, "invalid_structure")


def test_unknown_proof_class_is_rejected() -> None:
    _rejects(_registry(proof_class="VIBES"), "invalid_structure")


def test_proof_class_is_required() -> None:
    registry = fixture_registry()
    del registry["verifiers"]["structural"]["proof_class"]
    _rejects(registry, "invalid_structure")


def test_unsupported_executable_strategy_is_rejected() -> None:
    _rejects(_registry(executable="/bin/sh"), "invalid_structure")
    _rejects(_registry(executable="SYSTEM_PYTHON"), "invalid_structure")


@pytest.mark.parametrize("timeout", [0, -1, -600, "30", 1.5, None, True])
def test_non_positive_or_non_integer_timeout_is_rejected(timeout: Any) -> None:
    _rejects(_registry(timeout_seconds=timeout), "invalid_structure")


def test_missing_timeout_is_rejected() -> None:
    registry = fixture_registry()
    del registry["verifiers"]["structural"]["timeout_seconds"]
    _rejects(registry, "invalid_structure")


def test_empty_mode_map_is_rejected() -> None:
    _rejects(_registry(modes={}), "invalid_structure")


def test_missing_mode_map_is_rejected() -> None:
    registry = fixture_registry()
    del registry["verifiers"]["structural"]["modes"]
    _rejects(registry, "invalid_structure")


def test_empty_mode_name_is_rejected() -> None:
    _rejects(_registry(modes={"  ": {"args": []}}), "invalid_structure")


def test_malformed_mode_is_rejected() -> None:
    _rejects(_registry(modes={"default": "not-an-object"}), "invalid_structure")


def test_undeclared_default_mode_is_rejected() -> None:
    _rejects(_registry(default_mode="nonexistent"), "invalid_structure")


def test_non_string_mode_args_are_rejected() -> None:
    _rejects(_registry(modes={"default": {"args": [1, 2]}}), "invalid_structure")


# --- path containment at schema level ----------------------------------------


@pytest.mark.parametrize(
    "script",
    [
        "/etc/passwd",
        "/usr/bin/python",
        "~/evil.py",
        "../outside.py",
        "tools/../../outside.py",
        "",
        "   ",
    ],
)
def test_escaping_or_absolute_script_is_rejected(script: str) -> None:
    _rejects(_registry(script=script), "invalid_structure")


@pytest.mark.parametrize("working_directory", ["/tmp", "../elsewhere", "~/somewhere", "a/../../b", ""])
def test_escaping_working_directory_is_rejected(working_directory: str) -> None:
    _rejects(_registry(working_directory=working_directory), "invalid_structure")


def test_null_byte_in_script_is_rejected() -> None:
    _rejects(_registry(script="tools/ev\x00il.py"), "invalid_structure")


def test_contained_nested_script_is_accepted() -> None:
    assert _parse(_registry(script="tools/rgf/deep/verify.py")).verifiers["structural"].script


# --- unknown fields ----------------------------------------------------------


def test_unknown_verifier_field_is_rejected() -> None:
    """An unmodelled key is exactly where an execution-relevant setting would hide."""
    _rejects(_registry(shell=True), "invalid_structure")
    _rejects(_registry(command="rm -rf /"), "invalid_structure")
    _rejects(_registry(args=["--unsafe"]), "invalid_structure")


def test_unknown_top_level_field_is_rejected() -> None:
    registry = fixture_registry()
    registry["allow_arbitrary_commands"] = True
    _rejects(registry, "invalid_structure")


def test_unknown_mode_field_is_rejected() -> None:
    _rejects(_registry(modes={"default": {"args": [], "shell": True}}), "invalid_structure")


# --- argument placeholders ---------------------------------------------------


def test_run_directory_placeholder_is_accepted() -> None:
    registry = _parse(_registry(modes={"default": {"args": ["--out", "{run_directory}"]}}))
    assert registry.verifiers["structural"].modes["default"].args == ["--out", "{run_directory}"]


@pytest.mark.parametrize("arg", ["{repo_root}", "{home}", "{run_directory_evil}", "prefix{x}suffix"])
def test_unsupported_placeholder_is_rejected(arg: str) -> None:
    _rejects(_registry(modes={"default": {"args": [arg]}}), "invalid_structure")


def test_null_byte_in_argument_is_rejected() -> None:
    _rejects(_registry(modes={"default": {"args": ["--flag\x00"]}}), "invalid_structure")


# --- registry-defined environment --------------------------------------------


def test_static_registry_environment_is_accepted() -> None:
    registry = _parse(_registry(environment={"HIWAGA_FIXTURE": "1"}))
    assert registry.verifiers["structural"].environment == {"HIWAGA_FIXTURE": "1"}


@pytest.mark.parametrize("environment", [{"NAME": 1}, {"NAME": None}, {"": "x"}, ["NAME=1"]])
def test_non_static_registry_environment_is_rejected(environment: Any) -> None:
    _rejects(_registry(environment=environment), "invalid_structure")


# --- the packaged registry ---------------------------------------------------


def test_packaged_registry_exists_and_is_valid() -> None:
    registry = load_verifier_registry()
    assert registry.schema_version == 1
    assert registry.verifiers, "the packaged registry seeds at least one verifier"


def test_packaged_registry_seeds_the_expected_verifiers() -> None:
    registry = load_verifier_registry()
    assert set(registry.verifiers) == {"asset_authority", "player_v2_motion_review"}


def test_packaged_registry_uses_only_closed_executable_strategies() -> None:
    for definition in load_verifier_registry().verifiers.values():
        assert isinstance(definition.executable, ExecutableStrategy)
        assert definition.timeout_seconds > 0
        assert definition.modes


def test_packaged_registry_declares_distinct_proof_classes() -> None:
    classes = {d.proof_class for d in load_verifier_registry().verifiers.values()}
    assert ProofClass.STRUCTURAL in classes
    assert ProofClass.HEADLESS in classes


def test_packaged_registry_contains_no_shell_fragments() -> None:
    """A registry entry requiring shell syntax would be invalid for P0."""
    for definition in load_verifier_registry().verifiers.values():
        for mode in definition.modes.values():
            for arg in mode.args:
                assert not any(token in arg for token in ("|", ";", "&&", "$(", "`", ">", "<"))


def test_registry_resource_path_is_stable() -> None:
    assert REGISTRY_RESOURCE == "policy/verifier_registry.json"


def test_explicit_text_overrides_the_packaged_registry() -> None:
    assert set(load_verifier_registry(registry_text()).verifiers) == {
        "structural",
        "failing",
        "slow",
        "noisy",
        "spawner",
    }


# --- selection ---------------------------------------------------------------


def test_known_verifier_and_mode_are_selected() -> None:
    registry = _parse(fixture_registry())
    verifier_id, definition, mode_name, mode = select_verifier(registry, "structural", "default")
    assert verifier_id == "structural"
    assert mode_name == "default"
    assert definition.proof_class is ProofClass.STRUCTURAL
    assert mode.args == []


def test_omitted_mode_uses_the_registry_default() -> None:
    registry = _parse(fixture_registry())
    _, _, mode_name, _ = select_verifier(registry, "structural", None)
    assert mode_name == "default"


def test_omitted_mode_without_a_default_is_rejected() -> None:
    registry = _parse(_registry(default_mode=None))
    with pytest.raises(UnsupportedVerifyModeError) as excinfo:
        select_verifier(registry, "structural", None)
    assert excinfo.value.code is ReasonCode.UNSUPPORTED_VERIFY_MODE


def test_unknown_verifier_is_an_invalid_request() -> None:
    registry = _parse(fixture_registry())
    with pytest.raises(UnknownVerifierError) as excinfo:
        select_verifier(registry, "does-not-exist", "default")
    assert excinfo.value.code is ReasonCode.UNKNOWN_VERIFIER
    assert "structural" in excinfo.value.details["registered_verifiers"]


def test_unsupported_mode_is_an_invalid_request() -> None:
    registry = _parse(fixture_registry())
    with pytest.raises(UnsupportedVerifyModeError) as excinfo:
        select_verifier(registry, "structural", "native")
    assert excinfo.value.code is ReasonCode.UNSUPPORTED_VERIFY_MODE
    assert excinfo.value.details["supported_modes"] == ["default", "with_output"]


def test_selection_is_not_fuzzy() -> None:
    """No case folding, prefix matching, or nearest-neighbour fallback."""
    registry = _parse(fixture_registry())
    for name in ("STRUCTURAL", "Structural", "struct"):
        with pytest.raises(UnknownVerifierError):
            select_verifier(registry, name, "default")
    with pytest.raises(UnsupportedVerifyModeError):
        select_verifier(registry, "structural", "DEFAULT")


def test_surrounding_whitespace_in_selection_is_tolerated() -> None:
    registry = _parse(fixture_registry())
    verifier_id, _, mode_name, _ = select_verifier(registry, "  structural  ", "  default  ")
    assert (verifier_id, mode_name) == ("structural", "default")
