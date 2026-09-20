"""MCP protocol surface, exercised through the SDK's in-memory client path.

These tests drive the real `mcp.Client` against the real `MCPServer`, so the
registered tool list, its declared schema, and its structured output are proven
over the protocol rather than by calling the Python function directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import Client

from hiwaga_mcp import SERVER_NAME, SERVER_TITLE, __version__
from hiwaga_mcp.config import REPO_ROOT_ENV_VAR, ServerConfig, load_config
from hiwaga_mcp.errors import ConfigurationError, ReasonCode
from hiwaga_mcp.server import build_server, create_server_from_environment

from .conftest import make_hiwaga_repo

EXPECTED_TOOLS = {"hiwaga_server_info", "hiwaga_project_state"}


def _run(async_fn: Any) -> Any:
    """Run one async protocol body without an asyncio pytest plugin."""
    return anyio.run(async_fn)


def test_server_initializes_and_reports_its_identity(hiwaga_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=hiwaga_repo))

    async def body() -> None:
        async with Client(server) as client:
            info = client.server_info
            assert info is not None
            assert info.name == SERVER_NAME
            assert info.version == __version__
            assert info.title == SERVER_TITLE

    _run(body)


def test_tool_list_is_exactly_the_current_surface(hiwaga_repo: Path) -> None:
    """Only bootstrap diagnostics and `hiwaga_project_state` are registered."""
    server = build_server(config=ServerConfig(repo_root=hiwaga_repo))

    async def body() -> None:
        async with Client(server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names == EXPECTED_TOOLS

    _run(body)


def test_no_later_p0_tool_is_registered(hiwaga_repo: Path) -> None:
    deferred = {
        "hiwaga_context",
        "hiwaga_authority",
        "hiwaga_preflight",
        "hiwaga_model_gate",
        "hiwaga_verify",
    }
    server = build_server(config=ServerConfig(repo_root=hiwaga_repo))

    async def body() -> None:
        async with Client(server) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names.isdisjoint(deferred)

    _run(body)


def test_tool_declares_a_structured_output_schema(hiwaga_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=hiwaga_repo))

    async def body() -> None:
        async with Client(server) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == "hiwaga_server_info")
            schema = tool.output_schema
            assert schema is not None
            assert schema["type"] == "object"
            assert "configuration_status" in schema["properties"]
            assert "repository_identity" in schema["properties"]

    _run(body)


def test_tool_returns_structured_output_for_a_valid_repository(hiwaga_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=hiwaga_repo))

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool("hiwaga_server_info", {})
            assert result.is_error is False
            payload = result.structured_content
            assert payload is not None
            assert payload["server_name"] == SERVER_NAME
            assert payload["server_version"] == __version__
            assert payload["product"] == SERVER_TITLE
            assert payload["configuration_status"] == "CONFIGURED"
            assert payload["configured_repo_root"] == str(hiwaga_repo.resolve())
            assert payload["configuration_error"] is None
            identity = payload["repository_identity"]
            assert identity["status"] == "VALID"
            assert identity["missing_sentinels"] == []
            assert identity["error"] is None

    _run(body)


def test_tool_reports_invalid_identity_without_a_protocol_error(tmp_path: Path) -> None:
    """An invalid checkout is structured domain output, not a tool failure."""
    root = make_hiwaga_repo(tmp_path / "partial", omit=("docs/CANON.md",))
    server = build_server(config=ServerConfig(repo_root=root))

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool("hiwaga_server_info", {})
            assert result.is_error is False
            identity = result.structured_content["repository_identity"]
            assert identity["status"] == "INVALID"
            assert identity["missing_sentinels"] == ["docs/CANON.md"]
            assert identity["error"]["code"] == ReasonCode.REPOSITORY_IDENTITY_INVALID.value

    _run(body)


def test_tool_reports_missing_configuration_structurally() -> None:
    server = build_server(config=None)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool("hiwaga_server_info", {})
            assert result.is_error is False
            payload = result.structured_content
            assert payload["configuration_status"] == "INVALID"
            assert payload["configured_repo_root"] is None
            assert payload["repository_identity"] is None
            assert payload["configuration_error"]["code"] == ReasonCode.CONFIGURATION_INVALID.value

    _run(body)


def test_tool_preserves_the_configuration_failure_it_was_given(tmp_path: Path) -> None:
    try:
        load_config({REPO_ROOT_ENV_VAR: str(tmp_path / "absent")})
    except ConfigurationError as exc:
        server = build_server(config=None, config_error=exc)
    else:  # pragma: no cover - load_config must have raised
        raise AssertionError("expected ConfigurationError")

    async def body() -> None:
        async with Client(server) as client:
            error = (await client.call_tool("hiwaga_server_info", {})).structured_content[
                "configuration_error"
            ]
            assert error["details"]["problem"] == "does_not_exist"

    _run(body)


def test_tool_takes_no_arguments(hiwaga_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=hiwaga_repo))

    async def body() -> None:
        async with Client(server) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == "hiwaga_server_info")
            assert tool.input_schema.get("properties", {}) == {}

    _run(body)


def test_environment_built_server_uses_the_configured_root(hiwaga_repo: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv(REPO_ROOT_ENV_VAR, str(hiwaga_repo))
    server = create_server_from_environment()

    async def body() -> None:
        async with Client(server) as client:
            payload = (await client.call_tool("hiwaga_server_info", {})).structured_content
            assert payload["configuration_status"] == "CONFIGURED"
            assert payload["configured_repo_root"] == str(hiwaga_repo.resolve())

    _run(body)


def test_environment_built_server_starts_without_configuration(monkeypatch: Any) -> None:
    """Configuration failure is reported, not fatal at construction time."""
    monkeypatch.delenv(REPO_ROOT_ENV_VAR, raising=False)
    server = create_server_from_environment()

    async def body() -> None:
        async with Client(server) as client:
            payload = (await client.call_tool("hiwaga_server_info", {})).structured_content
            assert payload["configuration_status"] == "INVALID"
            assert payload["configuration_error"]["details"]["problem"] == "not_set"

    _run(body)


def test_no_resources_or_prompts_are_exposed(hiwaga_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=hiwaga_repo))

    async def body() -> None:
        async with Client(server) as client:
            assert (await client.list_resources()).resources == []
            assert (await client.list_prompts()).prompts == []

    _run(body)
