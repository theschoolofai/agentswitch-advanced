from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ea_briefing.slots import free_slots, label
from fakes import FakeClient

NY = ZoneInfo("America/New_York")
KOL = ZoneInfo("Asia/Kolkata")
ME = {"id": "u1", "email": "Me@Example.test", "name": "Me Myself", "company_id": "c1", "employee_id": "e1",
      "party_id": "p1"}
MON_AFTERNOON = datetime(2026, 11, 9, 15, 0, tzinfo=NY)  # 2026-11-09 is a Monday


def cal(id, **kw):
    base = {"id": id, "name": f"Cal {id}", "type": "personal", "owner_party_id": None, "created_by": "u9",
            "timezone": "America/New_York"}
    base.update(kw)
    return base


CALS = [
    cal("mine", created_by="u1"),
    cal("theirs", created_by="u9", owner_party_id="p9"),
    cal("bday", type="birthday", created_by="admin", owner_party_id="p1"),
    cal("hol", type="holiday", created_by="admin", owner_party_id="p1"),
]


def event(id, start, end, calendar_id="mine", **kw):
    base = {"id": id, "calendar_id": calendar_id, "title": f"Title {id}", "start_at": start, "end_at": end,
            "all_day": False, "location": None, "status": "confirmed", "organizer_email": "boss@example.test",
            "attendees": [], "recurrence_rule": None, "exdates": [], "timezone": "America/New_York"}
    base.update(kw)
    return base


def run(events, now=MON_AFTERNOON, tz=NY, calendars=None, **kw):
    fc = FakeClient(ME, {"Calendar": CALS if calendars is None else calendars, "CalendarEvent": events})
    return fc, free_slots(fc, ME, tz, now, **kw)


def starts(res):
    return [s["start"] for s in res["slots"]]


def test_shape_and_three_earliest_one_per_day():
    fc, res = run([])
    assert set(res) == {"status", "slots", "error"}
    assert res["status"] == "ok" and res["error"] is None
    assert starts(res) == ["2026-11-10T09:00:00-05:00", "2026-11-11T09:00:00-05:00", "2026-11-12T09:00:00-05:00"]
    assert [s["end"] for s in res["slots"]] == ["2026-11-10T09:30:00-05:00", "2026-11-11T09:30:00-05:00",
                                               "2026-11-12T09:30:00-05:00"]
    assert set(res["slots"][0]) == {"start", "end", "label"}
    assert fc.refused == []
    assert all(n.endswith(".list") for n in fc.names())


def test_label_format_exact():
    assert [s["label"] for s in run([])[1]["slots"]] == [
        "Tue 10 Nov, 09:00–09:30 EST", "Wed 11 Nov, 09:00–09:30 EST", "Thu 12 Nov, 09:00–09:30 EST"]


def test_label_single_digit_day_24h_and_ist():
    start = datetime(2026, 11, 2, 14, 0, tzinfo=KOL)
    assert label(start, datetime(2026, 11, 2, 14, 30, tzinfo=KOL)) == "Mon 2 Nov, 14:00–14:30 IST"


def test_kolkata_slot_after_morning_meeting():
    now = datetime(2026, 11, 10, 12, 0, tzinfo=KOL)
    ev = event("m", "2026-11-11T09:00:00+05:30", "2026-11-11T10:00:00+05:30", timezone="Asia/Kolkata")
    _, res = run([ev], now=now, tz=KOL)
    assert res["slots"][0]["label"] == "Wed 11 Nov, 10:00–10:30 IST"
    assert res["slots"][0]["start"] == "2026-11-11T10:00:00+05:30"


def test_meeting_straddling_slot_boundary_blocks_both_slots():
    _, res = run([event("m", "2026-11-10T09:15:00-05:00", "2026-11-10T09:45:00-05:00")])
    assert starts(res)[0] == "2026-11-10T10:00:00-05:00"


def test_meeting_ending_at_slot_start_does_not_block_it():
    _, res = run([event("m", "2026-11-10T09:00:00-05:00", "2026-11-10T09:30:00-05:00")])
    assert starts(res)[0] == "2026-11-10T09:30:00-05:00"


def test_busy_meeting_given_in_utc():
    # 14:00Z is 09:00 EST
    _, res = run([event("m", "2026-11-10T14:00:00Z", "2026-11-10T15:00:00Z")])
    assert starts(res)[0] == "2026-11-10T10:00:00-05:00"


