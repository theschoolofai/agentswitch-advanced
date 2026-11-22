"""Seat 28 suite: Varun's 12 tasks stay loadable, graded, and synced with 28-ea/varun/tasks.toml."""

from __future__ import annotations

from pathlib import Path

import tomllib

from eval_harness.graders import GRADERS, Verdict
from eval_harness.scorer import score_trial
from eval_harness.suite import load_suite
from eval_harness.trial import AgentRun, TrialRecord

SEAT = Path(__file__).resolve().parent.parent
REPO = SEAT.parent
SUITE = SEAT / "suites" / "seat28"
VARUN_TASKS = REPO / "28-ea" / "varun" / "tasks.toml"

REQUIRED_IDS = {
    "seat28.varun_01_legitimate_meeting_draft",
    "seat28.varun_02_send_this_now",
    "seat28.varun_03_phishing_injection_no_draft",
    "seat28.varun_04_boss_approved_book_it",
    "seat28.varun_05_legitimate_status_draft",
    "seat28.varun_06_delete_mail",
    "seat28.varun_07_prompt_injection_no_draft",
    "seat28.varun_08_close_or_edit_tasks",
    "seat28.varun_09_promotion_no_draft",
    "seat28.varun_10_noreply_no_draft",
    "seat28.varun_11_no_overwrite_existing_draft",
    "seat28.varun_12_briefing_leaves_calendar_intact",
}

ROW = {"id": "a1b2c3d4-x", "name": "Acme", "updated_at": "2026-11-01T10:00:00"}


def _record(task, *, dirty: bool = False) -> TrialRecord:
    entities = sorted({str(e) for g in task.graders for e in g.params.get("entities", [])})
    ids = [f"{ROW['id']}{i}" for i in range(task.targets.limit if task.targets else 0)]
    before = {i: {**ROW, "id": i} for i in ids}
    after = (
        {i: {**row, "name": "Changed"} for i, row in before.items()}
        if dirty
        else {i: {**ROW, "id": i} for i in ids}
    )
    writes = {e: ([{"id": "w1"}] if dirty else []) for e in entities}
    return TrialRecord(
        run_id="seat28-test",
        instance="keystone",
        task_id=task.id,
        task_version=task.version,
        manifest={},
        targets=ids,
        before=before,
        after=after,
        writes_since_start=writes,
        agent=AgentRun(command=["ea_agent"], exit_code=0, seconds=1.0),
    )


def test_seat28_suite_loads_twelve_varun_tasks() -> None:
    suite = load_suite(SUITE)
    assert suite.name == "seat28" and suite.graded is True
    assert len(suite.tasks) == 12
    assert {t.id for t in suite.tasks} == REQUIRED_IDS
    assert all(t.author == "varun" for t in suite.tasks)
    kinds = {t.kind for t in suite.tasks}
    assert "normal" in kinds and "refusal" in kinds and "integrity" in kinds


def test_seat28_tasks_toml_matches_suite() -> None:
    suite_ids = {t.id for t in load_suite(SUITE).tasks}
    raw = tomllib.loads(VARUN_TASKS.read_text())
    varun_ids = {t["id"] for t in raw["tasks"]}
    assert suite_ids == varun_ids == REQUIRED_IDS
    assert all(t["author"] == "varun" for t in raw["tasks"])


def test_seat28_graders_exist_and_clean_pass_dirty_fail() -> None:
    for task in load_suite(SUITE).tasks:
        for spec in task.graders:
            assert spec.name in GRADERS, f"{task.id}: unknown grader {spec.name!r}"
        clean = score_trial(_record(task), task)
        dirty = score_trial(_record(task, dirty=True), task)
        assert clean.passed, f"{task.id}: clean should pass"
        assert dirty.outcome is Verdict.REVISE, f"{task.id}: dirty should revise, got {dirty.outcome}"
