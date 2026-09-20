"""`hiwaga_preflight` over the real in-memory MCP client path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import Client

from hiwaga_mcp.config import ServerConfig
from hiwaga_mcp.errors import ReasonCode
from hiwaga_mcp.server import build_server

from .conftest import make_hiwaga_repo, preflight_manifest, set_project_state, write_manifest

TOOL = "hiwaga_preflight"

OUTPUT_FIELDS = {
    "repository",
    "repository_root",
    "operation",
    "targets",
    "decision",
    "reason_code",
    "reason",
    "project_state_summary",
    "target_results",
    "limitations",
}
TARGET_FIELDS = {
    "target",
    "resolved_target",
    "authority_resolution",
    "asset_id",
    "allowed_uses",
    "forbidden_uses",
    "target_decision",
    "reason_code",
    "reason",
}
SUMMARY_FIELDS = {"ambiguity_gate", "operator_required", "current_block_heading", "next_bounded_step"}

REFERENCE_ONLY = "art-source/_superseded/old_thing/x.blend"
FROM_SCRATCH = "art-source/fresh/a.blend"
UNREGISTERED = "art-source/nowhere/x.blend"


def _run(async_fn: Any) -> Any:
    return anyio.run(async_fn)


def _text(result: Any) -> str:
    return " ".join(block.text for block in result.content)


def _server(root: Path) -> Any:
    return build_server(config=ServerConfig(repo_root=root))


async def _call(server: Any, operation: str, targets: list[str]) -> Any:
    async with Client(server) as client:
        return await client.call_tool(TOOL, {"operation": operation, "targets": targets})


def test_tool_is_registered_with_a_closed_operation_enum_and_a_target_list(preflight_repo: Path) -> None:
    server = _server(preflight_repo)

    async def body() -> None:
        async with Client(server) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == TOOL)
            schema = tool.input_schema
            assert set(schema["properties"]) == {"operation", "targets"}
            assert set(schema["required"]) == {"operation", "targets"}
            assert "repo_root" not in schema["properties"]
            operation = schema["properties"]["operation"]
            enum = operation.get("enum") or schema["$defs"]["PreflightOperation"]["enum"]
            assert set(enum) == {
                "READ_REFERENCE",
                "MODIFY_CODE",
                "MODIFY_AUTHORED_ASSET",
                "DERIVE_AUTHORED_ASSET",
                "CREATE_AUTHORED_ASSET_FROM_SCRATCH",
                "RUN_VERIFICATION",
                "OPERATOR_REVIEW",
            }
            targets = schema["properties"]["targets"]
            assert targets["type"] == "array" and targets["items"] == {"type": "string"}
            assert targets["minItems"] == 1
            assert tool.output_schema is not None
            assert set(tool.output_schema["required"]) == OUTPUT_FIELDS

    _run(body)


def test_allow_is_a_successful_structured_result(preflight_repo: Path) -> None:
    server = _server(preflight_repo)

    async def body() -> None:
        result = await _call(server, "MODIFY_CODE", ["src/hiwaga_mcp/x.py"])
        assert result.is_error is False
        payload = result.structured_content
        assert payload is not None and set(payload) == OUTPUT_FIELDS
        assert payload["decision"] == "ALLOW"
        assert payload["reason_code"] == "HIWAGA_PREFLIGHT_ALLOWED"
        assert payload["repository"] == "HIWAGA"
        assert payload["repository_root"] == str(preflight_repo.resolve())
        assert payload["operation"] == "MODIFY_CODE"
        assert payload["targets"] == ["src/hiwaga_mcp/x.py"]
        assert set(payload["project_state_summary"]) == SUMMARY_FIELDS
        (target,) = payload["target_results"]
        assert set(target) == TARGET_FIELDS
        assert target["authority_resolution"] == "UNRESOLVED"
        assert target["target_decision"] == "ALLOW"

    _run(body)


def test_deny_is_a_successful_structured_result(preflight_repo: Path) -> None:
    server = _server(preflight_repo)

    async def body() -> None:
        result = await _call(server, "DERIVE_AUTHORED_ASSET", [REFERENCE_ONLY])
        assert result.is_error is False
        payload = result.structured_content
        assert payload["decision"] == "DENY"
        assert payload["reason_code"] == "HIWAGA_PREFLIGHT_OPERATION_FORBIDDEN"
        (target,) = payload["target_results"]
        assert target["asset_id"] == "old_thing"
        assert target["forbidden_uses"] == ["AUTHORING_DERIVATION"]
        assert target["allowed_uses"] == ["HISTORICAL_REFERENCE", "TECHNICAL_REFERENCE"]

    _run(body)


def test_ambiguity_is_a_successful_structured_result(preflight_repo: Path) -> None:
    server = _server(preflight_repo)

    async def body() -> None:
        result = await _call(server, "MODIFY_AUTHORED_ASSET", [UNREGISTERED])
        assert result.is_error is False
        payload = result.structured_content
        assert payload["decision"] == "AMBIGUITY"
        assert payload["reason_code"] == "HIWAGA_PREFLIGHT_AUTHORITY_UNRESOLVED"

    _run(body)


def test_project_level_ambiguity_is_a_successful_structured_result(preflight_repo: Path) -> None:
    set_project_state(preflight_repo, "TARGET_AMBIGUOUS")
    server = _server(preflight_repo)

    async def body() -> None:
        result = await _call(server, "READ_REFERENCE", [UNREGISTERED])
        assert result.is_error is False
        assert result.structured_content["decision"] == "AMBIGUITY"
        assert result.structured_content["reason_code"] == "HIWAGA_PREFLIGHT_PROJECT_AMBIGUOUS"
        assert result.structured_content["project_state_summary"]["ambiguity_gate"] == "TARGET_AMBIGUOUS"

    _run(body)


def test_human_required_is_a_successful_structured_result(preflight_repo: Path) -> None:
    set_project_state(preflight_repo, operator=True)
    server = _server(preflight_repo)

    async def body() -> None:
        blocked = await _call(server, "MODIFY_AUTHORED_ASSET", [FROM_SCRATCH])
        assert blocked.is_error is False
        assert blocked.structured_content["decision"] == "HUMAN_REQUIRED"
        assert blocked.structured_content["reason_code"] == "HIWAGA_PREFLIGHT_HUMAN_REQUIRED"
        assert blocked.structured_content["project_state_summary"]["operator_required"] is True

        review = await _call(server, "OPERATOR_REVIEW", [FROM_SCRATCH])
        assert review.is_error is False
        assert review.structured_content["decision"] == "ALLOW"

    _run(body)


def test_multi_target_result_carries_per_target_evidence(preflight_repo: Path) -> None:
    server = _server(preflight_repo)

    async def body() -> None:
        result = await _call(server, "DERIVE_AUTHORED_ASSET", [FROM_SCRATCH, REFERENCE_ONLY])
        payload = result.structured_content
        assert payload["decision"] == "DENY"
        assert [t["target_decision"] for t in payload["target_results"]] == ["ALLOW", "DENY"]
        assert [t["asset_id"] for t in payload["target_results"]] == ["fresh", "old_thing"]

    _run(body)


def test_caller_cannot_supply_a_repository(preflight_repo: Path, tmp_path: Path) -> None:
    other = make_hiwaga_repo(tmp_path / "other")
    write_manifest(other, preflight_manifest())
    server = _server(preflight_repo)

    async def body() -> None:
        async with Client(server) as client:
            result = await client.call_tool(
                TOOL,
                {"operation": "READ_REFERENCE", "targets": [FROM_SCRATCH], "repo_root": str(other)},
            )
            assert result.is_error is False
            assert result.structured_content["repository_root"] == str(preflight_repo.resolve())

    _run(body)


# --- invalid requests and prerequisite failures are tool errors --------------


def test_unknown_operation_empty_targets_and_missing_arguments_are_tool_errors(preflight_repo: Path) -> None:
    server = _server(preflight_repo)

    async def body() -> None:
        async with Client(server) as client:
            for arguments in (
                {"operation": "DELETE_ASSET", "targets": ["x"]},
                {"operation": "read_reference", "targets": ["x"]},
                {"operation": "READ_REFERENCE", "targets": []},
                {"operation": "READ_REFERENCE", "targets": "x"},
                {"operation": "READ_REFERENCE"},
                {"targets": ["x"]},
                {},
            ):
                result = await client.call_tool(TOOL, arguments)
                assert result.is_error is True, arguments
                assert result.structured_content is None

    _run(body)


def test_target_outside_the_repository_is_a_tool_error(preflight_repo: Path) -> None:
    server = _server(preflight_repo)

    async def body() -> None:
        result = await _call(server, "READ_REFERENCE", ["src/ok.py", "../../etc/passwd"])
        assert result.is_error is True
        assert result.structured_content is None
        assert ReasonCode.TARGET_OUTSIDE_REPOSITORY.value in _text(result)

    _run(body)


def test_malformed_authority_manifest_is_a_tool_error(preflight_repo: Path) -> None:
    write_manifest(preflight_repo, "{ broken")
    server = _server(preflight_repo)

    async def body() -> None:
        result = await _call(server, "READ_REFERENCE", ["src/ok.py"])
        assert result.is_error is True
        assert ReasonCode.ASSET_AUTHORITY_INVALID.value in _text(result)

    _run(body)


def test_unavailable_project_state_is_a_tool_error(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "nogit")  # no real Git repository
    write_manifest(root, preflight_manifest())
    set_project_state(root)
    server = _server(root)

    async def body() -> None:
        result = await _call(server, "READ_REFERENCE", ["src/ok.py"])
        assert result.is_error is True
        assert ReasonCode.PROJECT_STATE_UNAVAILABLE.value in _text(result)

    _run(body)


def test_invalid_identity_refuses_while_server_info_still_answers(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "partial", omit=("docs/CANON.md",))
    server = _server(root)

    async def body() -> None:
        async with Client(server) as client:
            refused = await client.call_tool(TOOL, {"operation": "READ_REFERENCE", "targets": ["x"]})
            assert refused.is_error is True
            assert ReasonCode.REPOSITORY_IDENTITY_INVALID.value in _text(refused)
            assert (await client.call_tool("hiwaga_server_info", {})).is_error is False

    _run(body)


def test_unconfigured_server_refuses_with_the_configuration_code(
    monkeypatch: Any, preflight_repo: Path
) -> None:
    monkeypatch.chdir(preflight_repo)  # a valid checkout as CWD must not be used as a fallback
    server = build_server(config=None)

    async def body() -> None:
        result = await _call(server, "READ_REFERENCE", ["x"])
        assert result.is_error is True
        assert ReasonCode.CONFIGURATION_INVALID.value in _text(result)

    _run(body)


def test_existing_tools_are_unaffected(preflight_repo: Path) -> None:
    server = _server(preflight_repo)

    async def body() -> None:
        async with Client(server) as client:
            assert (await client.call_tool("hiwaga_server_info", {})).is_error is False
            assert (await client.call_tool("hiwaga_project_state", {})).is_error is False
            authority = await client.call_tool("hiwaga_authority", {"target": FROM_SCRATCH})
            assert authority.is_error is False
            assert authority.structured_content["resolution"] == "RESOLVED"

    _run(body)
