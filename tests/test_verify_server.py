"""`hiwaga_verify` over the real in-memory MCP path.

The distinction these tests exist to pin down: a verification outcome — PASS,
FAIL, TIMEOUT, EXECUTION_ERROR — is a successful tool call carrying structured
content, while an invalid request is a tool error. Neither ever becomes the
other.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import anyio
from mcp import Client
from mcp.server import MCPServer

from hiwaga_mcp.config import ServerConfig
from hiwaga_mcp.errors import ReasonCode
from hiwaga_mcp.server import build_server

from .conftest import (
    install_fixture_verifiers,
    install_repo_python,
    make_hiwaga_repo,
    registry_text,
)


def _run(async_fn: Any) -> Any:
    return anyio.run(async_fn)


def _text(result: Any) -> str:
    return " ".join(block.text for block in result.content if getattr(block, "text", None))


def server_for(root: Path, registry: Any = None) -> MCPServer:
    """A server pointed at `root`, with the fixture registry substituted at construction."""
    return build_server(
        config=ServerConfig(repo_root=root),
        verifier_registry_text=registry_text(registry) if registry is not None else registry_text(),
    )


def call(root: Path, arguments: dict[str, Any], registry: Any = None) -> Any:
    """Call `hiwaga_verify` through the protocol and return the raw tool result."""

    async def body() -> Any:
        async with Client(server_for(root, registry)) as client:
            return await client.call_tool("hiwaga_verify", arguments)

    return _run(body)


# --- registration ------------------------------------------------------------


def test_verify_is_registered(verify_repo: Path) -> None:
    async def body() -> None:
        async with Client(server_for(verify_repo)) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert "hiwaga_verify" in names
            assert "hiwaga_context" not in names

    _run(body)


def test_verify_input_schema_is_narrow(verify_repo: Path) -> None:
    """The caller may name a verifier and a mode, and nothing else."""

    async def body() -> None:
        async with Client(server_for(verify_repo)) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == "hiwaga_verify")
            properties = tool.input_schema["properties"]
            assert set(properties) == {"verifier", "mode"}
            assert tool.input_schema["required"] == ["verifier"]

    _run(body)


def test_verify_input_schema_exposes_no_execution_controls(verify_repo: Path) -> None:
    """Nothing in the contract lets a caller supply a command, cwd, timeout, or environment."""

    async def body() -> None:
        async with Client(server_for(verify_repo)) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == "hiwaga_verify")
            forbidden = {
                "command",
                "args",
                "argv",
                "executable",
                "script",
                "cwd",
                "working_directory",
                "timeout",
                "timeout_seconds",
                "env",
                "environment",
                "repo_root",
                "repository_root",
                "output_path",
                "shell",
                "unsafe",
                "force",
                "approved",
                "allow_execution",
            }
            assert forbidden.isdisjoint(tool.input_schema["properties"])

    _run(body)


def test_verify_declares_structured_output(verify_repo: Path) -> None:
    async def body() -> None:
        async with Client(server_for(verify_repo)) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == "hiwaga_verify")
            schema = tool.output_schema
            assert schema is not None
            for field in ("status", "proof_class", "run_id", "artifacts", "limitations"):
                assert field in schema["properties"]

    _run(body)


# --- the four statuses are ordinary results ----------------------------------


def test_pass_is_a_successful_structured_result(verify_repo: Path) -> None:
    result = call(verify_repo, {"verifier": "structural", "mode": "default"})
    assert result.is_error is False
    payload = result.structured_content
    assert payload is not None
    assert payload["status"] == "PASS"
    assert payload["exit_code"] == 0
    assert payload["timed_out"] is False
    assert payload["proof_class"] == "STRUCTURAL"


def test_fail_is_a_successful_structured_result(verify_repo: Path) -> None:
    """A verifier that finds a defect is a domain result, never a protocol failure."""
    result = call(verify_repo, {"verifier": "failing", "mode": "default"})
    assert result.is_error is False
    assert result.structured_content["status"] == "FAIL"
    assert result.structured_content["exit_code"] == 1


def test_timeout_is_a_successful_structured_result(verify_repo: Path) -> None:
    result = call(verify_repo, {"verifier": "slow", "mode": "default"})
    assert result.is_error is False
    assert result.structured_content["status"] == "TIMEOUT"
    assert result.structured_content["timed_out"] is True


def test_execution_error_is_a_successful_structured_result(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    (root / ".venv" / "bin").mkdir(parents=True)
    install_fixture_verifiers(root)

    result = call(root, {"verifier": "structural", "mode": "default"})
    assert result.is_error is False
    assert result.structured_content["status"] == "EXECUTION_ERROR"


def test_every_status_carries_structured_content(verify_repo: Path) -> None:
    for verifier, expected in (
        ("structural", "PASS"),
        ("failing", "FAIL"),
        ("slow", "TIMEOUT"),
    ):
        result = call(verify_repo, {"verifier": verifier})
        assert result.is_error is False
        assert result.structured_content["status"] == expected


# --- invalid requests are tool errors ----------------------------------------


def test_unknown_verifier_is_a_tool_error(verify_repo: Path) -> None:
    result = call(verify_repo, {"verifier": "does-not-exist"})
    assert result.is_error is True
    assert ReasonCode.UNKNOWN_VERIFIER.value in _text(result)


def test_unsupported_mode_is_a_tool_error(verify_repo: Path) -> None:
    result = call(verify_repo, {"verifier": "structural", "mode": "native"})
    assert result.is_error is True
    assert ReasonCode.UNSUPPORTED_VERIFY_MODE.value in _text(result)


def test_invalid_registry_is_a_tool_error(verify_repo: Path) -> None:
    async def body() -> Any:
        server = build_server(config=ServerConfig(repo_root=verify_repo), verifier_registry_text="{ not json")
        async with Client(server) as client:
            return await client.call_tool("hiwaga_verify", {"verifier": "structural"})

    result = _run(body)
    assert result.is_error is True
    assert ReasonCode.VERIFIER_REGISTRY_INVALID.value in _text(result)


def test_unconfigured_server_refuses(verify_repo: Path) -> None:
    async def body() -> Any:
        async with Client(build_server(config=None)) as client:
            return await client.call_tool("hiwaga_verify", {"verifier": "structural"})

    result = _run(body)
    assert result.is_error is True
    assert ReasonCode.CONFIGURATION_INVALID.value in _text(result)


def test_invalid_repository_identity_refuses(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga", omit=("docs/CANON.md",))
    result = call(root, {"verifier": "structural"})
    assert result.is_error is True
    assert ReasonCode.REPOSITORY_IDENTITY_INVALID.value in _text(result)


def test_nothing_runs_when_identity_is_invalid(tmp_path: Path) -> None:
    root = make_hiwaga_repo(tmp_path / "hiwaga", omit=("docs/CANON.md",))
    install_repo_python(root)
    install_fixture_verifiers(root)
    assert call(root, {"verifier": "structural"}).is_error is True
    assert not (root / ".hiwaga-mcp").exists()


def test_missing_verifier_argument_is_rejected(verify_repo: Path) -> None:
    assert call(verify_repo, {}).is_error is True


# --- the caller cannot widen the boundary ------------------------------------


def test_extra_arguments_are_ignored_and_never_reach_execution(verify_repo: Path) -> None:
    """Unmodelled arguments are dropped: they cannot smuggle in a command, cwd, or timeout."""
    result = call(
        verify_repo,
        {
            "verifier": "structural",
            "mode": "default",
            "command": "rm -rf /",
            "cwd": "/etc",
            "timeout_seconds": 99999,
            "environment": {"GIT_DIR": "/elsewhere"},
        },
    )
    assert result.is_error is False
    payload = result.structured_content
    assert payload["status"] == "PASS"
    # The registry's script ran, not the smuggled command, and the run landed in
    # this server's own external state, not the supplied /etc.
    assert Path(payload["run_directory"]).is_absolute()
    assert verify_repo.resolve() not in Path(payload["run_directory"]).parents
    assert not payload["run_directory"].startswith("/etc")
    assert "structural check ok" in payload["stdout_tail"]


def test_mode_defaults_from_the_registry(verify_repo: Path) -> None:
    result = call(verify_repo, {"verifier": "structural"})
    assert result.is_error is False
    assert result.structured_content["mode"] == "default"


def test_proof_class_is_not_caller_controlled(verify_repo: Path) -> None:
    """A caller cannot claim a headless verifier produced native rendered evidence."""
    result = call(verify_repo, {"verifier": "slow", "proof_class": "NATIVE_RENDERED"})
    assert result.is_error is False
    assert result.structured_content["proof_class"] == "HEADLESS"


# --- result shape ------------------------------------------------------------


def test_result_reports_the_contracted_fields(verify_repo: Path) -> None:
    payload = call(verify_repo, {"verifier": "structural", "mode": "with_output"}).structured_content
    for field in (
        "repository",
        "repository_root",
        "verifier",
        "mode",
        "proof_class",
        "status",
        "exit_code",
        "timed_out",
        "duration_ms",
        "run_id",
        "run_directory",
        "stdout_log",
        "stderr_log",
        "stdout_tail",
        "stderr_tail",
        "artifacts",
        "limitations",
    ):
        assert field in payload, field


def test_result_does_not_carry_the_execution_plan(verify_repo: Path) -> None:
    """The resolved argv, interpreter, and environment stay internal."""
    payload = call(verify_repo, {"verifier": "structural"}).structured_content
    for internal in ("argv", "executable", "environment", "cwd"):
        assert internal not in payload


def test_result_never_claims_operator_acceptance(verify_repo: Path) -> None:
    payload = call(verify_repo, {"verifier": "structural"}).structured_content
    assert payload["limitations"]
    for invented in ("animation_accepted", "visual_quality_passed", "gameplay_good", "approved"):
        assert invented not in payload


def test_response_does_not_carry_unbounded_output(verify_repo: Path) -> None:
    payload = call(verify_repo, {"verifier": "noisy"}).structured_content
    assert payload["stdout_bytes"] > 20000
    assert len(payload["stdout_tail"]) <= 2000
    assert len(payload["stderr_tail"]) <= 2000
    assert payload["output_truncated"] is True


def test_verify_does_not_consult_preflight_or_the_model_gate(verify_repo: Path) -> None:
    """Verify owns safe execution, not development authorization."""
    import hiwaga_mcp.server as server_module

    called: list[str] = []
    original_preflight = server_module.run_preflight
    original_gate = server_module.run_model_gate

    def record_preflight(*args: Any, **kwargs: Any) -> Any:
        called.append("preflight")
        return original_preflight(*args, **kwargs)

    def record_gate(*args: Any, **kwargs: Any) -> Any:
        called.append("model_gate")
        return original_gate(*args, **kwargs)

    server_module.run_preflight = record_preflight  # type: ignore[assignment]
    server_module.run_model_gate = record_gate  # type: ignore[assignment]
    try:
        assert call(verify_repo, {"verifier": "structural"}).is_error is False
    finally:
        server_module.run_preflight = original_preflight  # type: ignore[assignment]
        server_module.run_model_gate = original_gate  # type: ignore[assignment]

    assert called == []


def test_existing_tools_still_work_alongside_verify(verify_repo: Path) -> None:
    """Adding verify did not disturb the established surface."""

    async def body() -> None:
        async with Client(server_for(verify_repo)) as client:
            info = await client.call_tool("hiwaga_server_info", {})
            assert info.is_error is False
            assert info.structured_content["repository_identity"]["status"] == "VALID"

    _run(body)
