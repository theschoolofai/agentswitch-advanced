"""Checks for the daily briefing. No network and no live records."""

import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import briefing

ZONE = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 3, 21, 0, tzinfo=ZONE)
START, END = briefing.today_bounds(NOW)


class BriefingTests(unittest.TestCase):
    def test_meeting_during_today_counts(self):
        row = {
            "start_at": "2026-11-03T10:15:00+05:30",
            "end_at": "2026-11-03T10:45:00+05:30",
            "status": "confirmed",
        }
        self.assertTrue(briefing.overlaps_today(row, START, END))

    def test_meeting_from_yesterday_that_ends_today_counts(self):
        row = {
            "start_at": "2026-11-02T23:30:00+05:30",
            "end_at": "2026-11-03T00:30:00+05:30",
        }
        self.assertTrue(briefing.overlaps_today(row, START, END))

    def test_yesterdays_meeting_does_not_count(self):
        row = {
            "start_at": "2026-11-02T10:00:00+05:30",
            "end_at": "2026-11-02T11:00:00+05:30",
        }
        self.assertFalse(briefing.overlaps_today(row, START, END))

    def test_naive_time_is_read_as_ist(self):
        parsed = briefing.parse_when("2026-11-03T09:00:00")
        self.assertEqual(parsed.tzinfo, ZONE)
        self.assertEqual(parsed.hour, 9)

    def test_overdue_open_task(self):
        self.assertTrue(
            briefing.open_and_overdue(
                {"due_date": "2026-10-22", "status": "todo"}, "2026-11-03"
            )
        )

    def test_done_or_due_today_is_not_overdue(self):
        self.assertFalse(
            briefing.open_and_overdue(
                {"due_date": "2026-10-22", "status": "done"}, "2026-11-03"
            )
        )
        self.assertFalse(
            briefing.open_and_overdue(
                {"due_date": "2026-11-03", "status": "todo"}, "2026-11-03"
            )
        )

    def test_answered_or_draft_mail_does_not_need_a_reply(self):
        self.assertTrue(briefing.needs_answer({"folder": "inbox"}))
        self.assertFalse(briefing.needs_answer({"folder": "inbox", "is_answered": True}))
        self.assertFalse(briefing.needs_answer({"folder": "inbox", "is_draft": 1}))
        self.assertFalse(briefing.needs_answer({"folder": "sent"}))

    def test_render_proposes_a_reply_and_does_not_claim_it_was_saved(self):
        text = briefing.render(
            NOW,
            [
                {
                    "system": "Suryodaya",
                    "mail": [{"subject": "Quote", "from_email": "a@example.com"}],
                    "events": [],
                    "tasks": [],
                }
            ],
        )
        self.assertIn("Draft, not saved:", text)
        self.assertIn("Quote", text)
        self.assertIn("revised lead time", text)
        self.assertIn("no draft was saved", text)

    def test_draft_is_not_a_send(self):
        arguments = briefing.draft_arguments(
            {
                "subject": "Quote follow-up",
                "mailbox_id": "box",
                "company_id": "co",
                "to": "me@example.com",
                "from_email": "them@example.com",
                "message_id": "<m@example.com>",
                "thread_id": "thread",
            }
        )
        self.assertEqual(arguments["folder"], "drafts")
        self.assertTrue(arguments["is_draft"])
        self.assertEqual(arguments["to"], "them@example.com")
        self.assertIsNone(
            briefing.draft_arguments({"subject": "Hello", "from_email": "a@example.com"})
        )

    def test_tool_error_is_not_treated_as_a_record(self):
        with self.assertRaises(RuntimeError):
            briefing.tool_result(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {"code": -32602, "message": "Due Date cannot be before 2026-11-04"},
                },
                "Task.create",
            )

    def test_free_slots_skip_a_busy_time(self):
        busy = datetime(2026, 11, 9, 10, 0, tzinfo=briefing.ZONE)
        slots = briefing.free_slots(
            datetime(2026, 11, 7, 12, 0, tzinfo=briefing.ZONE),
            [
                {
                    "start_at": "2026-11-09T10:00:00+05:30",
                    "end_at": "2026-11-09T10:30:00+05:30",
                    "status": "confirmed",
                }
            ],
        )
        self.assertEqual(len(slots), 2)
        self.assertNotIn(busy, [start for start, _end in slots])
        self.assertGreater(slots[0][0], datetime(2026, 11, 7, 12, 0, tzinfo=briefing.ZONE))

    def test_meeting_reply_uses_only_free_slots(self):
        text = briefing.proposed_reply(
            {
                "subject": "Meeting request: quarterly review",
                "_free_slots": [
                    (
                        datetime(2026, 11, 9, 15, 0, tzinfo=briefing.ZONE),
                        datetime(2026, 11, 9, 15, 30, tzinfo=briefing.ZONE),
                    ),
                    (
                        datetime(2026, 11, 12, 10, 0, tzinfo=briefing.ZONE),
                        datetime(2026, 11, 12, 10, 30, tzinfo=briefing.ZONE),
                    ),
                ],
            }
        )
        self.assertIn("Monday 9 November 15:00–15:30 IST", text)
        self.assertIn("Thursday 12 November 10:00–10:30 IST", text)
        self.assertIn("not booked", text)
        empty = briefing.proposed_reply({"subject": "Meeting request: quarterly review"})
        self.assertNotIn("November", empty)

    def test_script_never_sends_or_books(self):
        source = Path(briefing.__file__).read_text()
        for forbidden in (
            "send_email",
            "EmailMessage.reply",
            "EmailMessage.send_email",
            "endpoint.email.messages.send",
            "CalendarEvent.create",
            "CalendarEvent.update",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("10 November", source)
        self.assertNotIn("11 November", source)


if __name__ == "__main__":
    unittest.main()