def test_overnight_meeting_from_previous_day_blocks_morning():
    _, res = run([event("m", "2026-11-09T22:00:00-05:00", "2026-11-10T09:30:00-05:00")])
    assert starts(res)[0] == "2026-11-10T09:30:00-05:00"


def test_all_day_on_own_calendar_blocks_the_day():
    ev = event("off", "2026-11-10T00:00:00-05:00", "2026-11-11T00:00:00-05:00", all_day=True)
    _, res = run([ev])
    assert starts(res) == ["2026-11-11T09:00:00-05:00", "2026-11-12T09:00:00-05:00", "2026-11-13T09:00:00-05:00"]


def test_all_day_birthday_and_holiday_not_busy():
    events = [
        event("b", "2026-11-10T00:00:00-05:00", "2026-11-11T00:00:00-05:00", calendar_id="bday", all_day=True),
        event("h", "2026-11-10T00:00:00-05:00", "2026-11-11T00:00:00-05:00", calendar_id="hol", all_day=True),
    ]
    _, res = run(events)
    assert starts(res)[0] == "2026-11-10T09:00:00-05:00"


@pytest.mark.parametrize("status,blocked", [("accepted", True), ("tentative", True), ("declined", False),
                                            ("needs_action", False), (None, False)])
def test_all_day_on_others_calendar_blocks_only_once_accepted(status, blocked):
    attendees = [{"email": "me@example.test", "status": status}] if status else ["me@example.test"]
    ev = event("off", "2026-11-10T00:00:00-05:00", "2026-11-11T00:00:00-05:00", calendar_id="theirs", all_day=True,
               attendees=attendees)
    _, res = run([ev])
    assert starts(res)[0] == ("2026-11-11T09:00:00-05:00" if blocked else "2026-11-10T09:00:00-05:00")


def test_declined_meeting_is_not_busy_but_tentative_and_unanswered_are():
    me_declined = [{"email": "ME@example.test", "status": "declined"}]
    events = [
        event("d", "2026-11-10T09:00:00-05:00", "2026-11-10T17:00:00-05:00", attendees=me_declined),
        event("t", "2026-11-11T09:00:00-05:00", "2026-11-11T10:00:00-05:00", status="tentative"),
        event("n", "2026-11-12T09:00:00-05:00", "2026-11-12T10:00:00-05:00",
              attendees=[{"email": "me@example.test", "status": "needs_action"}]),
    ]
    _, res = run(events)
    assert starts(res) == ["2026-11-10T09:00:00-05:00", "2026-11-11T10:00:00-05:00", "2026-11-12T10:00:00-05:00"]


def test_cancelled_meeting_is_not_busy():
    _, res = run([event("c", "2026-11-10T09:00:00-05:00", "2026-11-10T17:00:00-05:00", status="cancelled")])
    assert starts(res)[0] == "2026-11-10T09:00:00-05:00"


def test_invited_meeting_on_someone_elses_calendar_is_busy():
    ev = event("inv", "2026-11-10T09:00:00-05:00", "2026-11-10T10:00:00-05:00", calendar_id="theirs",
               attendees=[{"email": "me@example.test", "status": "accepted"}])
    _, res = run([ev])
    assert starts(res)[0] == "2026-11-10T10:00:00-05:00"


def test_recurring_meeting_expanded_is_busy():
    ev = event("weekly", "2026-10-06T09:00:00-04:00", "2026-10-06T10:00:00-04:00", recurrence_rule="FREQ=WEEKLY")
    _, res = run([ev])  # Tuesdays 09:00 local, across the DST change
    assert starts(res)[0] == "2026-11-10T10:00:00-05:00"
    assert starts(res)[1] == "2026-11-11T09:00:00-05:00"


def test_unchecked_recurring_pattern_counts_as_busy_at_its_usual_time():
    ev = event("odd", "2026-10-06T09:00:00-04:00", "2026-10-06T10:00:00-04:00",
               recurrence_rule="FREQ=MONTHLY;BYSETPOS=1;BYDAY=TU")
    _, res = run([ev])
    assert starts(res) == ["2026-11-10T10:00:00-05:00", "2026-11-11T10:00:00-05:00", "2026-11-12T10:00:00-05:00"]


