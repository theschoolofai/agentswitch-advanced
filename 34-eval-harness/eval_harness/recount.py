"""Recount grader: compares the agent's AGENT_RESULT answer to expected ids from the trial record."""

from __future__ import annotations

from typing import Any

from eval_harness.trial import TrialRecord


def _as_id_set(value: Any) -> set[str] | None:
    """Return the answer as a set of ids, or None if it is not a list."""
    if not isinstance(value, list):
        return None
    return {str(x) for x in value}


def recount(record: TrialRecord, params: dict[str, Any]) -> Any:
    from eval_harness.graders import GraderResult, Verdict
    from eval_harness.rules import expected_ids

    name = "recount"
    answer_key = params.get("answer")
    if not answer_key:
        return GraderResult(name, Verdict.UNEVALUATED, 0.0, "no answer key in params")

    if record.agent is None or not record.agent.reported:
        return GraderResult(name, Verdict.REVISE, 0.0, "no AGENT_RESULT line")

    reported = record.agent.reported
    if not isinstance(reported, dict):
        return GraderResult(name, Verdict.REVISE, 0.0, "AGENT_RESULT is not a JSON object")

    answer = (
        (reported.get("answer") or {}).get(answer_key) if isinstance(reported.get("answer"), dict) else None
    )
    if answer is None:
        return GraderResult(name, Verdict.REVISE, 0.0, f"missing answer: {answer_key}")

    found = _as_id_set(answer)
    if found is None:
        return GraderResult(name, Verdict.REVISE, 0.0, f"answer is not a list: {answer_key}")

    pair = expected_ids(record.population, answer_key, params)
    if pair is None:
        return GraderResult(name, Verdict.UNEVALUATED, 0.0, "no population captured")

    before, after = pair
    if before is None and after is None:
        return GraderResult(name, Verdict.UNEVALUATED, 0.0, "could not read population")

    candidates = [s for s in (before, after) if s is not None]
    if any(found == candidate for candidate in candidates):
        return GraderResult(name, Verdict.APPROVE, 1.0, f"ids match ({len(found)})")

    diffs = []
    for label, candidate in (("before", before), ("after", after)):
        if candidate is not None:
            missing = candidate - found
            extra = found - candidate
            diffs.append(f"{label} missing={sorted(missing)} extra={sorted(extra)}")
    return GraderResult(name, Verdict.REVISE, 0.0, " ; ".join(diffs))
