"""Regressions for currency hints and independent summary verification (offline)."""
import unittest

from o2c import receipts as R, report, tasks_payments as T
from tests.test_receipts import v1
from tests.test_tasks_payments import FakePlatform, pay, D


class ReceiptCurrency(unittest.TestCase):
    def hint(self, receipts, currency="INR"):
        return R.hint_for({"party_id": "C", "currency": currency, "unallocated": 100},
                          R.history_by_customer(receipts))

    def test_different_currency_never_matches(self):
        receipt = v1("USD-1", "C", 100)
        receipt["currency_code"] = "USD"
        self.assertEqual(self.hint([receipt])["hint"], "has_history")

    def test_unknown_receipt_currency_never_matches(self):
        receipt = v1("U", "C", 100)
        receipt.pop("currency_code")
        self.assertEqual(self.hint([receipt])["same_amount_receipts"], [])

    def test_unknown_payment_currency_never_matches(self):
        hint = self.hint([v1("R", "C", 100)], None)
        self.assertEqual(hint["hint"], "has_history")
        self.assertIsNone(hint["receipts_applied_total"])

    def test_totals_separate_known_and_unknown_currencies(self):
        rows = [v1("I", "C", 100), v1("U", "C", 100), v1("X", "C", 100)]
        rows[1]["currency_code"] = "USD"
        rows[2].pop("currency_code")
        hint = self.hint(rows)
        self.assertEqual(hint["same_amount_receipts"], ["I"])
        self.assertEqual(hint["receipts_applied_total"], 100)
        self.assertEqual({x["currency"]: x["applied_total"] for x in hint["receipts_applied_by_currency"]},
                         {"INR": 100, "USD": 100, None: None})
        self.assertIsNone(R.history_by_customer(rows)["C"]["applied_total"])

    def test_live_field_match_requires_same_currency(self):
        receipt = v1(None, "C", 100)
        receipt.update(amount=None, number="REC-LIVE")
        self.assertEqual(self.hint([receipt])["same_amount_receipts"], ["REC-LIVE"])

    def test_receipt_currency_uses_customer_context(self):
        receipt = v1("R", "C", 100)
        receipt.pop("currency_code")
        rows = [{"party_id": "C", "currency": "USD", "unallocated": 100}]
        report.add_receipt_hints(rows, [receipt], {"parties": {"C": "USD"}})
        self.assertEqual(rows[0]["hint"], "same_amount")
        self.assertNotIn("currency", receipt)  # Reader must not mutate source rows.


class SummaryVerifier(unittest.TestCase):
    def context(self):
        return T.Ctx(FakePlatform({"SalesOrder": [], "EmailMessage": [],
                                  "Payment": [pay("R1"), pay("R2", party="P2")],
                                  "Party": [{"id": "P1", "currency_id": "INR"},
                                            {"id": "P2", "currency_id": "USD"}]}, tools={"Party.list"}), "t", D)

    def test_independent_mixed_currency_baseline(self):
        self.assertTrue(T.unapplied_payments(self.context())["passed"])

    def test_wrong_row_currency_and_consistent_summary_fail(self):
        c = self.context()
        section = c.report()["sections"]["payments_not_applied"]
        for row in section["rows"]:
            row["currency"] = "USD"
        section["summary"] = report.payments_summary(section["rows"])
        self.assertFalse(T.unapplied_payments(c)["passed"])

    def test_wrong_group_labels_fail_with_totals_unchanged(self):
        for table, field, wrong in [("by_age", "bucket", "90+"), ("by_status", "status", "reconciled"),
                                    ("by_customer", "party_id", "WRONG")]:
            with self.subTest(table=table):
                c = self.context()
                for group in c.report()["sections"]["payments_not_applied"]["summary"][table]:
                    group[field] = wrong
                self.assertFalse(T.unapplied_payments(c)["passed"])

    def test_missing_and_duplicate_groups_fail(self):
        for table in ("by_currency", "by_age", "by_status", "by_customer"):
            for duplicate in (True, False):
                with self.subTest(table=table, duplicate=duplicate):
                    c = self.context()
                    groups = c.report()["sections"]["payments_not_applied"]["summary"][table]
                    groups.append(dict(groups[0])) if duplicate else groups.pop()
                    self.assertFalse(T.unapplied_payments(c)["passed"])

    def test_duplicate_report_rows_fail(self):
        c = self.context()
        rows = c.report()["sections"]["payments_not_applied"]["rows"]
        rows.append(dict(rows[0]))
        self.assertFalse(T.unapplied_payments(c)["passed"])

    def test_company_fallback_is_independently_recounted(self):
        c = T.Ctx(FakePlatform({"Payment": [pay("R")], "Company": [{"id": "CO", "default_currency": "USD"}]},
                              tools={"Company.list"}), "t", D)
        self.assertTrue(T.unapplied_payments(c)["passed"])