def test_weekend_skipped():
    now = datetime(2026, 11, 12, 10, 0, tzinfo=NY)  # Thursday
    _, res = run([], now=now)
    assert starts(res) == ["2026-11-13T09:00:00-05:00", "2026-11-16T09:00:00-05:00", "2026-11-17T09:00:00-05:00"]


@pytest.mark.parametrize("now", [
    datetime(2026, 11, 13, 23, 30, tzinfo=NY),                     # late Friday
    datetime(2026, 11, 14, 4, 30, tzinfo=ZoneInfo("UTC")),         # same instant, given in UTC (already Saturday)
    datetime(2026, 11, 13, 8, 0, tzinfo=NY),                       # Friday morning: still starts next working day
    datetime(2026, 11, 15, 12, 0, tzinfo=NY),                      # Sunday
])
def test_late_friday_and_weekend_start_on_monday(now):
    _, res = run([], now=now)
    assert starts(res) == ["2026-11-16T09:00:00-05:00", "2026-11-17T09:00:00-05:00", "2026-11-18T09:00:00-05:00"]


def test_naive_now_is_taken_in_the_user_zone():
    _, res = run([], now=datetime(2026, 11, 13, 23, 30))
    assert starts(res)[0] == "2026-11-16T09:00:00-05:00"


def test_fewer_than_three_when_week_is_full():
    full = [event(f"f{d}", f"2026-11-{d}T08:00:00-05:00", f"2026-11-{d}T17:30:00-05:00") for d in (10, 11, 12, 13)]
    _, res = run(full)  # Tue-Fri full, Mon 16 is the fifth working day
    assert res["status"] == "ok"
    assert starts(res) == ["2026-11-16T09:00:00-05:00"]


def test_no_free_time_is_ok_and_empty():
    full = [event(f"f{d}", f"2026-11-{d}T09:00:00-05:00", f"2026-11-{d}T17:00:00-05:00")
            for d in (10, 11, 12, 13, 16)]
    _, res = run(full)
    assert res == {"status": "ok", "slots": [], "error": None}


def test_only_five_working_days_are_checked():
    full = [event(f"f{d}", f"2026-11-{d}T09:00:00-05:00", f"2026-11-{d}T17:00:00-05:00") for d in (10, 11, 12, 13)]
    fc, res = run(full, days=4)
    assert res["slots"] == []
    assert not any("2026-11-16" in str(a.get("start_at")) or "2026-11-17" in str(a.get("start_at"))
                   for a in fc.calls_to("CalendarEvent.list"))


def test_last_slot_of_day_ends_at_end_hour():
    _, res = run([event("m", "2026-11-10T09:00:00-05:00", "2026-11-10T16:30:00-05:00")])
    assert res["slots"][0]["label"] == "Tue 10 Nov, 16:30–17:00 EST"


def test_dst_fall_back_offset_and_abbreviation():
    now = datetime(2026, 10, 30, 16, 0, tzinfo=NY)  # Friday, EDT; clocks go back Sunday 1 Nov
    _, res = run([event("m", "2026-11-02T14:00:00Z", "2026-11-02T14:30:00Z")], now=now)  # 09:00 EST, 10:00 EDT
    assert res["slots"][0]["start"] == "2026-11-02T09:30:00-05:00"
    assert res["slots"][0]["label"] == "Mon 2 Nov, 09:30–10:00 EST"


def test_dst_spring_forward_offset_and_abbreviation():
    now = datetime(2026, 3, 6, 16, 0, tzinfo=NY)  # Friday, EST; clocks go forward Sunday 8 Mar
    _, res = run([], now=now)
    assert res["slots"][0]["start"] == "2026-03-09T09:00:00-04:00"
    assert res["slots"][0]["label"] == "Mon 9 Mar, 09:00–09:30 EDT"


def test_custom_window_and_length():
    _, res = run([], start_hour=13, end_hour=15, minutes=60, max_slots=2)
    assert [s["label"] for s in res["slots"]] == ["Tue 10 Nov, 13:00–14:00 EST", "Wed 11 Nov, 13:00–14:00 EST"]


def test_failed_event_read_is_an_error_not_empty():
    fc = FakeClient(ME, {"Calendar": CALS, "CalendarEvent": []})
    fc.fail("CalendarEvent.list", kind="forbidden", message="no access")
    res = free_slots(fc, ME, NY, MON_AFTERNOON)
    assert res["status"] == "error"
    assert res["slots"] == []
    assert "no access" in res["error"]


