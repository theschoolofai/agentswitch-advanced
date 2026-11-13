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
    "FREQ=HOURLY",
    "FREQ=MINUTELY",
    "FREQ=SECONDLY",
    "FREQ=MONTHLY;BYSETPOS=1;BYDAY=MO",
    "FREQ=MONTHLY;BYSETPOS=-1;BYDAY=MO,TU,WE,TH,FR",
    "FREQ=YEARLY;BYWEEKNO=20",
    "FREQ=YEARLY;BYYEARDAY=100",
    "FREQ=DAILY;BYHOUR=9,17",
    "FREQ=DAILY;BYMINUTE=30",
    "FREQ=WEEKLY;BYDAY=1WE",
    "FREQ=DAILY;BYDAY=2WE",
    "FREQ=YEARLY;BYDAY=1WE",
    "FREQ=MONTHLY;BYDAY=0WE",
    "FREQ=MONTHLY;BYDAY=WEX",
    "FREQ=MONTHLY;BYMONTHDAY=0",
    "FREQ=MONTHLY;BYMONTHDAY=32",
    "FREQ=MONTHLY;BYMONTHDAY=1,,2",
    "FREQ=MONTHLY;BYMONTH=13",
    "FREQ=MONTHLY;BYMONTH=-1",
    "FREQ=WEEKLY;BYMONTHDAY=4",
    "FREQ=MONTHLY;COUNT=0",
    "FREQ=YEARLY;FREQ=YEARLY",
    "garbage",
    "FREQ=WEEKLY;INTERVAL=abc",
    "",
])
def test_unsupported_returns_none(rule):
    assert occurs_on(ev(rule), date(2026, 11, 4), NY) is None


# ---- D10: YEARLY, MONTHLY BYDAY ordinals / BYMONTHDAY lists, BYMONTH filter, COUNT --------------------------------

def test_yearly_on_dtstart_month_and_day():
    e = ev("FREQ=YEARLY", start="2024-11-04T10:00:00-05:00", end="2024-11-04T11:00:00-05:00")
    assert occurs_on(e, date(2026, 11, 4), NY) is True
    assert occurs_on(e, date(2026, 11, 5), NY) is False
    assert occurs_on(e, date(2026, 10, 4), NY) is False
    assert occurs_on(e, date(2023, 11, 4), NY) is False


def test_yearly_interval():
    e = ev("FREQ=YEARLY;INTERVAL=2", start="2024-11-04T10:00:00-05:00", end="2024-11-04T11:00:00-05:00")
    assert occurs_on(e, date(2026, 11, 4), NY) is True
    assert occurs_on(e, date(2025, 11, 4), NY) is False


def test_yearly_feb_29_only_in_leap_years():
    e = ev("FREQ=YEARLY", start="2024-02-29T09:00:00-05:00", end="2024-02-29T10:00:00-05:00")
    assert occurs_on(e, date(2028, 2, 29), NY) is True
    # skipped, not moved to the 28th or 1 March
    assert occurs_on(e, date(2025, 2, 28), NY) is False
    assert occurs_on(e, date(2025, 3, 1), NY) is False
    assert occurs_on(e, date(2100, 2, 28), NY) is False


def test_yearly_feb_29_count_counts_only_real_occurrences():
    # 2024-02-29 (1), 2028 (2), 2032 (3): the non-leap years produce nothing to count.
    e = ev("FREQ=YEARLY;COUNT=3", start="2024-02-29T09:00:00-05:00", end="2024-02-29T10:00:00-05:00")
    assert occurs_on(e, date(2032, 2, 29), NY) is True
    assert occurs_on(e, date(2036, 2, 29), NY) is False


def test_yearly_bymonth_and_bymonthday():
    e = ev("FREQ=YEARLY;BYMONTH=3,11;BYMONTHDAY=4", start="2026-03-04T10:00:00-05:00",
           end="2026-03-04T11:00:00-05:00")
    assert occurs_on(e, date(2026, 11, 4), NY) is True
    assert occurs_on(e, date(2027, 3, 4), NY) is True
    assert occurs_on(e, date(2026, 10, 4), NY) is False
    assert occurs_on(e, date(2026, 11, 5), NY) is False


