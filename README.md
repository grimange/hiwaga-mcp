# hiwaga-mcp

**HIWAGA Development & Evidence Control Plane** — a local-first, deterministic MCP
server for the HIWAGA game repository.

This server is an instrument and control plane. It reports and enforces
repository-defined state, authority, policy, and proof boundaries. It is not an
autonomous coding agent, a generic shell or filesystem MCP, or a Git/GitHub wrapper.

See `AGENTS.md` for the repository engineering contract.

---

## Status

This repository contains the **P0 bootstrap foundation** and all six planned P0
product tools: `hiwaga_project_state`, `hiwaga_context`, `hiwaga_authority`,
`hiwaga_preflight`, `hiwaga_model_gate`, and `hiwaga_verify`. See
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
| `HIWAGA_AI_WORKER` | only for `hiwaga_model_gate` | Trusted worker id of this process (e.g. `codex`, `claude-code`). |
| `HIWAGA_AI_MODEL` | only for `hiwaga_model_gate` | Trusted exact model id of this process. |

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
  `HIWAGA_PROGRESS_DOCUMENT_INVALID`, `HIWAGA_PROJECT_STATE_UNAVAILABLE`,
  `HIWAGA_ASSET_AUTHORITY_INVALID`, `HIWAGA_WORKER_POLICY_INVALID`,
  `HIWAGA_VERIFIER_REGISTRY_INVALID`, `HIWAGA_UNKNOWN_VERIFIER`,
  `HIWAGA_UNSUPPORTED_VERIFY_MODE`, `HIWAGA_RUNTIME_STATE_UNAVAILABLE`,
  `HIWAGA_CONTEXT_ROUTING_INVALID`.
- Typed vocabularies for later work: `GateDecision`, `VerificationStatus`,
  `ProofClass`.
- One bootstrap diagnostic tool, `hiwaga_server_info`, with typed structured output.
- `hiwaga_project_state`: the current deterministic development state of the
  configured HIWAGA repository (see below).
- `hiwaga_context`: which repository sources currently govern or support one
  explicit HIWAGA context domain, routed deterministically from `docs/CANON.md`
  (see below).
- `hiwaga_authority`: the asset authority that applies to a repository-relative
  target, from `art-source/ASSET_AUTHORITY.json` only (see below).
- `hiwaga_preflight`: whether a structured operation on explicit targets is currently
  permitted, from project state and asset authority (see below).
- `hiwaga_model_gate`: whether the configured AI worker/model is permitted for a task
  class, from the canonical worker policy (see below).
- `hiwaga_verify`: controlled execution of a registered verification operation, from
  the canonical verifier registry (see below).

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

### `hiwaga_context`

Answers exactly one question: given one explicit `domain`, which repository
sources does `docs/CANON.md` currently route for it? It is a routing interface,
not a search engine, summarizer, or authority-inference tool.

| Argument | Required | Meaning |
| --- | --- | --- |
| `domain` | yes | One of the ten closed `ContextDomain` values below. |

```text
PROJECT, GAMEPLAY, WORLD_LORE, VISUAL_IDENTITY, VERTICAL_SLICE,
CORE_ARCHITECTURE, PROGRESSION, REPRESENTATIVE_GAMEPLAY, ASSET_AUTHORITY,
VERIFICATION
```

There is no free-form query, target, search, detail-level, or history flag — the
caller cannot ask for anything CANON does not already route, and an unknown or
missing domain is a schema-validation tool error, never a fallback domain.

**How routing works.** Two independent, deterministic parsers compose: a bounded
grammar over `docs/CANON.md`'s three routing sections (`## Canonical sources`,
`## Supporting references`, `## Exploratory Prototype A — frozen findings and
history`), each parsed for `- Label: body` bullets and every Markdown link they
contain in document order; and the packaged
`src/hiwaga_mcp/policy/context_routing.json`, which holds the one fact CANON
cannot supply on its own — which CANON bullet *labels* answer which domain. CANON
remains the sole authority for paths, link titles, bullet text, and source
ordering; the packaged mapping holds domain→label pairs only, nothing else.

