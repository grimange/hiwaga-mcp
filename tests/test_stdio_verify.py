"""`hiwaga_verify` over a real stdio transport, in a real server subprocess.

Two angles:

* the shipped `python -m hiwaga_mcp` entrypoint driving the canonical packaged
  registry, proving PASS and FAIL end to end with nothing substituted;
* a test launcher with a fixture registry, proving TIMEOUT survives the same
  transport without waiting out a production-sized deadline.

Neither touches a real HIWAGA checkout, and neither starts Godot.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client, StdioServerParameters

from .conftest import (
    fixture_registry,
    install_fixture_verifiers,
    install_repo_python,
    make_hiwaga_repo,
    registry_text,
)

HANDSHAKE_TIMEOUT_SECONDS = 60.0

#: The script the packaged `asset_authority` entry names. A fixture repository
#: supplies its own copy so the shipped registry can be exercised without a
#: real HIWAGA checkout.
PACKAGED_ASSET_AUTHORITY_SCRIPT = "tools/verify_asset_authority.py"


def _child_environment(repo_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HIWAGA_REPO_ROOT"] = str(repo_root)
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = os.pathsep.join([src, env["PYTHONPATH"]]) if env.get("PYTHONPATH") else src
    return env


def entrypoint_parameters(repo_root: Path) -> StdioServerParameters:
    """The shipped entrypoint, with the canonical packaged registry."""
    return StdioServerParameters(
        command=sys.executable, args=["-m", "hiwaga_mcp"], env=_child_environment(repo_root)
    )


def launcher_parameters(repo_root: Path, registry_file: Path) -> StdioServerParameters:
    """The test launcher, with a fixture registry substituted at construction."""
    launcher = Path(__file__).resolve().parent / "stdio_verify_server.py"
    return StdioServerParameters(
        command=sys.executable,
        args=[str(launcher), str(repo_root), str(registry_file)],
        env=_child_environment(repo_root),
    )


def over_stdio(parameters: StdioServerParameters, arguments: dict[str, Any]) -> Any:
    """Start a real server subprocess, call `hiwaga_verify`, and shut it down."""

    async def body() -> Any:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(parameters) as client:
                return await client.call_tool("hiwaga_verify", arguments)

    try:
        return anyio.run(body)
    except TimeoutError as exc:  # pragma: no cover - only on a hung server
        pytest.fail(f"stdio verification did not complete in time: {exc}")


def packaged_repo(tmp_path: Path, script_body: str) -> Path:
    """A fixture checkout supplying the script the packaged registry names."""
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    install_repo_python(root)
    script = root / PACKAGED_ASSET_AUTHORITY_SCRIPT
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(script_body, encoding="utf-8")
    return root


def fixture_registry_repo(tmp_path: Path) -> tuple[Path, Path]:
    """A fixture checkout plus a registry file on disk for the test launcher."""
    root = make_hiwaga_repo(tmp_path / "hiwaga")
    install_repo_python(root)
    install_fixture_verifiers(root)
    registry_file = tmp_path / "registry.json"
    registry_file.write_text(registry_text(), encoding="utf-8")
    return root, registry_file


# --- the shipped entrypoint with the canonical packaged registry -------------


def test_packaged_verifier_passes_over_stdio(tmp_path: Path) -> None:
    root = packaged_repo(tmp_path, 'print("PASS: boundary intact")\nraise SystemExit(0)\n')
    result = over_stdio(entrypoint_parameters(root), {"verifier": "asset_authority"})

    assert result.is_error is False
    payload = result.structured_content
    assert payload["status"] == "PASS"
    assert payload["verifier"] == "asset_authority"
    assert payload["mode"] == "default"
    assert payload["proof_class"] == "STRUCTURAL"
    assert payload["exit_code"] == 0
    assert "boundary intact" in payload["stdout_tail"]


def test_packaged_verifier_fails_over_stdio(tmp_path: Path) -> None:
    """A real FAIL crosses the transport as a result, not a protocol error."""
    root = packaged_repo(
        tmp_path,
        'import sys\nprint("FAIL: a sentinel is missing", file=sys.stderr)\nraise SystemExit(1)\n',
    )
    result = over_stdio(entrypoint_parameters(root), {"verifier": "asset_authority"})

    assert result.is_error is False
    payload = result.structured_content
    assert payload["status"] == "FAIL"
    assert payload["exit_code"] == 1
    assert "a sentinel is missing" in payload["stderr_tail"]


def test_packaged_registry_rejects_an_unknown_verifier_over_stdio(tmp_path: Path) -> None:
    root = packaged_repo(tmp_path, "raise SystemExit(0)\n")
    result = over_stdio(entrypoint_parameters(root), {"verifier": "arbitrary_command"})

    assert result.is_error is True
    text = " ".join(block.text for block in result.content if getattr(block, "text", None))
    assert "HIWAGA_UNKNOWN_VERIFIER" in text


def test_packaged_registry_is_the_one_the_entrypoint_loads(tmp_path: Path) -> None:
    """The shipped server exposes exactly the seeded verifiers, and no way to add more."""
    root = packaged_repo(tmp_path, "raise SystemExit(0)\n")

    async def body() -> Any:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(entrypoint_parameters(root)) as client:
                return await client.call_tool("hiwaga_verify", {"verifier": "player_v2_motion_review"})

    # The seeded headless verifier is registered; it fails to run here only
    # because this fixture repository has no such script.
    result = anyio.run(body)
    assert result.is_error is False
    assert result.structured_content["proof_class"] == "HEADLESS"


def test_run_artifacts_land_in_the_scratch_tree_over_stdio(tmp_path: Path) -> None:
    root = packaged_repo(tmp_path, 'print("PASS")\nraise SystemExit(0)\n')
    payload = over_stdio(entrypoint_parameters(root), {"verifier": "asset_authority"}).structured_content

    run_directory = root / payload["run_directory"]
    assert run_directory.is_dir()
    assert (root / payload["stdout_log"]).is_file()
    assert payload["run_directory"].startswith(".hiwaga-mcp/runs/")


# --- the fixture registry, for a fast deadline -------------------------------


def test_timeout_survives_the_stdio_transport(tmp_path: Path) -> None:
    """A terminated verifier is a structured result over a real transport."""
    root, registry_file = fixture_registry_repo(tmp_path)
    result = over_stdio(launcher_parameters(root, registry_file), {"verifier": "slow"})

    assert result.is_error is False
    payload = result.structured_content
    assert payload["status"] == "TIMEOUT"
    assert payload["timed_out"] is True


def test_pass_and_fail_survive_the_stdio_transport(tmp_path: Path) -> None:
    root, registry_file = fixture_registry_repo(tmp_path)
    parameters = launcher_parameters(root, registry_file)

    passed = over_stdio(parameters, {"verifier": "structural"})
    assert passed.is_error is False
    assert passed.structured_content["status"] == "PASS"

    failed = over_stdio(parameters, {"verifier": "failing"})
    assert failed.is_error is False
    assert failed.structured_content["status"] == "FAIL"


def test_server_stays_usable_after_a_timeout(tmp_path: Path) -> None:
    """Terminating a verifier does not damage the session it ran in."""
    root, registry_file = fixture_registry_repo(tmp_path)

    async def body() -> tuple[Any, Any]:
        with anyio.fail_after(HANDSHAKE_TIMEOUT_SECONDS):
            async with Client(launcher_parameters(root, registry_file)) as client:
                timed_out = await client.call_tool("hiwaga_verify", {"verifier": "slow"})
                after = await client.call_tool("hiwaga_verify", {"verifier": "structural"})
                return timed_out, after

    timed_out, after = anyio.run(body)
    assert timed_out.structured_content["status"] == "TIMEOUT"
    assert after.is_error is False
    assert after.structured_content["status"] == "PASS"


def test_large_verifier_output_does_not_bloat_the_stdio_response(tmp_path: Path) -> None:
    root, registry_file = fixture_registry_repo(tmp_path)
    payload = over_stdio(launcher_parameters(root, registry_file), {"verifier": "noisy"}).structured_content

    assert payload["stdout_bytes"] > 20000
    assert len(json.dumps(payload)) < 20000
    assert payload["output_truncated"] is True


def test_descendants_do_not_survive_a_stdio_timeout(tmp_path: Path) -> None:
    root, registry_file = fixture_registry_repo(tmp_path)
    payload = over_stdio(launcher_parameters(root, registry_file), {"verifier": "spawner"}).structured_content

    assert payload["status"] == "TIMEOUT"
    marker = root / payload["run_directory"] / "child.pid"
    assert marker.exists(), "the fixture grandchild never started"

    first = marker.read_text()
    anyio.run(anyio.sleep, 1.0)
    assert marker.read_text() == first, "a descendant survived the stdio timeout"


def test_registry_seed_is_reported_for_a_fixture_registry(tmp_path: Path) -> None:
    """The launcher really does substitute the registry it was given."""
    root, registry_file = fixture_registry_repo(tmp_path)
    result = over_stdio(launcher_parameters(root, registry_file), {"verifier": "asset_authority"})
    assert result.is_error is True
    assert set(fixture_registry()["verifiers"]) == {
        "structural",
        "failing",
        "slow",
        "noisy",
        "spawner",
    }
