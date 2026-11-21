"""Bug hunt E (20 Nov): extreme-case regressions for E1-E6. No platform calls."""
import argparse
import builtins
import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from unittest import mock

from o2c import drafts, matching, receipts, report, tasks_payments as T
from o2c.client import Client, McpError, _response_message, platform_failure, tool_result
from o2c.output import days_option

D = date(2026, 11, 20)


class E1Settings(unittest.TestCase):
    def test_token_with_carriage_return_is_a_short_error_without_the_token(self):
        with self.assertRaises(McpError) as cm:
            Client("https://example.invalid", "sekret-TOKEN-123\r\nX")
        self.assertNotIn("sekret", str(cm.exception))
        self.assertIn("AGENTSWITCH_TOKEN", str(cm.exception))

    def test_trailing_newline_is_stripped(self):
        self.assertEqual(Client("https://example.invalid", "abc\n").token, "abc")

    def test_base_url_needs_a_scheme(self):
        for url in ("example.invalid", "ftp://example.invalid", "https://", "https://exa mple.invalid"):
            with self.assertRaises(McpError, msg=url):
                Client(url, "t")
        self.assertEqual(Client(" https://example.invalid/ \r", "t").base_url, "https://example.invalid")


class E2UnsafeText(unittest.TestCase):
    ESC = "\x1b]52;c;ZXZpbA==\x07Evil"

    def test_markdown_cell_drops_escape_sequences_and_direction_marks(self):
        out = report.cell(self.ESC + " Ac‮me\x9b")
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x07", out)
        self.assertNotIn("‮", out)
        self.assertNotIn("\x9b", out)

    def test_indic_joiners_are_kept(self):
        self.assertEqual(report.cell("क्‍ष"), "क्‍ष")

    def test_plain_text_in_drafts_drops_them_too(self):
        self.assertNotIn("\x1b", drafts._plain(self.ESC))

    def test_customer_name_with_invisible_marks_is_not_copied(self):
        for raw in ("Acme ‮Txt.exe", "Zero​Width", "C1\x9bcontrol"):
            name, note = drafts.safe_name(raw)
            self.assertIsNone(name, raw)
            self.assertTrue(note)
        self.assertEqual(drafts.safe_name("Bharat EV Motors Ltd")[0], "Bharat EV Motors Ltd")

    def test_email_with_invisible_marks_is_not_an_address(self):
        self.assertIsNone(drafts.safe_email("pay‮@evil.com"))
        self.assertIsNone(drafts.safe_email("pay​@example.com"))
        self.assertEqual(drafts.safe_email("pay@example.com"), "pay@example.com")

    def test_platform_failure_line_has_no_escape_sequence(self):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit):
            platform_failure("o2c", McpError("x: " + self.ESC))
        self.assertNotIn("\x1b", err.getvalue())


def pay_row(pid, number, party, amount):
    return {"id": pid, "number": number, "customer": party, "party_id": party, "unallocated": amount,
            "currency": "INR", "status": "draft", "payment_date": "2026-10-01", "fixture": False}


class E3MatchedById(unittest.TestCase):
    def test_payments_without_numbers_keep_their_own_matches(self):
        pays = [pay_row("A", None, "P1", 100.0), pay_row("B", None, "P2", 999.0)]
        docs = [{"kind": "invoice", "number": "INV-1", "id": "i1", "party_id": "P1", "date": None, "amount": 100.0, "currency": "INR"},
                {"kind": "invoice", "number": "INV-9", "id": "i9", "party_id": "P2", "date": None, "amount": 999.0, "currency": "INR"}]
        rep = {"instance": "x", "report_date": "2026-11-20", "days": 7, "sections": {
            "orders_not_invoiced": {"status": "ok", "rows": []},
            "invoices_overdue": {"status": "ok", "rows": [], "no_due_date": []},
            "payments_not_applied": {"status": "ok", "rows": pays}}}
        body = drafts.accounts_digest(rep, matching.candidate_matches(pays, docs), "a@example.com")["body_text"]
        line_p1 = next(l for l in body.splitlines() if "100.00 INR" in l and "draft" in l)
        self.assertIn("INV-1", line_p1)
        self.assertNotIn("INV-9", line_p1)

    def _ctx(self, payments):
        from tests.test_tasks_payments import FakePlatform
        return T.Ctx(FakePlatform({"Payment": payments}), "x", D)

    def test_task7_passes_with_two_unnumbered_payments(self):
        base = {"type": "receive", "docstatus": 1, "unallocated": 50.0, "amount": 50.0, "status": "draft",
                "date": "2026-11-01", "party_id": "P1"}
        res = T.unapplied_payments(self._ctx([dict(base, id="A", number=None), dict(base, id="B", number=None)]))
        self.assertTrue(res["passed"], res["evidence"])

    def test_task8_no_false_leak_from_a_shared_missing_number(self):
        base = {"docstatus": 1, "unallocated": 50.0, "amount": 50.0, "status": "draft", "date": "2026-11-01", "party_id": "P1"}
        res = T.unapplied_excludes_outgoing(self._ctx([dict(base, id="A", number=None, type="receive"),
                                                       dict(base, id="B", number=None, type="pay")]))
        self.assertTrue(res["passed"], res["evidence"])


