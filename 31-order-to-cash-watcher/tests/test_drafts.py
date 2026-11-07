"""Unit tests for matching and reminder drafts, on made-up rows (no platform data)."""
import unittest

from o2c import drafts, matching
from o2c.client import WriteBlocked


def pay_row(number, unallocated, party="P1", customer="Acme"):
    return {"number": number, "party_id": party, "customer": customer, "unallocated": unallocated,
            "payment_date": "2026-11-01", "status": "submitted", "fixture": False}


def order(number, total, party="P1", invoiced="invoiced", docstatus=1):
    return {"number": number, "id": number, "party_id": party, "grand_total": total,
            "invoiced_status": invoiced, "docstatus": docstatus, "date": "2026-10-01"}


def inv_row(number, outstanding, party="P1", customer="Acme", due="2026-11-01", fixture=False):
    return {"number": number, "party_id": party, "customer": customer, "due_date": due,
            "outstanding": outstanding, "currency": "INR", "fixture": fixture}


def rep(order_rows=(), pay_rows=()):
    return {"instance": "t", "report_date": "2026-11-15", "days": 7, "sections": {
        "orders_not_invoiced": {"status": "ok", "rows": list(order_rows)},
        "invoices_overdue": {"status": "blocked", "rows": []},
        "payments_not_applied": {"status": "ok", "rows": list(pay_rows)}}}


class Matching(unittest.TestCase):
    def test_only_invoiced_submitted_orders_are_documents(self):
        docs = matching.order_documents([order("A", 10), order("B", 10, invoiced="unbilled"),
                                         order("C", 10, docstatus=0), order("D", 10, invoiced="partially_invoiced")])
        self.assertEqual([d["number"] for d in docs], ["A", "D"])

    def test_same_customer_exact_amount_first(self):
        docs = matching.order_documents([order("far", 900.0), order("exact", 500.0), order("near", 510.0),
                                         order("other", 500.0, party="P2")])
        m = matching.candidate_matches([pay_row("PAY1", 500.0)], docs)[0]
        self.assertEqual([c["number"] for c in m["candidates"]], ["exact", "near", "far"])
        self.assertTrue(m["candidates"][0]["exact"])
        self.assertEqual(matching.summary([m]), {"payments": 1, "with_candidates": 1, "with_exact_match": 1})

    def test_no_candidate_when_customer_has_no_documents(self):
        m = matching.candidate_matches([pay_row("PAY1", 500.0, party="P9")], matching.order_documents([order("A", 500)]))
        self.assertEqual(m[0]["candidates"], [])


class Drafts(unittest.TestCase):
    def test_digest_lists_both_sections_and_stays_proposed(self):
        o = {"number": "SO-1", "customer": "Acme", "order_date": "2026-10-01", "age_days": 45,
             "invoiced_status": "unbilled", "grand_total": 100.0, "currency": "INR", "fixture": False}
        p = pay_row("PAY1", 500.0)
        d = drafts.accounts_digest(rep([o], [p]), matching.candidate_matches([p], []))
        self.assertEqual(d["status"], "proposed")
        self.assertEqual(d["to"], drafts.ACCOUNTS_PLACEHOLDER)
        self.assertIn("SO-1", d["body_text"])
        self.assertIn("PAY1", d["body_text"])
        self.assertIn("no candidate found", d["body_text"])

    def test_no_digest_when_nothing_to_report(self):
        self.assertIsNone(drafts.accounts_digest(rep(), []))

    def test_one_reminder_per_customer_and_skip_without_email(self):
        rows = [inv_row("INV-1", 100.0), inv_row("INV-2", 50.0), inv_row("INV-3", 70.0, party="P2", customer="Beta")]
        made, skipped = drafts.overdue_reminders(rows, {"P1": {"email": "ap@acme.example"}, "P2": {}})
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]["to"], "ap@acme.example")
        self.assertEqual(made[0]["refs"], ["INV-1", "INV-2"])
        self.assertIn("150.00 INR", made[0]["body_text"])
        self.assertEqual(skipped[0]["customer"], "Beta")

    def test_payload_is_always_a_draft(self):
        d = {"to": "x@y.example", "subject": "s", "body_text": "b"}
        p = drafts.to_payload(d, "MB", "CO")
        self.assertEqual((p["folder"], p["is_draft"]), ("drafts", True))


class DraftWriterSafety(unittest.TestCase):
    """The writer refuses before any request: the fake client fails the test if it is called."""

    class NoCalls:
        def _rpc(self, *a):
            raise AssertionError("a request was made")

    def setUp(self):
        self.w = drafts.DraftWriter(self.NoCalls(), "MB", "CO")

    def test_every_send_and_change_tool_is_refused(self):
        for name in ("endpoint.email.messages.send", "EmailMessage.send_email", "EmailMessage.record_sent",
                     "EmailCampaign.send", "EmailMessage.update", "EmailMessage.delete", "SalesOrder.update"):
            with self.assertRaises(WriteBlocked, msg=name):
                self.w.call(name, {"folder": "drafts", "is_draft": True, "to": "x@y.example"})

    def test_non_draft_message_is_refused(self):
        for args in ({"folder": "outbox", "is_draft": True, "to": "x@y.example"},
                     {"folder": "drafts", "is_draft": False, "to": "x@y.example"}):
            with self.assertRaises(WriteBlocked):
                self.w.call(drafts.DRAFT_TOOL, args)

    def test_draft_without_recipient_is_refused(self):
        with self.assertRaises(WriteBlocked):
            self.w.create({"to": drafts.ACCOUNTS_PLACEHOLDER, "subject": "s", "body_text": "b"})


if __name__ == "__main__":
    unittest.main()
