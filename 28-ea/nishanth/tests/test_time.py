from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from ea_briefing.collect import day_window, resolve_tz
from fakes import FakeClient

NY = ZoneInfo("America/New_York")
ME = {"id": "u1", "email": "me@x.test", "name": "Me", "company_id": "c1", "employee_id": "e1", "party_id": "p1"}


def test_day_window_dst_fall_back_is_25_hours():
    start, end = day_window(date(2026, 11, 1), NY)
    s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
    assert s.utcoffset() == timedelta(hours=-4)
    assert e.utcoffset() == timedelta(hours=-5)
    assert (s.year, s.month, s.day, s.hour, s.minute) == (2026, 11, 1, 0, 0)
    assert (e.year, e.month, e.day, e.hour, e.minute) == (2026, 11, 2, 0, 0)
    assert e - s == timedelta(hours=25)


def test_day_window_dst_spring_forward_is_23_hours():
    start, end = day_window(date(2026, 3, 8), NY)
    assert datetime.fromisoformat(end) - datetime.fromisoformat(start) == timedelta(hours=23)


def test_day_window_ordinary_day_after_dst():
    start, end = day_window(date(2026, 11, 4), NY)
    assert datetime.fromisoformat(start) == datetime(2026, 11, 4, 5, 0, tzinfo=ZoneInfo("UTC"))
    assert datetime.fromisoformat(end) == datetime(2026, 11, 5, 5, 0, tzinfo=ZoneInfo("UTC"))
    assert start.endswith("-05:00") and end.endswith("-05:00")


def test_day_window_kolkata():
    start, end = day_window(date(2026, 11, 4), ZoneInfo("Asia/Kolkata"))
    assert start.startswith("2026-11-04T00:00")
    assert start.endswith("+05:30")
    assert end.startswith("2026-11-05T00:00")
    assert end.endswith("+05:30")
    assert datetime.fromisoformat(end) - datetime.fromisoformat(start) == timedelta(hours=24)


def _cal(**kw):
    base = {"id": "c", "name": "Cal", "type": "personal", "owner_party_id": None, "created_by": "other",
            "timezone": "UTC"}
    base.update(kw)
    return base


def test_resolve_tz_explicit_wins():
    fc = FakeClient(ME, {"Calendar": [_cal(id="mine", created_by="u1", timezone="Asia/Kolkata")]})
    assert resolve_tz(fc, ME, "Europe/Berlin").key == "Europe/Berlin"


def test_resolve_tz_from_own_personal_calendar_not_others():
    fc = FakeClient(ME, {"Calendar": [
        _cal(id="theirs", created_by="u9", owner_party_id="p9", timezone="Europe/London"),
        _cal(id="team", type="team", created_by="u1", timezone="America/Chicago"),
        _cal(id="mine", created_by="u1", timezone="Asia/Kolkata"),
    ]})
    assert resolve_tz(fc, ME, None).key == "Asia/Kolkata"


def test_resolve_tz_own_calendar_by_party_id():
    fc = FakeClient(ME, {"Calendar": [
        _cal(id="theirs", created_by="u9", owner_party_id="p9", timezone="Europe/London"),
        _cal(id="mine", created_by="admin", owner_party_id="p1", timezone="Asia/Tokyo"),
    ]})
    assert resolve_tz(fc, ME, None).key == "Asia/Tokyo"


def test_resolve_tz_null_party_does_not_match_null_owner():
    me = dict(ME, party_id=None)
    fc = FakeClient(me, {"Calendar": [_cal(id="orphan", created_by="u9", owner_party_id=None,
                                           timezone="Europe/London")]})
    assert str(resolve_tz(fc, me, None)) == "UTC"


def test_resolve_tz_falls_back_to_utc():
    fc = FakeClient(ME, {"Calendar": []})
    assert str(resolve_tz(fc, ME, None)) == "UTC"


def test_resolve_tz_invalid_name_raises():
    fc = FakeClient(ME, {"Calendar": []})
    with pytest.raises(ZoneInfoNotFoundError):
        resolve_tz(fc, ME, "Mars/Olympus_Mons")


# ---- D6: system default zones and where the zone came from -----------------------------------------------------

from ea_briefing import collect  # noqa: E402


def test_system_zones_exact():
    assert collect.SYSTEM_ZONES == {"suryodaya": "Asia/Kolkata", "keystone": "America/New_York"}