def test_truncated_calendar_read_offers_nothing():
    fc = FakeClient(ME, {"Calendar": CALS, "CalendarEvent": []})
    fc.total_override["CalendarEvent.list"] = 5000
    res = free_slots(fc, ME, NY, MON_AFTERNOON)
    assert res["status"] == "error" and res["slots"] == []
    assert "capped" in res["error"]


def test_unscoped_user_is_an_error():
    res = free_slots(FakeClient({}, {"Calendar": CALS, "CalendarEvent": []}), {}, NY, MON_AFTERNOON)
    assert res["status"] == "error" and "cannot scope" in res["error"]


@pytest.mark.parametrize("client,now,kw", [
    (None, MON_AFTERNOON, {}),
    ("x", MON_AFTERNOON, {}),
    (FakeClient(ME, {"Calendar": CALS, "CalendarEvent": []}), None, {}),
    (FakeClient(ME, {"Calendar": CALS, "CalendarEvent": []}), "2026-11-09", {}),
    (FakeClient(ME, {"Calendar": CALS, "CalendarEvent": []}), MON_AFTERNOON, {"minutes": 0}),
    (FakeClient(ME, {"Calendar": CALS, "CalendarEvent": []}), MON_AFTERNOON, {"start_hour": 17, "end_hour": 9}),
    (FakeClient(ME, {"Calendar": CALS, "CalendarEvent": []}), MON_AFTERNOON, {"days": 0}),
    (FakeClient(ME, {"Calendar": CALS, "CalendarEvent": []}), MON_AFTERNOON, {"minutes": 600}),
])
def test_never_raises(client, now, kw):
    res = free_slots(client, ME, NY, now, **kw)
    assert res["status"] == "error"
    assert res["slots"] == []
    assert isinstance(res["error"], str) and res["error"]


# ---- platform calls: each costs ~2 s live, so the search must not grow with the number of days ------------------

def test_one_read_for_the_whole_search_span():
    events = [event("m", "2026-11-10T09:00:00-05:00", "2026-11-10T17:00:00-05:00"),
              event("w", "2026-10-06T09:00:00-04:00", "2026-10-06T10:00:00-04:00", recurrence_rule="FREQ=WEEKLY")]
    fc, res = run(events, days=5)
    assert len(res["slots"]) == 3
    assert fc.names().count("Calendar.list") == 1
    ev_calls = fc.calls_to("CalendarEvent.list")
    one_off = [a for a in ev_calls if "calendar_id" not in a]
    masters = [a for a in ev_calls if "calendar_id" in a]
    assert len(one_off) == 1
    assert sorted(a["calendar_id"] for a in masters) == ["mine"]  # one masters read per own meeting calendar
    # the single window runs from the first to the end of the last working day (Tue 10 .. Mon 16)
    assert one_off[0]["end_at"] == "gt:2026-11-10T00:00:00-05:00"
    assert one_off[0]["start_at"] == "lt:2026-11-17T00:00:00-05:00"
    assert masters[0]["start_at"] == "lt:2026-11-17T00:00:00-05:00"


def test_call_count_does_not_depend_on_days():
    counts = []
    for days in (1, 5, 10):
        fc, _ = run([], days=days)
        counts.append(len(fc.calls))
    assert counts[0] == counts[1] == counts[2]


def test_recurring_master_starting_later_in_span_not_busy_before_it_starts():
    ev = event("new", "2026-11-12T09:00:00-05:00", "2026-11-12T10:00:00-05:00", recurrence_rule="FREQ=DAILY")
    _, res = run([ev])
    assert starts(res) == ["2026-11-10T09:00:00-05:00", "2026-11-11T09:00:00-05:00", "2026-11-12T10:00:00-05:00"]


def test_typical_run_reads_calendars_once():
    from ea_briefing.collect import collect_meetings, resolve_tz
    from datetime import date
    fc = FakeClient(ME, {"Calendar": CALS, "CalendarEvent": []})
    tz = resolve_tz(fc, ME, None, "keystone")
    collect_meetings(fc, ME, date(2026, 11, 9), tz)
    free_slots(fc, ME, tz, MON_AFTERNOON)
    assert fc.names().count("Calendar.list") == 1
    # zone 1 + today's meetings (1 window + 1 masters) + free time (1 window + 1 masters)
    assert len(fc.calls) == 5
