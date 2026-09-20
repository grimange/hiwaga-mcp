"""Independently testable domain services.

MCP tool adapters stay thin; behaviour lives here.
"""

from __future__ import annotations

from hiwaga_mcp.services.authority import resolve_authority
from hiwaga_mcp.services.context import get_context
from hiwaga_mcp.services.context_routing import (
    load_context_routing_mapping,
    parse_canon_document,
    parse_context_routing_mapping,
    read_canon_document,
)
from hiwaga_mcp.services.project_state import get_project_state
from hiwaga_mcp.services.repository import (
    REQUIRED_SENTINELS,
    resolve_within_repository,
    validate_repository_identity,
)
from hiwaga_mcp.services.runtime_state import (
    repository_state_key,
    resolve_run_directory,
    resolve_state_root,
)
from hiwaga_mcp.services.verification import build_execution_plan, execute_plan, run_verification
from hiwaga_mcp.services.verification_registry import (
    load_verifier_registry,
    parse_verifier_registry,
    select_verifier,
)

__all__ = [
    "REQUIRED_SENTINELS",
    "build_execution_plan",
    "execute_plan",
    "get_context",
    "get_project_state",
    "load_context_routing_mapping",
    "load_verifier_registry",
    "parse_canon_document",
    "parse_context_routing_mapping",
    "parse_verifier_registry",
    "read_canon_document",
    "repository_state_key",
    "resolve_authority",
    "resolve_run_directory",
    "resolve_state_root",
    "resolve_within_repository",
    "run_verification",
    "select_verifier",
    "validate_repository_identity",
]
