"""Bootstrap diagnostic output.

This exists only to prove server registration, configuration loading, and
structured-output behaviour. It is not a partial implementation of any planned
P0 product tool.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from hiwaga_mcp.models.common import ErrorDetail
from hiwaga_mcp.models.project import RepositoryIdentityReport


class ConfigurationStatus(str, Enum):
    """Whether the server holds a usable `HIWAGA_REPO_ROOT`."""

    CONFIGURED = "CONFIGURED"
    INVALID = "INVALID"


class ServerInfoResult(BaseModel):
    """What this server is, and what it currently points at."""

    model_config = ConfigDict(frozen=True)

    server_name: str = Field(description="MCP server name.")
    server_version: str = Field(description="Package version of hiwaga-mcp.")
    product: str = Field(description="Human-readable product identity.")
    configuration_status: ConfigurationStatus = Field(description="State of the repository configuration.")
    configured_repo_root: str | None = Field(
        default=None,
        description="Canonicalized configured root; null when configuration is INVALID.",
    )
    repository_identity: RepositoryIdentityReport | None = Field(
        default=None,
        description="Identity verdict for the configured root; null when configuration is INVALID.",
    )
    configuration_error: ErrorDetail | None = Field(
        default=None,
        description="Populated when configuration_status is INVALID.",
    )


__all__ = ["ConfigurationStatus", "ServerInfoResult"]
