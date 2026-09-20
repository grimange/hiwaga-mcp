# hiwaga-mcp

**HIWAGA Development & Evidence Control Plane** — a local-first, deterministic MCP
server for the HIWAGA game repository.

This server is an instrument and control plane. It reports and enforces
repository-defined state, authority, policy, and proof boundaries. It is not an
autonomous coding agent, a generic shell or filesystem MCP, or a Git/GitHub wrapper.

See `AGENTS.md` for the repository engineering contract.

---

## Status

This repository contains the **P0 bootstrap foundation** and the first product tool,
`hiwaga_project_state`. The remaining planned tools are not implemented yet. See
[Scope](#scope) below for exactly what exists today.

## Requirements

- Python 3.10 or newer
- Official Python MCP SDK v2 (`mcp[cli]==2.2.0`), installed as a dependency

## Install

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Configuration

The server operates only against an explicitly configured HIWAGA checkout.

| Variable | Required | Meaning |
| --- | --- | --- |
| `HIWAGA_REPO_ROOT` | yes | Absolute path to the HIWAGA checkout. `~` is expanded and the path is canonicalized. |

There is no fallback to the current working directory. If `HIWAGA_REPO_ROOT` is
unset, empty, missing on disk, or not a directory, the server still starts but
reports `HIWAGA_CONFIGURATION_INVALID` through `hiwaga_server_info` instead of
guessing at a repository.

A configured root is a valid HIWAGA checkout only when all of these are present:

```text
.git/                             (directory)
game/project.godot                (file)
docs/CANON.md                     (file)
docs/progress/HIWAGA_PROGRESS.md  (file)
art-source/ASSET_AUTHORITY.json   (file)
```

Otherwise identity is reported as `INVALID` with reason code
`HIWAGA_REPOSITORY_IDENTITY_INVALID` and the list of missing sentinels.

## Run

```bash
export HIWAGA_REPO_ROOT=/absolute/path/to/hiwaga
python -m hiwaga_mcp
```

The console script `hiwaga-mcp` is equivalent. stdio is the only transport.

Diagnostic logging goes to stderr; stdout carries the MCP transport.

## Test

```bash
pytest
```

Unit, protocol, and stdio tests all run against throwaway fixture repositories
under pytest's `tmp_path`. No test reads or mutates a real HIWAGA checkout, and
no test launches Godot or Blender.

Lint:

```bash
ruff check .
```

## Scope

### Implemented now

- Installable `hiwaga_mcp` package (src layout) with a `python -m hiwaga_mcp`
  stdio entrypoint.
- MCP server registration on the official Python MCP SDK v2 `MCPServer`.
- `HIWAGA_REPO_ROOT` parsing, normalization, and validation.
- HIWAGA repository identity validation from structural sentinels.
- Repository path containment, rejecting traversal, external absolute paths, and
  resolvable symlink escape.
- Stable reason codes: `HIWAGA_CONFIGURATION_INVALID`,
  `HIWAGA_REPOSITORY_IDENTITY_INVALID`, `HIWAGA_TARGET_OUTSIDE_REPOSITORY`,
  `HIWAGA_PROGRESS_DOCUMENT_INVALID`, `HIWAGA_PROJECT_STATE_UNAVAILABLE`.
- Typed vocabularies for later work: `GateDecision`, `VerificationStatus`,
  `ProofClass`.
- One bootstrap diagnostic tool, `hiwaga_server_info`, with typed structured output.
- `hiwaga_project_state`: the current deterministic development state of the
  configured HIWAGA repository (see below).

`hiwaga_server_info` reports server name and version, the configured repository
root, and the identity verdict for that root. It reports **no project state** and
remains available when configuration or identity is invalid.

### `hiwaga_project_state`

Takes **no arguments**. The repository is always the configured `HIWAGA_REPO_ROOT`;
a caller cannot supply another, and the working directory is never used.

It returns Git facts plus the fields declared in the **first `##` block** of
`docs/progress/HIWAGA_PROGRESS.md`. That block is the sole current-state authority;
later blocks are history and never contribute a value.

| Field | Source |
| --- | --- |
| `repository`, `repository_root` | validated identity |
| `branch` (null when detached), `head` (full SHA), `detached_head` | Git |
| `worktree_clean`, `worktree_change_count` | `git status --porcelain=v1`, tracked and untracked, one entry per untracked file |
| `phase`, `current_focus`, `status`, `design_question`, `player_goal`, `success_condition`, `next_bounded_step` | matching labels in the current block, verbatim, else `null` |
| `ambiguity_gate` | `TARGET_CLEAR`, `TARGET_PARTIALLY_CONSTRAINED`, or `TARGET_AMBIGUOUS` when declared; `null` otherwise (absence is never `TARGET_CLEAR`) |
| `operator_required` | `true` only for explicit operator/human review, outing, playtest, or acceptance wording in the current block's focus, status, or next-step text |
| `progress_document`, `current_block_heading` | the ledger path and the block's heading text |
| `limitations` | deterministic notes on what could not be established |

Combined labels are never split: `Current Focus / Status` is reported whole in
`current_focus` (with `status` null), and `Design Question / Player Goal` whole in
`design_question` (with `player_goal` null), unless the second part is also declared
on its own line. A field may also be null because the current block simply does not
declare it. `operator_required: false` means "not explicitly declared", not "no
operator action exists". Git inspection is read-only.

The tool **refuses** instead of returning partial state. A refusal is an MCP tool
error (`is_error`) whose text begins with the stable reason code:

| Situation | Reason code |
| --- | --- |
| `HIWAGA_REPO_ROOT` unset or unusable | `HIWAGA_CONFIGURATION_INVALID` |
| configured root is not a HIWAGA checkout | `HIWAGA_REPOSITORY_IDENTITY_INVALID` |
| ledger empty, unreadable, not UTF-8, or has no `##` block | `HIWAGA_PROGRESS_DOCUMENT_INVALID` |
| ledger resolves outside the repository | `HIWAGA_TARGET_OUTSIDE_REPOSITORY` |
| Git missing, not a repository, or HEAD has no commit | `HIWAGA_PROJECT_STATE_UNAVAILABLE` |

### Planned P0 tools — not implemented

```text
hiwaga_context
hiwaga_authority
hiwaga_preflight
hiwaga_model_gate
hiwaga_verify
```

### Deferred — not implemented

Verifier registry and subprocess verifier execution, worker/model policy
evaluation, CANON routing, asset-authority resolution,
evidence capture and packaging, Godot and Blender integration, GitHub
integration, semantic search, embeddings, and any HTTP, OAuth, or remote
transport.

No verification, evidence, or authority capability exists in this repository yet.

## Runtime scratch state

Runtime output belongs under the ignored `.hiwaga-mcp/` directory (`runs/`,
`logs/`). Bootstrap does not create it; nothing is written there yet. Scratch
results are never automatically promoted to tracked evidence.

## Layout

```text
src/hiwaga_mcp/
├── __main__.py            module entrypoint
├── server.py              MCP adapter: registration only
├── config.py              HIWAGA_REPO_ROOT parsing and validation
├── errors.py              stable reason codes and exception types
├── models/                typed models and bounded vocabularies
└── services/
    ├── repository.py      identity validation and path containment
    ├── git_state.py       read-only Git branch/HEAD/worktree facts
    ├── progress.py        current-block parser for the progress ledger
    └── project_state.py   composes identity + ledger + Git into ProjectStateResult
```

MCP tool adapters stay thin; behaviour lives in services and is tested directly.