def test_yearly_bymonth_only_takes_dtstart_day():
    e = ev("FREQ=YEARLY;BYMONTH=6,11", start="2026-06-04T10:00:00-04:00", end="2026-06-04T11:00:00-04:00")
    assert occurs_on(e, date(2026, 11, 4), NY) is True
    assert occurs_on(e, date(2026, 11, 5), NY) is False
    assert occurs_on(e, date(2026, 7, 4), NY) is False


def test_yearly_bymonthday_without_bymonth_is_every_month():
    # RFC 5545: BYMONTHDAY expands a YEARLY rule over every month (python-dateutil agrees).
    e = ev("FREQ=YEARLY;BYMONTHDAY=4", start="2026-01-04T10:00:00-05:00", end="2026-01-04T11:00:00-05:00")
    assert occurs_on(e, date(2026, 11, 4), NY) is True
    assert occurs_on(e, date(2026, 11, 5), NY) is False


def test_yearly_bymonth_byday_ordinal_is_within_the_month():
    # US Thanksgiving: fourth Thursday of November. 2026-11-26 is the fourth Thursday.
    e = ev("FREQ=YEARLY;BYMONTH=11;BYDAY=4TH", start="2025-11-27T12:00:00-05:00", end="2025-11-27T15:00:00-05:00")
    assert occurs_on(e, date(2026, 11, 26), NY) is True
    assert occurs_on(e, date(2026, 11, 19), NY) is False
    assert occurs_on(e, date(2027, 11, 25), NY) is True


def test_monthly_byday_ordinal_second_tuesday():
    e = ev("FREQ=MONTHLY;BYDAY=2TU", start="2026-09-08T10:00:00-04:00", end="2026-09-08T11:00:00-04:00")
    assert occurs_on(e, date(2026, 11, 10), NY) is True
    assert occurs_on(e, date(2026, 11, 3), NY) is False
    assert occurs_on(e, date(2026, 11, 17), NY) is False
    assert occurs_on(e, date(2026, 10, 13), NY) is True


def test_monthly_last_friday_in_five_friday_month():
    # January 2027 has five Fridays (1, 8, 15, 22, 29): -1FR is the 29th, not the 22nd.
    e = ev("FREQ=MONTHLY;BYDAY=-1FR", start="2026-10-30T10:00:00-04:00", end="2026-10-30T11:00:00-04:00")
    assert occurs_on(e, date(2027, 1, 29), NY) is True
    assert occurs_on(e, date(2027, 1, 22), NY) is False
    # November 2026 has four Fridays; the last is the 27th.
    assert occurs_on(e, date(2026, 11, 27), NY) is True
    assert occurs_on(e, date(2026, 11, 20), NY) is False


def test_monthly_fifth_weekday_skips_months_without_one():
    e = ev("FREQ=MONTHLY;BYDAY=5FR", start="2026-10-30T10:00:00-04:00", end="2026-10-30T11:00:00-04:00")
    assert occurs_on(e, date(2027, 1, 29), NY) is True
    assert occurs_on(e, date(2026, 11, 27), NY) is False  # only 4 Fridays in November 2026


def test_monthly_plain_byday_is_every_such_weekday():
    e = ev("FREQ=MONTHLY;BYDAY=WE", start="2026-10-07T10:00:00-04:00", end="2026-10-07T11:00:00-04:00")
    assert occurs_on(e, date(2026, 11, 4), NY) is True
    assert occurs_on(e, date(2026, 11, 25), NY) is True
    assert occurs_on(e, date(2026, 11, 5), NY) is False


def test_monthly_bymonthday_list_with_negative():
    e = ev("FREQ=MONTHLY;BYMONTHDAY=1,15,-1", start="2026-10-01T10:00:00-04:00", end="2026-10-01T11:00:00-04:00")
    assert occurs_on(e, date(2026, 11, 1), NY) is True
    assert occurs_on(e, date(2026, 11, 15), NY) is True
    assert occurs_on(e, date(2026, 11, 30), NY) is True
    assert occurs_on(e, date(2026, 11, 29), NY) is False
    assert occurs_on(e, date(2027, 2, 28), NY) is True
    assert occurs_on(e, date(2028, 2, 29), NY) is True
    assert occurs_on(e, date(2028, 2, 28), NY) is False