**Classification** (`CANONICAL`, `SUPPORTING`, `PROTOTYPE_A`) comes solely from
which routing section a bullet lives in — never from that bullet's own status
prose (`DIRECTIONAL`, `FOUNDATION`, provisional markers, and similar are
preserved verbatim in `note` instead, not interpreted). `CURRENT_STATE` marks the
one `PROJECT`-domain source that is the routing index itself, `docs/CANON.md`.
Historical (`PROTOTYPE_A`) sources are always isolated in `historical_sources`
and never contaminate `canonical_sources` or `supporting_sources`, even when the
same underlying path is also routed elsewhere for a different role (a path
appearing in two sections is returned once per role, never deduplicated).

The result carries **routing metadata only** — `path`, `title` (CANON's own link
text, verbatim), `label` (the CANON bullet label, verbatim), `classification`,
`section` (an internal document section, only where routing authority names one,
e.g. the Vertical Slice acceptance gate; `null` otherwise, with no excerpt),
`note` (the complete CANON bullet text, verbatim), `exists`, and `size_bytes`
(`null` for a directory or a missing path) — never a document body, excerpt,
summary, or search result.

`PROJECT` is the one special case: its canonical source is `docs/CANON.md`
itself, and `project_state` is populated by calling the existing
`hiwaga_project_state` service exactly once. Every other domain leaves
`project_state` null and never touches that service — `hiwaga_context` does not
infer which domain a progress-ledger update belongs to.

`CORE_ARCHITECTURE`, `PROGRESSION`, `REPRESENTATIVE_GAMEPLAY`, and
`ASSET_AUTHORITY` currently have no canonical source in CANON; that is a valid
repository fact, reported as `canonical_sources: []` plus a limitation, never a
tool error. `hiwaga_context` also never calls `hiwaga_authority`'s resolution
service — it answers "which documents govern asset authority?", not "which
registered authority applies to this path?" — and never calls
`hiwaga_preflight`, `hiwaga_model_gate`, or a verifier. It performs no
filesystem enumeration beyond containment-checking CANON's own routed links (for
example, `WORLD_LORE` never scans `docs/lore/`; CANON's class rule for that
material is reported as a limitation instead).

Tool errors carry `HIWAGA_CONTEXT_ROUTING_INVALID` and fail closed: `docs/CANON.md`
missing, unreadable, or not UTF-8; a required routing section missing, renamed,
or duplicated; the packaged mapping malformed or structurally invalid; a mapped
label no longer matching any CANON bullet (routing drift); or a `CANONICAL`
source missing on disk. A missing `SUPPORTING` or `PROTOTYPE_A` source is never a
tool error — it is reported as `exists: false` plus a limitation.

### `hiwaga_authority`

Input: `target`, a repository-relative file or directory path. The repository is
always the configured `HIWAGA_REPO_ROOT`; the target goes through the same
containment check as every other path (traversal, external absolute paths, and
symlink escape are refused). The target does not have to exist.

P0 authority comes **only** from `art-source/ASSET_AUTHORITY.json`. Prose
documents, READMEs, `docs/CANON.md`, and the progress ledger are not consulted.
Authority is not a quality or acceptance judgement.

