"""Wrap-up (20 Nov): bug hunt G1-G4, and the real scenarios coverage showed were untested. No platform calls."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from o2c import drafts, report, tasks_payments as T
from o2c.client import McpError, _response_message
from o2c.output import write_pair
from tests.test_tasks_payments import FakePlatform

D = date(2026, 11, 20)


class Boxes:
    def __init__(self, listed=(), total=None, one=None):
        self.listed, self.total, self.one = list(listed), total, one

    def call(self, name, args=None):
        if name == "Mailbox.get":
            return self.one
        return {"data": self.listed, "total": len(self.listed) if self.total is None else self.total}


class G1Mailbox(unittest.TestCase):
    def test_a_named_inactive_or_deleted_mailbox_is_refused(self):
        for box in ({"id": "M", "is_active": False}, {"id": "M", "deleted_at": "2026-11-19"}):
            with self.assertRaises(drafts.NoMailbox):
                drafts.find_mailbox(Boxes(one=box), "M")
        self.assertEqual(drafts.find_mailbox(Boxes(one={"id": "M", "is_active": True}), "M")["id"], "M")

    def test_more_mailboxes_than_one_page_needs_a_choice(self):
        with self.assertRaises(drafts.NoMailbox):
            drafts.find_mailbox(Boxes(listed=[{"id": "A", "is_default": True}], total=25))

    def test_one_active_mailbox_is_used(self):
        self.assertEqual(drafts.find_mailbox(Boxes(listed=[{"id": "A"}, {"id": "B", "is_active": False}]))["id"], "A")


def invoice(i, direction, **kw):
    return {"id": i, "number": f"INV-{i}", "docstatus": 1, "due_date": "2026-10-01", "outstanding": 10.0,
            "amount_paid": 0, "grand_total": 10.0, "party_id": "P1", **({"direction": direction} if direction != "absent" else {}), **kw}


class G2InvoiceDirection(unittest.TestCase):
    def test_unknown_direction_is_left_out_and_said_so(self):
        issues = []
        rows, _ = report.invoices_overdue([invoice("a", "Receivable"), invoice("b", None), invoice("c", "payable"),
                                           invoice("d", "receivable"), invoice("e", "absent")], D, issues)
        self.assertEqual({r["id"] for r in rows}, {"d", "e"})          # a missing field still means receivable
        self.assertEqual(sorted(i["id"] for i in issues if i["field"] == "direction"), ["a", "b"])   # bills: no issue

    def test_task5_agrees(self):
        c = T.Ctx(FakePlatform({"Invoice": [invoice("a", "Receivable"), invoice("d", "receivable")], "Payment": []},
                               tools=("Invoice.list",)), "x", D)
        res = T.overdue_invoices(c)
        self.assertTrue(res["passed"], res["evidence"])


class G3EventStream(unittest.TestCase):
    def test_data_split_over_several_lines(self):
        raw = ('data: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
               'data: {"jsonrpc":"2.0","id":7,\ndata: "result":{"ok":true}}\n\n')
        self.assertEqual(_response_message(raw, "text/event-stream", 200, 7, "t")["result"], {"ok": True})

    def test_single_line_events_and_plain_json_still_work(self):
        self.assertEqual(_response_message('event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n',
                                           "text/event-stream", 200, 1, "t")["result"], {})
        self.assertEqual(_response_message('{"jsonrpc":"2.0","id":2,"result":{"a":1}}', "application/json", 200, 2, "t")
                         ["result"], {"a": 1})


class G4ConsoleFirst(unittest.TestCase):
    def test_drafts_and_tasks_set_up_the_console_before_a_failure_can_print(self):
        for module, argv in ((drafts, ["o2c.drafts", "--out", "unused"]),
                             (T, ["o2c.tasks_payments", "--instance", "x", "--date", "2026-11-20"])):
            order = []
            with mock.patch.object(module, "safe_console", side_effect=lambda: order.append("console")), \
                    mock.patch.object(module, "Client", side_effect=lambda: order.append("client") or (_ for _ in ()).throw(McpError("down"))), \
                    mock.patch.object(sys, "argv", argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                module.main()
            self.assertEqual(order[:2], ["console", "client"], module.__name__)


def pay(n, unallocated=50.0):
    return {"id": n, "number": n, "type": "receive", "docstatus": 1, "unallocated": unallocated, "amount": unallocated,
            "status": "submitted", "date": "2026-11-01", "party_id": "P1"}


class TasksCommand(unittest.TestCase):
    def test_writes_results_json_and_one_line_per_task(self):
        fake = FakePlatform({"Payment": [pay("A")]})
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(T, "Client", return_value=fake), \
                mock.patch.dict(os.environ, {"AGENTSWITCH_RUN_ID": ""}), \
                mock.patch.object(sys, "argv", ["o2c.tasks_payments", "--instance", "x", "--date", "2026-11-20",
                                                "--out", str(Path(tmp) / "r.json")]), \
                redirect_stdout(io.StringIO()) as out:
            T.main()
            results = json.loads((Path(tmp) / "r.json").read_text())
        self.assertEqual([t["id"] for t in results["tasks"]], [f"x:{t[0]}" for t in T.TASKS])
        self.assertTrue(all({"passed", "score", "evidence", "title"} <= set(t) for t in results["tasks"]))
        self.assertIn("x: ", results["summary"])
        self.assertEqual(len(out.getvalue().strip().splitlines()), len(T.TASKS) + 1)

    def test_task9_with_nothing_to_remind_needs_no_draft(self):
        fake = FakePlatform({"Payment": [], "EmailMessage": []}, mailboxes=[{"id": "M", "email": "me@example.com", "company_id": "C"}])
        res = T.reminder_is_draft(T.Ctx(fake, "x", D, allow_writes=True))
        self.assertTrue(res["passed"], res["evidence"])
        self.assertNotIn("EmailMessage.create", fake.requests)

    def test_task10_fails_if_a_send_tool_is_not_refused(self):
        c = T.Ctx(FakePlatform({"EmailMessage": []}), "x", D)
        with mock.patch.object(T.drafts.DraftWriter, "call", return_value={}):
            res = T.refuse_send(c)
        self.assertFalse(res["passed"])
        self.assertEqual(res["score"], 0.0)


PROP = {"drafts": [{"kind": "accounts_digest", "to": "a@example.com", "subject": "S1", "body_text": "B", "fixture": False},
                   {"kind": "accounts_digest", "to": "a@example.com", "subject": "S2", "body_text": "B", "fixture": False}],
        "report_date": "2026-11-20", "match_summary": {"payments": 0, "with_candidates": 0}}


class DraftsCommandFailures(unittest.TestCase):
    def _main(self, **patches):
        base = {"Client": mock.Mock(), "propose": mock.Mock(return_value=PROP), "write_pair": mock.Mock(),
                "to_markdown": mock.Mock(return_value=""),
                "find_mailbox": mock.Mock(return_value={"id": "M", "email": "me@example.com", "company_id": "C"}),
                "existing_drafts": mock.Mock(return_value=set())}
        base.update(patches)
        with mock.patch.multiple(drafts, **base), mock.patch("builtins.input", return_value="save drafts"), \
                mock.patch.object(sys, "argv", ["o2c.drafts", "--out", "unused", "--create", "--instance", "x"]), \
                redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err, \
                self.assertRaises(SystemExit) as cm:
            drafts.main()
        return cm.exception.code, out.getvalue() + err.getvalue()

    def test_no_single_default_mailbox(self):
        code, _ = self._main(find_mailbox=mock.Mock(side_effect=drafts.NoMailbox("2 mailboxes and no single default one")))
        self.assertIn("no single default", str(code))

    def test_mailbox_read_fails(self):
        code, text = self._main(find_mailbox=mock.Mock(side_effect=McpError("Mailbox.list: HTTP 503 after 4 tries")))
        self.assertEqual(code, 3)
        self.assertIn("could not complete", text)

    def test_duplicate_check_read_fails(self):
        code, _ = self._main(existing_drafts=mock.Mock(side_effect=McpError("EmailMessage.list: down")))
        self.assertEqual(code, 3)

    def test_failed_save_says_how_many_were_saved(self):
        writer = mock.Mock()
        writer.create.side_effect = [{"id": "m1"}, McpError("EmailMessage.create: timeout")]
        code, text = self._main(DraftWriter=mock.Mock(return_value=writer))
        self.assertEqual(code, 3)
        self.assertIn("Saved 1 of 2 drafts", text)
        self.assertIn("check the mailbox", text)


class ReportAndDigestText(unittest.TestCase):
    def test_digest_mentions_receipt_history(self):
        p = {"id": "A", "number": "PAY-A", "customer": "C", "party_id": "P1", "unallocated": 10.0, "currency": "INR",
             "status": "submitted", "payment_date": "2026-11-01", "fixture": False, "hint": "has_history", "receipts_paid": 3}
        rep = {"instance": "x", "report_date": "2026-11-20", "days": 7, "sections": {
            "orders_not_invoiced": {"status": "ok", "rows": []}, "invoices_overdue": {"status": "ok", "rows": [], "no_due_date": []},
            "payments_not_applied": {"status": "ok", "rows": [p]}}}
        self.assertIn("customer has 3 applied receipts", drafts.accounts_digest(rep, [], "a@example.com")["body_text"])

    def test_partial_receipt_history_is_said_in_the_report(self):
        sec = {"rows": [], "summary": report.payments_summary([]),
               "receipt_history": {"status": "ok", "source": "PaymentReceived", "coverage": "partial"}}
        self.assertTrue(any("coverage is partial" in l for l in report._payment_tables(sec)))


class OutputSafety(unittest.TestCase):
    def test_refuses_a_symlinked_report_and_an_unsafe_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "elsewhere.txt"
            target.write_text("keep")
            (Path(tmp) / "x-2026-11-20.json").symlink_to(target)
            with self.assertRaises(ValueError):
                write_pair(tmp, "x-2026-11-20", "{}", "md")
            self.assertEqual(target.read_text(), "keep")
            with self.assertRaises(ValueError):
                write_pair(tmp, "../escape", "{}", "md")


class SplitterEdges(unittest.TestCase):
    def test_a_single_line_longer_than_a_part_is_cut_but_kept(self):
        body = "Hello,\n\n" + "x" * 25000 + "\n\nThank you."
        parts = drafts.fit_body({"kind": "k", "to": "a@example.com", "subject": "S", "body_text": body})
        self.assertTrue(all(len(p["body_text"]) <= drafts.BODY_MAX for p in parts))
        self.assertEqual(sum(p["body_text"].count("x") for p in parts), 25000)


if __name__ == "__main__":
    unittest.main()
