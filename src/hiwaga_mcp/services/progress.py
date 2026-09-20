"""Current-block parser for the HIWAGA progress ledger.

Authority contract: the **first `##` block** of `docs/progress/HIWAGA_PROGRESS.md`
is the sole source of current project state. Later blocks are history. They are
scanned only to find where the first block ends, and never contribute a value.

Parsing is deliberately small and closed:

* a line is a field only if its label normalizes to an entry in `_LABEL_FIELDS`;
* values are the field's own text plus its wrapped continuation lines, verbatim;
* a combined label (`Current Focus / Status`) is never split, because the source
  does not say where one part ends and the other begins;
* anything not declared is `None`.

There is no general natural-language handling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hiwaga_mcp.errors import ProgressDocumentError
from hiwaga_mcp.models.state import AmbiguityGate
from hiwaga_mcp.services.repository import resolve_within_repository

PROGRESS_DOCUMENT_PATH = "docs/progress/HIWAGA_PROGRESS.md"

# Normalized label -> result field. Combined labels map to the first-named
# field (or, for the next-step family, to the field the result actually has).
_LABEL_FIELDS: dict[str, str] = {
    "phase": "phase",
    "current focus": "current_focus",
    "current focus / status": "current_focus",
    "status": "status",
    "design question": "design_question",
    "design question / player goal": "design_question",
    "player goal": "player_goal",
    "player goal / success condition": "player_goal",
    "success condition": "success_condition",
    "ambiguity gate": "ambiguity_gate",
    "next bounded step": "next_bounded_step",
    "next ai goal / next bounded step": "next_bounded_step",
    "next bounded step / next human goal": "next_bounded_step",
    "next human goal / next bounded step": "next_bounded_step",
    "next human goal": "next_human_goal",
    "next human goal / operator dependency": "next_human_goal",
}

# Combined labels whose second part has its own result field. When such a label
# supplies the value and the second part is not declared separately, the value
# stays whole in the first field and the second is reported as unsplit.
_UNSPLIT_LABELS: dict[str, tuple[str, str]] = {
    "current focus / status": ("current_focus", "status"),
    "design question / player goal": ("design_question", "player_goal"),
    "player goal / success condition": ("player_goal", "success_condition"),
}

_H2_RE = re.compile(r"^ {0,3}##[ \t]+(?P<text>\S.*?)[ \t]*$")
_ANY_HEADING_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})")
_LIST_MARKER_RE = re.compile(r"^(?:[-*+]|\d{1,3}[.)])[ \t]+")
_BOLD_LABEL_RE = re.compile(r"^\*\*(?P<label>[^*\n]+?)\*\*(?P<rest>.*)$")
_PLAIN_LABEL_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z /&-]{0,60}?)[ \t]*:(?:[ \t]+(?P<rest>.*))?$")
_GATE_RE = re.compile(r"\b(TARGET_CLEAR|TARGET_PARTIALLY_CONSTRAINED|TARGET_AMBIGUOUS)\b")

# Operator requirement: an explicit operator/human subject followed either by a
# closed set of modifiers and a review/outing/playtest/acceptance noun
# ("operator visual acceptance"), or directly by an action verb
# ("operator runs the native review"). Subject and action must both be present.
_OPERATOR_SUBJECT = r"(?:(?:human )?operator|human)"
_OPERATOR_RE = re.compile(
    rf"\b{_OPERATOR_SUBJECT} (?:"
    r"(?:(?:visual|experiential|integrated|native) )*(?:review|outing|playtest|acceptance)"
    r"|(?:runs?|performs?|plays?|reviews?)"
    r")\b"
)
# Negation is judged inside one clause, so a `no` in an earlier sentence or
# clause cannot suppress a later, separately stated requirement.
_CLAUSE_SPLIT_RE = re.compile(r"[.;:!?,\n—–]")
_NEGATORS = frozenset({"no", "not", "without", "never", "nor"})
_TRAILING_NEGATION_RE = re.compile(r"^(?:is |are )?(?:not|no longer) (?:required|needed)\b")
_OPERATOR_SCANNED_FIELDS = ("current_focus", "status", "next_bounded_step", "next_human_goal")


@dataclass(frozen=True)
class ProgressBlock:
    """The parsed current block. Unset fields are `None`, never guessed."""

    heading: str
    phase: str | None
    current_focus: str | None
    status: str | None
    design_question: str | None
    player_goal: str | None
    success_condition: str | None
    ambiguity_gate: AmbiguityGate | None
    next_bounded_step: str | None
    next_human_goal: str | None
    operator_required: bool
    limitations: tuple[str, ...]


def _normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*/\s*", " / ", label.strip().lower()))


def _split_field_line(line: str) -> tuple[str, str] | None:
    """Return `(normalized_label, remainder)` if `line` has label syntax, else None.

    Recognizes `**Label:** value`, `**Label**: value`, and `Label: value`, each
    optionally behind a list marker. Says nothing about whether the label is
    one this parser knows.
    """
    text = _LIST_MARKER_RE.sub("", line.strip(), count=1)

    bold = _BOLD_LABEL_RE.match(text)
    if bold:
        label = bold.group("label").strip()
        rest = bold.group("rest")
        if label.endswith(":"):
            label = label[:-1].strip()
        elif rest.lstrip().startswith(":"):
            rest = rest.lstrip()[1:]
        else:
            return None
        return (_normalize_label(label), rest.strip()) if label else None

    plain = _PLAIN_LABEL_RE.match(text)
    if plain:
        return _normalize_label(plain.group("label")), (plain.group("rest") or "").strip()
    return None


def _extract_current_block(text: str) -> tuple[str, list[str]]:
    """Return the first H2's heading text and the lines up to the next H2 or EOF."""
    if not text.strip():
        raise ProgressDocumentError(
            f"{PROGRESS_DOCUMENT_PATH} is empty.",
            details={"problem": "empty", "path": PROGRESS_DOCUMENT_PATH},
        )

    heading: str | None = None
    body: list[str] = []
    fence: str | None = None

    for line in text.splitlines():
        marker = _FENCE_RE.match(line)
        if marker:
            token = marker.group("fence")
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None:
            h2 = _H2_RE.match(line)
            if h2:
                if heading is not None:
                    break
                heading = re.sub(r"[ \t]+#+$", "", h2.group("text")).strip()
                continue
        if heading is not None:
            body.append(line)

    if heading is None:
        raise ProgressDocumentError(
            f"{PROGRESS_DOCUMENT_PATH} has no `##` block, so no current block can be established.",
            details={"problem": "no_current_block", "path": PROGRESS_DOCUMENT_PATH},
        )
    return heading, body


