"""`hiwaga_authority` over the real in-memory MCP client path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import Client

from hiwaga_mcp.config import ServerConfig
from hiwaga_mcp.errors import ReasonCode
from hiwaga_mcp.server import build_server

from .conftest import fixture_manifest, make_hiwaga_repo, write_manifest

TOOL = "hiwaga_authority"

OUTPUT_FIELDS = {
    "repository",
    "repository_root",
    "target",
    "resolved_target",
    "resolution",
    "asset_id",
    "matched_asset_ids",
    "status",
    "visual_authority",
    "runtime_active",
    "runtime_required_temporarily",
    "creation_mode",
    "authoring_reuse",
    "source_path",
    "runtime_path",
    "allowed_uses",
    "forbidden_uses",
    "replacement",
    "limitations",
}


def _run(async_fn: Any) -> Any:
    return anyio.run(async_fn)


def _text(result: Any) -> str:
    return " ".join(block.text for block in result.content)


def _server(root: Path) -> Any:
    return build_server(config=ServerConfig(repo_root=root))


def test_tool_is_registered_with_a_single_required_target_and_a_structured_schema(
    authority_repo: Path,
) -> None:
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == TOOL)
            assert set(tool.input_schema["properties"]) == {"target"}
            assert tool.input_schema["required"] == ["target"]
            schema = tool.output_schema
            assert schema is not None and schema["type"] == "object"
            assert set(schema["required"]) == OUTPUT_FIELDS
            assert set(schema["properties"]) == OUTPUT_FIELDS

    _run(body)


def test_resolved_target_returns_structured_authority(authority_repo: Path) -> None:
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"target": "art-source/_superseded/old_thing/m.blend"})
            assert result.is_error is False
            payload = result.structured_content
            assert payload is not None and set(payload) == OUTPUT_FIELDS
            assert payload["repository"] == "HIWAGA"
            assert payload["repository_root"] == str(authority_repo.resolve())
            assert payload["target"] == "art-source/_superseded/old_thing/m.blend"
            assert payload["resolved_target"] == "art-source/_superseded/old_thing/m.blend"
            assert payload["resolution"] == "RESOLVED"
            assert payload["asset_id"] == "old_thing"
            assert payload["matched_asset_ids"] == ["old_thing"]
            assert payload["status"] == "superseded"
            assert payload["visual_authority"] is False
            assert payload["runtime_active"] is None
            assert payload["runtime_required_temporarily"] is False
            assert payload["authoring_reuse"] == "reference_only"
            assert payload["source_path"] == "art-source/_superseded/old_thing"
            assert payload["runtime_path"] == "game/assets/old_thing_proof"
            assert payload["allowed_uses"] == ["HISTORICAL_REFERENCE", "TECHNICAL_REFERENCE"]
            assert payload["forbidden_uses"] == ["AUTHORING_DERIVATION"]
            assert payload["replacement"] is None

    _run(body)


def test_from_scratch_target_over_the_wire(authority_repo: Path) -> None:
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"target": "art-source/fresh/static.blend"})
            payload = result.structured_content
            assert payload["creation_mode"] == "from_scratch"
            assert payload["allowed_uses"] == []
            assert "DUPLICATE_SUPERSEDED_SOURCE" in payload["forbidden_uses"]

    _run(body)


def test_unresolved_is_a_successful_structured_result(authority_repo: Path) -> None:
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"target": "docs/README.md"})
            assert result.is_error is False
            payload = result.structured_content
            assert payload["resolution"] == "UNRESOLVED"
            assert payload["asset_id"] is None
            assert payload["matched_asset_ids"] == []
            assert payload["status"] is None

    _run(body)


def test_conflict_is_a_successful_structured_result(authority_repo: Path) -> None:
    manifest = fixture_manifest()
    manifest["assets"]["twin"] = {"source_path": "art-source/fresh"}
    write_manifest(authority_repo, manifest)
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"target": "art-source/fresh/x.blend"})
            assert result.is_error is False
            payload = result.structured_content
            assert payload["resolution"] == "CONFLICT"
            assert payload["asset_id"] is None
            assert payload["matched_asset_ids"] == ["fresh", "twin"]
            assert payload["status"] is None
            assert payload["allowed_uses"] == [] and payload["forbidden_uses"] == []

    _run(body)


def test_caller_cannot_supply_a_repository(authority_repo: Path, tmp_path: Path) -> None:
    other = make_hiwaga_repo(tmp_path / "other")
    write_manifest(other, {"schema_version": 1, "assets": {"elsewhere": {"source_path": "art-source/fresh"}}})
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"target": "art-source/fresh", "repo_root": str(other)})
            assert result.is_error is False
            assert result.structured_content["repository_root"] == str(authority_repo.resolve())
            assert result.structured_content["asset_id"] == "fresh"

    _run(body)


# --- refusals ----------------------------------------------------------------


def test_missing_target_argument_is_a_tool_error(authority_repo: Path) -> None:
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            assert (await client.call_tool(TOOL, {})).is_error is True

    _run(body)


def test_traversal_and_external_paths_are_refused_with_the_containment_code(
    authority_repo: Path, outside_dir: Path
) -> None:
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            for target in ("../outside/secret.txt", "/etc/passwd", str(outside_dir / "secret.txt")):
                result = await client.call_tool(TOOL, {"target": target})
                assert result.is_error is True, target
                assert result.structured_content is None
                assert ReasonCode.TARGET_OUTSIDE_REPOSITORY.value in _text(result)

    _run(body)


def test_malformed_manifest_is_a_tool_error_with_the_authority_code(authority_repo: Path) -> None:
    write_manifest(authority_repo, "{ broken")
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"target": "art-source/fresh"})
            assert result.is_error is True
            assert result.structured_content is None
            assert ReasonCode.ASSET_AUTHORITY_INVALID.value in _text(result)

    _run(body)


def test_unsupported_manifest_version_is_a_tool_error(authority_repo: Path) -> None:
    write_manifest(authority_repo, {"schema_version": 7, "assets": {}})
    server = _server(authority_repo)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"target": "art-source/fresh"})
            assert result.is_error is True
            assert ReasonCode.ASSET_AUTHORITY_INVALID.value in _text(result)
            assert "not supported" in _text(result)

    _run(body)


def test_invalid_identity_refuses_while_server_info_still_answers(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "partial", omit=("docs/CANON.md",))
    write_manifest(root, fixture_manifest())
    server = _server(root)

    async def body() -> None:
        async with Client(server) as client:
            refused = await client.call_tool(TOOL, {"target": "art-source/fresh"})
            assert refused.is_error is True
            assert ReasonCode.REPOSITORY_IDENTITY_INVALID.value in _text(refused)
            assert (await client.call_tool("hiwaga_server_info", {})).is_error is False

    _run(body)


def test_unconfigured_server_refuses_with_the_configuration_code() -> None:
    server = build_server(config=None)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"target": "art-source/fresh"})
            assert result.is_error is True
            assert ReasonCode.CONFIGURATION_INVALID.value in _text(result)

    _run(body)


def test_working_directory_is_not_a_fallback_repository(authority_repo: Path, monkeypatch: Any) -> None:
    monkeypatch.chdir(authority_repo)
    server = build_server(config=None)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"target": "art-source/fresh"})
            assert result.is_error is True
            assert ReasonCode.CONFIGURATION_INVALID.value in _text(result)

    _run(body)


def test_project_state_and_server_info_are_unaffected(state_repo: Path) -> None:
    server = _server(state_repo)

    async def body() -> None:
        async with Client(server) as client:
            assert (await client.call_tool("hiwaga_server_info", {})).is_error is False
            assert (await client.call_tool("hiwaga_project_state", {})).is_error is False

    _run(body)
