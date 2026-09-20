"""Asset-authority manifest: typed parsing and refusal of untrustworthy data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hiwaga_mcp.errors import AssetAuthorityError, ReasonCode, TargetOutsideRepositoryError
from hiwaga_mcp.services.authority import load_asset_manifest, parse_manifest

from .conftest import fixture_manifest, make_hiwaga_repo, write_manifest


def _parse(manifest: Any) -> Any:
    return parse_manifest(manifest if isinstance(manifest, str) else json.dumps(manifest))


def _refused(text: str, problem: str) -> AssetAuthorityError:
    with pytest.raises(AssetAuthorityError) as info:
        parse_manifest(text)
    assert info.value.code is ReasonCode.ASSET_AUTHORITY_INVALID
    assert info.value.details["problem"] == problem
    return info.value


def test_supported_schema_version_is_parsed_into_typed_entries() -> None:
    manifest = _parse(fixture_manifest())
    assert manifest.schema_version == 1
    assert set(manifest.assets) == {"old_thing", "solo", "fresh", "fresh_old"}
    old = manifest.assets["old_thing"]
    assert (old.status, old.visual_authority, old.authoring_reuse) == ("superseded", False, "reference_only")
    assert old.runtime_required_temporarily is False


@pytest.mark.parametrize("version", [0, 2, 99, -1])
def test_unsupported_schema_version_is_refused(version: int) -> None:
    error = _refused(json.dumps({"schema_version": version, "assets": {}}), "unsupported_schema_version")
    assert error.details["schema_version"] == version


@pytest.mark.parametrize("version", ['"1"', "true", "1.0", "null"])
def test_schema_version_must_be_an_integer(version: str) -> None:
    _refused(f'{{"schema_version": {version}, "assets": {{}}}}', "invalid_structure")


def test_missing_schema_version_is_refused() -> None:
    _refused('{"assets": {}}', "invalid_structure")


@pytest.mark.parametrize("text", ["", "{", "not json", '{"schema_version": 1,}', "[1,"])
def test_malformed_json_is_refused(text: str) -> None:
    _refused(text, "malformed_json")


@pytest.mark.parametrize("text", ["[]", '"text"', "1", "null"])
def test_non_object_top_level_is_refused(text: str) -> None:
    _refused(text, "not_an_object")


def test_missing_assets_is_refused() -> None:
    _refused('{"schema_version": 1}', "invalid_structure")


@pytest.mark.parametrize("assets", ["[]", '"x"', "null", "3"])
def test_non_object_assets_is_refused(assets: str) -> None:
    _refused(f'{{"schema_version": 1, "assets": {assets}}}', "invalid_structure")


@pytest.mark.parametrize("entry", ['"just a string"', "[]", "5", "null"])
def test_malformed_asset_entry_is_refused(entry: str) -> None:
    error = _refused(f'{{"schema_version": 1, "assets": {{"thing": {entry}}}}}', "invalid_structure")
    assert "thing" in error.message


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("visual_authority", "true"),
        ("visual_authority", 1),
        ("runtime_active", "yes"),
        ("runtime_required_temporarily", 0),
        ("status", 5),
        ("authoring_reuse", ["reference_only"]),
        ("source_path", 5),
        ("runtime_path", False),
        ("motion_proof_path", ["a"]),
        ("static_form_source", {"a": 1}),
        ("replacement", 3),
    ],
)
def test_wrongly_typed_known_fields_are_refused(field: str, value: Any) -> None:
    manifest = {"schema_version": 1, "assets": {"thing": {field: value}}}
    error = _refused(json.dumps(manifest), "invalid_structure")
    assert field in error.message


def test_optional_fields_may_all_be_absent() -> None:
    entry = _parse({"schema_version": 1, "assets": {"bare": {}}}).assets["bare"]
    assert entry.status is None and entry.visual_authority is None and entry.runtime_active is None
    assert entry.source_path is None and entry.runtime_path is None and entry.replacement is None


def test_an_empty_asset_registry_is_valid() -> None:
    assert _parse({"schema_version": 1, "assets": {}}).assets == {}


def test_unknown_additive_fields_are_tolerated_and_not_exposed() -> None:
    manifest = fixture_manifest()
    manifest["future_top_level"] = {"anything": True}
    manifest["assets"]["fresh"]["rig_bone_count"] = 19
    parsed = _parse(manifest)
    assert not hasattr(parsed.assets["fresh"], "rig_bone_count")
    assert parsed.assets["fresh"].status == "active_rebuild_target"


def test_duplicate_asset_ids_are_refused_not_last_one_wins() -> None:
    text = '{"schema_version": 1, "assets": {"a": {"status": "x"}, "a": {"status": "y"}}}'
    _refused(text, "duplicate_keys")


def test_duplicate_fields_inside_an_entry_are_refused() -> None:
    text = '{"schema_version": 1, "assets": {"a": {"status": "x", "status": "y"}}}'
    _refused(text, "duplicate_keys")


def test_empty_asset_id_is_refused() -> None:
    _refused('{"schema_version": 1, "assets": {" ": {}}}', "invalid_structure")


# --- loading from a repository ----------------------------------------------


def test_load_reads_the_repository_manifest(authority_repo: Path) -> None:
    assert "fresh" in load_asset_manifest(authority_repo).assets


def test_missing_manifest_is_refused(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga", omit=("art-source/ASSET_AUTHORITY.json",))
    with pytest.raises(AssetAuthorityError) as info:
        load_asset_manifest(root)
    assert info.value.details["problem"] == "missing"


def test_non_utf8_manifest_is_refused(authority_repo: Path) -> None:
    (authority_repo / "art-source/ASSET_AUTHORITY.json").write_bytes(b'{"schema_version": \xff}')
    with pytest.raises(AssetAuthorityError) as info:
        load_asset_manifest(authority_repo)
    assert info.value.details["problem"] == "not_utf8"


def test_utf8_bom_manifest_is_tolerated(authority_repo: Path) -> None:
    text = json.dumps(fixture_manifest()).encode("utf-8")
    (authority_repo / "art-source/ASSET_AUTHORITY.json").write_bytes(b"\xef\xbb\xbf" + text)
    assert "solo" in load_asset_manifest(authority_repo).assets


def test_manifest_symlinked_outside_the_repository_is_not_read(tmp_path: Path, outside_dir: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga", omit=("art-source/ASSET_AUTHORITY.json",))
    (outside_dir / "m.json").write_text(json.dumps(fixture_manifest()), encoding="utf-8")
    (root / "art-source").mkdir(parents=True, exist_ok=True)
    (root / "art-source/ASSET_AUTHORITY.json").symlink_to(outside_dir / "m.json")
    with pytest.raises(TargetOutsideRepositoryError):
        load_asset_manifest(root)


def test_write_manifest_helper_round_trips(authority_repo: Path) -> None:
    write_manifest(authority_repo, {"schema_version": 1, "assets": {}})
    assert load_asset_manifest(authority_repo).assets == {}
