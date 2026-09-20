"""External runtime-state resolution: state root, repository key, run directory.

These are pure functions, tested entirely through the `env` mapping seam so no
test ever touches the real process environment or the operator's real
`~/.local/state`. The autouse `_isolated_runtime_state_home` fixture protects
every other test in the suite the same way, at the `os.environ` level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hiwaga_mcp.errors import ReasonCode, RuntimeStateError
from hiwaga_mcp.services.runtime_state import (
    REPOSITORY_KEY_LENGTH,
    STATE_APP_NAME,
    repository_state_key,
    resolve_run_directory,
    resolve_state_root,
)

# --- state root: XDG_STATE_HOME ----------------------------------------------


def test_xdg_state_home_is_used_when_absolute() -> None:
    assert resolve_state_root({"XDG_STATE_HOME": "/tmp/state"}) == Path("/tmp/state/hiwaga-mcp")


def test_state_root_is_named_after_the_app() -> None:
    assert resolve_state_root({"XDG_STATE_HOME": "/tmp/state"}).name == STATE_APP_NAME == "hiwaga-mcp"


def test_missing_xdg_state_home_falls_back_to_home_local_state() -> None:
    assert resolve_state_root({"HOME": "/home/fixture"}) == Path("/home/fixture/.local/state/hiwaga-mcp")


@pytest.mark.parametrize("value", ["", "   ", "\t"])
def test_blank_xdg_state_home_is_treated_as_unset(value: str) -> None:
    root = resolve_state_root({"XDG_STATE_HOME": value, "HOME": "/home/fixture"})
    assert root == Path("/home/fixture/.local/state/hiwaga-mcp")


@pytest.mark.parametrize("value", ["relative/state", "./state", "~/state", "state"])
def test_relative_or_tilde_xdg_state_home_is_ignored_deterministically(value: str) -> None:
    """A non-absolute value is never anchored to the CWD; it falls back instead."""
    root = resolve_state_root({"XDG_STATE_HOME": value, "HOME": "/home/fixture"})
    assert root == Path("/home/fixture/.local/state/hiwaga-mcp")


def test_xdg_state_home_with_surrounding_whitespace_is_trimmed() -> None:
    assert resolve_state_root({"XDG_STATE_HOME": "  /tmp/state  "}) == Path("/tmp/state/hiwaga-mcp")


def test_xdg_state_home_is_canonicalized() -> None:
    root = resolve_state_root({"XDG_STATE_HOME": "/tmp/./state/../state"})
    assert root == Path("/tmp/state/hiwaga-mcp")


# --- state root: HOME fallback ------------------------------------------------


def test_home_with_surrounding_whitespace_is_trimmed() -> None:
    assert resolve_state_root({"HOME": "  /home/fixture  "}) == Path("/home/fixture/.local/state/hiwaga-mcp")


def test_default_reads_the_real_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", "/home/real-fixture")
    assert resolve_state_root() == Path("/home/real-fixture/.local/state/hiwaga-mcp")


def test_no_usable_home_or_xdg_value_is_refused() -> None:
    with pytest.raises(RuntimeStateError) as info:
        resolve_state_root({})
    assert info.value.code is ReasonCode.RUNTIME_STATE_UNAVAILABLE
    assert info.value.details["problem"] == "no_home"


@pytest.mark.parametrize("home", ["", "   "])
def test_blank_home_is_refused(home: str) -> None:
    with pytest.raises(RuntimeStateError) as info:
        resolve_state_root({"HOME": home})
    assert info.value.details["problem"] == "no_home"


@pytest.mark.parametrize("home", ["relative/home", "~fixture", "./home"])
def test_non_absolute_home_is_refused_not_silently_anchored_to_cwd(home: str) -> None:
    with pytest.raises(RuntimeStateError) as info:
        resolve_state_root({"HOME": home})
    assert info.value.details["problem"] == "home_not_absolute"


def test_never_falls_back_into_the_hiwaga_repository(tmp_path: Path) -> None:
    """No matter how state resolution fails, it never returns a path under a repository."""
    with pytest.raises(RuntimeStateError):
        resolve_state_root({})
    # There is no code path in resolve_state_root that can see a repository root at all;
    # this documents that guarantee rather than exercising a specific escape.


# --- repository key ------------------------------------------------------------


def test_same_canonical_root_yields_the_same_key(tmp_path: Path) -> None:
    root = tmp_path / "hiwaga"
    root.mkdir()
    assert repository_state_key(root) == repository_state_key(root)
    assert repository_state_key(root) == repository_state_key(Path(str(root)))


def test_different_roots_yield_different_keys(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    assert repository_state_key(first) != repository_state_key(second)


def test_key_is_stable_across_equivalent_spellings_of_the_same_path(tmp_path: Path) -> None:
    root = tmp_path / "hiwaga"
    (root / "sub").mkdir(parents=True)
    messy = root / "sub" / ".." / "."
    assert repository_state_key(root) == repository_state_key(messy)


def test_key_is_stable_across_a_trailing_slash(tmp_path: Path) -> None:
    root = tmp_path / "hiwaga"
    root.mkdir()
    assert repository_state_key(root) == repository_state_key(Path(f"{root}/"))


def test_key_follows_a_symlinked_root_to_its_real_path(tmp_path: Path) -> None:
    real = tmp_path / "real-hiwaga"
    real.mkdir()
    link = tmp_path / "linked-hiwaga"
    link.symlink_to(real, target_is_directory=True)
    assert repository_state_key(link) == repository_state_key(real)


def test_key_does_not_depend_on_branch_or_head(tmp_path: Path) -> None:
    """The key is a pure function of the path; nothing here even looks at Git."""
    root = tmp_path / "hiwaga"
    root.mkdir()
    before = repository_state_key(root)
    (root / ".git").mkdir()  # simulates the repository moving through states
    (root / "HEAD").write_text("ref: refs/heads/feature\n", encoding="utf-8")
    after = repository_state_key(root)
    assert before == after


def test_key_is_a_short_deterministic_hex_digest(tmp_path: Path) -> None:
    root = tmp_path / "hiwaga"
    root.mkdir()
    key = repository_state_key(root)
    assert len(key) == REPOSITORY_KEY_LENGTH
    assert all(c in "0123456789abcdef" for c in key)


def test_key_is_not_the_basename_or_a_raw_path_hierarchy(tmp_path: Path) -> None:
    root = tmp_path / "hiwaga"
    root.mkdir()
    key = repository_state_key(root)
    assert key != root.name
    assert "/" not in key
    assert str(root) not in key


# --- run directory -------------------------------------------------------------


def test_run_directory_shape(tmp_path: Path) -> None:
    root = tmp_path / "hiwaga"
    root.mkdir()
    directory = resolve_run_directory(root, "abc123", env={"HOME": "/home/fixture"})
    key = repository_state_key(root)
    assert directory == Path(f"/home/fixture/.local/state/hiwaga-mcp/repositories/{key}/runs/abc123")


def test_run_directory_is_always_absolute(tmp_path: Path) -> None:
    root = tmp_path / "hiwaga"
    root.mkdir()
    assert resolve_run_directory(root, "abc123", env={"HOME": "/home/fixture"}).is_absolute()


def test_run_directory_state_root_failure_propagates() -> None:
    with pytest.raises(RuntimeStateError):
        resolve_run_directory(Path("/nonexistent/hiwaga"), "abc123", env={})


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "", "  ", "a\x00b", "a/../../etc"])
def test_unsafe_run_id_is_refused_not_joined_into_a_path(tmp_path: Path, run_id: str) -> None:
    root = tmp_path / "hiwaga"
    root.mkdir()
    with pytest.raises(RuntimeStateError) as info:
        resolve_run_directory(root, run_id, env={"HOME": "/home/fixture"})
    assert info.value.code is ReasonCode.RUNTIME_STATE_UNAVAILABLE
    assert info.value.details["problem"] == "unsafe_path_component"


def test_a_real_uuid4_hex_run_id_is_accepted(tmp_path: Path) -> None:
    import uuid

    root = tmp_path / "hiwaga"
    root.mkdir()
    run_id = uuid.uuid4().hex
    directory = resolve_run_directory(root, run_id, env={"HOME": "/home/fixture"})
    assert directory.name == run_id


def test_no_target_or_verifier_supplied_string_reaches_this_function(tmp_path: Path) -> None:
    """Only the internally generated run id is a variable path component here."""
    root = tmp_path / "hiwaga"
    root.mkdir()
    # A verifier id or mode name is never a parameter of this function at all,
    # so there is no argument through which either could shape the path.
    import inspect

    parameters = set(inspect.signature(resolve_run_directory).parameters)
    assert parameters == {"repo_root", "run_id", "env"}
