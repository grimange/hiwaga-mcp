"""`hiwaga_project_state` over the real in-memory MCP client path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import Client

from hiwaga_mcp.config import REPO_ROOT_ENV_VAR, ServerConfig, load_config
from hiwaga_mcp.errors import ConfigurationError, ReasonCode
from hiwaga_mcp.server import build_server

from .conftest import make_hiwaga_repo, run_git, write_progress

TOOL = "hiwaga_project_state"

REQUIRED_OUTPUT_FIELDS = {
    "repository",
    "repository_root",
    "branch",
    "head",
    "detached_head",
    "worktree_clean",
    "worktree_change_count",
    "phase",
    "current_focus",
    "status",
    "design_question",
    "player_goal",
    "success_condition",
    "ambiguity_gate",
    "next_bounded_step",
    "operator_required",
    "progress_document",
    "current_block_heading",
    "limitations",
}


def _run(async_fn: Any) -> Any:
    return anyio.run(async_fn)


def _error_text(result: Any) -> str:
    return " ".join(block.text for block in result.content)


def test_tool_is_registered_with_no_arguments_and_a_structured_schema(state_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=state_repo))

    async def body() -> None:
        async with Client(server) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == TOOL)
            assert tool.input_schema.get("properties", {}) == {}
            assert not tool.input_schema.get("required")
            schema = tool.output_schema
            assert schema is not None and schema["type"] == "object"
            assert REQUIRED_OUTPUT_FIELDS <= set(schema["properties"])
            assert set(schema["required"]) == REQUIRED_OUTPUT_FIELDS

    _run(body)


def test_valid_repository_returns_structured_state(state_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=state_repo))
    head = run_git(state_repo, "rev-parse", "HEAD")

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {})
            assert result.is_error is False
            payload = result.structured_content
            assert payload is not None
            assert set(payload) == REQUIRED_OUTPUT_FIELDS
            assert payload["repository"] == "HIWAGA"
            assert payload["repository_root"] == str(state_repo.resolve())
            assert payload["branch"] == "main"
            assert payload["head"] == head
            assert payload["detached_head"] is False
            assert payload["worktree_clean"] is True
            assert payload["worktree_change_count"] == 0
            assert payload["phase"] == "REPRESENTATIVE_GAMEPLAY_PROTOTYPING."
            assert payload["status"] is None
            assert payload["ambiguity_gate"] == "TARGET_CLEAR"
            assert payload["next_bounded_step"] == "`NEXT_STEP_TOKEN` — implement it."
            assert payload["operator_required"] is False
            assert payload["progress_document"] == "docs/progress/HIWAGA_PROGRESS.md"
            assert payload["current_block_heading"] == "Current Block Title — 2026-09-20"
            assert isinstance(payload["limitations"], list)

    _run(body)


def test_detached_head_is_null_branch_over_the_wire(state_repo: Path) -> None:
    run_git(state_repo, "checkout", "-q", "--detach")
    server = build_server(config=ServerConfig(repo_root=state_repo))

    async def body() -> None:
        async with Client(server) as client:
            payload = (await client.call_tool(TOOL, {})).structured_content
            assert payload["branch"] is None
            assert payload["detached_head"] is True

    _run(body)


def test_undeclared_gate_and_fields_are_json_null(state_repo: Path) -> None:
    write_progress(state_repo, "## Sparse\n\n- **Phase:** P\n")
    server = build_server(config=ServerConfig(repo_root=state_repo))

    async def body() -> None:
        async with Client(server) as client:
            payload = (await client.call_tool(TOOL, {})).structured_content
            assert payload["ambiguity_gate"] is None
            assert payload["next_bounded_step"] is None
            assert payload["worktree_clean"] is False  # the edited ledger is an uncommitted change
            assert payload["worktree_change_count"] == 1

    _run(body)


def test_inline_gate_and_operator_action_reach_the_mcp_output(state_repo: Path) -> None:
    write_progress(
        state_repo,
        "## Hardened\n\n"
        "- **Current Focus / Status:** `X__READY`. Ambiguity gate `TARGET_PARTIALLY_CONSTRAINED`.\n"
        "- **Next Bounded Step:** operator runs the native review.\n",
    )
    server = build_server(config=ServerConfig(repo_root=state_repo))

    async def body() -> None:
        async with Client(server) as client:
            payload = (await client.call_tool(TOOL, {})).structured_content
            assert payload["ambiguity_gate"] == "TARGET_PARTIALLY_CONSTRAINED"
            assert payload["operator_required"] is True
            assert set(payload) == REQUIRED_OUTPUT_FIELDS  # public schema unchanged

    _run(body)


def test_caller_cannot_supply_a_repository(state_repo: Path, tmp_path: Path) -> None:
    other = make_hiwaga_repo(tmp_path / "other")
    write_progress(other, "## Other\n- **Phase:** OTHER\n")
    server = build_server(config=ServerConfig(repo_root=state_repo))

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {"repo_root": str(other), "path": str(other)})
            assert result.is_error is False
            assert result.structured_content["repository_root"] == str(state_repo.resolve())
            assert result.structured_content["phase"] == "REPRESENTATIVE_GAMEPLAY_PROTOTYPING."

    _run(body)


# --- refusals ----------------------------------------------------------------


def test_unconfigured_server_refuses_with_the_configuration_code() -> None:
    server = build_server(config=None)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {})
            assert result.is_error is True
            assert result.structured_content is None
            assert ReasonCode.CONFIGURATION_INVALID.value in _error_text(result)

    _run(body)


def test_the_original_configuration_failure_is_what_gets_reported(tmp_path: Path) -> None:
    try:
        load_config({REPO_ROOT_ENV_VAR: str(tmp_path / "absent")})
    except ConfigurationError as exc:
        server = build_server(config=None, config_error=exc)
    else:  # pragma: no cover
        raise AssertionError("expected ConfigurationError")

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {})
            assert result.is_error is True
            text = _error_text(result)
            assert ReasonCode.CONFIGURATION_INVALID.value in text
            assert "does not exist" in text

    _run(body)


def test_invalid_repository_identity_refuses_while_server_info_still_answers(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "partial", omit=("docs/CANON.md",))
    server = build_server(config=ServerConfig(repo_root=root))

    async def body() -> None:
        async with Client(server) as client:
            refused = await client.call_tool(TOOL, {})
            assert refused.is_error is True
            assert refused.structured_content is None
            text = _error_text(refused)
            assert ReasonCode.REPOSITORY_IDENTITY_INVALID.value in text
            assert "docs/CANON.md" in text

            # Bootstrap diagnostic behavior is preserved: still structured, never an error.
            info = await client.call_tool("hiwaga_server_info", {})
            assert info.is_error is False
            assert info.structured_content["repository_identity"]["status"] == "INVALID"

    _run(body)


def test_unusable_progress_ledger_refuses_with_the_progress_code(state_repo: Path) -> None:
    write_progress(state_repo, "# No blocks here\n")
    server = build_server(config=ServerConfig(repo_root=state_repo))

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {})
            assert result.is_error is True
            assert ReasonCode.PROGRESS_DOCUMENT_INVALID.value in _error_text(result)

    _run(body)


def test_unestablishable_git_state_refuses_with_the_unavailable_code(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "nogit")
    write_progress(root, "## Block\n- **Phase:** P\n")
    server = build_server(config=ServerConfig(repo_root=root))

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {})
            assert result.is_error is True
            assert result.structured_content is None
            assert ReasonCode.PROJECT_STATE_UNAVAILABLE.value in _error_text(result)

    _run(body)


def test_working_directory_is_not_a_fallback_repository(
    state_repo: Path, monkeypatch: Any
) -> None:
    monkeypatch.chdir(state_repo)
    server = build_server(config=None)  # unconfigured, while the CWD is a valid HIWAGA checkout

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(TOOL, {})
            assert result.is_error is True
            assert ReasonCode.CONFIGURATION_INVALID.value in _error_text(result)

    _run(body)
