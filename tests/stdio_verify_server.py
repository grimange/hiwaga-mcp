"""Test-only stdio launcher with a substituted verifier registry.

`python -m hiwaga_mcp` always loads the canonical packaged registry, whose
timeouts are sized for real HIWAGA verifiers. This launcher builds the same
server through the same construction seam `build_server` already exposes, but
with a fixture registry, so a TIMEOUT can be proven over a real stdio transport
in about a second instead of two minutes.

It is a test artifact. It adds no production surface: nothing here is reachable
from a tool call, and the shipped entrypoint has no registry override.

Usage: python tests/stdio_verify_server.py <repo_root> <registry.json>
"""

from __future__ import annotations

import sys
from pathlib import Path

from hiwaga_mcp.config import ServerConfig
from hiwaga_mcp.server import build_server


def main() -> None:
    repo_root = Path(sys.argv[1]).resolve()
    registry_text = Path(sys.argv[2]).read_text(encoding="utf-8")
    build_server(
        config=ServerConfig(repo_root=repo_root),
        verifier_registry_text=registry_text,
    ).run("stdio")


if __name__ == "__main__":
    main()
