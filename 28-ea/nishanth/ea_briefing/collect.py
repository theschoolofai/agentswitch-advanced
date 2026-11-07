"""Collectors for the three briefing sections. The login can see other people's data, so all of it is scoped here."""
import html
import re
from email.utils import getaddresses
import sys
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import rrule
from .mcp import McpError, list_capped, safe_id

OPEN_STATUSES = ("todo", "in_progress", "in_review")
NON_MEETING_TYPES = {"birthday", "holiday", "subscribed"}
CALENDAR_CAP = 200
EVENT_CAP = 200
TASK_CAP = 200
MAILBOX_CAP = 50


def section(status: str = "ok", items: list | None = None, truncated: bool = False, notes: list | None = None,
            error: str | None = None) -> dict:
    return {"status": status, "items": items if items is not None else [], "truncated": truncated,
            "notes": notes if notes is not None else [], "error": error}


def _error_section(exc: Exception) -> dict:
    if isinstance(exc, McpError):
        msg = f"{exc.kind}: {exc.message}"
    else:
        msg = f"{type(exc).__name__}: {exc}"
    return section("error", error=msg[:300])


class _Unscoped(Exception):
    pass


def _require(me: dict, *fields: str) -> None:
    for field in fields:
        if me.get(field) in (None, ""):
            raise _Unscoped(f"cannot scope to user: missing {field}")


def _scoped_error(exc: _Unscoped) -> dict:
    return section("error", error=str(exc))


def _lower(value) -> str:
    return str(value or "").strip().lower()


def _add_counts(sec: dict, res: dict) -> None:
    sec["fetched"] = sec.get("fetched", 0) + len(res["rows"])
    sec["total"] = sec.get("total", 0) + res["total"]


# ---- ownership -------------------------------------------------------------------------------------------------

def is_my_calendar(cal: dict, me: dict) -> bool:
    if cal.get("id") is None:
        return False
    if me.get("id") is not None and cal.get("created_by") == me.get("id"):
        return True
    return me.get("party_id") is not None and cal.get("owner_party_id") == me.get("party_id")


def is_meeting_calendar(cal: dict, me: dict) -> bool:
    if not is_my_calendar(cal, me):
        return False
    return cal.get("type") not in NON_MEETING_TYPES or cal.get("created_by") == me.get("id")


def _attendee_emails(event: dict) -> set[str]:
    out = set()
    for a in rrule.as_list(event.get("attendees")):
        if isinstance(a, dict):
            out.add(_lower(a.get("email")))
        elif isinstance(a, str):
            out.add(_lower(a))
    out.discard("")
    return out


def is_my_event(event: dict, me: dict, my_calendar_ids: set) -> bool:
    if event.get("calendar_id") is not None and event.get("calendar_id") in my_calendar_ids:
        return True
    email = _lower(me.get("email"))
    if not email:
        return False
    return _lower(event.get("organizer_email")) == email or email in _attendee_emails(event)


def is_my_task(task: dict, me: dict) -> bool:
    eid = me.get("employee_id")
    if eid is not None and task.get("assignee_id") == eid:
        return True
    return me.get("id") is not None and task.get("created_by") == me.get("id") and task.get("assignee_id") is None


def _calendars(client) -> tuple[list[dict], bool]:
    res = list_capped(client, "Calendar.list", {}, cap=CALENDAR_CAP)
    return res["rows"], res["truncated"]


# ---- time zone and day window ----------------------------------------------------------------------------------

TZ_LOOKUP_FAILED = "time zone lookup failed; times shown in UTC"


