"""Answer rules for recount tasks: the harness works out the right answer itself, from platform rows.

A recount task asks the agent a question ("which orders are not invoiced?"). The agent states its answer
in its AGENT_RESULT line; the recount grader compares it with the ids a rule here picks from saved rows.
The truth always comes from the platform, never from the agent (decision 0011, which amends 0005).

Each rule is written from the seat's own written rule, never by importing the seat's code: checking an agent
against its own code would only prove it agrees with itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel

IST = timezone(timedelta(hours=5, minutes=30))  # seat 31 dates its report in India time (`today_ist`)
NOT_INVOICED = ("unbilled", "partially_invoiced")
SUBMITTED = 1


class Population(BaseModel):
    """The rows one rule needs, read before and after the agent ran (only the rule's fields are kept)."""

    entity: str
    as_of: datetime | None = None  # the platform's clock when `before` was read
    before: list[dict[str, Any]] | None = None  # None: the read failed (could not check)
    after: list[dict[str, Any]] | None = None


Select = Callable[[list[dict[str, Any]], datetime, dict[str, Any]], set[str]]


@dataclass(frozen=True)
class Rule:
    entity: str
    fields: tuple[str, ...]
    select: Select


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def orders_not_invoiced(rows: list[dict[str, Any]], as_of: datetime, params: dict[str, Any]) -> set[str]:
    """Seat 31's rule: submitted orders, not (fully) invoiced, dated more than `days` days (default 7)
    before the report date. The report date is the India date of `as_of`. One pass: O(n) in rows."""
    days = int(params.get("days", 7))
    report_date = as_of.astimezone(IST).date()
    picked: set[str] = set()
    for row in rows:
        if row.get("docstatus") != SUBMITTED or row.get("invoiced_status") not in NOT_INVOICED:
            continue
        day = _day(row.get("date"))
        if day is not None and (report_date - day).days > days:
            picked.add(str(row["id"]))
    return picked


RULES: dict[str, Rule] = {
    "orders_not_invoiced": Rule(
        entity="SalesOrder",
        fields=("id", "docstatus", "invoiced_status", "date"),
        select=orders_not_invoiced,
    ),
}


def expected_ids(
    population: dict[str, Population], answer: str, params: dict[str, Any]
) -> tuple[set[str] | None, set[str] | None] | None:
    """The right ids before and after the agent ran. None for either side means that read failed.
    None overall means nothing was captured for this answer (unknown answer, or not a recount task)."""
    rule, pop = RULES.get(answer), population.get(answer)
    if rule is None or pop is None or pop.as_of is None:
        return None
    before = rule.select(pop.before, pop.as_of, params) if pop.before is not None else None
    after = rule.select(pop.after, pop.as_of, params) if pop.after is not None else None
    return before, after
