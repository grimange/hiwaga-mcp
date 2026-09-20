"""`resolve_authority`: path-relation resolution, derived uses, and fail-closed manifest handling."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hiwaga_mcp.errors import (
    AssetAuthorityError,
    ReasonCode,
    RepositoryIdentityError,
    TargetOutsideRepositoryError,
)
from hiwaga_mcp.models.authority import AssetAuthorityEntry, AuthorityResolution, AuthorityUse
from hiwaga_mcp.services.authority import derive_uses, resolve_authority

from .conftest import fixture_manifest, make_hiwaga_repo, write_manifest

R = AuthorityResolution
U = AuthorityUse


def _write(root: Path, mutate: Any) -> None:
    manifest = fixture_manifest()
    mutate(manifest["assets"])
    write_manifest(root, manifest)


# --- resolution --------------------------------------------------------------


def test_exact_runtime_file_resolves(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "game/assets/solo/solo.glb")
    assert result.resolution is R.RESOLVED
    assert result.asset_id == "solo"
    assert result.matched_asset_ids == ["solo"]


def test_exact_source_file_resolves(authority_repo: Path) -> None:
    assert resolve_authority(authority_repo, "art-source/solo/solo.blend").asset_id == "solo"


def test_child_of_a_source_directory_resolves(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/fresh/deep/nested/file.blend")
    assert (result.resolution, result.asset_id) == (R.RESOLVED, "fresh")


def test_the_source_directory_itself_resolves(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/fresh")
    assert (result.resolution, result.asset_id) == (R.RESOLVED, "fresh")


def test_trailing_slash_and_dot_segments_are_normalized(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/./fresh//sub/")
    assert result.asset_id == "fresh"
    assert result.target == "art-source/./fresh//sub/"
    assert result.resolved_target == "art-source/fresh/sub"


def test_runtime_directory_children_resolve(authority_repo: Path) -> None:
    assert resolve_authority(authority_repo, "game/assets/old_thing_proof/x.glb").asset_id == "old_thing"


def test_separately_declared_proof_path_resolves(authority_repo: Path) -> None:
    assert resolve_authority(authority_repo, "game/proofs/fresh/field.tscn").asset_id == "fresh"


def test_source_relative_fields_resolve_against_source_path(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    # The asset's only declared `source_path` is a directory elsewhere; the relative fields
    # must be anchored to it, not to the repository root.
    write_manifest(
        root,
        {
            "schema_version": 1,
            "assets": {"a": {"source_path": "art-source/a", "motion_source": "m/motion.blend"}},
        },
    )
    assert resolve_authority(root, "art-source/a/m/motion.blend").asset_id == "a"
    assert resolve_authority(root, "m/motion.blend").resolution is R.UNRESOLVED


def test_target_need_not_exist(authority_repo: Path) -> None:
    assert not (authority_repo / "art-source/fresh").exists()
    assert resolve_authority(authority_repo, "art-source/fresh/never_created.blend").asset_id == "fresh"
    unowned = resolve_authority(authority_repo, "art-source/nowhere/never_created.blend")
    assert unowned.resolution is R.UNRESOLVED


def test_existing_and_missing_targets_resolve_identically(authority_repo: Path) -> None:
    (authority_repo / "art-source/fresh").mkdir(parents=True)
    (authority_repo / "art-source/fresh/real.blend").write_text("x", encoding="utf-8")
    real = resolve_authority(authority_repo, "art-source/fresh/real.blend")
    missing = resolve_authority(authority_repo, "art-source/fresh/absent.blend")
    assert (real.resolution, real.asset_id) == (missing.resolution, missing.asset_id)


def test_sibling_prefix_directory_does_not_match(authority_repo: Path) -> None:
    # `fresh` and `fresh_old` are distinct assets whose paths share a string prefix.
    assert resolve_authority(authority_repo, "art-source/fresh_old/x.blend").asset_id == "fresh_old"
    assert resolve_authority(authority_repo, "art-source/fresh/x.blend").asset_id == "fresh"
    assert resolve_authority(authority_repo, "art-source/fresh_older/x.blend").resolution is R.UNRESOLVED
    assert resolve_authority(authority_repo, "art-source/fres").resolution is R.UNRESOLVED
    assert resolve_authority(authority_repo, "art-source/fresh_x").resolution is R.UNRESOLVED


def test_declared_file_owns_only_itself_not_a_path_beneath_it(authority_repo: Path) -> None:
    glb = authority_repo / "game/assets/solo/solo.glb"
    glb.parent.mkdir(parents=True)
    glb.write_text("glb", encoding="utf-8")
    assert resolve_authority(authority_repo, "game/assets/solo/solo.glb").asset_id == "solo"
    assert resolve_authority(authority_repo, "game/assets/solo/solo.glb/inner").resolution is R.UNRESOLVED


def test_same_filename_elsewhere_does_not_match(authority_repo: Path) -> None:
    assert resolve_authority(authority_repo, "elsewhere/solo.glb").resolution is R.UNRESOLVED
    assert resolve_authority(authority_repo, "game/assets/solo.glb").resolution is R.UNRESOLVED


def test_names_alone_confer_no_authority(authority_repo: Path) -> None:
    for target in ("game/player_v2/x.blend", "docs/fresh.md", "art-source/rooter/fresh.blend"):
        assert resolve_authority(authority_repo, target).resolution is R.UNRESOLVED, target


def test_no_matching_asset_is_unresolved_not_an_error(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/unrelated/thing.blend")
    assert result.resolution is R.UNRESOLVED
    assert result.asset_id is None
    assert result.matched_asset_ids == []
    assert result.status is None and result.visual_authority is None and result.source_path is None
    assert result.allowed_uses == [] and result.forbidden_uses == []
    assert any("No asset" in note for note in result.limitations)


def test_repository_root_target_is_unresolved(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, ".")
    assert (result.resolution, result.resolved_target) == (R.UNRESOLVED, ".")


def test_multiple_owning_assets_are_a_conflict_with_no_winner(authority_repo: Path) -> None:
    _write(authority_repo, lambda assets: assets.update(zz_twin={"source_path": "art-source/fresh"}))
    result = resolve_authority(authority_repo, "art-source/fresh/x.blend")
    assert result.resolution is R.CONFLICT
    assert result.asset_id is None
    assert result.matched_asset_ids == ["fresh", "zz_twin"]
    assert result.status is None and result.source_path is None and result.runtime_path is None
    assert result.allowed_uses == [] and result.forbidden_uses == []
    assert any("fresh, zz_twin" in note for note in result.limitations)


def test_conflict_does_not_depend_on_manifest_order(authority_repo: Path) -> None:
    def reorder(assets: dict[str, Any]) -> None:
        twin = {"source_path": "art-source/fresh"}
        items = list(assets.items())
        assets.clear()
        assets["aa_twin"] = twin  # sorts and appears first, unlike the first test
        assets.update(items)

    _write(authority_repo, reorder)
    result = resolve_authority(authority_repo, "art-source/fresh/x.blend")
    assert (result.resolution, result.matched_asset_ids) == (R.CONFLICT, ["aa_twin", "fresh"])


def test_nested_declared_paths_of_different_assets_conflict(authority_repo: Path) -> None:
    # Ownership is not "most specific wins": a child asset inside a parent asset's tree is ambiguous.
    _write(authority_repo, lambda assets: assets.update(inner={"source_path": "art-source/fresh/inner"}))
    assert resolve_authority(authority_repo, "art-source/fresh/inner/a.blend").resolution is R.CONFLICT
    assert resolve_authority(authority_repo, "art-source/fresh/other/a.blend").asset_id == "fresh"


def test_one_asset_matching_through_several_paths_is_not_a_conflict(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/fresh/motion/fresh_motion.blend")
    assert (result.resolution, result.matched_asset_ids) == (R.RESOLVED, ["fresh"])


def test_manifest_key_is_the_identity_verbatim(authority_repo: Path) -> None:
    assert resolve_authority(authority_repo, "art-source/fresh/x").asset_id == "fresh"


# --- containment -------------------------------------------------------------


@pytest.mark.parametrize("target", ["../outside/secret.txt", "../../etc/passwd", "art-source/../../x"])
def test_traversal_is_rejected(authority_repo: Path, target: str) -> None:
    with pytest.raises(TargetOutsideRepositoryError) as info:
        resolve_authority(authority_repo, target)
    assert info.value.code is ReasonCode.TARGET_OUTSIDE_REPOSITORY


def test_external_absolute_path_is_rejected(authority_repo: Path, outside_dir: Path) -> None:
    with pytest.raises(TargetOutsideRepositoryError):
        resolve_authority(authority_repo, str(outside_dir / "secret.txt"))
    with pytest.raises(TargetOutsideRepositoryError):
        resolve_authority(authority_repo, "/etc/passwd")


def test_symlink_escape_is_rejected(authority_repo: Path, outside_dir: Path) -> None:
    (authority_repo / "art-source/escape").symlink_to(outside_dir)
    with pytest.raises(TargetOutsideRepositoryError):
        resolve_authority(authority_repo, "art-source/escape/secret.txt")


@pytest.mark.parametrize("target", ["", "   ", "a\x00b"])
def test_empty_and_null_byte_targets_are_rejected(authority_repo: Path, target: str) -> None:
    with pytest.raises(TargetOutsideRepositoryError):
        resolve_authority(authority_repo, target)


def test_absolute_path_inside_the_repository_is_accepted(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, str(authority_repo / "art-source/fresh/x.blend"))
    assert (result.asset_id, result.resolved_target) == ("fresh", "art-source/fresh/x.blend")


def test_tilde_is_a_literal_repository_relative_name(authority_repo: Path) -> None:
    assert resolve_authority(authority_repo, "~/art-source/fresh").resolution is R.UNRESOLVED


def test_in_repository_symlink_is_judged_by_its_canonical_path(authority_repo: Path) -> None:
    (authority_repo / "art-source/fresh").mkdir(parents=True)
    (authority_repo / "art-source/alias").symlink_to(authority_repo / "art-source/fresh")
    result = resolve_authority(authority_repo, "art-source/alias/f.blend")
    assert (result.asset_id, result.resolved_target) == ("fresh", "art-source/fresh/f.blend")


def test_invalid_identity_is_refused(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "partial", omit=("docs/CANON.md",))
    write_manifest(root, fixture_manifest())
    with pytest.raises(RepositoryIdentityError):
        resolve_authority(root, "art-source/fresh")


def test_the_result_names_the_validated_repository(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/fresh")
    assert result.repository == "HIWAGA"
    assert result.repository_root == str(authority_repo.resolve())


# --- machine-authority semantics (fixture-driven) ---------------------------


def test_superseded_reference_only_semantics_come_from_the_manifest(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/_superseded/old_thing/model.blend")
    assert result.asset_id == "old_thing"
    assert result.status == "superseded"
    assert result.visual_authority is False
    assert result.runtime_active is None
    assert result.runtime_required_temporarily is False
    assert result.authoring_reuse == "reference_only"
    assert result.creation_mode is None
    assert result.source_path == "art-source/_superseded/old_thing"
    assert result.runtime_path == "game/assets/old_thing_proof"
    assert result.allowed_uses == [U.HISTORICAL_REFERENCE, U.TECHNICAL_REFERENCE]
    assert result.forbidden_uses == [U.AUTHORING_DERIVATION]


def test_from_scratch_semantics_come_from_the_manifest(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/fresh/static.blend")
    assert result.status == "active_rebuild_target"
    assert result.creation_mode == "from_scratch"
    assert result.visual_authority is True
    assert result.runtime_active is True
    assert result.runtime_required_temporarily is False
    assert result.authoring_reuse is None
    assert result.allowed_uses == []
    assert result.forbidden_uses == [
        U.DUPLICATE_SUPERSEDED_SOURCE,
        U.LINK_SUPERSEDED_SOURCE,
        U.RESHAPE_SUPERSEDED_SOURCE,
        U.REUSE_SUPERSEDED_TOPOLOGY,
    ]


def test_status_strings_are_preserved_verbatim_and_derive_nothing(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/solo/solo.blend")
    assert result.status == "some_future_status"
    assert result.allowed_uses == [] and result.forbidden_uses == []


def test_absent_fields_are_null_not_defaulted(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/fresh_old/x")
    assert result.asset_id == "fresh_old"
    for name in (
        "status",
        "visual_authority",
        "runtime_active",
        "runtime_required_temporarily",
        "creation_mode",
        "authoring_reuse",
        "runtime_path",
        "replacement",
    ):
        assert getattr(result, name) is None, name
    assert result.allowed_uses == [] and result.forbidden_uses == []


def test_the_manifest_not_the_asset_name_drives_the_result(authority_repo: Path) -> None:
    # Same paths, different declared values: the result follows the file, not any hard-coded id.
    def flip(assets: dict[str, Any]) -> None:
        assets["old_thing"].update(status="active_representative", visual_authority=True)
        assets["old_thing"].pop("authoring_reuse")

    _write(authority_repo, flip)
    result = resolve_authority(authority_repo, "art-source/_superseded/old_thing/model.blend")
    assert (result.status, result.visual_authority, result.authoring_reuse) == (
        "active_representative",
        True,
        None,
    )
    assert result.allowed_uses == [] and result.forbidden_uses == []


def test_replacement_is_reported_verbatim_only_when_declared(authority_repo: Path) -> None:
    _write(authority_repo, lambda assets: assets["old_thing"].update(replacement="fresh"))
    assert resolve_authority(authority_repo, "art-source/_superseded/old_thing").replacement == "fresh"
    assert resolve_authority(authority_repo, "art-source/fresh").replacement is None


def test_the_result_states_what_it_does_not_consult(authority_repo: Path) -> None:
    result = resolve_authority(authority_repo, "art-source/fresh")
    assert any("not consulted" in note and "not a quality" in note for note in result.limitations)


# --- derived-use mapping -----------------------------------------------------


def _entry(**fields: Any) -> AssetAuthorityEntry:
    return AssetAuthorityEntry(**fields)


def test_no_explicit_field_means_no_derived_uses() -> None:
    assert derive_uses(_entry()) == ([], [])
    assert derive_uses(_entry(status="superseded", visual_authority=False)) == ([], [])


def test_unknown_reuse_and_creation_values_derive_nothing() -> None:
    assert derive_uses(_entry(authoring_reuse="free", creation_mode="adapted")) == ([], [])


def test_reference_only_derives_reference_uses_and_forbids_derivation() -> None:
    assert derive_uses(_entry(authoring_reuse="reference_only")) == (
        [U.HISTORICAL_REFERENCE, U.TECHNICAL_REFERENCE],
        [U.AUTHORING_DERIVATION],
    )


def test_from_scratch_forbids_superseded_reuse_and_allows_nothing() -> None:
    allowed, forbidden = derive_uses(_entry(creation_mode="from_scratch"))
    assert allowed == []
    assert forbidden == [
        U.DUPLICATE_SUPERSEDED_SOURCE,
        U.LINK_SUPERSEDED_SOURCE,
        U.RESHAPE_SUPERSEDED_SOURCE,
        U.REUSE_SUPERSEDED_TOPOLOGY,
    ]


def test_both_fields_combine_in_a_stable_order() -> None:
    allowed, forbidden = derive_uses(_entry(authoring_reuse="reference_only", creation_mode="from_scratch"))
    assert allowed == [U.HISTORICAL_REFERENCE, U.TECHNICAL_REFERENCE]
    assert forbidden == [
        U.AUTHORING_DERIVATION,
        U.DUPLICATE_SUPERSEDED_SOURCE,
        U.LINK_SUPERSEDED_SOURCE,
        U.RESHAPE_SUPERSEDED_SOURCE,
        U.REUSE_SUPERSEDED_TOPOLOGY,
    ]


# --- fail closed: the whole manifest must be trustworthy --------------------


def _refused(root: Path, target: str = "art-source/fresh") -> AssetAuthorityError:
    with pytest.raises(AssetAuthorityError) as info:
        resolve_authority(root, target)
    assert info.value.code is ReasonCode.ASSET_AUTHORITY_INVALID
    return info.value


def test_malformed_manifest_returns_no_partial_authority(authority_repo: Path) -> None:
    write_manifest(authority_repo, "{ not json")
    assert _refused(authority_repo).details["problem"] == "malformed_json"


def test_unsupported_version_is_refused(authority_repo: Path) -> None:
    write_manifest(authority_repo, {"schema_version": 2, "assets": {}})
    assert _refused(authority_repo).details["problem"] == "unsupported_schema_version"


def test_a_bad_entry_elsewhere_refuses_even_an_unrelated_target(authority_repo: Path) -> None:
    _write(authority_repo, lambda assets: assets.update(broken={"visual_authority": "true"}))
    assert _refused(authority_repo, "art-source/fresh/x").details["problem"] == "invalid_structure"


def test_the_placeholder_sentinel_manifest_is_refused(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")  # sentinel content is not JSON
    assert _refused(root).details["problem"] == "malformed_json"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_path", "/etc"),
        ("runtime_path", "../outside/thing.glb"),
        ("source_path", "art-source/../../out"),
        ("source_path", "."),
        ("runtime_path", ""),
        ("motion_proof_path", "   "),
    ],
)
def test_unusable_declared_paths_are_refused(authority_repo: Path, field: str, value: str) -> None:
    _write(authority_repo, lambda assets: assets.update(bad={field: value}))
    error = _refused(authority_repo)
    assert error.details["problem"] == "invalid_path"
    assert error.details["asset_id"] == "bad"
    assert error.details["field"] == field


def test_source_relative_field_without_a_source_path_is_refused(authority_repo: Path) -> None:
    _write(authority_repo, lambda assets: assets.update(bad={"motion_source": "m.blend"}))
    error = _refused(authority_repo)
    assert error.details["problem"] == "invalid_path" and error.details["field"] == "motion_source"


@pytest.mark.parametrize("value", ["../other/x.blend", "/abs/x.blend", "."])
def test_source_relative_field_must_stay_beneath_the_source_path(authority_repo: Path, value: str) -> None:
    _write(
        authority_repo,
        lambda assets: assets.update(bad={"source_path": "art-source/bad", "motion_source": value}),
    )
    assert _refused(authority_repo).details["field"] == "motion_source"


def test_source_relative_field_under_a_file_source_path_is_refused(authority_repo: Path) -> None:
    (authority_repo / "art-source").mkdir(exist_ok=True)
    (authority_repo / "art-source/only.blend").write_text("x", encoding="utf-8")
    _write(
        authority_repo,
        lambda assets: assets.update(
            bad={"source_path": "art-source/only.blend", "motion_source": "m.blend"}
        ),
    )
    assert _refused(authority_repo).details["field"] == "motion_source"


def test_declared_path_symlinked_outside_the_repository_is_refused(
    authority_repo: Path, outside_dir: Path
) -> None:
    (authority_repo / "art-source/leak").symlink_to(outside_dir)
    _write(authority_repo, lambda assets: assets.update(bad={"source_path": "art-source/leak"}))
    assert _refused(authority_repo).details["problem"] == "invalid_path"
