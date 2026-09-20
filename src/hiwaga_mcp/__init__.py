"""HIWAGA Development & Evidence Control Plane.

A local-first, deterministic MCP control plane for the HIWAGA game repository.

This package is an instrument and control plane. It reports and enforces
repository-defined state, authority, policy, and proof boundaries. It does not
perform autonomous development work.
"""

from __future__ import annotations

SERVER_NAME = "hiwaga-mcp"
SERVER_TITLE = "HIWAGA Development & Evidence Control Plane"
__version__ = "0.1.0"

__all__ = ["SERVER_NAME", "SERVER_TITLE", "__version__"]
