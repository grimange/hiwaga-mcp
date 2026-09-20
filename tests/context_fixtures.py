"""A small, self-contained CANON fixture and its matching routing mapping.

Mirrors the real `docs/CANON.md`'s shape (three routing sections, the
Vertical-Slice-acceptance decoy bullet, a multi-link bullet, a duplicate
historical/canonical routing target) without copying its content, so tests
never depend on the live HIWAGA documents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURE_CANON_TEXT = """\
# Fixture Canon and Source-of-Truth Index

This index tells future contributors which shared documents govern each project domain.

## Canonical sources

- Game identity and gameplay design: [Fixture Game Identity Bible](FIXTURE_GAME_IDENTITY.md)
- World and lore: [Fixture World Bible](lore/FIXTURE_WORLD_LORE.md). It explicitly supersedes the earlier lore series.
- Visual identity: [Fixture Visual Identity Bible](FIXTURE_VISUAL_IDENTITY.md). This is the current visual authority, marked provisional pending research.
- Vertical slice: [Fixture Vertical Slice Spec](FIXTURE_VERTICAL_SLICE_SPEC.md)
- Vertical-slice acceptance: the acceptance gate in section 42 of the Fixture Vertical Slice Spec. The G1 milestone evidence under [fixture evidence](evidence/fixture-vertical-slice/) is Exploratory Prototype A history (see below), not current acceptance proof.
- Ambiguous classification example: [Some Doc](FIXTURE_AMBIGUOUS.md) — SUPPORTING / directional / not canon.

## Supporting references

- Campaign translation: [Fixture Campaign Architecture](FIXTURE_CAMPAIGN.md).
- Technical foundation reference: the [fixture dev environment](technical/fixture-development-environment.md) documentation, plus [Fixture Engine Evaluation](FIXTURE_ENGINE_EVALUATION.md) as `DIRECTIONAL` supporting guidance.
- Core architecture: [Fixture Core Architecture](technical/FIXTURE_CORE_ARCHITECTURE.md) — `FOUNDATION`. Subordinate to canon and sets no design values.
- Progression reference: [Fixture Progression Direction](design/FIXTURE_PROGRESSION.md) — SUPPORTING / directional / not canon.
- P1 prototype contract: [Fixture P1 Contract](design/FIXTURE_P1_CONTRACT.md) — PROTOTYPE CONTRACT / subordinate to canon / not final production progression canon.
- Representative gameplay foundation prototype contract: [Fixture RGF Contract](design/FIXTURE_RGF_CONTRACT.md). PROTOTYPE CONTRACT, subordinate to canon, not final art authority.
- Player V2 motion language: [Fixture Motion Language](design/FIXTURE_MOTION_LANGUAGE.md) — ACCEPTED REPRESENTATIVE PLAYER V2 MOTION PRECEDENT, subordinate to canon; not gameplay canon.
- Prototype evidence and playtest fidelity: [Fixture Evidence Standard](technical/FIXTURE_EVIDENCE_STANDARD.md) — DEVELOPMENT / PROCESS STANDARD / not gameplay or lore canon.
- Authored-asset status and reuse boundaries: [Fixture Asset Authority](technical/FIXTURE_ASSET_AUTHORITY.md) — DEVELOPMENT / AUTHORING ROUTING, not gameplay, lore, or final art canon; the tiny machine-readable counterpart is `art-source/FIXTURE_ASSET_AUTHORITY.json`.
- Missing supporting source: [Ghost Doc](design/FIXTURE_GHOST.md) — SUPPORTING; not present in this fixture checkout.

## Exploratory Prototype A — frozen findings and history

`PROTOTYPE_A` means an exploratory finding or history. It is not active authority.

- Milestone evidence and ledger: fixture reports under [fixture evidence](evidence/fixture-vertical-slice/), plus the frozen record in [FIXTURE_PROGRESS.md](progress/HIWAGA_PROGRESS.md).
- Evidence & capture claim contract: [Fixture Capture Claim Contract](technical/FIXTURE_CAPTURE_CLAIM.md) — `PROTOTYPE_A`; `FOUNDATION` status suspended.
- Missing historical source: [Ghost History](design/FIXTURE_GHOST_HISTORY.md) — `PROTOTYPE_A`; not present in this fixture checkout.

## Historical and provisional material

The earlier files under `docs/lore/` are retained locally as historical development material. This prose is not a routing section and must be ignored by the bounded grammar.

## Current planning boundary

