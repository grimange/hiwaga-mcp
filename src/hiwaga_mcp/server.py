"""MCP protocol adapter.

This module registers the server and its tools and does nothing else. All
behaviour is delegated to `hiwaga_mcp.config` and `hiwaga_mcp.services`.

Transport for P0 is stdio only.
"""

from __future__ import annotations

import logging

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from hiwaga_mcp import SERVER_NAME, SERVER_TITLE, __version__
from hiwaga_mcp.config import REPO_ROOT_ENV_VAR, ServerConfig, load_config
from hiwaga_mcp.errors import ConfigurationError, HiwagaError
from hiwaga_mcp.models.authority import AuthorityResult
from hiwaga_mcp.models.common import ErrorDetail
from hiwaga_mcp.models.diagnostics import ConfigurationStatus, ServerInfoResult
from hiwaga_mcp.models.state import ProjectStateResult
from hiwaga_mcp.services.authority import resolve_authority
from hiwaga_mcp.services.project_state import get_project_state
from hiwaga_mcp.services.repository import validate_repository_identity

logger = logging.getLogger(__name__)


def _refusal(error: HiwagaError) -> ToolError:
    """Render a deterministic refusal: the stable reason code leads the message."""
    return ToolError(f"{error.code.value}: {error.message}")


def build_server(
    config: ServerConfig | None = None,
    config_error: ConfigurationError | None = None,
) -> MCPServer:
    """Construct the MCP server.

    Args:
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

    return server


def create_server_from_environment() -> MCPServer:
    """Build the server from the process environment, reporting config failure.

    Configuration failure is logged to stderr and surfaced through
    `hiwaga_server_info` rather than aborting startup.
    """
    try:
        return build_server(config=load_config())
    except ConfigurationError as exc:
        logger.warning("%s: %s", exc.code.value, exc.message)
        return build_server(config=None, config_error=exc)


def main() -> None:
    """Run the control plane over stdio."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    create_server_from_environment().run("stdio")


__all__ = ["build_server", "create_server_from_environment", "main"]
