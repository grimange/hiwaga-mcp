"""MCP protocol adapter.

This module registers the server and its tools and does nothing else. All
behaviour is delegated to `hiwaga_mcp.config` and `hiwaga_mcp.services`.

Transport for P0 is stdio only.
"""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from hiwaga_mcp import SERVER_NAME, SERVER_TITLE, __version__
from hiwaga_mcp.config import (
    REPO_ROOT_ENV_VAR,
    ServerConfig,
    WorkerIdentity,
    load_config,
    load_worker_identity,
)
from hiwaga_mcp.errors import ConfigurationError, HiwagaError, RepositoryIdentityError
from hiwaga_mcp.models.authority import AuthorityResult
from hiwaga_mcp.models.common import ErrorDetail
from hiwaga_mcp.models.diagnostics import ConfigurationStatus, ServerInfoResult
from hiwaga_mcp.models.model_gate import ModelGateResult, TaskClass
from hiwaga_mcp.models.preflight import PreflightOperation, PreflightRequest, PreflightResult
from hiwaga_mcp.models.state import ProjectStateResult
from hiwaga_mcp.models.verification import VerificationResult
from hiwaga_mcp.services.authority import resolve_authority
from hiwaga_mcp.services.model_gate import run_model_gate
from hiwaga_mcp.services.preflight import run_preflight
from hiwaga_mcp.services.project_state import get_project_state
from hiwaga_mcp.services.repository import validate_repository_identity
from hiwaga_mcp.services.verification import run_verification

logger = logging.getLogger(__name__)


def _refusal(error: HiwagaError) -> ToolError:
    """Render a deterministic refusal: the stable reason code leads the message."""
    return ToolError(f"{error.code.value}: {error.message}")


