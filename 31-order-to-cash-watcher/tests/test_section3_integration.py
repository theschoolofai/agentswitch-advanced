"""Compatibility of Deepak's #35 with the report validation follow-up."""
from datetime import date
from decimal import Decimal
import json
import unittest

from o2c import report, drafts

D = date(2026, 11, 12)


def payment(number, amount=100, day="2026-08-20", currency="INR", **kw):
    row = {"id": number, "number": number, "party_id": currency, "company_id": "CO",
           "_party_id_display": currency + " synthetic", "type": "receive", "docstatus": 1,
           "date": day, "amount": str(amount), "unallocated": str(amount), "status": "reconciled"}
    row.update(kw)
    return row


def receipt(**kw):
    row = {"id": "REC-1", "number": "REC-1", "customer_id": "INR", "status": "paid", "date": "2026-10-01",
           "allocation_evidence_version": 1, "allocation_consideration": "100.00", "amount": None,
           "applied_allocations": [{"target_entity": "Invoice", "target_id": "I", "amount": "100.00"}],
           "allocation_history": [{"event_id": "posted", "amount": "100.00"},
                                  {"event_id": "applied", "target_id": "I", "amount": "100.00"}]}
    row.update(kw)
    return row


class Reads:
    def __init__(self, payments=(), receipts=(), history=True):
        self.data = {"SalesOrder": [], "Invoice": [], "Payment": list(payments), "PaymentReceived": list(receipts),
                     "Party": [{"id": "INR", "currency_id": "INR"}, {"id": "USD", "currency_id": "USD"}],
                     "Company": [{"id": "CO", "default_currency": "INR"}]}
        self.names_calls, self.calls, self.history = 0, [], history

    def tool_names(self):
        self.names_calls += 1
        return {k + ".list" for k in self.data if self.history or k != "PaymentReceived"}

    def list_all(self, entity, filters=None):
        self.calls.append(entity)
        return [dict(r) for r in self.data[entity] if all(r.get(k) == v for k, v in (filters or {}).items())]


class Section3Integration(unittest.TestCase):
    def test_order_and_payment_buckets_are_distinct(self):
        self.assertEqual(report.order_age_bucket(8), "8-14")
        self.assertEqual(report.age_bucket(8), "0-30")
        self.assertEqual(report.age_bucket(90), "61-90")
        self.assertEqual(report.age_bucket(91), "90+")

    def test_every_summary_dimension_adds_up_currency_by_currency(self):
        c = Reads([payment("A", 100), payment("B", 50, currency="USD"), payment("C", 0.10), payment("D", 0.20)])
        sec = report.build(c, report_date=D)["sections"]["payments_not_applied"]
        expected = {"INR": (3, Decimal("100.30")), "USD": (1, Decimal("50.00"))}
        for name in ("by_currency", "by_age", "by_status", "by_customer"):
            folded = {}
            for entry in sec["summary"][name]:
                n, total = folded.get(entry["currency"], (0, Decimal(0)))
                folded[entry["currency"]] = n + entry["count"], total + Decimal(str(entry["unallocated"]))
            self.assertEqual(folded, expected, name)
        self.assertEqual(sec["summary"]["count"], 4)
        self.assertEqual(c.names_calls, 1)

    def test_new_row_fields_and_applied_history_survive_validation(self):
        c = Reads([payment("PAY")], [receipt()])
        rep = report.build(c, report_date=D)
        row = rep["sections"]["payments_not_applied"]["rows"][0]
        self.assertEqual((row["hint"], row["receipts_paid"], row["receipts_applied_total"]), ("same_amount", 1, 100.0))
        self.assertEqual(row["same_amount_receipts"], ["REC-1"])
        self.assertEqual(row["notes"], ["reconciled but nothing allocated"])
        self.assertEqual((row["age_bucket"], row["docstatus"]), ("61-90", 1))
        md = report.to_markdown(rep)
        self.assertIn("**check: same amount**", md)
        self.assertIn("do not allocate money", md)
        json.dumps(rep, allow_nan=False)

    def test_missing_receipt_tool_is_blocked_and_not_read(self):
        c = Reads([payment("PAY")], [receipt()], history=False)
        sec = report.build(c, report_date=D)["sections"]["payments_not_applied"]
        self.assertEqual(sec["receipt_history"]["status"], "blocked")
        self.assertNotIn("PaymentReceived", c.calls)
        self.assertNotIn("hint", sec["rows"][0])

    def test_future_payment_has_future_bucket_not_order_deliverability_age(self):
        sec = report.build(Reads([payment("future", day="2026-11-13")]), report_date=D)["sections"]["payments_not_applied"]
        self.assertEqual((sec["rows"][0]["age_days"], sec["rows"][0]["age_bucket"]), (-1, "future"))
        self.assertEqual(sec["coverage"], "partial")

    def test_bad_receipt_amount_does_not_become_zero_or_nan_hint(self):
        sec = report.build(Reads([payment("PAY")], [receipt(allocation_consideration="NaN")]), report_date=D)["sections"]["payments_not_applied"]
        self.assertEqual(sec["receipt_history"]["coverage"], "partial")
        self.assertEqual(sec["rows"][0]["receipts_paid"], 0)
        self.assertEqual(sec["rows"][0]["hint"], "unknown")
        self.assertIsNone(sec["rows"][0]["receipts_applied_total"])
        self.assertTrue(sec["data_issues"])
        json.dumps(sec, allow_nan=False)

    def test_bad_receipt_child_or_date_is_diagnosed(self):
        for invalid in (receipt(applied_allocations=[{"amount": "bad"}]), receipt(applied_allocations={"amount": 100}), receipt(applied_allocations={}),
                        receipt(date="2026-11-01junk")):
            sec = report.build(Reads([payment("PAY")], [invalid]), report_date=D)["sections"]["payments_not_applied"]
            self.assertEqual(sec["receipt_history"]["coverage"], "partial")
            json.dumps(sec, allow_nan=False)

    def test_legacy_summary_rows_without_age_bucket_still_render(self):
        rows = report.payments_not_applied([payment("PAY")], D)
        rows[0].pop("age_bucket")
        self.assertEqual(report.payments_summary(rows)["by_age"][0]["bucket"], "61-90")

    def test_empty_payment_source_keeps_expected_note_and_complete_summary(self):
        sec = report.build(Reads(), report_date=D)["sections"]["payments_not_applied"]
        self.assertEqual(sec["summary"]["count"], 0)
        self.assertEqual(sec["summary"]["by_currency"], [])
        self.assertIn("expected", sec["note"])


if __name__ == "__main__":
    unittest.main()
