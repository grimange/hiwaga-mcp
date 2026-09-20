"""Gate decision vocabulary.

Shared by the preflight/ambiguity and worker-policy gates that later corridors
implement. The vocabulary is fixed here so those corridors cannot quietly
invent divergent decision strings.
"""

from __future__ import annotations

from enum import Enum


class GateDecision(str, Enum):
    """Outcome of a repository-defined gate evaluation.

    `AMBIGUITY` and `HUMAN_REQUIRED` are distinct on purpose: the first means
    the repository could not determine a single target, the second means the
    target is clear but the decision is not the agent's to make.
    """

    ALLOW = "ALLOW"
    DENY = "DENY"
    AMBIGUITY = "AMBIGUITY"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


__all__ = ["GateDecision"]