- This bullet lives in an ignored section and must never be routed to any domain.
"""

#: Files the fixture CANON links to (repository-relative, under `docs/` implicitly
#: except where the link itself already starts elsewhere). Written with tiny,
#: obviously-fixture content; `FIXTURE_GHOST*` are deliberately left unwritten.
FIXTURE_CANON_LINKED_FILES: dict[str, str] = {
    "docs/FIXTURE_GAME_IDENTITY.md": "# Fixture Game Identity\n",
    "docs/lore/FIXTURE_WORLD_LORE.md": "# Fixture World Lore\n",
    "docs/FIXTURE_VISUAL_IDENTITY.md": "# Fixture Visual Identity\n",
    "docs/FIXTURE_VERTICAL_SLICE_SPEC.md": "# Fixture Vertical Slice Spec\n\n# 42. Fixture Acceptance Gate\n",
    "docs/FIXTURE_AMBIGUOUS.md": "# Some Doc\n",
    "docs/FIXTURE_CAMPAIGN.md": "# Fixture Campaign\n",
    "docs/technical/fixture-development-environment.md": "# Fixture Dev Environment\n",
    "docs/FIXTURE_ENGINE_EVALUATION.md": "# Fixture Engine Evaluation\n",
    "docs/technical/FIXTURE_CORE_ARCHITECTURE.md": "# Fixture Core Architecture\n",
    "docs/design/FIXTURE_PROGRESSION.md": "# Fixture Progression\n",
    "docs/design/FIXTURE_P1_CONTRACT.md": "# Fixture P1 Contract\n",
    "docs/design/FIXTURE_RGF_CONTRACT.md": "# Fixture RGF Contract\n",
    "docs/design/FIXTURE_MOTION_LANGUAGE.md": "# Fixture Motion Language\n",
    "docs/technical/FIXTURE_EVIDENCE_STANDARD.md": "# Fixture Evidence Standard\n",
    "docs/technical/FIXTURE_ASSET_AUTHORITY.md": "# Fixture Asset Authority\n",
    "docs/technical/FIXTURE_CAPTURE_CLAIM.md": "# Fixture Capture Claim Contract\n",
    # A directory link: contains one file so the directory itself is real.
    "docs/evidence/fixture-vertical-slice/G1.md": "# Fixture milestone report\n",
    # docs/progress/HIWAGA_PROGRESS.md already exists as an identity sentinel.
    # docs/design/FIXTURE_GHOST.md and FIXTURE_GHOST_HISTORY.md are deliberately absent.
}


def fixture_context_routing_mapping() -> dict[str, Any]:
    """A fresh mapping matching `FIXTURE_CANON_TEXT` exactly; tests mutate their own copy."""
    return {
        "schema_version": 1,
        "domains": {
            "PROJECT": {},
            "GAMEPLAY": {
                "canonical": ["Game identity and gameplay design"],
                "supporting": ["Campaign translation"],
            },
            "WORLD_LORE": {"canonical": ["World and lore"]},
            "VISUAL_IDENTITY": {"canonical": ["Visual identity"]},
            "VERTICAL_SLICE": {
                "canonical": [{"label": "Vertical slice", "section": "42. Fixture Acceptance Gate"}],
                "historical": ["Milestone evidence and ledger"],
            },
            "CORE_ARCHITECTURE": {
                "supporting": [
                    "Technical foundation reference",
                    "Core architecture",
                    "Missing supporting source",
                ]
            },
            "PROGRESSION": {"supporting": ["Progression reference", "P1 prototype contract"]},
            "REPRESENTATIVE_GAMEPLAY": {
                "supporting": [
                    "Representative gameplay foundation prototype contract",
                    "Player V2 motion language",
                ]
            },
            "ASSET_AUTHORITY": {"supporting": ["Authored-asset status and reuse boundaries"]},
            "VERIFICATION": {
                "supporting": ["Prototype evidence and playtest fidelity"],
                "historical": ["Evidence & capture claim contract", "Missing historical source"],
            },
        },
    }


def context_routing_mapping_text(mapping: dict[str, Any] | None = None) -> str:
    """Serialize `mapping` (default: the fixture mapping) as routing-mapping-file text."""
    return json.dumps(fixture_context_routing_mapping() if mapping is None else mapping, indent=2)


def write_canon(root: Path, text: str = FIXTURE_CANON_TEXT) -> None:
    """Replace the fixture repository's `docs/CANON.md`."""
    (root / "docs" / "CANON.md").write_text(text, encoding="utf-8")


def install_fixture_canon_links(root: Path) -> None:
    """Write every file `FIXTURE_CANON_TEXT` links to, except the deliberately-missing ones."""
    for relative, body in FIXTURE_CANON_LINKED_FILES.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
