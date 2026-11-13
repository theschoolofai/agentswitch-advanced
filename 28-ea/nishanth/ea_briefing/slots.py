"""Free meeting slots offered in reply drafts. Busy time is the same set of meetings the briefing lists for a day."""
from datetime import date, datetime, time, timedelta, timezone

from . import collect

# Fixed English names: %a/%b follow the process locale, and the label is copied verbatim into a draft.
_DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
# The whole search span (a working week plus a weekend) is read in one query, so it gets more room than one day.
EVENT_CAP = 500


def _result(status: str, slots: list | None = None, error: str | None = None) -> dict:
    return {"status": status, "slots": slots or [], "error": error}


def label(start: datetime, end: datetime) -> str:
    """"Tue 11 Nov, 10:00–10:30 IST": 24-hour clock, en dash, zone abbreviation as strftime("%Z") gives it."""
    return (f"{_DAY_NAMES[start.weekday()]} {start.day} {_MONTH_NAMES[start.month - 1]}, "
            f"{start:%H:%M}–{end:%H:%M} {start.strftime('%Z')}")


def _wall(day: date, minute_of_day: int, tz) -> datetime:
    return datetime.combine(day + timedelta(days=minute_of_day // 1440),
                            time((minute_of_day % 1440) // 60, minute_of_day % 60), tzinfo=tz)


def _utc(value: datetime) -> datetime:
    # Aware datetimes sharing one ZoneInfo compare by wall clock, so every comparison here happens in UTC.
    return value.astimezone(timezone.utc)


def _busy(items: list[dict], own: set, day: date, tz) -> tuple[bool, list[tuple[datetime, datetime]]]:
    """(whole day blocked, busy spans in UTC). Declined meetings are free time; cancelled ones never got listed."""
    whole_day, spans = False, []
    for item in items:
        if item.get("declined"):
            continue
        ev = item.get("_event") or {}
        if item.get("all_day"):
            # Someone else's all-day event (an offsite, a training day) only blocks the day once I have said yes.
            if ev.get("calendar_id") in own or item.get("my_status") in ("accepted", "tentative"):
                whole_day = True
            continue
        if item.get("recurring") and not item.get("expanded"):
            # Pattern not understood: assume it happens today at its usual time rather than offer a clashing slot.
            occ = collect._occurrence(ev, day, tz)
            span = collect._span_utc({"start_at": occ[0], "end_at": occ[1]}) if occ else None
        else:
            span = collect._span_utc(item)
        if span:
            spans.append(span)
    return whole_day, spans


def _valid(days, start_hour, end_hour, minutes, max_slots) -> bool:
    ints = all(isinstance(v, int) and not isinstance(v, bool) for v in (days, start_hour, end_hour, minutes, max_slots))
    return (ints and days >= 1 and max_slots >= 1 and 0 <= start_hour < end_hour <= 24 and minutes >= 1
            and minutes <= (end_hour - start_hour) * 60)


def free_slots(client, me, tz, now: datetime, days: int = 5, start_hour: int = 9, end_hour: int = 17,
               minutes: int = 30, max_slots: int = 3) -> dict:
    """Up to `max_slots` free `minutes`-long slots, at most one per working day (Mon–Fri), earliest first, between
    `start_hour` and `end_hour` local time, over the `days` working days after `now`'s local date. Never raises."""
    try:
        if not _valid(days, start_hour, end_hour, minutes, max_slots):
            return _result("error", error="invalid slot settings")
        if not isinstance(now, datetime):
            return _result("error", error="no current time given")
        now_local = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
        now_utc = _utc(now_local)
        day, work_days = now_local.date(), []
        while len(work_days) < days:
            day += timedelta(days=1)
            if day.weekday() < 5:
                work_days.append(day)
        sec, per_day = collect.meetings_by_day(client, me, work_days, tz, cap=EVENT_CAP)
        if sec.get("truncated"):
            # Missing events would make busy time look free; better no offer than a clashing one.
            return _result("error", error="calendar read was capped; free times not offered")
        own = sec.get("meeting_calendar_ids") or set()
        slots: list[dict] = []
        for day in work_days:
            if len(slots) >= max_slots:
                break
            whole_day, busy = _busy(per_day[day], own, day, tz)
            if whole_day:
                continue
            for begin in range(start_hour * 60, end_hour * 60 - minutes + 1, minutes):
                start, end = _wall(day, begin, tz), _wall(day, begin + minutes, tz)
                s_utc, e_utc = _utc(start), _utc(end)
                if s_utc <= now_utc or e_utc <= s_utc:
                    continue
                if any(b0 < e_utc and s_utc < b1 for b0, b1 in busy):
                    continue
                slots.append({"start": start.isoformat(), "end": end.isoformat(), "label": label(start, end)})
                break
        return _result("ok", slots)
    except collect._Unscoped as exc:
        return _result("error", error=str(exc))
    except Exception as exc:  # free times are optional context; a failure is reported, never raised
        return _result("error", error=collect._error_section(exc)["error"])