A target is owned by an asset when its canonical path equals, or is beneath, a path
the asset declares. Only these fields are read as paths: `source_path`,
`runtime_path`, `motion_proof_path` (repository-relative), and `static_form_source`,
`rig_proof_source`, `motion_source`, `representative_pose_reference_source`
(relative to that asset's `source_path`). A declared file owns only itself. There is
no filename, substring, or fuzzy matching.

| `resolution` | Meaning |
| --- | --- |
| `RESOLVED` | exactly one asset owns the target; `asset_id` is its manifest key and its declared fields are returned verbatim (`null` when not declared) |
| `UNRESOLVED` | no asset owns the target; `asset_id` is null |
| `CONFLICT` | several assets own the target; none is chosen, `asset_id` is null, and `matched_asset_ids` lists them |

`UNRESOLVED` is not an error, and `CONFLICT` is not an execution error: both are
ordinary structured results.

`allowed_uses` / `forbidden_uses` are derived from two explicit fields only, and
are empty when neither applies:

| Manifest field | Allowed | Forbidden |
| --- | --- | --- |
| `authoring_reuse: "reference_only"` | `HISTORICAL_REFERENCE`, `TECHNICAL_REFERENCE` | `AUTHORING_DERIVATION` |
| `creation_mode: "from_scratch"` | — | `DUPLICATE_SUPERSEDED_SOURCE`, `LINK_SUPERSEDED_SOURCE`, `RESHAPE_SUPERSEDED_SOURCE`, `REUSE_SUPERSEDED_TOPOLOGY` |

`status` and other manifest strings are reported as declared, not mapped to an enum.
`replacement` is reported verbatim only if an asset declares one.

The tool **refuses** with a stable reason code (an MCP tool error whose text starts
with the code) when configuration or identity is invalid (`HIWAGA_CONFIGURATION_INVALID`,
`HIWAGA_REPOSITORY_IDENTITY_INVALID`), the target escapes the repository
(`HIWAGA_TARGET_OUTSIDE_REPOSITORY`), or the manifest is missing, not JSON, has
duplicate keys, an unsupported `schema_version` (only `1` is supported), a malformed
entry, or an unusable declared path (`HIWAGA_ASSET_AUTHORITY_INVALID`). The whole
manifest is validated on every call, so no partial authority is returned from an
untrustworthy one.

### `hiwaga_preflight`

Input: `operation` (a closed enum) and `targets` (a non-empty list of
repository-relative paths). The caller states the operation; nothing is inferred from
natural language. The repository is always the configured `HIWAGA_REPO_ROOT`.

| `operation` | Meaning |
| --- | --- |
| `READ_REFERENCE` | inspect a target without modifying it |
| `MODIFY_CODE` | change ordinary source, tests, or documentation |
| `MODIFY_AUTHORED_ASSET` | change an existing authored asset as the authoring base |
| `DERIVE_AUTHORED_ASSET` | create or change authored work by deriving from a target |
| `CREATE_AUTHORED_ASSET_FROM_SCRATCH` | create authored work under a target that declares `creation_mode: from_scratch` |
| `RUN_VERIFICATION` | run verification against a target (preflight authorizes the intent only) |
| `OPERATOR_REVIEW` | a human/operator review step |

`decision` is `ALLOW`, `DENY`, `AMBIGUITY`, or `HUMAN_REQUIRED`, with a stable
`reason_code` (`HIWAGA_PREFLIGHT_*`), a `reason`, a `project_state_summary`, and a
per-target result (authority resolution, derived uses, and that target's decision).
Precedence, highest first:

1. Project gate `TARGET_AMBIGUOUS` gives `AMBIGUITY` for every operation.
2. `operator_required` in project state gives `HUMAN_REQUIRED` for the mutating
   operations (`MODIFY_CODE`, `MODIFY_AUTHORED_ASSET`, `DERIVE_AUTHORED_ASSET`,
   `CREATE_AUTHORED_ASSET_FROM_SCRATCH`). `READ_REFERENCE`, `RUN_VERIFICATION`, and
   `OPERATOR_REVIEW` are not blocked.
3. Per-target authority rules:
   - the three authored operations need exactly one resolved authority: `UNRESOLVED` or
     `CONFLICT` gives `AMBIGUITY`;
   - `MODIFY_AUTHORED_ASSET` and `DERIVE_AUTHORED_ASSET` are `DENY` when the authority
     forbids `AUTHORING_DERIVATION` (`reference_only`), otherwise `ALLOW`; `status`
     alone never denies;
   - `CREATE_AUTHORED_ASSET_FROM_SCRATCH` is `ALLOW` when `creation_mode` is
     `from_scratch`, otherwise `AMBIGUITY`;
   - `MODIFY_CODE` is `ALLOW` for a target with no asset authority, and `AMBIGUITY` for
     an asset-governed target, so it cannot bypass authored-asset policy;
   - `READ_REFERENCE`, `RUN_VERIFICATION`, and `OPERATOR_REVIEW` are not blocked by
     authority (a conflict adds a limitation).
4. Targets aggregate as `AMBIGUITY` > `HUMAN_REQUIRED` > `DENY` > `ALLOW`, independent
   of target order.

`TARGET_CLEAR` never overrides the rules above, `TARGET_PARTIALLY_CONSTRAINED` is not a
stop, and an undeclared gate is treated as neither clear nor ambiguous.

`ALLOW`, `DENY`, `AMBIGUITY`, and `HUMAN_REQUIRED` are all ordinary results
(`is_error` false). A tool error is reserved for an invalid request (unknown operation,
empty `targets`) or a failed prerequisite: configuration, repository identity, project
state, a target outside the repository, or an untrustworthy authority manifest.

Preflight is advisory and decision-only. It executes nothing, and choosing a worker or
model is not part of it.

### `hiwaga_model_gate`

Input: `task_class` only, one of `EVIDENCE_AUDIT`, `BUG_DIAGNOSIS`,
`BOUNDED_IMPLEMENTATION`, `EXECUTION_BOUNDARY_CHANGE`, `RELEASE_REVIEW`,
`HIGH_COMPLEXITY_CONVERGENCE`, `OPERATOR_REVIEW`. It is never inferred from text. The
tool takes no `worker`, `model`, repository, or policy-path argument, and extra
arguments cannot override the configured identity.

**Identity** comes only from the server process environment: `HIWAGA_AI_WORKER` (trimmed
and lowercased) and `HIWAGA_AI_MODEL` (trimmed, matched exactly and case-sensitively).
Nothing is guessed from the process name, the MCP client, or any other variable, and no
alias is mapped (`claude`, `cc`, and `anthropic` are not `claude-code`). Neither variable
is needed for the server to start or for any other tool. The gate does not verify that the
configured identity is the real client; it trusts the operator's configuration.

**Policy** is `src/hiwaga_mcp/policy/worker_policy.json`, packaged with the server. It is
the canonical, vendor-neutral worker authorization policy: per task class, either
`human_required: true` or an allowlist of `{worker, models}` entries with exact model ids.
It is separate from the client hook policies, which have different schemas and duties and
are not runtime authority here: `.codex/policy/model-policy.json` (Codex hook behavior) and
`.claude/policy/model-policy.json` (Claude hook/model-switch behavior). The three are not
synchronized and are not guaranteed consistent.

Current contents: `EVIDENCE_AUDIT`, `BOUNDED_IMPLEMENTATION`, `EXECUTION_BOUNDARY_CHANGE`,
and `RELEASE_REVIEW` allow the `codex` worker with the model slugs the repository's Codex
policy records for them, and `OPERATOR_REVIEW` is human-only. `BUG_DIAGNOSIS` and
`HIGH_COMPLEXITY_CONVERGENCE` have no rule. No Claude model ids are recorded anywhere in
the repository, so none are listed: with an allowlist, `claude-code` is therefore `DENY`
for the four classes that list only `codex`, until canonical Claude model ids are added.

| Situation | `decision` | `reason_code` |
| --- | --- | --- |
| class is `human_required` (identity is irrelevant) | `HUMAN_REQUIRED` | `HIWAGA_MODEL_GATE_HUMAN_REQUIRED` |
| class has no rule | `AMBIGUITY` | `HIWAGA_MODEL_GATE_POLICY_UNDEFINED` |
| either identity variable unset, empty, or blank | `AMBIGUITY` | `HIWAGA_MODEL_GATE_IDENTITY_UNAVAILABLE` |
| worker not listed for the class | `DENY` | `HIWAGA_MODEL_GATE_WORKER_DENIED` |
| worker listed, model not listed for it | `DENY` | `HIWAGA_MODEL_GATE_MODEL_DENIED` |
| worker and model listed | `ALLOW` | `HIWAGA_MODEL_GATE_ALLOWED` |

Matching is exact: no substring or family matching, newer versions are not inherited, and
a class with no rule gets no fallback from another class. The gate authorizes membership
only. It ranks and recommends nothing, and reasoning effort and cost are not gated.

All six outcomes above are ordinary results (`is_error` false). A tool error
(`HIWAGA_WORKER_POLICY_INVALID`) is reserved for an untrustworthy policy: not JSON,
duplicate keys, an unsupported `schema_version` (only `1`), an unknown key, a rule that
sets neither or both of `human_required` and `allowed`, an empty or non-canonical
worker/model, or a repeated worker or model. A valid policy that simply lacks a class is
`AMBIGUITY`, not an error.

The gate is independent of `hiwaga_preflight`, project state, and asset authority, and
does not call them or the repository. A caller who wants both answers calls both.

### `hiwaga_verify`

Executes one registered verification operation and reports a typed result.

Input is deliberately narrow:

| Argument | Required | Meaning |
| --- | --- | --- |
| `verifier` | yes | A registered verifier id. |
| `mode` | no | A mode that verifier declares. Omitted uses the registry's default mode. |

There is **no arbitrary command execution.** The caller cannot supply a command,
executable, script, working directory, timeout, environment, output path, or
repository root — there is no argument for any of them, and unmodelled arguments
are ignored. Everything that determines what runs comes from the canonical
packaged registry at `src/hiwaga_mcp/policy/verifier_registry.json` and the
validated `HIWAGA_REPO_ROOT`. The registry is the allowlist: a verifier that is
not in it cannot be run through this tool at all.

Registry definitions are never read from `AGENTS.md`, `README.md`, the progress
ledger, or Codex/Claude configuration.

Execution is argv-based via `asyncio.create_subprocess_exec`. No shell is
involved anywhere — no `shell=True`, no `os.system`, no `sh -c` — and a registry
entry that needed shell syntax would be invalid. Registry paths (script, working
directory, run directory) pass the same containment boundary as every other path,
so traversal, external absolute paths, and symlink escape are refused. The child
runs in its own session with a built-from-scratch environment: an allowlist of
`PATH`, `HOME`, `LANG`, `TZ`, and `LC_*`, plus any static entries the registry
declares. `GIT_DIR`, `GIT_WORK_TREE`, `PYTHONPATH`, `PYTHONHOME`, and everything
else never reach it.

**Status meanings.** All four are ordinary results with `is_error: false`:

| Status | Meaning |
| --- | --- |
| `PASS` | The verifier ran to completion and reported success (exit 0). |
| `FAIL` | The verifier ran correctly and **found a defect** (nonzero exit). |
| `TIMEOUT` | The verifier exceeded its registry deadline and was terminated. |
| `EXECUTION_ERROR` | The verifier could not run, or died by signal before reporting. |

A verifier `FAIL` is a verification result about HIWAGA, **not** a failure of
this server — do not treat it as a tool error. `EXECUTION_ERROR` is the opposite
case: execution itself broke, so nothing was established about what was checked.

Tool errors (`is_error: true`, message led by a stable reason code) are reserved
for invalid requests and untrustworthy configuration: `HIWAGA_UNKNOWN_VERIFIER`,
`HIWAGA_UNSUPPORTED_VERIFY_MODE`, `HIWAGA_VERIFIER_REGISTRY_INVALID`,
`HIWAGA_CONFIGURATION_INVALID`, `HIWAGA_REPOSITORY_IDENTITY_INVALID`,
`HIWAGA_TARGET_OUTSIDE_REPOSITORY`, and `HIWAGA_RUNTIME_STATE_UNAVAILABLE` (this
server's own external state root cannot be established — see
[Runtime state](#runtime-state)). A malformed registry is never partially
trusted: no verifier from it runs.

**Timeout.** Every registry entry carries an explicit positive timeout and the
caller cannot override it. On expiry the whole process group gets `SIGTERM`, then
`SIGKILL` after a short grace period, and the process is reaped — so a verifier
that spawned Godot or other children does not leave them running.

**Logs and run directory.** Each invocation gets its own run directory under
this server's own external state root (see [Runtime state](#runtime-state)
below), never inside the HIWAGA checkout, named by a random, filesystem-safe id.
`run_directory`, `stdout_log`, `stderr_log`, and every artifact `path` are
absolute paths into that external state. Complete `stdout.log` and `stderr.log`
are written there; the result carries only a bounded 2000-character tail of each
plus the full byte counts, so a verbose verifier cannot consume unbounded
response tokens. `artifacts` lists what the verifier left in that run directory
only — the repository is never scanned for modified files, and neither is any
other repository's namespace under the state root.

**Proof class** comes from the registry, never the caller: a caller cannot claim
a headless verifier produced native rendered evidence. No status asserts operator
acceptance, and `limitations` says so explicitly.

`hiwaga_verify` does **not** call `hiwaga_preflight` or `hiwaga_model_gate`. It
owns safe execution, not development authorization; whether work may proceed and
whether a worker is authorized are separate questions an external planner
composes by calling those tools itself. There is no approval flag, no
`unsafe`/`force` escape, and no preflight token.

Seeded verifiers:

| Verifier | Modes | Proof class | Timeout | Runs |
| --- | --- | --- | --- | --- |
| `asset_authority` | `default` | `STRUCTURAL` | 120s | `tools/verify_asset_authority.py` |
| `player_v2_motion_review` | `headless` | `HEADLESS` | 600s | `tools/rgf/verify_player_v2_motion_review.py headless --out <run-dir>` |

Both run under the checkout's own `.venv/bin/python` (`REPO_PYTHON`, the only
executable strategy). The registry is the normalization layer for these entries
only; historical `tools/rgf/verify_*.py` interfaces are not normalized, and
further entries are added incrementally.

### Deferred — not implemented

Prose authority resolution or reconciliation with the machine registry,
context-domain document excerpts/heading extraction/free-form query, semantic
search, embeddings, reasoning-effort and cost policy, client hook policy
synchronization, evidence promotion and packaging, contact sheets and screenshot
judgement, GitHub integration, background or queued verification runs, and any
HTTP, OAuth, or remote transport.

Verification executes registered verifiers only. Nothing is promoted into
`docs/evidence/`, and asset authority covers the machine-readable registry only.

## Runtime state

`hiwaga_verify` writes every run — `stdout.log`, `stderr.log`, and whatever the
verifier itself wrote — to a directory this server owns, entirely outside the
configured HIWAGA checkout:

```text
$XDG_STATE_HOME/hiwaga-mcp/repositories/<repository-key>/runs/<run-id>/
```

falling back to `~/.local/state/hiwaga-mcp/...` when `XDG_STATE_HOME` is unset,
blank, or not an absolute path (a relative or `~`-prefixed value is treated the
same as unset, deterministically, rather than being anchored to the current
working directory). `<repository-key>` is a short SHA-256 digest of the
checkout's canonical absolute path, so two different HIWAGA checkouts never
share a namespace and one checkout keeps the same namespace regardless of its
branch, HEAD, or worktree state. State directories are created lazily, only
when a verifier actually runs — never merely by starting the server or calling
any other tool.

**No target-repository configuration is required or read.** A HIWAGA checkout
needs no `.gitignore` entry, no `.git/info/exclude` entry, and no awareness of
`hiwaga-mcp` at all to stay clean: `hiwaga_verify` does not write inside it.
Nothing is written to `docs/evidence/` either — evidence promotion is a separate
lifecycle that does not exist yet. Run retention (pruning, TTLs, size limits) is
not implemented; runs accumulate under the state root until removed by hand.

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
    ├── project_state.py   composes identity + ledger + Git into ProjectStateResult
    ├── authority.py       asset-authority manifest loading and path-ownership resolution
    ├── preflight.py       rule table combining project state and asset authority into a decision
    ├── model_gate.py      worker policy loading and the worker/model membership decision
    ├── context_routing.py CANON's bounded grammar and the packaged domain→label mapping parser
    ├── context.py         composes CANON routing + the mapping + project state into ContextResult
    ├── verification_registry.py  registry loading, strict validation, verifier/mode lookup
    ├── verification.py    execution plan construction and controlled subprocess execution
    └── runtime_state.py   external XDG state root, per-repository namespace, run directory

src/hiwaga_mcp/policy/worker_policy.json      canonical worker authorization policy (packaged)
src/hiwaga_mcp/policy/verifier_registry.json  canonical verifier allowlist (packaged)
src/hiwaga_mcp/policy/context_routing.json    canonical domain→CANON-label routing mapping (packaged)
```

MCP tool adapters stay thin; behaviour lives in services and is tested directly.