def resolve_tz(client, me, tz_name: str | None) -> ZoneInfo:
    """A failed lookup falls back to UTC and is recorded as `client.tz_note`, which build_briefing shows."""
    if tz_name:
        return ZoneInfo(tz_name)
    try:
        cals, _ = _calendars(client)
    except Exception as exc:  # a bad reply only costs us the calendar's zone, not the run
        print(f"note: could not read calendars for the time zone ({type(exc).__name__}); using UTC", file=sys.stderr)
        try:
            client.tz_note = TZ_LOOKUP_FAILED
        except AttributeError:
            pass
        return ZoneInfo("UTC")
    mine = [c for c in cals if c.get("type") == "personal" and is_my_calendar(c, me) and c.get("timezone")]
    mine.sort(key=lambda c: c.get("created_by") != me.get("id"))
    for cal in mine:
        try:
            return ZoneInfo(str(cal["timezone"]))
        except (ZoneInfoNotFoundError, ValueError):
            continue
    print("note: no time zone given and no personal calendar time zone found; using UTC", file=sys.stderr)
    return ZoneInfo("UTC")


def day_window(day: date, tz: ZoneInfo) -> tuple[str, str]:
    # Each end is built from its own local midnight so a DST change inside the day keeps the right offset.
    start = datetime.combine(day, time(0), tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    return start.isoformat(), end.isoformat()


# ---- meetings --------------------------------------------------------------------------------------------------

def _is_all_day(event: dict, tz: ZoneInfo) -> bool:
    if event.get("all_day"):
        return True
    start, end = rrule.to_local(event.get("start_at"), tz), rrule.to_local(event.get("end_at"), tz)
    if isinstance(start, date) and not isinstance(start, datetime):
        return True
    if isinstance(start, datetime) and isinstance(end, datetime):
        return start.time() == time(0) and end.time() == time(0) and end > start
    return False


def _local_date(value, tz: ZoneInfo, end: bool = False) -> date | None:
    d = rrule.to_local(value, tz)
    if isinstance(d, datetime):
        # An all-day end is exclusive at local midnight; any later time (23:59:59.999 included) still covers that
        # local day, so the exclusive bound is the next one.
        if end and d.time() != time(0):
            return d.date() + timedelta(days=1)
        return d.date()
    return d


def _event_tz(event: dict, fallback):
    for key in ("timezone", "effective_timezone"):
        name = event.get(key)
        if isinstance(name, str) and name.strip():
            try:
                return ZoneInfo(name.strip())
            except (ZoneInfoNotFoundError, ValueError):
                continue
    return fallback


def _all_day_span(event: dict, tz: ZoneInfo | None = None) -> tuple[date | None, date | None]:
    tz = tz or timezone.utc
    if event.get("all_day"):
        # A flagged all-day event names a calendar date in its own zone; read in the viewer's zone it can slip a day.
        tz = _event_tz(event, tz)
    start = _local_date(event.get("start_at"), tz)
    end = _local_date(event.get("end_at"), tz, end=True)
    if start and (end is None or end <= start):
        end = start + timedelta(days=1)
    return start, end


def _aware(value, tz) -> datetime | None:
    d = rrule.to_local(value, tz)
    if isinstance(d, datetime):
        return d
    if isinstance(d, date):
        return datetime.combine(d, time(0), tzinfo=tz)
    return None


def _overlaps(event: dict, day: date, tz: ZoneInfo) -> bool:
    if _is_all_day(event, tz):
        start, end = _all_day_span(event, tz)
        return bool(start) and start <= day < end
    win_start = datetime.combine(day, time(0), tzinfo=tz)
    win_end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)
    start = _aware(event.get("start_at"), tz)
    end = _aware(event.get("end_at"), tz) or start
    if start is None:
        return False
    if end == start:
        return win_start <= start < win_end
    return start < win_end and end > win_start


def _meeting_item(event: dict, cal_names: dict, tz: ZoneInfo, recurring: bool, expanded: bool,
                  start_at=None, end_at=None) -> dict:
    return {
        "id": event.get("id"),
        "title": event.get("title"),
        "start_at": start_at if start_at is not None else event.get("start_at"),
        "end_at": end_at if end_at is not None else event.get("end_at"),
        "all_day": _is_all_day(event, tz),
        "location": event.get("location"),
        "calendar": cal_names.get(event.get("calendar_id")),
        "recurring": recurring,
        "expanded": expanded,
    }


