from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ea_briefing.collect import collect_meetings
from fakes import FakeClient

NY = ZoneInfo("America/New_York")
DAY = date(2026, 11, 4)  # a Wednesday, after the 2026-11-01 DST change
ME = {"id": "u1", "email": "Me@Example.test", "name": "Me Myself", "company_id": "c1", "employee_id": "e1",
      "party_id": "p1"}

ITEM_KEYS = {"id", "title", "start_at", "end_at", "all_day", "location", "calendar", "recurring", "expanded"}


def cal(id, **kw):
    base = {"id": id, "name": f"Cal {id}", "type": "personal", "owner_party_id": None, "created_by": "u9",
            "timezone": "America/New_York"}
    base.update(kw)
    return base


def event(id, start, end, calendar_id="mine", **kw):
    base = {"id": id, "calendar_id": calendar_id, "title": f"Title {id}", "start_at": start, "end_at": end,
            "all_day": False, "location": None, "status": "confirmed", "organizer_email": "boss@example.test",
            "attendees": [], "recurrence_rule": None, "exdates": [], "timezone": "America/New_York",
            "effective_timezone": "America/New_York", "created_by": "u9"}
    base.update(kw)
    return base


def base_calendars():
    return [
        cal("mine", created_by="u1", name="My Calendar"),
        cal("party", created_by="admin", owner_party_id="p1", name="Party Calendar"),
        cal("theirs", created_by="u9", owner_party_id="p9", name="Their Calendar"),
        cal("orphan", created_by="u8", owner_party_id=None, name="Orphan Calendar"),
        cal("bday", type="birthday", created_by="admin", owner_party_id="p1", name="Birthdays"),
        cal("hol", type="holiday", created_by="admin", owner_party_id="p1", name="Holidays"),
        cal("sub", type="subscribed", created_by="admin", owner_party_id="p1", name="Subscribed"),
        cal("mysub", type="subscribed", created_by="u1", name="My Subscribed"),
    ]


def run(events, calendars=None, me=ME, day=DAY, tz=NY):
    fc = FakeClient(me, {"Calendar": base_calendars() if calendars is None else calendars, "CalendarEvent": events},
                    today=day)
    section = collect_meetings(fc, me, day, tz)
    return fc, section


def ids(section):
    return [i["id"] for i in section["items"]]


def same_instant(a, b):
    return datetime.fromisoformat(a.replace("Z", "+00:00")) == datetime.fromisoformat(b.replace("Z", "+00:00"))


