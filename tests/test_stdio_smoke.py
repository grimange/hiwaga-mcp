"""Bounded proof that `python -m hiwaga_mcp` is a working stdio MCP server.

This spawns a real subprocess over the real stdio transport, completes the MCP
initialize handshake, reads the tool list, and shuts the process down. It is
deliberately bounded: no server is left running.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client, StdioServerParameters

HANDSHAKE_TIMEOUT_SECONDS = 30.0


def _server_parameters(repo_root: Path) -> StdioServerParameters:
    env = dict(os.environ)
    env["HIWAGA_REPO_ROOT"] = str(repo_root)
    # Keep the child importing the same tree as the test run, whether or not the
    # package is installed into the active environment.
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join([src, env["PYTHONPATH"]]) if env.get("PYTHONPATH") else src
    return StdioServerParameters(command=sys.executable, args=["-m", "hiwaga_mcp"], env=env)


def test_module_entrypoint_serves_mcp_over_stdio(hiwaga_repo: Path) -> None:
    async def body() -> None:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(_server_parameters(hiwaga_repo)) as client:
                info = client.server_info
                assert info is not None
                assert info.name == "hiwaga-mcp"

                names = {tool.name for tool in (await client.list_tools()).tools}
                assert names == {
                    "hiwaga_server_info",
                    "hiwaga_project_state",
                    "hiwaga_authority",
                    "hiwaga_preflight",
                }

                result = await client.call_tool("hiwaga_server_info", {})
                assert result.is_error is False
                payload = result.structured_content
                assert payload["configuration_status"] == "CONFIGURED"
                assert payload["configured_repo_root"] == str(hiwaga_repo.resolve())
                assert payload["repository_identity"]["status"] == "VALID"

    try:
        anyio.run(body)
    except TimeoutError as exc:  # pragma: no cover - only on a hung bootstrap
        pytest.fail(f"stdio bootstrap did not complete the handshake in time: {exc}")


def test_stdio_server_reports_unconfigured_root_without_dying(tmp_path: Path) -> None:
    """A misconfigured server still boots and explains itself over stdio."""
    env = dict(os.environ)
    env.pop("HIWAGA_REPO_ROOT", None)
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join([src, env["PYTHONPATH"]]) if env.get("PYTHONPATH") else src
    params = StdioServerParameters(command=sys.executable, args=["-m", "hiwaga_mcp"], env=env)

    async def body() -> None:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(params) as client:
                payload = (await client.call_tool("hiwaga_server_info", {})).structured_content
                assert payload["configuration_status"] == "INVALID"
                assert payload["configuration_error"]["code"] == "HIWAGA_CONFIGURATION_INVALID"

    try:
        anyio.run(body)
    except TimeoutError as exc:  # pragma: no cover - only on a hung bootstrap
        pytest.fail(f"stdio bootstrap did not complete the handshake in time: {exc}")


def test_stdio_server_serves_project_state(state_repo: Path) -> None:
    """The new tool works through a real subprocess, and refuses without a HIWAGA checkout."""

    async def body() -> None:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(_server_parameters(state_repo)) as client:
                result = await client.call_tool("hiwaga_project_state", {})
                assert result.is_error is False
                payload = result.structured_content
                assert payload["repository_root"] == str(state_repo.resolve())
                assert payload["branch"] == "main"
                assert payload["ambiguity_gate"] == "TARGET_CLEAR"
                assert payload["current_block_heading"] == "Current Block Title — 2026-09-20"

    try:
        anyio.run(body)
    except TimeoutError as exc:  # pragma: no cover - only on a hung bootstrap
        pytest.fail(f"stdio project-state call did not complete in time: {exc}")


def test_stdio_server_serves_authority(authority_repo: Path) -> None:
    """`hiwaga_authority` works through a real subprocess, including a normal UNRESOLVED result."""

    async def body() -> None:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(_server_parameters(authority_repo)) as client:
                resolved = await client.call_tool("hiwaga_authority", {"target": "art-source/fresh/a.blend"})
                assert resolved.is_error is False
                assert resolved.structured_content["resolution"] == "RESOLVED"
                assert resolved.structured_content["asset_id"] == "fresh"

                unresolved = await client.call_tool("hiwaga_authority", {"target": "docs/CANON.md"})
                assert unresolved.is_error is False
                assert unresolved.structured_content["resolution"] == "UNRESOLVED"

                refused = await client.call_tool("hiwaga_authority", {"target": "../x"})
                assert refused.is_error is True

    try:
        anyio.run(body)
    except TimeoutError as exc:  # pragma: no cover - only on a hung bootstrap
        pytest.fail(f"stdio authority call did not complete in time: {exc}")


def test_stdio_server_serves_preflight(preflight_repo: Path) -> None:
    """`hiwaga_preflight` works through a real subprocess: a DENY is a result, a bad request an error."""

    async def body() -> None:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(_server_parameters(preflight_repo)) as client:
                denied = await client.call_tool(
                    "hiwaga_preflight",
                    {
                        "operation": "DERIVE_AUTHORED_ASSET",
                        "targets": ["art-source/_superseded/old_thing/x.blend"],
                    },
                )
                assert denied.is_error is False
                assert denied.structured_content["decision"] == "DENY"

                allowed = await client.call_tool(
                    "hiwaga_preflight", {"operation": "MODIFY_CODE", "targets": ["src/x.py"]}
                )
                assert allowed.is_error is False
                assert allowed.structured_content["decision"] == "ALLOW"

                refused = await client.call_tool(
                    "hiwaga_preflight", {"operation": "READ_REFERENCE", "targets": ["../x"]}
                )
                assert refused.is_error is True

    try:
        anyio.run(body)
    except TimeoutError as exc:  # pragma: no cover - only on a hung bootstrap
        pytest.fail(f"stdio preflight call did not complete in time: {exc}")