def test_monthly_31st_skips_short_months():
    e = ev("FREQ=MONTHLY", start="2026-08-31T10:00:00-04:00", end="2026-08-31T11:00:00-04:00")
    assert occurs_on(e, date(2026, 10, 31), NY) is True
    assert occurs_on(e, date(2026, 11, 30), NY) is False
    assert occurs_on(e, date(2026, 12, 1), NY) is False
    e2 = ev("FREQ=MONTHLY;BYMONTHDAY=31", start="2026-08-31T10:00:00-04:00", end="2026-08-31T11:00:00-04:00")
    assert occurs_on(e2, date(2026, 11, 30), NY) is False
    assert occurs_on(e2, date(2026, 12, 31), NY) is True


def test_monthly_31st_count_skipped_months_not_counted():
    # Aug 31 (1), Oct 31 (2), Dec 31 (3), Jan 31 (4): September and November have no 31st.
    e = ev("FREQ=MONTHLY;COUNT=4", start="2026-08-31T10:00:00-04:00", end="2026-08-31T11:00:00-04:00")
    assert occurs_on(e, date(2027, 1, 31), NY) is True
    assert occurs_on(e, date(2027, 3, 31), NY) is False


def test_monthly_byday_and_bymonthday_intersect():
    # Friday the 13th: BYMONTHDAY expands, BYDAY narrows. 2026-11-13 is a Friday; 2026-10-13 is a Tuesday.
    e = ev("FREQ=MONTHLY;BYDAY=FR;BYMONTHDAY=13", start="2026-02-13T10:00:00-05:00", end="2026-02-13T11:00:00-05:00")
    assert occurs_on(e, date(2026, 11, 13), NY) is True
    assert occurs_on(e, date(2026, 10, 13), NY) is False
    assert occurs_on(e, date(2026, 11, 20), NY) is False


def test_monthly_byday_ordinal_with_interval():
    e = ev("FREQ=MONTHLY;INTERVAL=2;BYDAY=1WE", start="2026-09-02T10:00:00-04:00", end="2026-09-02T11:00:00-04:00")
    assert occurs_on(e, date(2026, 11, 4), NY) is True
    assert occurs_on(e, date(2026, 10, 7), NY) is False


def test_monthly_byday_ordinal_count_exhausted():
    # 2TU from Sep 8: Sep 8 (1), Oct 13 (2), Nov 10 (3).
    e = ev("FREQ=MONTHLY;BYDAY=2TU;COUNT=2", start="2026-09-08T10:00:00-04:00", end="2026-09-08T11:00:00-04:00")
    assert occurs_on(e, date(2026, 10, 13), NY) is True
    assert occurs_on(e, date(2026, 11, 10), NY) is False
    e3 = ev("FREQ=MONTHLY;BYDAY=2TU;COUNT=3", start="2026-09-08T10:00:00-04:00", end="2026-09-08T11:00:00-04:00")
    assert occurs_on(e3, date(2026, 11, 10), NY) is True


def test_monthly_bymonthday_list_count_counts_each_day_in_order():
    # 1st and 15th from Oct 1: Oct 1, Oct 15, Nov 1, Nov 15 (4th), Dec 1 (5th).
    e = ev("FREQ=MONTHLY;BYMONTHDAY=1,15;COUNT=4", start="2026-10-01T10:00:00-04:00", end="2026-10-01T11:00:00-04:00")
    assert occurs_on(e, date(2026, 11, 15), NY) is True
    assert occurs_on(e, date(2026, 12, 1), NY) is False