def _occurrence(event: dict, day: date, tz: ZoneInfo) -> tuple[str, str] | None:
    if _is_all_day(event, tz):
        start, end = _all_day_span(event, tz)
        if not start:
            return None
        return day.isoformat(), (day + (end - start)).isoformat()
    start = _aware(event.get("start_at"), tz)
    end = _aware(event.get("end_at"), tz) or start
    if start is None:
        return None
    occ_start = datetime.combine(day, start.time(), tzinfo=tz)
    return occ_start.isoformat(), (occ_start + (end - start)).isoformat()


def _sort_key(item: dict, tz: ZoneInfo):
    start = _aware(item.get("start_at"), tz)
    utc = start.astimezone(timezone.utc) if start else datetime.max.replace(tzinfo=timezone.utc)
    return (utc, str(item.get("title") or ""))


def collect_meetings(client, me, day: date, tz: ZoneInfo) -> dict:
    try:
        _require(me, "id", "email")
        if safe_id(me["id"]) is None:
            raise _Unscoped("cannot scope to user: id is not a plain server id")
        cals, cal_truncated = _calendars(client)
        cal_names = {c.get("id"): c.get("name") for c in cals if c.get("id") is not None}
        meeting_cals = [c for c in cals if is_meeting_calendar(c, me)]
        meeting_ids = {c.get("id") for c in meeting_cals}
        start_iso, end_iso = day_window(day, tz)
        out = section("ok")
        if cal_truncated:
            out["truncated"] = True
            out["notes"].append(f"calendar list capped at {CALENDAR_CAP}; some calendars were not checked")

        items: dict = {}
        one_off = list_capped(client, "CalendarEvent.list", {"start_at": f"lt:{end_iso}", "end_at": f"gt:{start_iso}"},
                              cap=EVENT_CAP)
        _add_counts(out, one_off)
        if one_off["truncated"]:
            out["truncated"] = True
            out["notes"].append(f"event query read first {len(one_off['rows'])} of {one_off['total']} events in the "
                                "window")
        for ev in one_off["rows"]:
            if ev.get("recurrence_rule") or _lower(ev.get("status")) == "cancelled":
                continue
            if ev.get("id") in items or not is_my_event(ev, me, meeting_ids) or not _overlaps(ev, day, tz):
                continue
            items[ev.get("id")] = _meeting_item(ev, cal_names, tz, recurring=False, expanded=False)

        for cal in meeting_cals:
            cal_id = safe_id(cal.get("id"))
            if cal_id is None:
                out["notes"].append(f"calendar {cal.get('name')!r} has an unusual id; its recurring events were not "
                                    "checked")
                continue
            res = list_capped(client, "CalendarEvent.list", {"calendar_id": cal_id, "start_at": f"lt:{end_iso}"},
                              cap=EVENT_CAP)
            _add_counts(out, res)
            if res["truncated"]:
                out["truncated"] = True
                out["notes"].append(f"calendar {cal.get('name')!r}: read first {len(res['rows'])} of {res['total']} "
                                    "events")
            for ev in res["rows"]:
                if not ev.get("recurrence_rule") or _lower(ev.get("status")) == "cancelled" or ev.get("id") in items:
                    continue
                if ev.get("calendar_id") != cal.get("id"):
                    continue
                hit = rrule.occurs_on(ev, day, tz)
                if hit is True:
                    occ = _occurrence(ev, day, tz)
                    if occ:
                        items[ev.get("id")] = _meeting_item(ev, cal_names, tz, True, True, occ[0], occ[1])
                        continue
                    hit = None
                if hit is None:
                    items[ev.get("id")] = _meeting_item(ev, cal_names, tz, recurring=True, expanded=False)
                    out["notes"].append(f"recurring event, pattern not checked: {ev.get('title')}")
        out["items"] = sorted(items.values(), key=lambda i: _sort_key(i, tz))
        return out
    except _Unscoped as exc:
        return _scoped_error(exc)
    except Exception as exc:  # a collector reports failure as a section, it never raises
        return _error_section(exc)


# ---- overdue tasks ---------------------------------------------------------------------------------------------

