from datetime import date
from zoneinfo import ZoneInfo

import pytest

from ea_briefing.rrule import occurs_on

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def ev(rule, start="2026-10-07T10:00:00-04:00", end="2026-10-07T11:00:00-04:00", exdates=None):
    return {"id": "r", "start_at": start, "end_at": end, "recurrence_rule": rule, "exdates": exdates or []}


# 2026-10-07 is a Wednesday; 2026-11-04 is a Wednesday; 2026-10-26 and 2026-11-02 are Mondays.

@pytest.mark.parametrize("rule", ["FREQ=WEEKLY", "RRULE:FREQ=WEEKLY", "FREQ=WEEKLY;BYDAY=WE", "RRULE:FREQ=WEEKLY;BYDAY=WE"])
def test_weekly_with_and_without_prefix(rule):
    assert occurs_on(ev(rule), date(2026, 11, 4), NY) is True
    assert occurs_on(ev(rule), date(2026, 11, 5), NY) is False


def test_before_dtstart_is_false():
    assert occurs_on(ev("FREQ=WEEKLY"), date(2026, 9, 30), NY) is False


def test_dtstart_day_itself():
    assert occurs_on(ev("FREQ=WEEKLY"), date(2026, 10, 7), NY) is True


def test_weekly_byday_multiple():
    e = ev("FREQ=WEEKLY;BYDAY=MO,WE,FR", start="2026-10-26T09:00:00-04:00", end="2026-10-26T09:30:00-04:00")
    assert occurs_on(e, date(2026, 11, 4), NY) is True
    assert occurs_on(e, date(2026, 11, 6), NY) is True
    assert occurs_on(e, date(2026, 11, 5), NY) is False


def test_weekly_interval_two():
    e = ev("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,WE", start="2026-10-26T09:00:00-04:00", end="2026-10-26T09:30:00-04:00")
    assert occurs_on(e, date(2026, 10, 28), NY) is True
    assert occurs_on(e, date(2026, 11, 2), NY) is False
    assert occurs_on(e, date(2026, 11, 4), NY) is False
    assert occurs_on(e, date(2026, 11, 9), NY) is True
    assert occurs_on(e, date(2026, 11, 11), NY) is True


def test_weekly_count_exhausted():
    assert occurs_on(ev("FREQ=WEEKLY;COUNT=4"), date(2026, 10, 28), NY) is True
    assert occurs_on(ev("FREQ=WEEKLY;COUNT=4"), date(2026, 11, 4), NY) is False
    assert occurs_on(ev("FREQ=WEEKLY;COUNT=5"), date(2026, 11, 4), NY) is True


def test_weekly_count_counts_each_byday_occurrence():
    e = ev("FREQ=WEEKLY;BYDAY=MO,WE;COUNT=3", start="2026-10-26T09:00:00-04:00", end="2026-10-26T09:30:00-04:00")
    assert occurs_on(e, date(2026, 11, 2), NY) is True
    assert occurs_on(e, date(2026, 11, 4), NY) is False


def test_until_boundary_inclusive():
    # 10:00 New York on 2026-11-04 is 15:00Z
    assert occurs_on(ev("FREQ=WEEKLY;UNTIL=20261104T150000Z"), date(2026, 11, 4), NY) is True
    assert occurs_on(ev("FREQ=WEEKLY;UNTIL=20261104T145959Z"), date(2026, 11, 4), NY) is False
    assert occurs_on(ev("FREQ=WEEKLY;UNTIL=20261028T150000Z"), date(2026, 11, 4), NY) is False


def test_until_date_only():
    assert occurs_on(ev("FREQ=WEEKLY;UNTIL=20261104"), date(2026, 11, 4), NY) is True
    assert occurs_on(ev("FREQ=WEEKLY;UNTIL=20261103"), date(2026, 11, 4), NY) is False


def test_daily_interval():
    e = ev("FREQ=DAILY;INTERVAL=2", start="2026-11-01T08:00:00-04:00", end="2026-11-01T08:15:00-04:00")
    assert occurs_on(e, date(2026, 11, 1), NY) is True
    assert occurs_on(e, date(2026, 11, 2), NY) is False
    assert occurs_on(e, date(2026, 11, 3), NY) is True
    assert occurs_on(e, date(2026, 11, 4), NY) is False
    assert occurs_on(e, date(2026, 11, 5), NY) is True


def test_daily_plain_and_count():
    e = ev("FREQ=DAILY;COUNT=3", start="2026-11-01T08:00:00-04:00", end="2026-11-01T08:15:00-04:00")
    assert occurs_on(e, date(2026, 11, 3), NY) is True
    assert occurs_on(e, date(2026, 11, 4), NY) is False


def test_monthly_by_month_day():
    e = ev("FREQ=MONTHLY", start="2026-08-04T14:00:00-04:00", end="2026-08-04T15:00:00-04:00")
    assert occurs_on(e, date(2026, 11, 4), NY) is True
    assert occurs_on(e, date(2026, 11, 5), NY) is False
    assert occurs_on(e, date(2026, 7, 4), NY) is False


def test_monthly_interval():
    e = ev("FREQ=MONTHLY;INTERVAL=2", start="2026-08-04T14:00:00-04:00", end="2026-08-04T15:00:00-04:00")
    assert occurs_on(e, date(2026, 10, 4), NY) is True
    assert occurs_on(e, date(2026, 11, 4), NY) is False


def test_dtstart_is_taken_in_given_tz():
    # 02:30Z on Wednesday is still Tuesday evening in New York.
    e = ev("FREQ=WEEKLY", start="2026-10-07T02:30:00+00:00", end="2026-10-07T03:00:00+00:00")
    assert occurs_on(e, date(2026, 11, 3), NY) is True
    assert occurs_on(e, date(2026, 11, 4), NY) is False
    assert occurs_on(e, date(2026, 11, 4), UTC) is True


def test_exdate_datetime_excludes():
    e = ev("FREQ=WEEKLY", exdates=["2026-11-04T10:00:00-05:00"])
    assert occurs_on(e, date(2026, 11, 4), NY) is False
    assert occurs_on(e, date(2026, 11, 11), NY) is True


def test_exdate_date_only_excludes():
    e = ev("FREQ=WEEKLY", exdates=["2026-11-04"])
    assert occurs_on(e, date(2026, 11, 4), NY) is False


@pytest.mark.parametrize("rule", [
    "FREQ=YEARLY",
    "FREQ=HOURLY",
    "FREQ=MONTHLY;BYSETPOS=1;BYDAY=MO",
    "FREQ=MONTHLY;BYMONTHDAY=1,15",
    "FREQ=MONTHLY;BYDAY=2MO",
    "FREQ=WEEKLY;BYDAY=1WE",
    "garbage",
    "FREQ=WEEKLY;INTERVAL=abc",
    "",
])
def test_unsupported_returns_none(rule):
    assert occurs_on(ev(rule), date(2026, 11, 4), NY) is None
