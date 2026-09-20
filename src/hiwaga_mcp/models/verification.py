"""Verification vocabulary.

These enums keep machine proof and human acceptance separate. `ProofClass`
describes what kind of evidence a verifier can produce; it never asserts that
an operator accepted the result.
"""

from __future__ import annotations

from enum import Enum


class VerificationStatus(str, Enum):
    """Outcome of an allowlisted verifier execution.

    A `FAIL` is a successful execution that found a defect, and is structured
    domain output rather than an MCP protocol error. `EXECUTION_ERROR` means
    the verifier could not run at all.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    EXECUTION_ERROR = "EXECUTION_ERROR"


class ProofClass(str, Enum):
    """The strength and kind of evidence a verification produced.

    None of these values implies operator visual acceptance.
    """

    STRUCTURAL = "STRUCTURAL"
    HEADLESS = "HEADLESS"
    NATIVE_RENDERED = "NATIVE_RENDERED"


__all__ = ["ProofClass", "VerificationStatus"]