def _project_name(client, project_id, cache: dict):
    if project_id is None:
        return None
    key = str(project_id)
    if key not in cache:
        try:
            res = client.call("Project.get", {"id": project_id})
            row = res.get("data") if isinstance(res.get("data"), dict) else res
            name = row.get("name") if isinstance(row, dict) else None
            cache[key] = name if isinstance(name, str) else None
        except Exception:  # a missing project name is cosmetic; it must not fail the section
            cache[key] = None
    return cache[key]


def _due(value) -> date | None:
    d = rrule.parse_dt(value)
    return d.date() if isinstance(d, datetime) else d


def collect_overdue(client, me, day: date) -> dict:
    try:
        _require(me, "id")
        my_id = safe_id(me["id"])
        if my_id is None:
            raise _Unscoped("cannot scope to user: id is not a plain server id")
        base = {"due_date": f"lt:{day.isoformat()}", "status": ",".join(OPEN_STATUSES)}
        queries = []
        if me.get("employee_id") is not None:
            eid = safe_id(me["employee_id"])
            if eid is None:
                raise _Unscoped("cannot scope to user: employee_id is not a plain server id")
            queries.append({**base, "assignee_id": eid})
        queries.append({**base, "created_by": my_id})
        out = section("ok")
        tasks: dict = {}
        for q in queries:
            res = list_capped(client, "Task.list", q, cap=TASK_CAP)
            _add_counts(out, res)
            if res["truncated"]:
                out["truncated"] = True
                out["notes"].append(f"task query read first {len(res['rows'])} of {res['total']} overdue tasks")
            for t in res["rows"]:
                tasks.setdefault(t.get("id"), t)
        cache: dict = {}
        items = []
        for t in tasks.values():
            # Re-check every condition: a server that ignored a filter must not leak someone else's task in.
            due = _due(t.get("due_date"))
            if due is None or due >= day or t.get("status") not in OPEN_STATUSES or not is_my_task(t, me):
                continue
            items.append({
                "id": t.get("id"),
                "title": t.get("title"),
                "due_date": due.isoformat(),
                "days_overdue": (day - due).days,
                "status": t.get("status"),
                "project": _project_name(client, t.get("project_id"), cache),
            })
        items.sort(key=lambda i: (-i["days_overdue"], str(i["title"] or "")))
        out["items"] = items
        return out
    except _Unscoped as exc:
        return _scoped_error(exc)
    except Exception as exc:
        return _error_section(exc)


# ---- mail ------------------------------------------------------------------------------------------------------

_TAGS = re.compile(r"<[^>]+>")
_DROP_BLOCKS = re.compile(r"<(script|style)\b.*?</\1\s*>", re.I | re.S)


def html_to_text(markup: str) -> str:
    text = _DROP_BLOCKS.sub(" ", markup or "")
    text = re.sub(r"<\s*(br|/p|/div|/li|/tr)\b[^>]*>", "\n", text, flags=re.I)
    text = html.unescape(_TAGS.sub(" ", text))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


MAIL_FIELDS = ("id", "message_id", "thread_id", "mailbox_id", "from_email", "from_name", "subject", "received_at",
               "snippet", "body_text")


def recipients(message: dict) -> set[str]:
    """Lower-cased addresses in `to` and `cc`, which arrive as lists, dicts or "Name <addr>, addr" strings."""
    raw: list[str] = []
    for field in ("to", "cc"):
        value = message.get(field)
        for part in value if isinstance(value, (list, tuple)) else [value]:
            if isinstance(part, dict):
                part = part.get("email") or part.get("address")
            if isinstance(part, str) and part.strip():
                raw.append(part)
    return {addr.strip().lower() for _, addr in getaddresses(raw) if "@" in addr}


def _tool_missing(exc: Exception) -> bool:
    if not isinstance(exc, McpError):
        return False
    text = exc.message.lower()
    return exc.kind == "not_found" or exc.code == -32601 or "unknown tool" in text or "tool not found" in text


MAIL_LOOKBACK_DAYS = 14