def test_tz_source_explicit():
    fc = FakeClient(ME, {"Calendar": [_cal(id="mine", created_by="u1", timezone="Asia/Kolkata")]})
    assert resolve_tz(fc, ME, "Europe/Berlin", "keystone").key == "Europe/Berlin"
    assert fc.tz_source == "explicit"
    assert fc.calls == []


def test_own_calendar_beats_system_default():
    fc = FakeClient(ME, {"Calendar": [_cal(id="mine", created_by="u1", timezone="Asia/Tokyo")]})
    assert resolve_tz(fc, ME, None, "suryodaya").key == "Asia/Tokyo"
    assert fc.tz_source == "calendar"


@pytest.mark.parametrize("system,zone", [("suryodaya", "Asia/Kolkata"), ("keystone", "America/New_York"),
                                         ("Keystone", "America/New_York"), (" SURYODAYA ", "Asia/Kolkata")])
def test_system_default_when_no_calendar_zone(system, zone):
    fc = FakeClient(ME, {"Calendar": [_cal(id="theirs", created_by="u9", owner_party_id="p9",
                                           timezone="Europe/London")]})
    assert resolve_tz(fc, ME, None, system).key == zone
    assert fc.tz_source == "system default"
    assert getattr(fc, "tz_note", None) is None


def test_invalid_calendar_zone_falls_to_system_default():
    fc = FakeClient(ME, {"Calendar": [_cal(id="mine", created_by="u1", timezone="Mars/Base")]})
    assert resolve_tz(fc, ME, None, "keystone").key == "America/New_York"
    assert fc.tz_source == "system default"


@pytest.mark.parametrize("system", [None, "", "acme"])
def test_utc_only_for_unknown_system(system):
    fc = FakeClient(ME, {"Calendar": []})
    assert str(resolve_tz(fc, ME, None, system)) == "UTC"
    assert fc.tz_source == "utc fallback"


def test_lookup_failure_uses_system_default_and_notes_it():
    fc = FakeClient(ME, {"Calendar": []})
    fc.fail("Calendar.list", kind="network", message="down")
    assert resolve_tz(fc, ME, None, "suryodaya").key == "Asia/Kolkata"
    assert fc.tz_source == "system default"
    assert fc.tz_note == "time zone lookup failed; times shown in Asia/Kolkata"


def test_lookup_failure_unknown_system_is_utc_with_note():
    fc = FakeClient(ME, {"Calendar": []})
    fc.fail("Calendar.list", kind="network", message="down")
    assert str(resolve_tz(fc, ME, None)) == "UTC"
    assert fc.tz_source == "utc fallback"
    assert fc.tz_note == collect.TZ_LOOKUP_FAILED


def test_client_without_settable_attributes_still_resolves():
    class Frozen:
        __slots__ = ()

        def call(self, name, arguments=None):
            raise RuntimeError("down")

    assert resolve_tz(Frozen(), ME, None, "keystone").key == "America/New_York"


def test_calendar_list_read_once_per_client_and_failures_not_kept():
    from datetime import date
    fc = FakeClient(ME, {"Calendar": [_cal(id="mine", created_by="u1", timezone="Asia/Kolkata")], "CalendarEvent": []})
    fc.fail("Calendar.list", kind="network", message="down")
    resolve_tz(fc, ME, None, "keystone")
    assert collect.collect_meetings(fc, ME, date(2026, 11, 4), NY)["status"] == "error"
    del fc.failures["Calendar.list"]
    assert resolve_tz(fc, ME, None, "keystone").key == "Asia/Kolkata"
    collect.collect_meetings(fc, ME, date(2026, 11, 4), NY)
    assert fc.names().count("Calendar.list") == 3  # two failed reads, then one kept


@pytest.mark.parametrize("tz_name,system,cals", [("Europe/Berlin", None, []), (None, "keystone", []),
                                                 (None, None, []), (None, None, [{"id": "m", "type": "personal",
                                                                                  "created_by": "u1",
                                                                                  "timezone": "Asia/Tokyo"}])])
def test_tz_source_is_always_a_known_value(tz_name, system, cals):
    fc = FakeClient(ME, {"Calendar": cals})
    resolve_tz(fc, ME, tz_name, system)
    assert fc.tz_source in collect.TZ_SOURCES


def test_unknown_tz_source_is_refused():
    with pytest.raises(ValueError):
        collect._set_source(FakeClient(ME, {}), "guess")
