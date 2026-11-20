"""Recount support: the trial saves the rows a rule needs, and the rule turns them into the expected ids.

The recount grader (Ranjani's) compares these ids with the agent's AGENT_RESULT answer. No model or platform
calls: hand-made rows and a small fake reader.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from eval_harness.platform import PlatformError
from eval_harness.rules import RULES, Population, expected_ids, orders_not_invoiced
from eval_harness.suite import GraderSpec, Task
from eval_harness.trial import capture_after, capture_before

AS_OF = datetime(2026, 11, 19, 6, 0, tzinfo=UTC)  # 11:30 in India, so the report date is 19 Nov


def order(order_id: str, day: str, status: str = "unbilled", docstatus: int = 1) -> dict[str, Any]:
    return {"id": order_id, "date": day, "invoiced_status": status, "docstatus": docstatus, "notes": "x"}


# the rule ------------------------------------------------------------------------------------------------


def test_counts_submitted_orders_not_invoiced_and_older_than_the_limit() -> None:
    rows = [
        order("old-unbilled", "2026-11-01"),
        order("old-partial", "2026-11-01", status="partially_invoiced"),
        order("old-invoiced", "2026-11-01", status="invoiced"),
        order("old-draft", "2026-11-01", docstatus=0),
        order("no-date", ""),
    ]
    assert orders_not_invoiced(rows, AS_OF, {"days": 7}) == {"old-unbilled", "old-partial"}


def test_exactly_the_limit_is_not_counted_one_day_more_is() -> None:
    rows = [order("seven", "2026-11-12"), order("eight", "2026-11-11")]
    assert orders_not_invoiced(rows, AS_OF, {"days": 7}) == {"eight"}


def test_report_date_is_the_india_date_not_the_utc_date() -> None:
    late_utc = datetime(2026, 11, 18, 20, 0, tzinfo=UTC)  # already 19 Nov 01:30 in India
    rows = [order("eight-in-india", "2026-11-11")]
    assert orders_not_invoiced(rows, late_utc, {"days": 7}) == {"eight-in-india"}


def test_days_defaults_to_seven_and_a_bad_date_is_skipped() -> None:
    rows = [order("eight", "2026-11-11"), order("bad", "not-a-date")]
    assert orders_not_invoiced(rows, AS_OF, {}) == {"eight"}


# expected ids from a trial record ------------------------------------------------------------------------


def test_expected_ids_come_from_before_and_after() -> None:
    pop = Population(
        entity="SalesOrder",
        as_of=AS_OF,
        before=[order("a", "2026-11-01")],
        after=[order("a", "2026-11-01"), order("b", "2026-11-01")],
    )
    assert expected_ids({"orders_not_invoiced": pop}, "orders_not_invoiced", {}) == ({"a"}, {"a", "b"})


def test_a_read_that_failed_gives_none_never_an_empty_list() -> None:
    pop = Population(entity="SalesOrder", as_of=AS_OF, before=None, after=None)
    assert expected_ids({"orders_not_invoiced": pop}, "orders_not_invoiced", {}) == (None, None)


def test_unknown_or_uncaptured_answer_gives_none() -> None:
    assert expected_ids({}, "orders_not_invoiced", {}) is None
    assert expected_ids({}, "no_such_answer", {}) is None


# capture in the trial -------------------------------------------------------------------------------------


class Reader:
    """Lists SalesOrder rows; `fail` makes every list call raise like a 500."""

    def __init__(self, rows: list[dict[str, Any]], fail: bool = False) -> None:
        self.rows, self.fail, self.calls = rows, fail, 0

    async def list_all(self, entity: str, **filters: Any) -> list[dict[str, Any]]:
        self.calls += 1
        if self.fail:
            raise PlatformError(f"/api/{entity}", 500, "x")
        return self.rows


def recount_task(answer: str = "orders_not_invoiced") -> Task:
    return Task(
        id="t.recount",
        title="t",
        kind="normal",
        exercises=["correctness"],
        version=1,
        author="test",
        prompt="p",
        graders=[GraderSpec(name="recount", answer=answer, days=7)],
        fails_if="x",
    )


def test_capture_keeps_only_the_fields_the_rule_needs() -> None:
    reader = Reader([order("a", "2026-11-01")])
    pops = asyncio.run(capture_before(reader, recount_task(), AS_OF))  # type: ignore[arg-type]
    row = pops["orders_not_invoiced"].before[0]  # type: ignore[index]
    assert set(row) == set(RULES["orders_not_invoiced"].fields) and "notes" not in row
    assert pops["orders_not_invoiced"].as_of == AS_OF and pops["orders_not_invoiced"].after is None


def test_capture_after_reads_again_and_a_failed_read_is_none() -> None:
    pops = asyncio.run(capture_before(Reader([order("a", "2026-11-01")]), recount_task(), AS_OF))  # type: ignore[arg-type]
    after = asyncio.run(capture_after(Reader([], fail=True), pops))  # type: ignore[arg-type]
    assert after["orders_not_invoiced"].before is not None and after["orders_not_invoiced"].after is None


def test_tasks_without_recount_or_with_an_unknown_answer_capture_nothing() -> None:
    reader = Reader([order("a", "2026-11-01")])
    assert asyncio.run(capture_before(reader, recount_task("no_such_answer"), AS_OF)) == {}  # type: ignore[arg-type]
    assert reader.calls == 0