def collect_mail(client, me, cap: int = 25, day: date | None = None, tz=None) -> dict:
    """Inbox mail not yet answered, read or not: opening a message in the web app marks it read without answering
    it, so "unread" alone would hide mail that still needs a reply. With `day`, only the last MAIL_LOOKBACK_DAYS."""
    try:
        _require(me, "email")
        accounts = list_capped(client, "EmailAccount.list", {}, cap=MAILBOX_CAP)
        try:
            boxes = list_capped(client, "Mailbox.list", {}, cap=MAILBOX_CAP)
        except Exception as exc:
            if accounts["total"] == 0 and _tool_missing(exc):
                return section("no_mailbox", notes=["No mailbox is linked to this login yet."])
            raise
        if boxes["total"] == 0 and accounts["total"] == 0:
            return section("no_mailbox", notes=["No mailbox is linked to this login yet."])
        rows = [b for b in boxes["rows"] if isinstance(b, dict)]
        # Keystone links each mailbox to its user (`user_id`, verified live 2026-11-06), so ownership is proven and
        # everything in an owned mailbox counts, bcc and list mail included. Without that link, mail is kept only
        # when it is addressed to one of the user's addresses.
        verified = any("user_id" in b for b in rows)
        if verified:
            owned = [b for b in rows if me.get("id") is not None and str(b.get("user_id")) == str(me["id"])]
        else:
            owned = rows
        my_boxes = {str(safe_id(b.get("id"))) for b in owned if safe_id(b.get("id")) is not None}
        if not my_boxes:
            if boxes["total"] == 0:
                return section("error", error="mail account exists but no mailbox visible")
            if verified and not owned:
                return section("error", error="no visible mailbox belongs to this user")
            return section("error", error="mailbox ids are not usable as filters")
        box_email = {str(safe_id(b.get("id"))): b["email"] for b in owned
                     if safe_id(b.get("id")) is not None and isinstance(b.get("email"), str) and "@" in b["email"]}
        addresses = {_lower(me.get("email"))} | {_lower(e) for e in box_email.values()}
        out = section("ok")
        out["mailbox_ids"] = sorted(my_boxes)
        if boxes["truncated"]:
            out["notes"].append(f"only the first {MAILBOX_CAP} mailboxes were read")
        if len(owned) < len(rows):
            out["notes"].append(f"{len(rows) - len(owned)} visible mailboxes belong to other users and were skipped")
        filters = {"folder": "inbox", "mailbox_id": ",".join(sorted(my_boxes)), "sort_by": "received_at",
                   "sort_order": "desc"}
        since = None
        if day is not None:
            since = day_window(day - timedelta(days=MAIL_LOOKBACK_DAYS), tz or timezone.utc)[0]
            filters["received_at"] = f"gte:{since}"
        res = list_capped(client, "EmailMessage.list", filters, cap=cap)
        out["truncated"] = res["truncated"] or boxes["truncated"]
        _add_counts(out, res)
        items = []
        not_mine = 0
        for m in res["rows"]:
            if m.get("mailbox_id") is None or str(m.get("mailbox_id")) not in my_boxes:
                continue
            if not verified and not (addresses & recipients(m)):
                not_mine += 1
                continue
            if m.get("is_answered") is True or m.get("is_draft") is True:
                continue
            if m.get("folder") not in (None, "inbox"):
                continue
            received = _aware(m.get("received_at"), timezone.utc)
            if since is not None and received is not None and received < _aware(since, timezone.utc):
                continue
            if _lower(m.get("from_email")) in addresses:
                continue
            item = {k: m.get(k) for k in MAIL_FIELDS}
            item["mailbox_email"] = box_email.get(str(m.get("mailbox_id")))
            item["is_read"] = m.get("is_read") is True
            if not isinstance(item["body_text"], str) or not item["body_text"].strip():
                markup = m.get("body_html")
                item["body_text"] = html_to_text(markup if isinstance(markup, str) else "")
            items.append(item)
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        items.sort(key=lambda i: _aware(i.get("received_at"), timezone.utc) or oldest, reverse=True)
        out["items"] = items
        if not_mine:
            out["notes"].append(f"{not_mine} unread messages in visible mailboxes are not addressed to you and were "
                                "skipped")
        return out
    except _Unscoped as exc:
        return _scoped_error(exc)
    except Exception as exc:
        return _error_section(exc)