def test_monthly_until_boundary():
    # 10:00 New York on 2026-11-10 (second Tuesday) is 15:00Z
    rule = "FREQ=MONTHLY;BYDAY=2TU;UNTIL=20261110T150000Z"
    e = ev(rule, start="2026-09-08T10:00:00-04:00", end="2026-09-08T11:00:00-04:00")
    assert occurs_on(e, date(2026, 11, 10), NY) is True
    e2 = ev(rule.replace("150000Z", "145959Z"), start="2026-09-08T10:00:00-04:00", end="2026-09-08T11:00:00-04:00")
    assert occurs_on(e2, date(2026, 11, 10), NY) is False
    assert occurs_on(e2, date(2026, 10, 13), NY) is True


def test_bymonth_filters_weekly_daily_and_monthly():
    weekly = ev("FREQ=WEEKLY;BYMONTH=11,12")
    assert occurs_on(weekly, date(2026, 11, 4), NY) is True
    assert occurs_on(weekly, date(2026, 10, 28), NY) is False
    daily = ev("FREQ=DAILY;BYMONTH=11", start="2026-10-30T08:00:00-04:00", end="2026-10-30T08:15:00-04:00")
    assert occurs_on(daily, date(2026, 11, 4), NY) is True
    assert occurs_on(daily, date(2026, 10, 31), NY) is False
    monthly = ev("FREQ=MONTHLY;BYDAY=1WE;BYMONTH=1,11", start="2026-01-07T10:00:00-05:00",
                 end="2026-01-07T11:00:00-05:00")
    assert occurs_on(monthly, date(2026, 11, 4), NY) is True
    assert occurs_on(monthly, date(2026, 10, 7), NY) is False


def test_bymonth_filter_count_only_counts_kept_occurrences():
    # Weekly Wednesdays limited to November, from 2026-10-07: Oct 7 is DTSTART (1), then Nov 4 (2), Nov 11 (3).
    e = ev("FREQ=WEEKLY;BYMONTH=11;COUNT=3")
    assert occurs_on(e, date(2026, 11, 11), NY) is True
    assert occurs_on(e, date(2026, 11, 18), NY) is False


def test_daily_byday_limits_to_weekdays():
    e = ev("FREQ=DAILY;BYDAY=MO,TU,WE,TH,FR", start="2026-11-02T08:00:00-05:00", end="2026-11-02T08:15:00-05:00")
    assert occurs_on(e, date(2026, 11, 6), NY) is True
    assert occurs_on(e, date(2026, 11, 7), NY) is False
    assert occurs_on(e, date(2026, 11, 8), NY) is False


def test_dtstart_counts_as_first_occurrence_even_off_rule():
    # RFC 5545 3.8.5.3: DTSTART always counts as the first occurrence. Start Wed, rule says Fridays, COUNT=2:
    # Wed Oct 7 (1), Fri Oct 9 (2), Fri Oct 16 would be the third.
    e = ev("FREQ=WEEKLY;BYDAY=FR;COUNT=2")
    assert occurs_on(e, date(2026, 10, 7), NY) is True
    assert occurs_on(e, date(2026, 10, 9), NY) is True
    assert occurs_on(e, date(2026, 10, 16), NY) is False
    assert occurs_on(e, date(2026, 10, 14), NY) is False


def test_live_data_patterns_still_expand():
    fr = ev("RRULE:FREQ=WEEKLY;BYDAY=FR", start="2026-10-02T10:00:00-04:00", end="2026-10-02T11:00:00-04:00")
    mo = ev("RRULE:FREQ=WEEKLY;BYDAY=MO", start="2026-10-05T10:00:00-04:00", end="2026-10-05T11:00:00-04:00")
    assert occurs_on(fr, date(2026, 11, 6), NY) is True
    assert occurs_on(fr, date(2026, 11, 9), NY) is False
    assert occurs_on(mo, date(2026, 11, 9), NY) is True
    assert occurs_on(mo, date(2026, 11, 6), NY) is False


def test_yearly_exdate_still_excludes():
    e = ev("FREQ=YEARLY", start="2024-11-04T10:00:00-05:00", end="2024-11-04T11:00:00-05:00",
           exdates=["2026-11-04"])
    assert occurs_on(e, date(2026, 11, 4), NY) is False
    assert occurs_on(e, date(2027, 11, 4), NY) is True
