"""Unit tests on made-up rows (no platform data)."""
import unittest
from datetime import date

from o2c import report
from o2c.client import Client, WriteBlocked, is_read_tool

D = date(2026, 11, 15)


def order(number, d, invoiced="unbilled", docstatus=1, party="Acme"):
    return {"number": number, "id": number, "date": d, "invoiced_status": invoiced,
            "docstatus": docstatus, "_party_id_display": party, "grand_total": 100.0}


def payment(number, d, unallocated, type_="receive", docstatus=1, party="Acme"):
    return {"number": number, "id": number, "date": d, "type": type_, "docstatus": docstatus,
            "amount": 500.0, "unallocated": unallocated, "status": "submitted", "_party_id_display": party}


class OrdersNotInvoiced(unittest.TestCase):
    def test_threshold_is_strictly_more_than_n_days(self):
        rows = report.orders_not_invoiced([order("A", "2026-11-08"), order("B", "2026-11-07")], D, 7)
        self.assertEqual([r["number"] for r in rows], ["B"])  # A is exactly 7 days old

    def test_skips_drafts_cancelled_and_invoiced(self):
        rows = report.orders_not_invoiced([
            order("draft", "2026-10-01", docstatus=0),
            order("cancelled", "2026-10-01", docstatus=2),
            order("done", "2026-10-01", invoiced="invoiced"),
            order("partial", "2026-10-01", invoiced="partially_invoiced"),
        ], D, 7)
        self.assertEqual([r["number"] for r in rows], ["partial"])

    def test_oldest_first_and_fixture_flag(self):
        rows = report.orders_not_invoiced([
            order("new", "2026-11-01"), order("old", "2026-09-01", party="[team07-test X] H4 party"),
        ], D, 7)
        self.assertEqual([r["number"] for r in rows], ["old", "new"])
        self.assertTrue(rows[0]["fixture"])
        self.assertFalse(rows[1]["fixture"])


class PaymentsNotApplied(unittest.TestCase):
    def test_incoming_not_cancelled_with_money_left(self):
        rows = report.payments_not_applied([
            payment("ok", "2026-11-01", 200.0),
            payment("applied", "2026-11-01", 0.0),
            payment("outgoing", "2026-11-01", 200.0, type_="pay"),
            payment("transfer", "2026-11-01", 200.0, type_="internal_transfer"),
            payment("draft", "2026-11-01", 200.0, docstatus=0),
            payment("cancelled", "2026-11-01", 200.0, docstatus=2),
            payment("rounding", "2026-11-01", 0.001),
        ], D)
        self.assertEqual([r["number"] for r in rows], ["draft", "ok"])
        self.assertEqual(rows[0]["age_days"], 14)


class ReadOnlyClient(unittest.TestCase):
    def test_allowlist(self):
        for name in ("SalesOrder.list", "Payment.get", "endpoint.make.thread", "tools.search"):
            self.assertTrue(is_read_tool(name), name)
        for name in ("SalesOrder.make.StockEntry", "EmailMessage.create", "EmailReminder.delete",
                     "endpoint.email.messages.send", "Party.update"):
            self.assertFalse(is_read_tool(name), name)

    def test_write_is_refused_before_any_request(self):
        c = Client(base_url="http://invalid.example", token="x")
        with self.assertRaises(WriteBlocked):
            c.call("endpoint.email.messages.send", {"id": "1"})


class Markdown(unittest.TestCase):
    def test_blocked_section_is_shown(self):
        rep = {"instance": "t", "report_date": "2026-11-15", "days": 7, "generated_at": "x",
               "sections": {"orders_not_invoiced": {"status": "ok", "rule": "r", "rows": []},
                            "invoices_overdue": {"status": "blocked", "reason": "no access", "rows": []},
                            "payments_not_applied": {"status": "ok", "rule": "r", "rows": []}}}
        md = report.to_markdown(rep)
        self.assertIn("**BLOCKED:** no access", md)
        self.assertIn("## Orders not invoiced (0)", md)


if __name__ == "__main__":
    unittest.main()
