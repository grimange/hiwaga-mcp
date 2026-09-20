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
                    "hiwaga_model_gate",
                    "hiwaga_verify",
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


def _gate_parameters(worker: str | None, model: str | None, repo_root: Path | None) -> StdioServerParameters:
    """A real server process with an explicit (synthetic) identity; ambient identity is removed."""
    env = dict(os.environ)
    for name in ("HIWAGA_AI_WORKER", "HIWAGA_AI_MODEL", "HIWAGA_REPO_ROOT"):
        env.pop(name, None)
    if worker is not None:
        env["HIWAGA_AI_WORKER"] = worker
    if model is not None:
        env["HIWAGA_AI_MODEL"] = model
    if repo_root is not None:
        env["HIWAGA_REPO_ROOT"] = str(repo_root)
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join([src, env["PYTHONPATH"]]) if env.get("PYTHONPATH") else src
    return StdioServerParameters(command=sys.executable, args=["-m", "hiwaga_mcp"], env=env)


def test_stdio_server_serves_model_gate_with_an_explicit_synthetic_identity(hiwaga_repo: Path) -> None:
    """Synthetic test identity codex / gpt-5.6-luna: a real process, real env, packaged policy."""

    async def body() -> None:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(_gate_parameters("codex", "gpt-5.6-luna", hiwaga_repo)) as client:
                bounded = {"task_class": "BOUNDED_IMPLEMENTATION"}
                allowed = await client.call_tool("hiwaga_model_gate", bounded)
                assert allowed.is_error is False
                assert allowed.structured_content["decision"] == "ALLOW"
                assert allowed.structured_content["worker"] == "codex"
                assert allowed.structured_content["model"] == "gpt-5.6-luna"

                denied = await client.call_tool("hiwaga_model_gate", {"task_class": "EVIDENCE_AUDIT"})
                assert denied.is_error is False
                assert denied.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_MODEL_DENIED"

                human = await client.call_tool("hiwaga_model_gate", {"task_class": "OPERATOR_REVIEW"})
                assert human.is_error is False
                assert human.structured_content["decision"] == "HUMAN_REQUIRED"

                undefined = await client.call_tool("hiwaga_model_gate", {"task_class": "BUG_DIAGNOSIS"})
                assert undefined.is_error is False
                assert undefined.structured_content["decision"] == "AMBIGUITY"

                override = await client.call_tool(
                    "hiwaga_model_gate",
                    {"task_class": "EXECUTION_BOUNDARY_CHANGE", "worker": "codex", "model": "gpt-5.6-sol"},
                )
                assert override.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_MODEL_DENIED"
                # The reported model is the process identity, not the argument.
                assert override.structured_content["model"] == "gpt-5.6-luna"

                refused = await client.call_tool("hiwaga_model_gate", {"task_class": "NOT_A_CLASS"})
                assert refused.is_error is True

    try:
        anyio.run(body)
    except TimeoutError as exc:  # pragma: no cover - only on a hung bootstrap
        pytest.fail(f"stdio model-gate call did not complete in time: {exc}")


def test_stdio_model_gate_without_identity_or_repository_is_ambiguity_not_a_crash() -> None:
    async def body() -> None:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(_gate_parameters(None, None, None)) as client:
                bounded = {"task_class": "BOUNDED_IMPLEMENTATION"}
                ambiguous = await client.call_tool("hiwaga_model_gate", bounded)
                assert ambiguous.is_error is False
                assert ambiguous.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_IDENTITY_UNAVAILABLE"

                human = await client.call_tool("hiwaga_model_gate", {"task_class": "OPERATOR_REVIEW"})
                assert human.structured_content["decision"] == "HUMAN_REQUIRED"

                info = await client.call_tool("hiwaga_server_info", {})
                assert info.is_error is False
                assert info.structured_content["configuration_status"] == "INVALID"

    try:
        anyio.run(body)
    except TimeoutError as exc:  # pragma: no cover - only on a hung bootstrap
        pytest.fail(f"stdio model-gate call did not complete in time: {exc}")


def test_stdio_model_gate_denies_an_unauthorized_synthetic_worker() -> None:
    async def body() -> None:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(_gate_parameters("claude-code", "some-model", None)) as client:
                result = await client.call_tool("hiwaga_model_gate", {"task_class": "BOUNDED_IMPLEMENTATION"})
                assert result.is_error is False
                assert result.structured_content["decision"] == "DENY"
                assert result.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_WORKER_DENIED"

    try:
        anyio.run(body)
    except TimeoutError as exc:  # pragma: no cover - only on a hung bootstrap
        pytest.fail(f"stdio model-gate call did not complete in time: {exc}")
