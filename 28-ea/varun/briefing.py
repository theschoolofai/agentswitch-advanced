#!/usr/bin/env python3
"""Daily briefing for seat 28.

Reads unread inbox mail that still needs an answer, today's meetings, and
overdue open tasks on Suryodaya and Keystone. By default it saves one unsent
draft reply for each such message that already has a mailbox. It never sends
mail, books a meeting, or deletes a record. A person has to approve a draft
before it is sent. Pass --read-only to print proposals without saving.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
OUT_DIR = Path(__file__).resolve().parent / "briefings"
ZONE = ZoneInfo("Asia/Kolkata")
DONE = {"done", "completed", "complete", "cancelled", "canceled", "closed"}
PRIORITY = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
SYSTEMS = {
    "Suryodaya": (
        "https://agentswitch.theschoolofai.in",
        ROOT / ".token.suryodaya",
    ),
    "Keystone": (
        "https://class.agentswitch.theschoolofai.in",
        ROOT / ".token.keystone",
    ),
}


def today_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def call(base: str, token: str, name: str, arguments: dict) -> dict:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    ).encode()
    request = urllib.request.Request(
        f"{base}/api/mcp",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read().decode()
    if raw.startswith("event:") or raw.startswith("data:"):
        data = "\n".join(
            line[5:].strip()
            for line in raw.splitlines()
            if line.startswith("data:")
        )
        payload = json.loads(data)
    else:
        payload = json.loads(raw)
    return tool_result(payload, name)


def tool_result(payload: dict, name: str) -> dict:
    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        message = err.get("message") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"{name} failed: {message}")
    result = payload.get("result", payload)
    if isinstance(result, dict) and result.get("isError"):
        raise RuntimeError(f"{name} failed: {result}")
    content = result.get("content") or [] if isinstance(result, dict) else []
    if content and isinstance(content[0], dict) and "text" in content[0]:
        parsed = json.loads(content[0]["text"])
        if isinstance(parsed, dict) and parsed.get("error"):
            err = parsed["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"{name} failed: {message}")
        return parsed
    return result


def list_all(base: str, token: str, name: str, arguments: dict) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    limit = 200
    while True:
        page = call(
            base,
            token,
            name,
            {**arguments, "limit": limit, "offset": offset},
        )
        data = page.get("data") or []
        rows.extend(data)
        total = int(page.get("total") or len(rows))
        offset += len(data)
        if not data or offset >= total:
            return rows


def parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZONE)
    return parsed.astimezone(ZONE)


def overlaps_today(row: dict, start: datetime, end: datetime) -> bool:
    begins = parse_when(row.get("start_at"))
    finishes = parse_when(row.get("end_at")) or begins
    if begins is None:
        return False
    return begins < end and finishes > start


def needs_answer(row: dict) -> bool:
    if row.get("is_read") or row.get("is_draft") or row.get("is_answered"):
        return False
    folder = str(row.get("folder") or "inbox").lower()
    return folder == "inbox"


def slot_label(start: datetime, end: datetime) -> str:
    return (
        f"{start.strftime('%A')} {start.day} {start.strftime('%B')} "
        f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')} IST"
    )


def free_slots(now: datetime, events: list[dict], count: int = 2) -> list[tuple[datetime, datetime]]:
    """Next weekday 30-minute slots at 10:00 or 15:00 IST that do not overlap an event."""
    busy: list[tuple[datetime, datetime]] = []
    for row in events:
        if str(row.get("status") or "").lower() == "cancelled":
            continue
        begins = parse_when(row.get("start_at"))
        finishes = parse_when(row.get("end_at")) or begins
        if begins and finishes and finishes > begins:
            busy.append((begins, finishes))
    found: list[tuple[datetime, datetime]] = []
    day = (now.astimezone(ZONE) + timedelta(days=1)).date()
    for _ in range(21):
        if day.weekday() < 5:
            for hour in (10, 15):
                start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=ZONE)
                end = start + timedelta(minutes=30)
                if start <= now:
                    continue
                if any(start < finish and end > begin for begin, finish in busy):
                    continue
                found.append((start, end))
                if len(found) == count:
                    return found
        day += timedelta(days=1)
    return found


def proposed_reply(row: dict) -> str:
    subject = (row.get("subject") or "").lower()
    if "meeting request" in subject or "quarterly" in subject:
        slots = row.get("_free_slots") or []
        if len(slots) >= 2:
            first, second = slot_label(*slots[0]), slot_label(*slots[1])
            return (
                "Thank you. These times are free on the calendar and are not booked: "
                f"{first}, or {second}. Please confirm one, and I will add it to the "
                "calendar only after this draft is approved."
            )
        return (
            "Thank you. I will check the calendar and propose two free times after "
            "this draft is approved. Nothing is booked."
        )
    if "quote" in subject or "lead time" in subject:
        return (
            "Thank you for following up. I do not have a revised lead time in this draft. "
            "A person needs to approve the lead time before this reply is sent."
        )
    if "delivery" in subject or "thursday" in subject:
        return (
            "Thank you. I cannot confirm Thursday morning's delivery window in this draft. "
            "A person needs to check the open order before this reply is sent."
        )
    shown = row.get("subject") or "your message"
    return (
        f'Thanks for writing about "{shown}". '
        "I have seen it and will reply once this draft is approved."
    )


def draft_arguments(row: dict) -> dict | None:
    if not row.get("mailbox_id"):
        return None
    subject = row.get("subject") or "your message"
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    arguments = {
        "company_id": row.get("company_id"),
        "mailbox_id": row.get("mailbox_id"),
        "from_email": row.get("to"),
        "to": row.get("from_email"),
        "subject": subject,
        "body_text": proposed_reply(row),
        "folder": "drafts",
        "is_draft": True,
        "is_read": False,
        "is_answered": False,
    }
    if row.get("thread_id"):
        arguments["thread_id"] = row["thread_id"]
    if isinstance(row.get("message_id"), str) and row["message_id"]:
        arguments["in_reply_to"] = row["message_id"]
    if isinstance(arguments["to"], list):
        arguments["to"] = arguments["to"][0].get("email") if arguments["to"] else ""
    return arguments


def same_draft(draft: dict, row: dict, arguments: dict) -> bool:
    marker = arguments.get("in_reply_to")
    if marker and draft.get("in_reply_to") == marker:
        return True
    return bool(
        not marker
        and row.get("thread_id")
        and draft.get("thread_id") == row.get("thread_id")
        and (draft.get("subject") or "") == arguments["subject"]
    )


def save_reply_draft(base: str, token: str, row: dict) -> str:
    arguments = draft_arguments(row)
    if arguments is None:
        return "not saved: message has no mailbox"
    existing = list_all(
        base,
        token,
        "EmailMessage.list",
        {"folder": "drafts", "is_draft": True},
    )
    for draft in existing:
        if same_draft(draft, row, arguments):
            if (draft.get("body_text") or "") != arguments["body_text"]:
                updated = call(
                    base,
                    token,
                    "EmailMessage.update",
                    {"id": draft["id"], "body_text": arguments["body_text"]},
                )
                return f"updated {updated.get('id') or draft.get('id')}"
            return f"already saved {draft.get('id')}"
    created = call(base, token, "EmailMessage.create", arguments)
    return f"saved {created.get('id')}"


def open_and_overdue(row: dict, day: str) -> bool:
    due = (row.get("due_date") or "")[:10]
    status = str(row.get("status") or "").lower()
    return bool(due) and due < day and status not in DONE


def clock(value: str | None) -> str:
    parsed = parse_when(value)
    if parsed is None:
        return value or ""
    return parsed.strftime("%H:%M")


def briefing_for(name: str, base: str, token: str, now: datetime) -> dict:
    start, end = today_bounds(now)
    day = start.date().isoformat()
    window = (
        f"between:{start.strftime('%Y-%m-%dT%H:%M:%S')}+05:30,"
        f"{end.strftime('%Y-%m-%dT%H:%M:%S')}+05:30"
    )
    mail = [
        row
        for row in list_all(
            base,
            token,
            "EmailMessage.list",
            {
                "is_read": False,
                "is_draft": False,
                "is_answered": False,
                "folder": "inbox",
            },
        )
        if needs_answer(row)
    ]
    horizon = now + timedelta(days=21)
    upcoming = [
        row
        for row in list_all(
            base,
            token,
            "CalendarEvent.list",
            {
                "start_at": (
                    f"between:{now.strftime('%Y-%m-%dT%H:%M:%S')}+05:30,"
                    f"{horizon.strftime('%Y-%m-%dT%H:%M:%S')}+05:30"
                ),
                "sort_by": "start_at",
                "sort_order": "asc",
            },
        )
        if parse_when(row.get("start_at")) is not None
    ]
    slots = free_slots(now, upcoming)
    for row in mail:
        row["_free_slots"] = slots
    events = [
        row
        for row in list_all(
            base,
            token,
            "CalendarEvent.list",
            {"start_at": window, "sort_by": "start_at", "sort_order": "asc"},
        )
        if overlaps_today(row, start, end)
        and str(row.get("status") or "").lower() != "cancelled"
    ]
    events.sort(key=lambda row: row.get("start_at") or "")
    tasks = [
        row
        for row in list_all(
            base,
            token,
            "Task.list",
            {"due_date": f"lt:{day}", "sort_by": "due_date", "sort_order": "asc"},
        )
        if open_and_overdue(row, day)
    ]
    tasks.sort(
        key=lambda row: (
            PRIORITY.get(str(row.get("priority") or "").lower(), 9),
            row.get("due_date") or "",
        )
    )
    return {"system": name, "mail": mail, "events": events, "tasks": tasks}


def render(now: datetime, reports: list[dict]) -> str:
    day = now.strftime("%-d %B %Y")
    saved = any(
        str(row.get("_draft_status") or "").startswith(("saved", "updated", "already saved"))
        for report in reports
        for row in report["mail"]
    )
    if saved:
        notice = [
            "Draft replies were saved. No mail was sent and no meeting was booked.",
            "A person must approve a draft before it is sent.",
        ]
    else:
        notice = [
            "Read only. No mail was sent, no draft was saved, and no meeting was booked.",
            "Any reply below is a proposal. A person must approve it before it is saved.",
        ]
    lines = [f"# Daily briefing — {day}", "", *notice, ""]
    for report in reports:
        lines.append(f"## {report['system']}")
        lines.append("")
        mail = report["mail"]
        lines.append(f"### Unread mail ({len(mail)})")
        lines.append("")
        if not mail:
            lines.append("None. No reply to propose.")
        else:
            for row in mail:
                subject = row.get("subject") or "(no subject)"
                sender = row.get("from_email") or row.get("from_name") or "unknown sender"
                lines.append(f"- {subject} — {sender}")
                saved = str(row.get("_draft_status") or "")
                prefix = (
                    "Draft saved"
                    if saved.startswith(("saved", "updated", "already saved"))
                    else "Draft, not saved"
                )
                lines.append(f"  {prefix}: {proposed_reply(row)}")
                if saved:
                    lines.append(f"  {saved}")
        lines.append("")
        events = report["events"]
        lines.append(f"### Today's meetings ({len(events)})")
        lines.append("")
        if not events:
            lines.append("None.")
        else:
            for row in events:
                title = row.get("title") or "(no title)"
                lines.append(
                    f"- {clock(row.get('start_at'))}–{clock(row.get('end_at'))} {title}"
                )
        lines.append("")
        tasks = report["tasks"]
        lines.append(f"### Overdue tasks ({len(tasks)})")
        lines.append("")
        if not tasks:
            lines.append("None.")
        else:
            counts: dict[str, int] = {}
            for row in tasks:
                key = str(row.get("priority") or "unset")
                counts[key] = counts.get(key, 0) + 1
            bits = [f"{counts[key]} {key}" for key in ("urgent", "high", "medium", "low") if counts.get(key)]
            lines.append("By priority: " + ", ".join(bits) + ".")
            lines.append("")
            for row in tasks:
                title = row.get("title") or "(no title)"
                due = (row.get("due_date") or "")[:10]
                status = row.get("status") or ""
                priority = row.get("priority") or ""
                lines.append(f"- due {due} [{status}, {priority}] {title}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    save_drafts = "--read-only" not in sys.argv
    now = datetime.now(ZONE)
    reports = []
    for name, (base, token_path) in SYSTEMS.items():
        token = token_path.read_text().strip()
        report = briefing_for(name, base, token, now)
        if save_drafts:
            for row in report["mail"]:
                try:
                    row["_draft_status"] = save_reply_draft(base, token, row)
                except RuntimeError as err:
                    row["_draft_status"] = f"not saved: {err}"
        reports.append(report)
    text = render(now, reports)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{now.date().isoformat()}.md"
    path.write_text(text)
    print(text)
    print(f"wrote {path}")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as err:
        detail = err.read().decode()[:500]
        raise SystemExit(f"HTTP {err.code}: {detail}") from err
