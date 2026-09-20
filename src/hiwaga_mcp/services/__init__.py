"""Independently testable domain services.

MCP tool adapters stay thin; behaviour lives here.
"""

from __future__ import annotations

from hiwaga_mcp.services.project_state import get_project_state
from hiwaga_mcp.services.repository import (
    REQUIRED_SENTINELS,
    resolve_within_repository,
    validate_repository_identity,
)

__all__ = [
    "REQUIRED_SENTINELS",
    "get_project_state",
    "resolve_within_repository",
    "validate_repository_identity",
]
