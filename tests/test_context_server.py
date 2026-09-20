"""`hiwaga_context` over the real in-memory MCP client path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client

from hiwaga_mcp.config import ServerConfig
from hiwaga_mcp.errors import ReasonCode
from hiwaga_mcp.server import build_server

from .conftest import context_routing_mapping_text, fixture_context_routing_mapping

TOOL = "hiwaga_context"

RESULT_FIELDS = {
    "repository",
    "repository_root",
    "domain",
    "canonical_sources",
    "supporting_sources",
    "historical_sources",
    "project_state",
    "routing_document",
    "limitations",
}
SOURCE_FIELDS = {"path", "title", "label", "classification", "section", "note", "exists", "size_bytes"}

ALL_DOMAINS = {
    "PROJECT",
    "GAMEPLAY",
    "WORLD_LORE",
    "VISUAL_IDENTITY",
    "VERTICAL_SLICE",
    "CORE_ARCHITECTURE",
    "PROGRESSION",
    "REPRESENTATIVE_GAMEPLAY",
    "ASSET_AUTHORITY",
    "VERIFICATION",
}


def _run(async_fn: Any) -> Any:
    return anyio.run(async_fn)


def _text(result: Any) -> str:
    return " ".join(block.text for block in result.content if getattr(block, "text", None))


_USE_FIXTURE_MAPPING = object()


def _server(root: Path, mapping: Any = _USE_FIXTURE_MAPPING) -> Any:
    """A server pointed at `root`, with the fixture routing mapping substituted by default.

    `mapping=None` uses the packaged (production) mapping instead; any other
    value is serialized and substituted as given.
    """
    if mapping is _USE_FIXTURE_MAPPING:
        mapping = fixture_context_routing_mapping()
    return build_server(
        config=ServerConfig(repo_root=root),
        context_routing_text=context_routing_mapping_text(mapping) if mapping is not None else None,
    )


async def _call(server: Any, domain: str) -> Any:
    async with Client(server) as client:
        return await client.call_tool(TOOL, {"domain": domain})


# --- registration and schema -------------------------------------------------


def test_tool_is_registered_with_a_single_closed_domain_enum(context_repo: Path) -> None:
    server = _server(context_repo)

    async def body() -> None:
        async with Client(server) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == TOOL)
            schema = tool.input_schema
            assert set(schema["properties"]) == {"domain"}
            assert schema["required"] == ["domain"]
            prop = schema["properties"]["domain"]
            enum = prop.get("enum") or schema["$defs"]["ContextDomain"]["enum"]
            assert set(enum) == ALL_DOMAINS
            assert tool.output_schema is not None
            assert set(tool.output_schema["required"]) == RESULT_FIELDS

    _run(body)


def test_all_ten_domains_are_registered_tool_set(hiwaga_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=hiwaga_repo))

    async def body() -> None:
        async with Client(server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert TOOL in names

    _run(body)


# --- valid results -------------------------------------------------------------


def test_project_domain_is_a_successful_structured_result(context_repo: Path) -> None:
    server = _server(context_repo)

    async def body() -> None:
        result = await _call(server, "PROJECT")
        assert result.is_error is False
        payload = result.structured_content
        assert payload is not None and set(payload) == RESULT_FIELDS
        assert payload["domain"] == "PROJECT"
        (source,) = payload["canonical_sources"]
        assert set(source) == SOURCE_FIELDS
        assert source["path"] == "docs/CANON.md"
        assert source["title"] == "HIWAGA Canon and Source-of-Truth Index"
        assert source["label"] == "PROJECT routing index"
        assert source["classification"] == "CURRENT_STATE"
        assert source["section"] is None
        assert source["exists"] is True
        assert isinstance(source["size_bytes"], int) and source["size_bytes"] > 0
        assert isinstance(source["note"], str) and source["note"]
        assert payload["project_state"] is not None
        assert payload["routing_document"] == "docs/CANON.md"

    _run(body)


def test_vertical_slice_isolates_historical_evidence_over_the_wire(context_repo: Path) -> None:
    server = _server(context_repo)

    async def body() -> None:
        result = await _call(server, "VERTICAL_SLICE")
        assert result.is_error is False
        payload = result.structured_content
        canonical_paths = [s["path"] for s in payload["canonical_sources"]]
        historical_paths = [s["path"] for s in payload["historical_sources"]]
        assert "docs/evidence/fixture-vertical-slice" not in canonical_paths
        assert "docs/evidence/fixture-vertical-slice" in historical_paths
        assert payload["canonical_sources"][0]["section"] == "42. Fixture Acceptance Gate"

    _run(body)


def test_representative_gameplay_is_a_successful_result_with_no_canonical_source(context_repo: Path) -> None:
    server = _server(context_repo)

    async def body() -> None:
        result = await _call(server, "REPRESENTATIVE_GAMEPLAY")
        assert result.is_error is False
        payload = result.structured_content
        assert payload["canonical_sources"] == []
        assert len(payload["supporting_sources"]) >= 1
        assert any("no canonical source" in note for note in payload["limitations"])

    _run(body)


def test_asset_authority_does_not_call_the_authority_service(context_repo: Path) -> None:
    server = _server(context_repo)

    async def body() -> None:
        result = await _call(server, "ASSET_AUTHORITY")
        assert result.is_error is False
        payload = result.structured_content
        assert payload["canonical_sources"] == []
        assert "resolution" not in payload
        assert "asset_id" not in payload

    _run(body)


def test_caller_cannot_supply_a_repository(context_repo: Path, tmp_path: Path) -> None:
    from .conftest import make_hiwaga_repo

    other = make_hiwaga_repo(tmp_path / "other")
    server = _server(context_repo)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"domain": "PROJECT", "repo_root": str(other)})
            assert result.is_error is False
            assert result.structured_content["repository_root"] == str(context_repo.resolve())

    _run(body)


# --- invalid requests and prerequisite failures are tool errors --------------


@pytest.mark.parametrize(
    "domain",
    ["PLAYER", "player_v2", "GENERAL", "OTHER", "AUTO", "gameplay", "", None, 5],
)
def test_an_unknown_or_missing_domain_fails_validation(context_repo: Path, domain: Any) -> None:
    server = _server(context_repo)

    async def body() -> None:
        async with Client(server) as client:
            arguments: dict[str, Any] = {} if domain is None else {"domain": domain}
            result = await client.call_tool(TOOL, arguments)
            assert result.is_error is True
            assert result.structured_content is None

    _run(body)


def test_malformed_canon_is_a_tool_error(context_repo: Path) -> None:
    from .conftest import write_canon

    write_canon(context_repo, "# No routing sections here\n")
    server = _server(context_repo)

    async def body() -> None:
        result = await _call(server, "PROJECT")
        assert result.is_error is True
        assert result.structured_content is None
        assert ReasonCode.CONTEXT_ROUTING_INVALID.value in _text(result)

    _run(body)


def test_invalid_packaged_mapping_is_a_tool_error(context_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=context_repo), context_routing_text="{ not json")

    async def body() -> None:
        result = await _call(server, "PROJECT")
        assert result.is_error is True
        assert ReasonCode.CONTEXT_ROUTING_INVALID.value in _text(result)

    _run(body)


def test_missing_canonical_source_is_a_tool_error(context_repo: Path) -> None:
    (context_repo / "docs/FIXTURE_GAME_IDENTITY.md").unlink()
    server = _server(context_repo)

    async def body() -> None:
        result = await _call(server, "GAMEPLAY")
        assert result.is_error is True
        assert ReasonCode.CONTEXT_ROUTING_INVALID.value in _text(result)

    _run(body)


def test_unconfigured_server_refuses(context_repo: Path) -> None:
    async def body() -> Any:
        async with Client(build_server(config=None)) as client:
            return await client.call_tool(TOOL, {"domain": "PROJECT"})

    result = _run(body)
    assert result.is_error is True
    assert ReasonCode.CONFIGURATION_INVALID.value in _text(result)


def test_invalid_repository_identity_refuses(tmp_path: Path) -> None:
    from .conftest import make_hiwaga_repo

    root = make_hiwaga_repo(tmp_path / "hiwaga", omit=("docs/CANON.md",))
    server = _server(root)

    async def body() -> Any:
        return await _call(server, "PROJECT")

    result = _run(body)
    assert result.is_error is True
    assert ReasonCode.REPOSITORY_IDENTITY_INVALID.value in _text(result)


def test_existing_tools_still_work_alongside_context(context_repo: Path) -> None:
    server = _server(context_repo)

    async def body() -> None:
        async with Client(server) as client:
            info = await client.call_tool("hiwaga_server_info", {})
            assert info.is_error is False
            state = await client.call_tool("hiwaga_project_state", {})
            assert state.is_error is False

    _run(body)


def test_context_does_not_consult_preflight_authority_or_model_gate(context_repo: Path) -> None:
    import hiwaga_mcp.server as server_module

    called: list[str] = []
    originals = {
        "run_preflight": server_module.run_preflight,
        "run_model_gate": server_module.run_model_gate,
        "resolve_authority": server_module.resolve_authority,
    }

    def record(name: str, original: Any) -> Any:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            called.append(name)
            return original(*args, **kwargs)

        return wrapper

    for name, original in originals.items():
        setattr(server_module, name, record(name, original))
    try:
        server = _server(context_repo)
        result = _run(lambda: _call(server, "ASSET_AUTHORITY"))
        assert result.is_error is False
    finally:
        for name, original in originals.items():
            setattr(server_module, name, original)

    assert called == []
