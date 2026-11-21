"""Review of PR #54 (Sunil, 20 Nov): reminder subjects carry the date; older unsent drafts are pointed out;
event-stream data loses exactly one leading space; the retry budget holds for the whole request."""
import io
import socket
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from o2c import client as C, drafts
from o2c.client import Client, PlatformUnavailable, _response_message


def inv(n, party="P1", out=100.0):
    return {"number": n, "id": n, "party_id": party, "customer": "Acme Ltd", "due_date": "2026-10-01",
            "outstanding": out, "currency": "INR", "payment_state": "unpaid", "fixture": False}


PARTIES = {"P1": {"id": "P1", "name": "Acme Ltd", "email": "ap@acme.example"}}


class ReminderSubjectDate(unittest.TestCase):
    def test_the_subject_carries_the_report_date(self):
        (d,), _ = drafts.overdue_reminders([inv("I1")], PARTIES, report_date="2026-11-20")
        self.assertTrue(d["subject"].startswith("Payment reminder 2026-11-20: 1 overdue invoice"), d["subject"])

    def test_same_count_and_amount_on_another_day_is_a_new_draft(self):
        (old,), _ = drafts.overdue_reminders([inv("I1")], PARTIES, report_date="2026-11-19")
        (new,), _ = drafts.overdue_reminders([inv("I9")], PARTIES, report_date="2026-11-20")
        existing = {drafts._draft_key(old["to"], old["subject"])}
        ready, dupes = drafts.without_duplicates([new], existing)
        self.assertEqual((len(ready), len(dupes)), (1, 0))


class OlderDrafts(unittest.TestCase):
    def test_an_older_reminder_or_digest_to_the_same_recipient_is_pointed_out(self):
        (new,), _ = drafts.overdue_reminders([inv("I1", out=250.0)], PARTIES, report_date="2026-11-20")
        existing = {drafts._draft_key("ap@acme.example", "Payment reminder 2026-11-19: 1 overdue invoice, 100.00 INR"),
                    drafts._draft_key("other@x.example", "Payment reminder 2026-11-19: 1 overdue invoice, 100.00 INR"),
                    drafts._draft_key("ap@acme.example", "Quote follow-up"),
                    drafts._draft_key(new["to"], new["subject"])}
        older = drafts.older_drafts([new], existing, "overdue_reminder")
        # Any recipient: other@x.example gets no reminder today (paid since, or now held), so its stale one counts.
        self.assertEqual(older, [("ap@acme.example", "Payment reminder 2026-11-19: 1 overdue invoice, 100.00 INR"),
                                 ("other@x.example", "Payment reminder 2026-11-19: 1 overdue invoice, 100.00 INR")])

    def test_a_stale_reminder_to_a_customer_with_none_today_is_pointed_out(self):
        # Second review of #54 follow-up: a customer who paid (or is now held back, B1) gets no reminder today;
        # yesterday's unsent one must not go out unnoticed.
        (today,), _ = drafts.overdue_reminders([inv("I1")], PARTIES, report_date="2026-11-20")
        stale = drafts._draft_key("ap@paid.example", "Payment reminder 2026-11-19: 2 overdue invoices, 50.00 INR")
        self.assertEqual(drafts.older_drafts([today], {stale}, "overdue_reminder"), [stale])
        # a digest run doesn't point out reminders, and the other way round
        self.assertEqual(drafts.older_drafts([today], {stale}, "accounts_digest"), [])

    def test_a_digest_whose_parts_changed_is_pointed_out(self):
        new = {"to": "acc@x.example", "subject": "Order-to-cash exceptions 2026-11-20: 9 orders (part 1 of 2)"}
        existing = {drafts._draft_key("acc@x.example", "Order-to-cash exceptions 2026-11-20: 8 orders (part 1 of 3)")}
        self.assertEqual(len(drafts.older_drafts([new], existing)), 1)

    def test_create_prints_the_check_line_and_still_saves(self):
        prop = {"drafts": [{"kind": "accounts_digest", "to": "acc@x.example", "fixture": False, "body_text": "B",
                            "subject": "Order-to-cash exceptions 2026-11-20: 9 orders"}],
                "report_date": "2026-11-20", "match_summary": {"payments": 0, "with_candidates": 0}}
        writer = mock.Mock()
        writer.create.return_value = {"id": "m1"}
        with mock.patch.multiple(drafts, Client=mock.Mock(), propose=mock.Mock(return_value=prop), write_pair=mock.Mock(),
                                 to_markdown=mock.Mock(return_value=""), DraftWriter=mock.Mock(return_value=writer),
                                 find_mailbox=mock.Mock(return_value={"id": "M", "email": "me@x.example", "company_id": "C"}),
                                 existing_drafts=mock.Mock(return_value={("acc@x.example", "Order-to-cash exceptions 2026-11-19: 8 orders")})), \
                mock.patch("builtins.input", return_value="save drafts"), \
                mock.patch.object(sys, "argv", ["o2c.drafts", "--out", "unused", "--create", "--instance", "x"]), \
                redirect_stdout(io.StringIO()) as out:
            drafts.main()
        self.assertIn("check: an older unsent draft to x.example", out.getvalue())
        writer.create.assert_called_once()