def test_section_shape_and_item_keys():
    fc, s = run([event("e1", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00", location="Room 1")])
    assert s["status"] == "ok"
    assert s["error"] is None
    assert s["truncated"] is False
    assert isinstance(s["notes"], list)
    assert ids(s) == ["e1"]
    item = s["items"][0]
    assert ITEM_KEYS <= set(item)
    assert item["title"] == "Title e1"
    assert item["location"] == "Room 1"
    assert item["calendar"] == "My Calendar"
    assert item["recurring"] is False
    assert fc.refused == []


def test_scoping_by_calendar_organizer_and_attendees():
    events = [
        event("on_mine", "2026-11-04T09:00:00-05:00", "2026-11-04T09:30:00-05:00", calendar_id="mine"),
        event("on_party", "2026-11-04T09:10:00-05:00", "2026-11-04T09:40:00-05:00", calendar_id="party"),
        event("theirs_plain", "2026-11-04T09:20:00-05:00", "2026-11-04T09:50:00-05:00", calendar_id="theirs"),
        event("theirs_org", "2026-11-04T09:30:00-05:00", "2026-11-04T10:00:00-05:00", calendar_id="theirs",
              organizer_email="ME@EXAMPLE.TEST"),
        event("theirs_att_dict", "2026-11-04T09:40:00-05:00", "2026-11-04T10:10:00-05:00", calendar_id="theirs",
              attendees=[{"email": "x@example.test"}, {"email": "me@example.TEST", "name": "Me"}]),
        event("theirs_att_str", "2026-11-04T09:50:00-05:00", "2026-11-04T10:20:00-05:00", calendar_id="theirs",
              attendees=["someone@example.test", "  ME@example.test"]),
        event("theirs_att_other", "2026-11-04T10:00:00-05:00", "2026-11-04T10:30:00-05:00", calendar_id="theirs",
              attendees=[{"email": "notme@example.test"}, "alsonotme@example.test", {"name": "no email"}]),
        event("theirs_similar", "2026-11-04T10:10:00-05:00", "2026-11-04T10:40:00-05:00", calendar_id="theirs",
              organizer_email="me@example.test.evil", attendees=["xme@example.test"]),
    ]
    fc, s = run(events)
    got = set(ids(s))
    assert {"on_mine", "on_party", "theirs_org", "theirs_att_dict"} <= got
    assert "theirs_plain" not in got
    assert "theirs_att_other" not in got
    assert "theirs_similar" not in got
    assert s["status"] == "ok"


def test_attendee_string_with_whitespace_is_optional_but_plain_string_matches():
    events = [event("att_str", "2026-11-04T09:50:00-05:00", "2026-11-04T10:20:00-05:00", calendar_id="theirs",
                    attendees=["someone@example.test", "ME@example.test"])]
    _, s = run(events)
    assert ids(s) == ["att_str"]


def test_null_party_id_does_not_match_null_owner():
    me = dict(ME, party_id=None)
    events = [
        event("orphan_one", "2026-11-04T09:00:00-05:00", "2026-11-04T09:30:00-05:00", calendar_id="orphan"),
        event("orphan_rec", "2026-10-07T12:00:00-04:00", "2026-10-07T12:30:00-04:00", calendar_id="orphan",
              recurrence_rule="FREQ=WEEKLY"),
        event("on_mine", "2026-11-04T10:00:00-05:00", "2026-11-04T10:30:00-05:00", calendar_id="mine"),
    ]
    fc, s = run(events, me=me)
    assert ids(s) == ["on_mine"]
    assert all(a.get("calendar_id") != "orphan" for a in fc.calls_to("CalendarEvent.list"))
    assert all(a.get("owner_party_id", "x") is not None for a in fc.calls_to("Calendar.list"))


def test_overlap_window_edges():
    events = [
        event("from_yesterday", "2026-11-03T23:00:00-05:00", "2026-11-04T01:00:00-05:00"),
        event("ends_at_midnight", "2026-11-03T22:00:00-05:00", "2026-11-04T00:00:00-05:00"),
        event("ends_at_midnight_utc", "2026-11-04T03:00:00+00:00", "2026-11-04T05:00:00+00:00"),
        event("starts_next_midnight", "2026-11-05T00:00:00-05:00", "2026-11-05T01:00:00-05:00"),
        event("starts_next_midnight_utc", "2026-11-05T05:00:00+00:00", "2026-11-05T06:00:00+00:00"),
        event("last_minute", "2026-11-04T23:59:00-05:00", "2026-11-05T00:30:00-05:00"),
        event("utc_late", "2026-11-05T02:00:00+00:00", "2026-11-05T03:00:00+00:00"),
        event("tomorrow", "2026-11-05T10:00:00-05:00", "2026-11-05T11:00:00-05:00"),
        event("yesterday", "2026-11-03T10:00:00-05:00", "2026-11-03T11:00:00-05:00"),
    ]
    _, s = run(events)
    assert set(ids(s)) == {"from_yesterday", "last_minute", "utc_late"}


def test_query_uses_overlap_filters():
    fc, _ = run([])
    one_off = [a for a in fc.calls_to("CalendarEvent.list") if "calendar_id" not in a]
    assert one_off, "expected an overlap query without calendar_id"
    a = one_off[0]
    assert a["start_at"].startswith("lt:")
    assert a["end_at"].startswith("gt:")
    assert same_instant(a["start_at"][3:], "2026-11-05T00:00:00-05:00")
    assert same_instant(a["end_at"][3:], "2026-11-04T00:00:00-05:00")


def test_cancelled_excluded():
    events = [
        event("ok", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00"),
        event("gone", "2026-11-04T12:00:00-05:00", "2026-11-04T13:00:00-05:00", status="cancelled"),
        event("gone_rec", "2026-10-07T12:00:00-04:00", "2026-10-07T13:00:00-04:00", status="cancelled",
              recurrence_rule="FREQ=WEEKLY"),
    ]
    _, s = run(events)
    assert ids(s) == ["ok"]


def test_birthday_holiday_subscribed_excluded_unless_created_by_me():
    events = [
        event("b", "2026-11-04T00:00:00-05:00", "2026-11-05T00:00:00-05:00", calendar_id="bday", all_day=True),
        event("h", "2026-11-04T00:00:00-05:00", "2026-11-05T00:00:00-05:00", calendar_id="hol", all_day=True),
        event("s", "2026-11-04T08:00:00-05:00", "2026-11-04T09:00:00-05:00", calendar_id="sub"),
        event("ms", "2026-11-04T08:30:00-05:00", "2026-11-04T09:00:00-05:00", calendar_id="mysub"),
        event("m", "2026-11-04T09:00:00-05:00", "2026-11-04T10:00:00-05:00", calendar_id="mine"),
    ]
    _, s = run(events)
    assert set(ids(s)) == {"ms", "m"}


def test_all_day_midnight_to_midnight():
    events = [
        event("today_allday", "2026-11-04T00:00:00-05:00", "2026-11-05T00:00:00-05:00", all_day=True),
        event("yesterday_allday", "2026-11-03T00:00:00-05:00", "2026-11-04T00:00:00-05:00", all_day=True),
        event("tomorrow_allday", "2026-11-05T00:00:00-05:00", "2026-11-06T00:00:00-05:00", all_day=True),
    ]
    _, s = run(events)
    assert ids(s) == ["today_allday"]
    assert s["items"][0]["all_day"] is True


def test_sorted_by_start():
    events = [
        event("c", "2026-11-04T15:00:00-05:00", "2026-11-04T16:00:00-05:00"),
        event("a", "2026-11-04T13:00:00+00:00", "2026-11-04T14:00:00+00:00"),  # 08:00 local
        event("b", "2026-11-04T09:00:00-05:00", "2026-11-04T10:00:00-05:00"),
        event("r", "2026-10-07T12:00:00-04:00", "2026-10-07T12:30:00-04:00", recurrence_rule="FREQ=WEEKLY"),
    ]
    _, s = run(events)
    assert ids(s) == ["a", "b", "r", "c"]


def test_recurring_weekly_expanded_to_today_with_local_time_and_duration():
    events = [event("weekly", "2026-10-07T10:00:00-04:00", "2026-10-07T10:45:00-04:00",
                    recurrence_rule="RRULE:FREQ=WEEKLY;BYDAY=WE")]
    fc, s = run(events)
    assert ids(s) == ["weekly"]
    item = s["items"][0]
    assert item["recurring"] is True
    assert item["expanded"] is True
    # Same wall-clock time across the DST change: 10:00 EDT -> 10:00 EST.
    assert same_instant(item["start_at"], "2026-11-04T10:00:00-05:00")
    assert same_instant(item["end_at"], "2026-11-04T10:45:00-05:00")
    assert item["calendar"] == "My Calendar"
    rec_queries = [a for a in fc.calls_to("CalendarEvent.list") if a.get("calendar_id") == "mine"]
    assert rec_queries
    assert all(a["start_at"].startswith("lt:") for a in rec_queries)


def test_recurring_not_today_excluded():
    events = [
        event("thursdays", "2026-10-08T10:00:00-04:00", "2026-10-08T11:00:00-04:00", recurrence_rule="FREQ=WEEKLY"),
        event("biweekly_off", "2026-10-28T10:00:00-04:00", "2026-10-28T11:00:00-04:00",
              recurrence_rule="FREQ=WEEKLY;INTERVAL=2"),
        event("count_done", "2026-10-07T10:00:00-04:00", "2026-10-07T11:00:00-04:00",
              recurrence_rule="FREQ=WEEKLY;COUNT=4"),
        event("until_done", "2026-10-07T10:00:00-04:00", "2026-10-07T11:00:00-04:00",
              recurrence_rule="FREQ=WEEKLY;UNTIL=20261030T000000Z"),
        event("exdated", "2026-10-07T10:00:00-04:00", "2026-10-07T11:00:00-04:00",
              recurrence_rule="FREQ=WEEKLY", exdates=["2026-11-04T10:00:00-05:00"]),
        event("biweekly_on", "2026-10-21T10:00:00-04:00", "2026-10-21T11:00:00-04:00",
              recurrence_rule="FREQ=WEEKLY;INTERVAL=2"),
        event("count_ok", "2026-10-07T10:00:00-04:00", "2026-10-07T11:00:00-04:00",
              recurrence_rule="FREQ=WEEKLY;COUNT=5"),
    ]
    _, s = run(events)
    assert set(ids(s)) == {"biweekly_on", "count_ok"}


def test_recurring_on_party_calendar_included():
    events = [event("party_rec", "2026-10-07T10:00:00-04:00", "2026-10-07T11:00:00-04:00", calendar_id="party",
                    recurrence_rule="FREQ=WEEKLY")]
    _, s = run(events)
    assert ids(s) == ["party_rec"]


def test_recurring_on_others_calendar_not_queried():
    events = [event("their_rec", "2026-10-07T10:00:00-04:00", "2026-10-07T11:00:00-04:00", calendar_id="theirs",
                    recurrence_rule="FREQ=WEEKLY")]
    fc, s = run(events)
    assert ids(s) == []
    assert all(a.get("calendar_id") != "theirs" for a in fc.calls_to("CalendarEvent.list"))


def test_unsupported_rrule_included_unexpanded_with_note():
    events = [event("setpos", "2025-11-04T10:00:00-05:00", "2025-11-04T11:00:00-05:00",
                    recurrence_rule="FREQ=MONTHLY;BYSETPOS=1;BYDAY=TU")]
    _, s = run(events)
    assert ids(s) == ["setpos"]
    item = s["items"][0]
    assert item["expanded"] is False
    assert item["recurring"] is True
    assert any("pattern not checked" in n for n in s["notes"])
    assert s["status"] == "ok"


def test_recurring_starting_today_not_double_counted():
    events = [event("starts_today", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00",
                    recurrence_rule="FREQ=WEEKLY")]
    _, s = run(events)
    assert ids(s) == ["starts_today"]
    assert s["items"][0]["recurring"] is True


def test_recurring_started_yesterday_overnight_handled_once():
    events = [
        event("plain", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00"),
        event("rec_today", "2026-11-04T09:00:00-05:00", "2026-11-04T09:30:00-05:00", recurrence_rule="FREQ=DAILY"),
    ]
    _, s = run(events)
    assert sorted(ids(s)) == ["plain", "rec_today"]
    assert len(s["items"]) == 2


def test_failing_tool_gives_error_section():
    fc = FakeClient(ME, {"Calendar": base_calendars(), "CalendarEvent": []}, today=DAY)
    fc.fail("CalendarEvent.list", kind="forbidden", message="no access to events")
    s = collect_meetings(fc, ME, DAY, NY)
    assert s["status"] == "error"
    assert s["error"]
    assert "forbidden" in s["error"] or "no access" in s["error"]


def test_failing_calendar_list_gives_error_section():
    fc = FakeClient(ME, {"Calendar": base_calendars(), "CalendarEvent": []}, today=DAY)
    fc.fail("Calendar.list", kind="network", message="unreachable")
    s = collect_meetings(fc, ME, DAY, NY)
    assert s["status"] == "error"
    assert s["error"]


def test_kolkata_day():
    kol = ZoneInfo("Asia/Kolkata")
    events = [
        event("k_in", "2026-11-03T19:00:00+00:00", "2026-11-03T19:30:00+00:00"),   # 00:30 IST on the 4th
        event("k_out", "2026-11-03T18:00:00+00:00", "2026-11-03T18:30:00+00:00"),  # 23:30 IST on the 3rd
    ]
    _, s = run(events, tz=kol)
    assert ids(s) == ["k_in"]


def test_no_writes_during_collection():
    _, s = run([event("e1", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00")])
    fc, _ = run([])
    assert all(n.endswith(".list") or n.endswith(".get") for n in fc.names())
    assert fc.refused == []


def test_duration_preserved_for_long_recurring_event():
    events = [event("long", "2026-10-07T22:00:00-04:00", "2026-10-08T00:30:00-04:00", recurrence_rule="FREQ=WEEKLY")]
    _, s = run(events)
    item = s["items"][0]
    dur = datetime.fromisoformat(item["end_at"]) - datetime.fromisoformat(item["start_at"])
    assert dur == timedelta(hours=2, minutes=30)
    assert same_instant(item["start_at"], "2026-11-04T22:00:00-05:00")


# ---- D5: my status, declined, tentative, clash ----------------------------------------------------------------

STATUS_KEYS = {"my_status", "declined", "tentative", "clash", "clash_with"}


def by_id(section):
    return {i["id"]: i for i in section["items"]}


def att(email, status, **kw):
    return {"email": email, "name": "x", "role": "required", "status": status, "is_organizer": False, **kw}


def test_items_carry_status_keys_and_no_internal_fields():
    _, s = run([event("e1", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00")])
    item = s["items"][0]
    assert STATUS_KEYS <= set(item)
    assert not any(k.startswith("_") for k in item)
    assert "meeting_calendar_ids" not in s
    assert item["my_status"] is None and item["declined"] is False and item["tentative"] is False
    assert item["clash"] is False and item["clash_with"] == []


def test_my_status_from_my_attendee_entry_case_insensitive():
    events = [
        event("acc", "2026-11-04T08:00:00-05:00", "2026-11-04T08:30:00-05:00",
              attendees=[att("other@example.test", "declined"), att("ME@EXAMPLE.test", "accepted")]),
        event("na", "2026-11-04T09:00:00-05:00", "2026-11-04T09:30:00-05:00",
              attendees=[att("me@example.test", "NEEDS_ACTION")]),
        event("tent", "2026-11-04T10:00:00-05:00", "2026-11-04T10:30:00-05:00",
              attendees=[att("me@example.test", "Tentative")]),
        event("dec", "2026-11-04T11:00:00-05:00", "2026-11-04T11:30:00-05:00",
              attendees=[att("me@example.test", "declined")]),
        event("dash", "2026-11-04T12:00:00-05:00", "2026-11-04T12:30:00-05:00",
              attendees=[att("me@example.test", "needs-action")]),
        event("odd", "2026-11-04T13:00:00-05:00", "2026-11-04T13:30:00-05:00",
              attendees=[att("me@example.test", "delegated")]),
        event("str", "2026-11-04T14:00:00-05:00", "2026-11-04T14:30:00-05:00", attendees=["me@example.test"]),
        event("none", "2026-11-04T15:00:00-05:00", "2026-11-04T15:30:00-05:00",
              attendees=[att("other@example.test", "accepted")]),
    ]
    items = by_id(run(events)[1])
    assert {k: v["my_status"] for k, v in items.items()} == {
        "acc": "accepted", "na": "needs_action", "tent": "tentative", "dec": "declined", "dash": "needs_action",
        "odd": None, "str": None, "none": None}


def test_extra_addresses_on_me_are_used():
    me = dict(ME, addresses=["alias@example.test"])
    ev = event("a", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00",
               attendees=[att("Alias@example.test", "declined")])
    item = run([ev], me=me)[1]["items"][0]
    assert item["my_status"] == "declined" and item["declined"] is True


def test_declined_stays_listed_marked_and_out_of_clash():
    events = [
        event("dec", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00",
              attendees=[att("me@example.test", "declined")]),
        event("ok", "2026-11-04T10:30:00-05:00", "2026-11-04T11:30:00-05:00"),
    ]
    items = by_id(run(events)[1])
    assert set(items) == {"dec", "ok"}
    assert items["dec"]["declined"] is True
    assert items["dec"]["clash"] is False and items["dec"]["clash_with"] == []
    assert items["ok"]["clash"] is False and items["ok"]["clash_with"] == []


def test_tentative_from_event_status_or_my_status():
    events = [
        event("ev_tent", "2026-11-04T08:00:00-05:00", "2026-11-04T08:30:00-05:00", status="Tentative"),
        event("my_tent", "2026-11-04T09:00:00-05:00", "2026-11-04T09:30:00-05:00",
              attendees=[att("me@example.test", "tentative")]),
        event("firm", "2026-11-04T10:00:00-05:00", "2026-11-04T10:30:00-05:00",
              attendees=[att("me@example.test", "accepted")]),
    ]
    items = by_id(run(events)[1])
    assert items["ev_tent"]["tentative"] is True and items["ev_tent"]["my_status"] is None
    assert items["my_tent"]["tentative"] is True
    assert items["firm"]["tentative"] is False


def test_clash_overlap_marks_both_with_titles():
    events = [
        event("a", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00", title="Alpha"),
        event("b", "2026-11-04T15:30:00Z", "2026-11-04T16:30:00Z", title="Beta"),  # 10:30-11:30 local
        event("c", "2026-11-04T11:00:00-05:00", "2026-11-04T12:00:00-05:00", title="Gamma"),
    ]
    items = by_id(run(events)[1])
    assert items["a"]["clash"] is True and items["a"]["clash_with"] == ["Beta"]
    assert items["b"]["clash"] is True and items["b"]["clash_with"] == ["Alpha", "Gamma"]
    assert items["c"]["clash"] is True and items["c"]["clash_with"] == ["Beta"]


def test_touching_meetings_do_not_clash():
    events = [
        event("a", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00"),
        event("b", "2026-11-04T11:00:00-05:00", "2026-11-04T12:00:00-05:00"),
    ]
    items = by_id(run(events)[1])
    assert not items["a"]["clash"] and not items["b"]["clash"]


def test_all_day_never_clashes():
    events = [
        event("ad", "2026-11-04T00:00:00-05:00", "2026-11-05T00:00:00-05:00", all_day=True),
        event("m", "2026-11-04T10:00:00-05:00", "2026-11-04T11:00:00-05:00"),
    ]
    items = by_id(run(events)[1])
    assert not items["ad"]["clash"] and not items["m"]["clash"]


def test_expanded_recurring_clashes_with_one_off_but_unchecked_pattern_does_not():
    events = [
        event("weekly", "2026-10-07T10:00:00-04:00", "2026-10-07T11:00:00-04:00", recurrence_rule="FREQ=WEEKLY",
              title="Weekly"),
        event("odd", "2026-10-07T10:00:00-04:00", "2026-10-07T11:00:00-04:00",
              recurrence_rule="FREQ=MONTHLY;BYSETPOS=1;BYDAY=WE", title="Odd"),
        event("one", "2026-11-04T10:30:00-05:00", "2026-11-04T10:45:00-05:00", title="One"),
    ]
    items = by_id(run(events)[1])
    assert items["weekly"]["clash_with"] == ["One"]
    assert items["one"]["clash_with"] == ["Weekly"]
    assert items["odd"]["clash"] is False
