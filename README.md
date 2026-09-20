# hiwaga-mcp

**HIWAGA Development & Evidence Control Plane** — a local-first, deterministic MCP
server for the HIWAGA game repository.

This server is an instrument and control plane. It reports and enforces
repository-defined state, authority, policy, and proof boundaries. It is not an
autonomous coding agent, a generic shell or filesystem MCP, or a Git/GitHub wrapper.

See `AGENTS.md` for the repository engineering contract.

---

## Status

This repository currently contains the **P0 bootstrap foundation only**. The planned
product tools are not implemented yet. See [Scope](#scope) below for exactly what
exists today.

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
  `HIWAGA_REPOSITORY_IDENTITY_INVALID`, `HIWAGA_TARGET_OUTSIDE_REPOSITORY`.
- Typed vocabularies for later work: `GateDecision`, `VerificationStatus`,
  `ProofClass`.
- One bootstrap diagnostic tool, `hiwaga_server_info`, with typed structured output.

`hiwaga_server_info` reports server name and version, the configured repository
root, and the identity verdict for that root. It reports **no project state** and
is not a partial implementation of any planned tool.

### Planned P0 tools — not implemented

```text
hiwaga_project_state
hiwaga_context
hiwaga_authority
hiwaga_preflight
hiwaga_model_gate
hiwaga_verify
```

### Deferred — not implemented

Verifier registry and subprocess verifier execution, worker/model policy
evaluation, progress-ledger parsing, CANON routing, asset-authority resolution,
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
└── services/repository.py identity validation and path containment
```

MCP tool adapters stay thin; behaviour lives in services and is tested directly.