def _collect_fields(body: list[str]) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Scan block lines for recognized fields.

    Returns `(values, source_label_by_field, notes)`. The first occurrence of a
    field wins; a repeat is recorded in `notes` rather than merged.
    """
    values: dict[str, str] = {}
    sources: dict[str, str] = {}
    notes: list[str] = []

    open_field: str | None = None
    open_label = ""
    open_indent = 0
    open_parts: list[str] = []
    fence: str | None = None

    def close() -> None:
        nonlocal open_field, open_parts
        if open_field is not None:
            value = " ".join(part for part in (p.strip() for p in open_parts) if part)
            if value:
                if open_field in values:
                    notes.append(
                        f"Field `{open_field}` is declared more than once in the current block; "
                        "the first declaration is used."
                    )
                else:
                    values[open_field] = value
                    sources[open_field] = open_label
        open_field = None
        open_parts = []

    for raw in body:
        line = raw.expandtabs(4)

        marker = _FENCE_RE.match(line)
        if marker:
            token = marker.group("fence")
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            close()
            continue
        if fence is not None or not line.strip() or _ANY_HEADING_RE.match(line):
            close()
            continue

        indent = len(line) - len(line.lstrip(" "))
        if open_field is not None and indent > open_indent:
            open_parts.append(line)
            continue

        parsed = _split_field_line(line)
        if parsed is not None and parsed[0] in _LABEL_FIELDS:
            close()
            open_field = _LABEL_FIELDS[parsed[0]]
            open_label = parsed[0]
            open_indent = indent
            open_parts = [parsed[1]]
        elif parsed is not None or _LIST_MARKER_RE.match(line.strip()):
            # A field or list item this parser does not own ends the open field.
            close()
        elif open_field is not None:
            open_parts.append(line)  # lazily wrapped plain text

    close()
    return values, sources, notes


def _resolve_ambiguity_gate(values: dict[str, str], notes: list[str]) -> AmbiguityGate | None:
    """Resolve the current block's gate from exact canonical tokens only.

    An `Ambiguity Gate:` field wins when it names exactly one token; canonical
    tokens inside the other recognized fields are then used only to detect a
    contradiction. Without that field, exactly one distinct inline token is
    used. Any disagreement is `None` plus a note, never a silent choice.
    """
    inline = {
        token
        for name, value in values.items()
        if name != "ambiguity_gate"
        for token in _GATE_RE.findall(value)
    }

    explicit = values.get("ambiguity_gate")
    if explicit is None:
        if len(inline) == 1:
            return AmbiguityGate(next(iter(inline)))
        if inline:
            notes.append(
                f"Current-block fields name several ambiguity gates ({', '.join(sorted(inline))}); "
                "ambiguity_gate is null."
            )
        return None

    declared = sorted(set(_GATE_RE.findall(explicit)))
    if len(declared) != 1:
        reason = "names none of the recognized gate values"
        if declared:
            reason = f"names several gates ({', '.join(declared)})"
        notes.append(f"`Ambiguity Gate` is declared but {reason}; ambiguity_gate is null.")
        return None

    conflicting = sorted(inline - {declared[0]})
    if conflicting:
        notes.append(
            f"`Ambiguity Gate` declares {declared[0]} but other current-block fields name "
            f"{', '.join(conflicting)}; ambiguity_gate is null."
        )
        return None
    return AmbiguityGate(declared[0])


def _operator_signals(*texts: str | None) -> tuple[int, int]:
    """Count `(affirmed, negated)` explicit operator/human requirements in `texts`.

    Text is split into clauses; each is lower-cased and stripped to alphanumeric
    words. A match is negated by a `no`/`not`/`without`/`never`/`nor` among the
    three words before it, or `not required`/`not needed` right after it, within
    the same clause.
    """
    affirmed = negated = 0
    for text in texts:
        if not text:
            continue
        for clause in _CLAUSE_SPLIT_RE.split(text):
            normalized = " ".join(re.sub(r"[^a-z0-9]+", " ", clause.lower()).split())
            for match in _OPERATOR_RE.finditer(normalized):
                before = normalized[: match.start()].split()[-3:]
                after = normalized[match.end() :].lstrip()
                if _NEGATORS.intersection(before) or _TRAILING_NEGATION_RE.match(after):
                    negated += 1
                else:
                    affirmed += 1
    return affirmed, negated


def detect_operator_requirement(*texts: str | None) -> bool:
    """True when any text explicitly requires an operator/human review, outing, playtest, or acceptance.

    Requires an explicit operator/human subject with a closed review/outing/
    playtest/acceptance noun or a run/perform/play/review verb; generic words
    such as `review` or `play` alone never count. A negated match does not count,
    and negation never suppresses a separate affirmed match. It is not a
    semantic classifier.
    """
    return _operator_signals(*texts)[0] > 0


def parse_current_block(text: str) -> ProgressBlock:
    """Parse the first `##` block of progress-ledger `text`.

    Raises:
        ProgressDocumentError: `text` is empty or contains no `##` block.
    """
    heading, body = _extract_current_block(text)
    values, sources, notes = _collect_fields(body)

    for label, (primary, secondary) in _UNSPLIT_LABELS.items():
        if sources.get(primary) == label and secondary not in values:
            notes.append(
                f"`{label.title()}` is one combined value and is not split: it is reported whole in "
                f"`{primary}`, and `{secondary}` is null."
            )

    if not values:
        notes.append("No supported progress fields were recognized in the current block.")

    gate = _resolve_ambiguity_gate(values, notes)

    affirmed, negated = _operator_signals(*(values.get(f) for f in _OPERATOR_SCANNED_FIELDS))
    operator_required = affirmed > 0
    if affirmed and negated:
        notes.append(
            "Operator wording is contradictory: the current block both requires and negates an operator "
            "action; operator_required is true because an explicit requirement is declared."
        )

    return ProgressBlock(
        heading=heading,
        phase=values.get("phase"),
        current_focus=values.get("current_focus"),
        status=values.get("status"),
        design_question=values.get("design_question"),
        player_goal=values.get("player_goal"),
        success_condition=values.get("success_condition"),
        ambiguity_gate=gate,
        next_bounded_step=values.get("next_bounded_step"),
        next_human_goal=values.get("next_human_goal"),
        operator_required=operator_required,
        limitations=tuple(notes),
    )


def read_current_progress_block(repo_root: Path) -> ProgressBlock:
    """Read and parse the current block of `repo_root`'s progress ledger.

    The path is resolved through repository containment, so a ledger that is a
    symlink out of the checkout is rejected rather than read.

    Raises:
        ProgressDocumentError: the ledger is missing, unreadable, not UTF-8,
            empty, or has no `##` block.
        TargetOutsideRepositoryError: the ledger resolves outside the repository.
    """
    path = resolve_within_repository(repo_root, PROGRESS_DOCUMENT_PATH)
    if not path.is_file():
        raise ProgressDocumentError(
            f"{PROGRESS_DOCUMENT_PATH} does not exist in the configured repository.",
            details={"problem": "missing", "path": PROGRESS_DOCUMENT_PATH},
        )
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ProgressDocumentError(
            f"{PROGRESS_DOCUMENT_PATH} is not valid UTF-8.",
            details={"problem": "not_utf8", "path": PROGRESS_DOCUMENT_PATH},
        ) from exc
    except OSError as exc:
        raise ProgressDocumentError(
            f"{PROGRESS_DOCUMENT_PATH} could not be read: {exc}",
            details={"problem": "unreadable", "path": PROGRESS_DOCUMENT_PATH},
        ) from exc
    return parse_current_block(text)


__all__ = [
    "PROGRESS_DOCUMENT_PATH",
    "ProgressBlock",
    "detect_operator_requirement",
    "parse_current_block",
    "read_current_progress_block",
]
