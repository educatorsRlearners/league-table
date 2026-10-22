"""Demo-only fault switches, read from the environment on every request."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("league_table.fault")

COMMITMENT_FAULT_VAR = "FAULT_COMMITMENT_ERRORS"


class CommitmentFault(RuntimeError):
    """Deliberate failure raised while FAULT_COMMITMENT_ERRORS is on."""


def commitment_fault_on() -> bool:
    return os.environ.get(COMMITMENT_FAULT_VAR, "").strip().lower() in ("1", "true")


def maybe_fail_commitment() -> None:
    """Raise an unhandled error when the demo switch is on. Call before any store access."""
    if commitment_fault_on():
        logger.error("Demo fault active: %s is on, failing the commitment submission", COMMITMENT_FAULT_VAR)
        raise CommitmentFault(f"Demo fault injected by {COMMITMENT_FAULT_VAR}")
