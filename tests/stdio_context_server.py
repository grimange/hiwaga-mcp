"""Test-only stdio launcher with a substituted context routing mapping.

`python -m hiwaga_mcp` always loads the canonical packaged mapping, sized for
the real HIWAGA `docs/CANON.md`. This launcher builds the same server through
the same construction seam `build_server` already exposes, but with a fixture
mapping matched to a fixture CANON, so representative domains can be proven
over a real stdio transport without a real HIWAGA checkout.

It is a test artifact. It adds no production surface: nothing here is
reachable from a tool call, and the shipped entrypoint has no mapping override.

Usage: python tests/stdio_context_server.py <repo_root> <context_routing.json>
"""

from __future__ import annotations

import sys
from pathlib import Path

from hiwaga_mcp.config import ServerConfig
from hiwaga_mcp.server import build_server


def main() -> None:
    repo_root = Path(sys.argv[1]).resolve()
    mapping_text = Path(sys.argv[2]).read_text(encoding="utf-8")
    build_server(
        config=ServerConfig(repo_root=repo_root),
        context_routing_text=mapping_text,
    ).run("stdio")


if __name__ == "__main__":
    main()
