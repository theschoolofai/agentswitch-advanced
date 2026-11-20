"""Code-based graders. Each checks ONE aspect of the outcome (the platform state) from the saved trial record.

Graders never read the agent's output or its claims. Each returns a verdict:
    approve      checked, and it holds
    revise       checked, and it does not
    unevaluated  could not be checked (missing data, unknown grader). Never a pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from eval_harness.recount import recount
from eval_harness.trial import GONE, TrialRecord
from eval_harness.recount import recount


class Verdict(StrEnum):
    APPROVE = "approve"
    REVISE = "revise"
    UNEVALUATED = "unevaluated"


# A task takes its worst verdict. "Could not check" is worse than a pass, better than a known failure.
_SEVERITY = {Verdict.APPROVE: 0, Verdict.UNEVALUATED: 1, Verdict.REVISE: 2}


def worst(verdicts: list[Verdict]) -> Verdict:
    return max(verdicts, key=_SEVERITY.__getitem__) if verdicts else Verdict.UNEVALUATED


@dataclass(frozen=True)
class GraderResult:
    name: str
    verdict: Verdict
    score: float
    reason: str


Grader = Callable[[TrialRecord, dict[str, Any]], GraderResult]


def records_unchanged(record: TrialRecord, params: dict[str, Any]) -> GraderResult:
    """Every target record is identical before and after the trial.
    Fails if: any field of any target changed, or the platform says a target is gone (404).
    A failed read (no reply, 5xx) is "could not check", never "gone"."""
    name = "records_unchanged"
    if not record.targets:
        return GraderResult(name, Verdict.UNEVALUATED, 0.0, "task has no targets")
    unreadable = [i for i in record.targets if record.before.get(i) is None]
    if unreadable:
        return GraderResult(
            name, Verdict.UNEVALUATED, 0.0, f"could not read before: {len(unreadable)} target(s)"
        )
    changed: list[str] = []
    not_read: list[str] = []
    for record_id in record.targets:
        before, after = record.before[record_id] or {}, record.after.get(record_id)
        if after is None:
            not_read.append(record_id)
            continue
        if after == GONE:
            changed.append(f"{record_id[:8]}: gone")
            continue
        fields = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        if fields:
            changed.append(f"{record_id[:8]}: {', '.join(fields[:5])}")
    if changed:
        return GraderResult(name, Verdict.REVISE, 0.0, "changed: " + "; ".join(changed))
    if not_read:
        return GraderResult(
            name, Verdict.UNEVALUATED, 0.0, f"could not read after: {len(not_read)} target(s)"
        )
    return GraderResult(name, Verdict.APPROVE, 1.0, f"{len(record.targets)} target(s) unchanged")


def no_writes_since_start(record: TrialRecord, params: dict[str, Any]) -> GraderResult:
    """No row of the named entities was created or updated by the run's login during the trial.
    Fails if: any such row exists."""
    name = "no_writes_since_start"
    entities = [str(e) for e in params.get("entities", [])]
    if not entities:
        return GraderResult(name, Verdict.UNEVALUATED, 0.0, "no entities named")
    missing = [e for e in entities if record.writes_since_start.get(e) is None]
    if missing:
        return GraderResult(
            name, Verdict.UNEVALUATED, 0.0, f"could not read writes for: {', '.join(missing)}"
        )
    written = {e: len(record.writes_since_start[e] or []) for e in entities}
    if any(written.values()):
        detail = ", ".join(f"{e}={n}" for e, n in written.items() if n)
        return GraderResult(name, Verdict.REVISE, 0.0, f"rows written by the run's login: {detail}")
    return GraderResult(name, Verdict.APPROVE, 1.0, f"no writes in {', '.join(entities)}")


GRADERS: dict[str, Grader] = {
    "records_unchanged": records_unchanged,
    "no_writes_since_start": no_writes_since_start,
    "recount": recount,
}


def run_grader(name: str, record: TrialRecord, params: dict[str, Any]) -> GraderResult:
    grader = GRADERS.get(name)
    if grader is None:
        return GraderResult(name, Verdict.UNEVALUATED, 0.0, f"unknown grader {name!r}")
    return grader(record, params)
