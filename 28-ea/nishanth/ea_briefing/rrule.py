"""A deliberately small RRULE subset. Anything outside it yields None so the caller can say "not checked"."""
import calendar
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
# BYSETPOS, BYWEEKNO, BYYEARDAY, BYHOUR, BYMINUTE and BYSECOND are left out on purpose: a rule using them is "not
# checked" rather than guessed.
_KNOWN = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "WKST", "BYMONTHDAY", "BYMONTH"}
_FREQS = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
_BYDAY = re.compile(r"^([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)$")
_SIGNED = re.compile(r"^[+-]?\d{1,2}$")
# Upper bound on candidate days walked when counting occurrences for COUNT.
_MAX_WALK = 20000

# One parser for every interpreter: 3.10's fromisoformat rejects Z, +0530 and odd fraction lengths, 3.11+ accepts
# them, so relying on it would make the same data parse differently depending on the Python version.
_EXTENDED = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?\s*(Z|z|[+-]\d{2}(?::?\d{2})?)?)?$")
_BASIC = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:[Tt](\d{2})(\d{2})(\d{2})?(Z|z)?)?$")


def _offset(text: str | None):
    if not text:
        return None
    if text in ("Z", "z"):
        return timezone.utc
    sign = -1 if text[0] == "-" else 1
    digits = text[1:].replace(":", "")
    hours, minutes = int(digits[:2]), int(digits[2:4] or 0)
    if hours > 23 or minutes > 59:
        raise ValueError("offset out of range")
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def parse_dt(value) -> datetime | date | None:
    """ISO-8601 (or RFC 5545 basic) date or datetime. Datetimes are always aware; a naive one is taken as UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    s = value.strip()
    m = _EXTENDED.match(s)
    if m:
        y, mo, d, hh, mi, ss, frac, off = m.groups()
    else:
        m = _BASIC.match(s)
        if not m:
            return None
        y, mo, d, hh, mi, ss, off = m.groups()
        frac = None
    try:
        if hh is None:
            return date(int(y), int(mo), int(d))
        micro = int((frac or "0")[:6].ljust(6, "0"))
        tz = _offset(off) or timezone.utc
        return datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), micro, tzinfo=tz)
    except ValueError:
        return None


def to_local(value, tz) -> datetime | date | None:
    d = parse_dt(value)
    if isinstance(d, datetime):
        return d.astimezone(tz) if tz is not None else d
    return d


def as_list(value) -> list:
    """A list field that may arrive as a comma-separated string, so a string is not iterated per character."""
    if value is None:
        return []
    if isinstance(value, str):
        return [p.strip() for p in value.split(",") if p.strip()]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _parse_exdate_line(line: str, tz: ZoneInfo) -> list | None:
    head, sep, values = line.partition(":")
    if not sep:
        return None
    params = dict(p.split("=", 1) for p in head.split(";")[1:] if "=" in p)
    line_tz = tz
    if params.get("TZID"):
        try:
            line_tz = ZoneInfo(params["TZID"])
        except (ZoneInfoNotFoundError, ValueError):
            return None
    out = []
    for v in as_list(values):
        m = _BASIC.match(v.strip())
        if m and m.group(4) and not m.group(7):
            # A floating basic-format EXDATE is wall time in its TZID (or the event's zone), not UTC.
            y, mo, d, hh, mi, ss, _ = m.groups()
            out.append(datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), tzinfo=line_tz))
        else:
            parsed = parse_dt(v)
            if parsed is None:
                return None
            out.append(parsed)
    return out


def _parse_rule(rule: str, tz: ZoneInfo) -> tuple[dict, list] | None:
    text = rule.strip()
    extra_exdates: list = []
    if "\n" in text:
        rules = []
        for ln in (ln.strip() for ln in text.splitlines()):
            upper = ln.upper()
            if not ln or upper.startswith("DTSTART"):
                continue
            if upper.startswith("RRULE:"):
                rules.append(ln)
            elif upper.startswith("EXDATE"):
                parsed = _parse_exdate_line(ln, tz)
                if parsed is None:
                    return None
                extra_exdates.extend(parsed)
            else:
                return None
        if len(rules) != 1:
            return None
        text = rules[0]
    if text.upper().startswith("RRULE:"):
        text = text[6:]
    parts: dict = {}
    for piece in text.split(";"):
        if not piece.strip():
            continue
        if "=" not in piece:
            return None
        k, v = piece.split("=", 1)
        k, v = k.strip().upper(), v.strip().upper()
        if k not in _KNOWN or k in parts or not v:
            return None
        parts[k] = v
    return (parts, extra_exdates) if "FREQ" in parts else None


def _parse_until(value: str, tz: ZoneInfo) -> datetime | date | None:
    m = _BASIC.match(value)
    if not m:
        return None
    y, mo, d, hh, mi, ss, z = m.groups()
    try:
        if hh is None:
            return date(int(y), int(mo), int(d))
        return datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), tzinfo=timezone.utc if z else tz)
    except ValueError:
        return None


def _pos_int(value: str | None, default: int | None) -> int | None | bool:
    if value is None:
        return default
    if not value.isdigit() or int(value) < 1:
        return False
    return int(value)


def _int_list(value: str, low: int, high: int, signed: bool) -> list[int] | None:
    out = []
    for piece in value.split(","):
        if not _SIGNED.match(piece) or (not signed and piece[0] in "+-"):
            return None
        n = int(piece)
        if n == 0 or abs(n) < low or abs(n) > high:
            return None
        out.append(n)
    return out


def _byday(value: str) -> list[tuple[int | None, int]] | None:
    out = []
    for piece in value.split(","):
        m = _BYDAY.match(piece)
        if not m:
            return None
        ordinal = int(m.group(1)) if m.group(1) else None
        if ordinal is not None and (ordinal == 0 or abs(ordinal) > 53):
            return None
        out.append((ordinal, DAYS[m.group(2)]))
    return out


def _monthday_hit(d: date, monthdays: list[int]) -> bool:
    last = calendar.monthrange(d.year, d.month)[1]
    # A negative day counts from the month's end (-1 = last day); a day the month lacks (31 in April) never matches.
    return any(d.day == (n if n > 0 else last + n + 1) for n in monthdays)


def _weekday_in_month_hit(d: date, days: list[tuple[int | None, int]]) -> bool:
    last = calendar.monthrange(d.year, d.month)[1]
    for ordinal, wd in days:
        if wd != d.weekday():
            continue
        if ordinal is None:
            return True
        if ordinal > 0 and (d.day - 1) // 7 + 1 == ordinal:
            return True
        if ordinal < 0 and (last - d.day) // 7 + 1 == -ordinal:
            return True
    return False


def occurs_on(event: dict, day: date, tz: ZoneInfo) -> bool | None:
    rule = event.get("recurrence_rule")
    if not rule or not isinstance(rule, str):
        return None
    parsed = _parse_rule(rule, tz)
    if parsed is None:
        return None
    parts, rule_exdates = parsed
    freq = parts["FREQ"]
    if freq not in _FREQS:
        return None
    interval = _pos_int(parts.get("INTERVAL"), 1)
    count = _pos_int(parts.get("COUNT"), None)
    if interval is False or count is False:
        return None
    start = to_local(event.get("start_at"), tz)
    if start is None:
        return None
    start_day = start.date() if isinstance(start, datetime) else start

    byday = None
    if "BYDAY" in parts:
        byday = _byday(parts["BYDAY"])
        if byday is None:
            return None
        has_ordinal = any(o is not None for o, _ in byday)
        # Ordinals only mean something inside a month (MONTHLY, or YEARLY narrowed by BYMONTH); "nth weekday of the
        # year" and plain YEARLY+BYDAY are rare enough to leave unchecked.
        if has_ordinal and freq in ("DAILY", "WEEKLY"):
            return None
        if freq == "YEARLY" and "BYMONTH" not in parts:
            return None
    monthdays = None
    if "BYMONTHDAY" in parts:
        if freq == "WEEKLY":  # RFC 5545 forbids BYMONTHDAY with WEEKLY
            return None
        monthdays = _int_list(parts["BYMONTHDAY"], 1, 31, signed=True)
        if monthdays is None:
            return None
    months = None
    if "BYMONTH" in parts:
        months = _int_list(parts["BYMONTH"], 1, 12, signed=False)
        if months is None:
            return None
        months = set(months)
    wkst = 0
    if "WKST" in parts:
        if parts["WKST"] not in DAYS:
            return None
        wkst = DAYS[parts["WKST"]]
    until = None
    if "UNTIL" in parts:
        until = _parse_until(parts["UNTIL"], tz)
        if until is None:
            return None
    weekly_days = {wd for _, wd in byday} if byday else {start_day.weekday()}

    def week_start(d: date) -> date:
        return d - timedelta(days=(d.weekday() - wkst) % 7)

    def in_period(d: date) -> bool:
        if freq == "DAILY":
            return (d - start_day).days % interval == 0
        if freq == "WEEKLY":
            return ((week_start(d) - week_start(start_day)).days // 7) % interval == 0
        if freq == "MONTHLY":
            return ((d.year - start_day.year) * 12 + d.month - start_day.month) % interval == 0
        return (d.year - start_day.year) % interval == 0

    def day_hit(d: date) -> bool:
        if months is not None and d.month not in months:
            return False
        if freq == "DAILY":
            return (byday is None or d.weekday() in weekly_days) and (monthdays is None or _monthday_hit(d, monthdays))
        if freq == "WEEKLY":
            return d.weekday() in weekly_days
        if byday is None and monthdays is None:
            # Day (and for YEARLY without BYMONTH, month) come from DTSTART; months lacking that day (Feb 30, Feb 29
            # outside leap years, the 31st) are skipped, not moved.
            if freq == "YEARLY" and months is None and d.month != start_day.month:
                return False
            return d.day == start_day.day
        # Within a month BYMONTHDAY expands and BYDAY then narrows (Friday the 13th = BYDAY=FR;BYMONTHDAY=13).
        return ((monthdays is None or _monthday_hit(d, monthdays))
                and (byday is None or _weekday_in_month_hit(d, byday)))

    def matches(d: date) -> bool:
        if d < start_day:
            return False
        # RFC 5545: DTSTART is always the first occurrence, even when it does not fit the rule.
        return d == start_day or (in_period(d) and day_hit(d))

    if not matches(day):
        return False
    if until is not None:
        if isinstance(until, datetime):
            if isinstance(start, datetime):
                occ = datetime.combine(day, start.time(), tzinfo=tz)
            else:
                occ = datetime.combine(day, datetime.min.time(), tzinfo=tz)
            if occ > until:
                return False
        elif day > until:
            return False
    if count is not None:
        if (day - start_day).days > _MAX_WALK:
            return None
        n, d = 0, start_day
        while d <= day:
            if matches(d):
                n += 1
                if n > count:
                    return False
            d += timedelta(days=1)
    for ex in as_list(event.get("exdates")) + rule_exdates:
        exd = to_local(ex, tz)
        if exd is None:
            continue
        if (exd.date() if isinstance(exd, datetime) else exd) == day:
            return False
    return True