class EventStreamSpace(unittest.TestCase):
    def test_exactly_one_leading_space_is_removed(self):
        raw = 'data:  {"jsonrpc":"2.0","id":1,\ndata:   "result":{"v":"a"}}\n\n'
        self.assertEqual(_response_message(raw, "text/event-stream", 200, 1, "t")["result"], {"v": "a"})
        # the payload lines keep their own indentation after the one space SSE removes
        payloads = []
        with mock.patch.object(C.json, "loads", side_effect=lambda t, **k: payloads.append(t) or {"id": 1, "result": {}}):
            _response_message("data:  x\ndata:   y\n\n", "text/event-stream", 200, 1, "t")
        self.assertEqual(payloads, [" x\n  y"])


class RetryBudget(unittest.TestCase):
    def test_a_read_that_keeps_timing_out_stops_by_the_budget(self):
        clock = [0.0]
        timeouts = []
        c = Client("https://example.invalid", "t")

        def post(body):
            t = getattr(c, "_try_timeout", None) or c.timeout
            timeouts.append(t)
            clock[0] += t                     # each try waits its full timeout
            raise socket.timeout()

        c._post = post
        c._sleep = lambda s: clock.__setitem__(0, clock[0] + s)
        with mock.patch.object(C.time, "monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(PlatformUnavailable):
                c._rpc("tools/call", {"name": "Payment.list", "arguments": {}})
        self.assertLessEqual(clock[0], C.RETRY_BUDGET + 0.001)
        self.assertEqual(timeouts[0], c.timeout)
        self.assertLess(timeouts[1], c.timeout)          # the second try only gets what is left

    def test_the_cut_timeout_reaches_urllib(self):
        # The real _post, with urlopen faked: the second try must be opened with the shortened timeout.
        clock, seen = [0.0], []
        c = Client("https://example.invalid", "t")

        class Reply:
            status, headers = 200, {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'

        def urlopen(req, timeout):
            seen.append(timeout)
            if len(seen) == 1:
                clock[0] += timeout
                raise socket.timeout()
            return Reply()

        c._sleep = lambda s: clock.__setitem__(0, clock[0] + s)
        with mock.patch.object(C.urllib.request, "urlopen", urlopen), \
                mock.patch.object(C.time, "monotonic", side_effect=lambda: clock[0]):
            c._rpc("tools/list", {})
        self.assertEqual(seen[0], c.timeout)
        self.assertEqual(seen[1], C.RETRY_BUDGET - c.timeout - C.RETRY_DELAYS[0])

    def test_quick_transient_errors_still_get_all_four_tries(self):
        c = Client("https://example.invalid", "t")
        calls = []
        c._post = lambda body: calls.append(1) or (_ for _ in ()).throw(socket.timeout())
        c._sleep = lambda s: None
        with self.assertRaises(PlatformUnavailable):
            c._rpc("tools/call", {"name": "Payment.list", "arguments": {}})
        self.assertEqual(len(calls), 4)


if __name__ == "__main__":
    unittest.main()


class EveryChangedLineRuns(unittest.TestCase):
    """Second review of #54: each line this PR changed is run by a test (private/prereview_check.sh, check 2)."""

    def test_a_third_payment_in_an_overflowed_group_keeps_it_unknown(self):
        from o2c import report
        row = lambda n, a: {"number": n, "id": n, "party_id": "P1", "customer": "C", "currency": "INR",
                            "status": "submitted", "age_days": 10, "age_bucket": "0-30", "unallocated": a}
        s = report.payments_summary([row("A", 1e30), row("B", 50.0), row("C", 25.0)])
        self.assertEqual(s["by_currency"][0]["count"], 3)
        self.assertIsNone(s["by_currency"][0]["unallocated"])

    def test_a_reply_whose_result_is_not_an_object_is_a_short_error(self):
        from o2c.client import McpError
        c = Client("https://example.invalid", "t")
        c._post = lambda body: (200, "application/json", '{"jsonrpc":"2.0","id":1,"result":[]}')
        with self.assertRaisesRegex(McpError, "reply has no result"):
            c._rpc("tools/list", {})

    def test_list_all_once_reads_without_the_reread(self):
        c = Client("https://example.invalid", "t")
        c.call = lambda name, args=None: {"data": [{"id": "a"}], "total": 1}
        self.assertEqual(c._list_all_once("Payment"), [{"id": "a"}])

    def test_a_cut_that_lands_on_a_heading_moves_the_heading_to_the_next_part(self):
        lines = ["Intro"] + ["r" * 97] * 50 + ["", "2. Invoices overdue (3)", "", "x"]
        chunks = drafts._pack(lines, budget=sum(len(l) + 1 for l in lines[:52]))
        self.assertEqual(chunks[1][0], "2. Invoices overdue (3)")
        self.assertEqual(chunks[0][-1], "")

    def test_a_part_never_starts_with_blank_lines(self):
        # The cut falls on a blank line with no other blank line to cut at, so the next chunk starts blank;
        # fit_body drops those blank lines from the part.
        lines = ["r" * 98] * 60 + ["", ""] + ["s" * 98] * 10
        budget = 60 * 99
        self.assertEqual(drafts._pack(lines, budget)[1][0], "")          # the raw chunk starts blank
        parts = drafts.fit_body({"kind": "k", "to": "a@example.com", "subject": "S", "body_text": "\n".join(lines)},
                                limit=budget + drafts._PART_MARGIN)
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[1]["body_text"].split("\n")[2], "s" * 98)

    def test_a_console_that_cannot_be_reconfigured_is_left_alone(self):
        from o2c import output

        class Stubborn(io.StringIO):
            def reconfigure(self, **kw):
                raise ValueError("cannot reconfigure")

        with mock.patch.object(sys, "stdout", Stubborn()), mock.patch.object(sys, "stderr", Stubborn()):
            output.safe_console()          # must not raise