class E4Task5DueDates(unittest.TestCase):
    def _ctx(self, invoices):
        from tests.test_tasks_payments import FakePlatform
        return T.Ctx(FakePlatform({"Invoice": invoices, "Payment": []}, tools=("Invoice.list",)), "x", D)

    def inv(self, i, due, **kw):
        return {"id": i, "number": f"INV-{i}", "docstatus": 1, "direction": "receivable", "due_date": due,
                "outstanding": 50.0, "amount_paid": 0, "grand_total": 50.0, "party_id": "P1", **kw}

    def test_unusable_due_dates_agree_with_the_report(self):
        res = T.overdue_invoices(self._ctx([self.inv("a", "2026-02-30"), self.inv("b", " 2026-10-15"),
                                            self.inv("c", "2026-10-15"), self.inv("d", None)]))
        self.assertTrue(res["passed"], res["evidence"])

    def test_missing_id_does_not_crash_the_evidence(self):
        res = T.overdue_invoices(self._ctx([self.inv(None, "2026-10-15"), self.inv("b", "2026-10-15")]))
        self.assertNotIn("infrastructure", res["evidence"])


class E5Options(unittest.TestCase):
    def test_days_option(self):
        self.assertEqual(days_option("7"), 7)
        for bad in ("abc", "-1", "", None, "1.5"):
            with self.assertRaises(argparse.ArgumentTypeError, msg=bad):
                days_option(bad)

    def _main(self, module, argv, env):
        with mock.patch.dict(os.environ, env), mock.patch.object(sys, "argv", argv), \
                redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as cm:
            module.main()
        return cm.exception.code, err.getvalue()

    def test_drafts_and_tasks_reject_bad_days_as_usage_errors(self):
        env = {"O2C_DAYS": "abc", "AGENTSWITCH_BASE_URL": "https://example.invalid", "AGENTSWITCH_TOKEN": "t"}
        code, err = self._main(drafts, ["o2c.drafts", "--out", "unused"], env)
        self.assertEqual(code, 2)
        self.assertIn("nonnegative", err)
        code, err = self._main(T, ["o2c.tasks_payments", "--instance", "x", "--date", "2026-11-20", "--days", "-1"], env)
        self.assertEqual(code, 2)

    def test_end_of_input_at_the_confirmation_is_not_confirmed(self):
        prop = {"drafts": [{"kind": "accounts_digest", "to": "a@example.com", "subject": "S", "body_text": "B", "fixture": False}],
                "report_date": "2026-11-20", "match_summary": {"payments": 0, "with_candidates": 0}}
        client = mock.Mock()
        writer = mock.Mock()
        with mock.patch.object(drafts, "Client", return_value=client), \
                mock.patch.object(drafts, "propose", return_value=prop), \
                mock.patch.object(drafts, "write_pair"), mock.patch.object(drafts, "to_markdown", return_value=""), \
                mock.patch.object(drafts, "find_mailbox", return_value={"id": "M1", "email": "me@example.com", "company_id": "C"}), \
                mock.patch.object(drafts, "existing_drafts", return_value=set()), \
                mock.patch.object(drafts, "DraftWriter", return_value=writer), \
                mock.patch.object(builtins, "input", side_effect=EOFError), \
                mock.patch.object(sys, "argv", ["o2c.drafts", "--out", "unused", "--create", "--instance", "x"]), \
                redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
            drafts.main()
        self.assertIn("not confirmed", str(cm.exception.code))
        writer.create.assert_not_called()


class E6Limits(unittest.TestCase):
    def row(self, n, amount):
        return {"number": n, "id": n, "party_id": "P1", "customer": "C", "currency": "INR", "status": "submitted",
                "age_days": 10, "age_bucket": "0-30", "unallocated": amount}

    def test_a_total_too_large_is_unknown_not_a_crash(self):
        s = report.payments_summary([self.row("A", 1e30), self.row("B", 50.0)])
        self.assertIsNone(s["by_currency"][0]["unallocated"])
        self.assertIn("unknown", report._payment_tables({"rows": [], "summary": s}) [0])

    def test_build_lists_it_as_a_data_issue(self):
        payments = [{"id": n, "number": n, "type": "receive", "docstatus": 1, "unallocated": a, "amount": a,
                     "date": "2026-11-01", "status": "submitted", "party_id": "P1"} for n, a in (("A", 1e30), ("B", 50.0))]

        class Fake:
            def tool_names(self):
                return {"SalesOrder.list", "Payment.list"}

            def list_all(self, entity, filters=None):
                return payments if entity == "Payment" else []

        rep = report.build(Fake(), report_date=D, currencies={"parties": {}, "companies": {}})
        issues = rep["sections"]["payments_not_applied"]["data_issues"]
        self.assertTrue(any(i["field"] == "summary" for i in issues))

    def test_receipt_history_total_too_large_is_unknown(self):
        rec = lambda i, amt: {"id": i, "customer_id": "P1", "status": "paid", "currency_code": "INR",
                              "invoices": [{"invoice_id": "I", "payment": amt}]}
        h = receipts.history_by_customer([rec("a", 1e30), rec("b", 50.0)])
        self.assertIsNone(h["P1"]["by_currency"]["INR"])

    def test_nan_and_infinity_in_a_reply_are_rejected(self):
        with self.assertRaises(McpError):
            _response_message('{"jsonrpc":"2.0","id":1,"result":{"v":NaN}}', "application/json", 200, 1, "t")
        with self.assertRaises(McpError):
            tool_result({"content": [{"type": "text", "text": '{"total": Infinity}'}]})


if __name__ == "__main__":
    unittest.main()
