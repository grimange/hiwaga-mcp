"""`hiwaga_model_gate` over the real in-memory MCP client path."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client

from hiwaga_mcp.config import MODEL_ENV_VAR, REPO_ROOT_ENV_VAR, WORKER_ENV_VAR, ServerConfig, WorkerIdentity
from hiwaga_mcp.errors import ReasonCode
from hiwaga_mcp.models.diagnostics import ServerInfoResult
from hiwaga_mcp.server import build_server, create_server_from_environment

from .conftest import fixture_worker_policy, worker_policy_text

TOOL = "hiwaga_model_gate"

OUTPUT_FIELDS = {
    "task_class",
    "decision",
    "worker",
    "model",
    "policy_schema_version",
    "matched_rule",
    "allowed_workers",
    "allowed_models",
    "reason_code",
    "reason",
    "limitations",
}
MATCHED_RULE_FIELDS = {"task_class", "human_required", "worker", "models"}


def _run(async_fn: Any) -> Any:
    return anyio.run(async_fn)


def _text(result: Any) -> str:
    return " ".join(block.text for block in result.content)


def _server(worker: str | None = "codex", model: str | None = "model-A", policy: str | None = None) -> Any:
    return build_server(
        config=None,  # the gate is independent of the repository, so none is configured here
        identity=WorkerIdentity(worker=worker, model=model),
        worker_policy_text=worker_policy_text() if policy is None else policy,
    )


async def _call(server: Any, arguments: dict[str, Any]) -> Any:
    async with Client(server) as client:
        return await client.call_tool(TOOL, arguments)


# --- registration and schema -------------------------------------------------


def test_tool_takes_only_a_closed_task_class_enum() -> None:
    server = _server()

    async def body() -> None:
        async with Client(server) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == TOOL)
            schema = tool.input_schema
            assert set(schema["properties"]) == {"task_class"}
            assert schema["required"] == ["task_class"]
            for forbidden in ("worker", "model", "repo_root", "policy_path", "policy"):
                assert forbidden not in schema["properties"]
            prop = schema["properties"]["task_class"]
            enum = prop.get("enum") or schema["$defs"]["TaskClass"]["enum"]
            assert set(enum) == {
                "EVIDENCE_AUDIT",
                "BUG_DIAGNOSIS",
                "BOUNDED_IMPLEMENTATION",
                "EXECUTION_BOUNDARY_CHANGE",
                "RELEASE_REVIEW",
                "HIGH_COMPLEXITY_CONVERGENCE",
                "OPERATOR_REVIEW",
            }
            assert tool.output_schema is not None
            assert set(tool.output_schema["required"]) == OUTPUT_FIELDS

    _run(body)


# --- the four outcomes are successful structured results ---------------------


def test_allow_is_a_successful_structured_result() -> None:
    async def body() -> None:
        result = await _call(_server(), {"task_class": "BOUNDED_IMPLEMENTATION"})
        assert result.is_error is False
        payload = result.structured_content
        assert payload is not None and set(payload) == OUTPUT_FIELDS
        assert payload["decision"] == "ALLOW"
        assert payload["reason_code"] == "HIWAGA_MODEL_GATE_ALLOWED"
        assert payload["task_class"] == "BOUNDED_IMPLEMENTATION"
        assert (payload["worker"], payload["model"]) == ("codex", "model-A")
        assert payload["policy_schema_version"] == 1
        assert set(payload["matched_rule"]) == MATCHED_RULE_FIELDS
        assert payload["matched_rule"]["worker"] == "codex"
        assert payload["allowed_workers"] == ["codex"] and payload["allowed_models"] == ["model-A"]

    _run(body)


def test_deny_is_a_successful_structured_result() -> None:
    async def body() -> None:
        wrong_worker = await _call(
            _server("claude-code", "model-A"), {"task_class": "BOUNDED_IMPLEMENTATION"}
        )
        assert wrong_worker.is_error is False
        assert wrong_worker.structured_content["decision"] == "DENY"
        assert wrong_worker.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_WORKER_DENIED"

        wrong_model = await _call(_server("codex", "model-B"), {"task_class": "BOUNDED_IMPLEMENTATION"})
        assert wrong_model.is_error is False
        assert wrong_model.structured_content["decision"] == "DENY"
        assert wrong_model.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_MODEL_DENIED"

    _run(body)


def test_ambiguity_is_a_successful_structured_result_for_undefined_policy_and_missing_identity() -> None:
    async def body() -> None:
        undefined = await _call(_server(), {"task_class": "BUG_DIAGNOSIS"})
        assert undefined.is_error is False
        assert undefined.structured_content["decision"] == "AMBIGUITY"
        assert undefined.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_POLICY_UNDEFINED"
        assert undefined.structured_content["matched_rule"] is None

        no_identity = await _call(_server(None, None), {"task_class": "BOUNDED_IMPLEMENTATION"})
        assert no_identity.is_error is False
        assert no_identity.structured_content["decision"] == "AMBIGUITY"
        assert no_identity.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_IDENTITY_UNAVAILABLE"
        assert (no_identity.structured_content["worker"], no_identity.structured_content["model"]) == (
            None,
            None,
        )

    _run(body)


def test_human_required_is_a_successful_structured_result_even_without_identity() -> None:
    async def body() -> None:
        for server in (_server(), _server(None, None), _server("nobody", "nothing")):
            result = await _call(server, {"task_class": "OPERATOR_REVIEW"})
            assert result.is_error is False
            assert result.structured_content["decision"] == "HUMAN_REQUIRED"
            assert result.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_HUMAN_REQUIRED"
            assert result.structured_content["matched_rule"]["human_required"] is True

    _run(body)


# --- the caller cannot supply or override identity --------------------------


def test_extra_caller_arguments_cannot_override_the_configured_identity() -> None:
    server = _server("codex", "model-A")

    async def body() -> None:
        result = await _call(
            server,
            {
                "task_class": "BOUNDED_IMPLEMENTATION",
                "worker": "claude-code",
                "model": "not-authorized",
                "repo_root": "/etc",
                "policy_path": "/etc/passwd",
                "HIWAGA_AI_WORKER": "claude-code",
            },
        )
        assert result.is_error is False
        assert result.structured_content["decision"] == "ALLOW"
        assert (result.structured_content["worker"], result.structured_content["model"]) == (
            "codex",
            "model-A",
        )

    _run(body)


def test_extra_caller_arguments_cannot_supply_an_identity_that_was_not_configured() -> None:
    server = _server(None, None)

    async def body() -> None:
        result = await _call(
            server, {"task_class": "BOUNDED_IMPLEMENTATION", "worker": "codex", "model": "model-A"}
        )
        assert result.is_error is False
        assert result.structured_content["decision"] == "AMBIGUITY"
        assert result.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_IDENTITY_UNAVAILABLE"

    _run(body)


# --- invalid requests and invalid policy are tool errors --------------------


@pytest.mark.parametrize(
    "arguments",
    [
        {"task_class": "GENERAL"},
        {"task_class": "OTHER"},
        {"task_class": "AUTO"},
        {"task_class": "UNKNOWN"},
        {"task_class": "bounded_implementation"},
        {"task_class": "make it faster"},
        {"task_class": ""},
        {"task_class": 5},
        {"task_class": None},
        {},
    ],
)
def test_an_unknown_or_missing_task_class_fails_validation_and_is_never_mapped(
    arguments: dict[str, Any],
) -> None:
    async def body() -> None:
        result = await _call(_server(), arguments)
        assert result.is_error is True
        assert result.structured_content is None

    _run(body)


@pytest.mark.parametrize(
    ("policy", "needle"),
    [
        ("{ broken", "not valid JSON"),
        ('{"schema_version": 1, "schema_version": 1, "task_classes": {}}', "duplicate JSON keys"),
        ('{"schema_version": 2, "task_classes": {}}', "not supported"),
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "task_classes": {
                        "OPERATOR_REVIEW": {
                            "human_required": True,
                            "allowed": [{"worker": "codex", "models": ["m"]}],
                        }
                    },
                }
            ),
            "invalid structure",
        ),
    ],
)
def test_an_invalid_policy_is_a_tool_error_with_the_policy_code(policy: str, needle: str) -> None:
    async def body() -> None:
        result = await _call(_server(policy=policy), {"task_class": "BOUNDED_IMPLEMENTATION"})
        assert result.is_error is True
        assert result.structured_content is None
        assert ReasonCode.WORKER_POLICY_INVALID.value in _text(result)
        assert needle in _text(result)

    _run(body)


def test_an_invalid_policy_does_not_prevent_the_server_or_other_tools_from_working(
    tmp_path: Path,
) -> None:
    server = build_server(
        config=None, identity=WorkerIdentity("codex", "model-A"), worker_policy_text="{ broken"
    )

    async def body() -> None:
        async with Client(server) as client:
            assert (await client.call_tool("hiwaga_server_info", {})).is_error is False
            assert (await client.call_tool(TOOL, {"task_class": "OPERATOR_REVIEW"})).is_error is True

    _run(body)


# --- independence and compatibility -----------------------------------------


def test_the_gate_works_without_any_configured_repository() -> None:
    server = _server()

    async def body() -> None:
        async with Client(server) as client:
            assert (await client.call_tool(TOOL, {"task_class": "BOUNDED_IMPLEMENTATION"})).is_error is False
            # A repository-dependent tool still refuses, showing the gate is not borrowing repo state.
            refused = await client.call_tool("hiwaga_project_state", {})
            assert refused.is_error is True
            assert ReasonCode.CONFIGURATION_INVALID.value in _text(refused)

    _run(body)


def test_repository_tools_work_without_any_worker_identity(preflight_repo: Path) -> None:
    server = build_server(config=ServerConfig(repo_root=preflight_repo))  # no identity, no policy override

    async def body() -> None:
        async with Client(server) as client:
            for name, arguments in (
                ("hiwaga_server_info", {}),
                ("hiwaga_project_state", {}),
                ("hiwaga_authority", {"target": "art-source/x"}),
                ("hiwaga_preflight", {"operation": "READ_REFERENCE", "targets": ["x"]}),
            ):
                assert (await client.call_tool(name, arguments)).is_error is False, name

    _run(body)


def test_server_info_does_not_expose_worker_identity() -> None:
    server = _server("codex", "model-A")

    async def body() -> None:
        async with Client(server) as client:
            payload = (await client.call_tool("hiwaga_server_info", {})).structured_content
            assert set(payload) == set(ServerInfoResult.model_fields)
            assert "worker" not in json.dumps(payload).lower().replace("worker/model", "")

    _run(body)


def test_the_packaged_policy_is_used_when_no_override_is_given() -> None:
    server = build_server(config=None, identity=WorkerIdentity("codex", "gpt-5.6-luna"))

    async def body() -> None:
        async with Client(server) as client:
            allowed = await client.call_tool(TOOL, {"task_class": "BOUNDED_IMPLEMENTATION"})
            assert allowed.structured_content["decision"] == "ALLOW"
            undefined = await client.call_tool(TOOL, {"task_class": "BUG_DIAGNOSIS"})
            assert undefined.structured_content["decision"] == "AMBIGUITY"
            human = await client.call_tool(TOOL, {"task_class": "OPERATOR_REVIEW"})
            assert human.structured_content["decision"] == "HUMAN_REQUIRED"
            not_luna = await client.call_tool(TOOL, {"task_class": "EVIDENCE_AUDIT"})
            assert not_luna.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_MODEL_DENIED"

    _run(body)


def test_environment_built_server_reads_identity_from_the_two_variables(
    monkeypatch: pytest.MonkeyPatch, state_repo: Path
) -> None:
    monkeypatch.setenv(REPO_ROOT_ENV_VAR, str(state_repo))
    monkeypatch.setenv(WORKER_ENV_VAR, "codex")
    monkeypatch.setenv(MODEL_ENV_VAR, "gpt-5.6-sol")
    server = create_server_from_environment()

    async def body() -> None:
        result = await _call(server, {"task_class": "EXECUTION_BOUNDARY_CHANGE"})
        assert result.structured_content["decision"] == "ALLOW"
        assert result.structured_content["model"] == "gpt-5.6-sol"

    _run(body)


def test_environment_built_server_starts_without_identity_and_reports_it_unavailable(
    monkeypatch: pytest.MonkeyPatch, state_repo: Path
) -> None:
    monkeypatch.setenv(REPO_ROOT_ENV_VAR, str(state_repo))
    monkeypatch.delenv(WORKER_ENV_VAR, raising=False)
    monkeypatch.delenv(MODEL_ENV_VAR, raising=False)
    server = create_server_from_environment()

    async def body() -> None:
        async with Client(server) as client:
            assert (await client.call_tool("hiwaga_server_info", {})).is_error is False
            gate = await client.call_tool(TOOL, {"task_class": "BOUNDED_IMPLEMENTATION"})
            assert gate.structured_content["reason_code"] == "HIWAGA_MODEL_GATE_IDENTITY_UNAVAILABLE"

    _run(body)


def test_environment_built_server_works_when_the_repository_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(REPO_ROOT_ENV_VAR, raising=False)
    monkeypatch.setenv(WORKER_ENV_VAR, "codex")
    monkeypatch.setenv(MODEL_ENV_VAR, "gpt-5.6-luna")
    server = create_server_from_environment()

    async def body() -> None:
        result = await _call(server, {"task_class": "RELEASE_REVIEW"})
        assert result.is_error is False
        assert result.structured_content["decision"] == "ALLOW"

    _run(body)


def test_fixture_policy_helper_is_valid_and_independent_per_call() -> None:
    first, second = fixture_worker_policy(), fixture_worker_policy()
    first["task_classes"].clear()
    assert second["task_classes"]