def build_server(
    config: ServerConfig | None = None,
    config_error: ConfigurationError | None = None,
    identity: WorkerIdentity | None = None,
    worker_policy_text: str | None = None,
    verifier_registry_text: str | None = None,
) -> MCPServer:
    """Construct the MCP server.

    Args:
        identity: The trusted worker/model identity for `hiwaga_model_gate`. None
            means not configured; no tool argument can supply or override it.
        worker_policy_text: A construction-time seam to substitute the canonical
            worker policy (for tests). Never reachable from a tool call.
        verifier_registry_text: The same seam for the canonical verifier registry.
            Never reachable from a tool call, so no caller can widen the
            execution allowlist.
        config: Validated configuration, or None when configuration failed.
        config_error: The failure that produced `config is None`, so the
            diagnostic tool can report it. Passing neither means the server
            reports an unconfigured root.

    A configuration failure does not prevent the server from starting: the
    diagnostic tool exists precisely to report that state. This is not a
    fallback to the working directory — no repository is assumed.
    """
    server = MCPServer(
        name=SERVER_NAME,
        title=SERVER_TITLE,
        version=__version__,
        instructions=(
            "Deterministic control plane for the HIWAGA game repository. "
            "This server reports and enforces repository-defined state, authority, "
            "policy, and proof boundaries. It does not perform development work and "
            "exposes no arbitrary shell or filesystem access."
        ),
    )

    @server.tool(
        name="hiwaga_server_info",
        title="HIWAGA server info",
        description=(
            "Report this control plane's identity, its configured HIWAGA repository "
            "root, and whether that root is a valid HIWAGA checkout. Bootstrap "
            "diagnostic only; it reports no project state."
        ),
    )
    def hiwaga_server_info() -> ServerInfoResult:
        if config is None:
            error = config_error or ConfigurationError(
                f"{REPO_ROOT_ENV_VAR} is not configured for this server process.",
                details={"env_var": REPO_ROOT_ENV_VAR, "problem": "not_set"},
            )
            return ServerInfoResult(
                server_name=SERVER_NAME,
                server_version=__version__,
                product=SERVER_TITLE,
                configuration_status=ConfigurationStatus.INVALID,
                configured_repo_root=None,
                repository_identity=None,
                configuration_error=ErrorDetail.from_error(error),
            )

        return ServerInfoResult(
            server_name=SERVER_NAME,
            server_version=__version__,
            product=SERVER_TITLE,
            configuration_status=ConfigurationStatus.CONFIGURED,
            configured_repo_root=str(config.repo_root),
            repository_identity=validate_repository_identity(config.repo_root),
            configuration_error=None,
        )

    @server.tool(
        name="hiwaga_project_state",
        title="HIWAGA project state",
        description=(
            "Report the current deterministic development state of the configured HIWAGA "
            "repository: Git branch/HEAD/worktree facts plus the fields declared in the first "
            "`##` block of docs/progress/HIWAGA_PROGRESS.md. Takes no arguments; the repository "
            "is always the configured HIWAGA_REPO_ROOT. Refuses with a stable reason code "
            "instead of returning partial state."
        ),
    )
    def hiwaga_project_state() -> ProjectStateResult:
        if config is None:
            raise _refusal(
                config_error
                or ConfigurationError(
                    f"{REPO_ROOT_ENV_VAR} is not configured for this server process.",
                    details={"env_var": REPO_ROOT_ENV_VAR, "problem": "not_set"},
                )
            )
        try:
            return get_project_state(config.repo_root)
        except HiwagaError as exc:
            raise _refusal(exc) from exc

    @server.tool(
        name="hiwaga_authority",
        title="HIWAGA asset authority",
        description=(
            "Report the asset authority that applies to a repository-relative target, read only "
            "from art-source/ASSET_AUTHORITY.json. Returns RESOLVED with the owning asset's "
            "declared authority fields, UNRESOLVED when no asset owns the target, or CONFLICT "
            "when several do; the last two are normal results, not errors. The repository is "
            "always the configured HIWAGA_REPO_ROOT. Refuses with a stable reason code when the "
            "target escapes the repository or the manifest cannot be trusted."
        ),
    )
    def hiwaga_authority(target: str) -> AuthorityResult:
        if config is None:
            raise _refusal(
                config_error
                or ConfigurationError(
                    f"{REPO_ROOT_ENV_VAR} is not configured for this server process.",
                    details={"env_var": REPO_ROOT_ENV_VAR, "problem": "not_set"},
                )
            )
        try:
            return resolve_authority(config.repo_root, target)
        except HiwagaError as exc:
            raise _refusal(exc) from exc

    @server.tool(
        name="hiwaga_preflight",
        title="HIWAGA preflight",
        description=(
            "Decide whether a structured operation on repository-relative targets is currently "
            "permitted, from the current project state and asset authority. Returns ALLOW, DENY, "
            "AMBIGUITY, or HUMAN_REQUIRED as an ordinary result with per-target evidence; it "
            "executes nothing and selects no worker or model. The repository is always the "
            "configured HIWAGA_REPO_ROOT. Refuses with a stable reason code only when a "
            "prerequisite fails (configuration, identity, project state, a target outside the "
            "repository, or an untrustworthy authority manifest)."
        ),
    )
    def hiwaga_preflight(
        operation: PreflightOperation,
        targets: Annotated[list[str], Field(min_length=1)],
    ) -> PreflightResult:
        if config is None:
            raise _refusal(
                config_error
                or ConfigurationError(
                    f"{REPO_ROOT_ENV_VAR} is not configured for this server process.",
                    details={"env_var": REPO_ROOT_ENV_VAR, "problem": "not_set"},
                )
            )
        try:
            return run_preflight(config.repo_root, PreflightRequest(operation=operation, targets=targets))
        except HiwagaError as exc:
            raise _refusal(exc) from exc

    @server.tool(
        name="hiwaga_model_gate",
        title="HIWAGA model gate",
        description=(
            "Decide whether the AI worker/model this server process is configured with "
            "(HIWAGA_AI_WORKER / HIWAGA_AI_MODEL) is permitted for the supplied task class, from the "
            "canonical worker policy. The only input is the task class; identity cannot be supplied or "
            "overridden by the caller. Returns ALLOW, DENY, AMBIGUITY (undefined policy or unconfigured "
            "identity), or HUMAN_REQUIRED as an ordinary result. Independent of the repository, project "
            "state, and preflight. Refuses with a stable reason code only when the policy itself is invalid."
        ),
    )
    def hiwaga_model_gate(task_class: TaskClass) -> ModelGateResult:
        try:
            return run_model_gate(task_class, identity or WorkerIdentity(), policy_text=worker_policy_text)
        except HiwagaError as exc:
            raise _refusal(exc) from exc

    @server.tool(
        name="hiwaga_verify",
        title="HIWAGA verify",
        description=(
            "Execute one registered HIWAGA verification operation and report a typed result. "
            "The caller selects only a registered verifier id and one of its declared modes; the "
            "executable, arguments, working directory, timeout, environment, and proof class all "
            "come from the canonical verifier registry, and no arbitrary command can be run. "
            "Returns PASS, FAIL, TIMEOUT, or EXECUTION_ERROR as an ordinary result — a verifier "
            "that finds a defect is a FAIL, not a tool error. Complete logs are written to an "
            "ignored scratch run directory and only a bounded tail is returned. Independent of "
            "preflight and the model gate, which it never calls."
        ),
    )
    async def hiwaga_verify(
        verifier: Annotated[str, Field(description="Registered verifier id.")],
        mode: Annotated[
            str | None,
            Field(default=None, description="Declared mode; omitted uses the registry default."),
        ] = None,
    ) -> VerificationResult:
        if config is None:
            raise _refusal(
                config_error
                or ConfigurationError(
                    f"{REPO_ROOT_ENV_VAR} is not configured for this server process.",
                    details={"env_var": REPO_ROOT_ENV_VAR, "problem": "not_set"},
                )
            )
        identity_report = validate_repository_identity(config.repo_root)
        if identity_report.error is not None:
            raise _refusal(
                RepositoryIdentityError(identity_report.error.message, details=identity_report.error.details)
            )
        try:
            return await run_verification(
                config.repo_root, verifier, mode, registry_text=verifier_registry_text
            )
        except HiwagaError as exc:
            raise _refusal(exc) from exc

    return server


def create_server_from_environment() -> MCPServer:
    """Build the server from the process environment, reporting config failure.

    Configuration failure is logged to stderr and surfaced through
    `hiwaga_server_info` rather than aborting startup.
    """
    identity = load_worker_identity()
    try:
        return build_server(config=load_config(), identity=identity)
    except ConfigurationError as exc:
        logger.warning("%s: %s", exc.code.value, exc.message)
        return build_server(config=None, config_error=exc, identity=identity)


def main() -> None:
    """Run the control plane over stdio."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    create_server_from_environment().run("stdio")


__all__ = ["build_server", "create_server_from_environment", "main"]
