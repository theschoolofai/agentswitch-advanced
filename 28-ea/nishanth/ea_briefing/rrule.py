"""A deliberately small RRULE subset. Anything outside it yields None so the caller can say "not checked"."""
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_KNOWN = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "WKST", "BYMONTHDAY"}
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


def occurs_on(event: dict, day: date, tz: ZoneInfo) -> bool | None:
    rule = event.get("recurrence_rule")
    if not rule or not isinstance(rule, str):
        return None
    parsed = _parse_rule(rule, tz)
    if parsed is None:
        return None
    parts, rule_exdates = parsed
    freq = parts["FREQ"]
    if freq not in ("DAILY", "WEEKLY", "MONTHLY"):
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
        if freq != "WEEKLY":
            return None
        codes = parts["BYDAY"].split(",")
        if any(c not in DAYS for c in codes):
            return None
        byday = {DAYS[c] for c in codes}
    wkst = 0
    if "WKST" in parts:
        if parts["WKST"] not in DAYS:
            return None
        wkst = DAYS[parts["WKST"]]
    if "BYMONTHDAY" in parts:
        # Only the trivial case (the DTSTART day itself) is understood.
        if freq != "MONTHLY" or parts["BYMONTHDAY"] != str(start_day.day):
            return None
    until = None
    if "UNTIL" in parts:
        until = _parse_until(parts["UNTIL"], tz)
        if until is None:
            return None
    if byday is None and freq == "WEEKLY":
        byday = {start_day.weekday()}

    def week_start(d: date) -> date:
        return d - timedelta(days=(d.weekday() - wkst) % 7)

    def matches(d: date) -> bool:
        if d < start_day:
            return False
        if freq == "DAILY":
            return (d - start_day).days % interval == 0
        if freq == "WEEKLY":
            weeks = (week_start(d) - week_start(start_day)).days // 7
            return weeks % interval == 0 and d.weekday() in byday
        months = (d.year - start_day.year) * 12 + d.month - start_day.month
        return months % interval == 0 and d.day == start_day.day

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
