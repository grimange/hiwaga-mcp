"""Shared fixtures.

Every test runs against a throwaway fixture repository under pytest's tmp_path.
No test reads, writes, or otherwise touches the operator's live HIWAGA checkout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hiwaga_mcp.models.project import SentinelKind
from hiwaga_mcp.services.repository import REQUIRED_SENTINELS


def make_hiwaga_repo(root: Path, *, omit: tuple[str, ...] = ()) -> Path:
    """Create a minimal structure satisfying HIWAGA identity sentinels.

    Args:
        root: Directory to populate. Created if absent.
        omit: Repository-relative sentinel paths to deliberately leave out.
    """
    root.mkdir(parents=True, exist_ok=True)
    for relative, kind in REQUIRED_SENTINELS:
        if relative in omit:
            continue
        target = root / relative
        if kind is SentinelKind.DIRECTORY:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"fixture sentinel: {relative}\n", encoding="utf-8")
    return root


@pytest.fixture
def hiwaga_repo(tmp_path: Path) -> Path:
    """A valid fixture HIWAGA checkout."""
    return make_hiwaga_repo(tmp_path / "hiwaga")


@pytest.fixture
def outside_dir(tmp_path: Path) -> Path:
    """A directory that is a sibling of, and never inside, `hiwaga_repo`."""
    target = tmp_path / "outside"
    target.mkdir(parents=True, exist_ok=True)
    (target / "secret.txt").write_text("outside\n", encoding="utf-8")
    return target
