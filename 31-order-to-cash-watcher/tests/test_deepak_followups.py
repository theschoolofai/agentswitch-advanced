"""Synthetic regressions for Deepak's 12 November follow-up review."""
from datetime import date
import unittest
from unittest.mock import patch

from o2c import report, values
from o2c.client import Client, PaginationError
from tests.test_pagination import rows
from tests.test_section3_integration import Reads, payment, receipt, D


class ReceiptCoverage(unittest.TestCase):
    def section(self, receipts):
        return report.build(Reads([payment("A"), payment("B", currency="USD")], receipts),
                            report_date=D)["sections"]["payments_not_applied"]

    def test_unrelated_bad_receipt_does_not_hide_absence(self):
        sec = self.section([receipt(customer_id="C9", allocation_consideration="NaN")])
        self.assertEqual([r["hint"] for r in sec["rows"]], ["no_history", "no_history"])
        self.assertEqual(sec["receipt_history"]["coverage"], "partial")

    def test_only_affected_customer_has_unknown_history(self):
        by_party = {r["party_id"]: r for r in self.section([receipt(allocation_consideration="NaN")])["rows"]}
        self.assertEqual(by_party["INR"]["hint"], "unknown")
        self.assertEqual(by_party["USD"]["hint"], "no_history")
        self.assertIsNone(by_party["INR"]["receipts_applied_total"])

    def test_unattributed_quarantine_affects_every_customer(self):
        sec = self.section([receipt(customer_id=None, allocation_consideration="NaN")])
        self.assertTrue(all(r["hint"] == "unknown" for r in sec["rows"]))

    def test_existing_history_keeps_hint_but_not_incomplete_totals(self):
        sec = self.section([receipt(allocation_consideration=101), receipt(allocation_consideration="bad")])
        row = next(r for r in sec["rows"] if r["party_id"] == "INR")
        self.assertEqual(row["hint"], "has_history")
        self.assertEqual(row["receipt_history_coverage"], "partial")
        self.assertIsNone(row["receipts_applied_total"])
        self.assertTrue(all(t["applied_total"] is None for t in row["receipts_applied_by_currency"]))

    def test_bad_date_does_not_quarantine_allocation_history(self):
        row = self.section([receipt(date="invalid")])["rows"][0]
        self.assertEqual(row["hint"], "same_amount")
        self.assertEqual(row["receipt_history_coverage"], "complete")
        self.assertIsNone(row["last_receipt_date"])


class PagingRestarts(unittest.TestCase):
    def client(self):
        return Client(base_url="https://synthetic.invalid", token="synthetic")

    def test_changed_total_restarts_at_zero_without_leaking_old_rows(self):
        pages = [{"data": rows("old"), "total": 2}, {"data": rows("shift"), "total": 3},
                 {"data": rows("a", "b"), "total": 3}, {"data": rows("c"), "total": 3}]
        c = self.client()
        with patch.object(c, "call", side_effect=pages) as call:
            self.assertEqual(c.list_all("Invoice"), rows("a", "b", "c"))
        self.assertEqual([x.args[1]["offset"] for x in call.call_args_list], [0, 1, 0, 2])
        self.assertTrue(all(x.args[1]["sort_by"] == "id" and x.args[1]["sort_order"] == "asc"
                            for x in call.call_args_list))

    def test_duplicate_id_restarts_whole_read(self):
        pages = [{"data": rows("a", "a"), "total": 2}, {"data": rows("a", "b"), "total": 2}]
        c = self.client()
        with patch.object(c, "call", side_effect=pages) as call:
            self.assertEqual(c.list_all("Invoice"), rows("a", "b"))
        self.assertEqual([x.args[1]["offset"] for x in call.call_args_list], [0, 0])

    def test_permanent_instability_is_bounded(self):
        c = self.client()
        pages = [{"data": rows("a"), "total": 2}, {"data": rows("b"), "total": 3}] * 3
        with patch.object(c, "call", side_effect=pages) as call, self.assertRaises(PaginationError):
            c.list_all("Invoice")
        self.assertEqual(call.call_count, 6)

    def test_malformed_response_is_not_retried(self):
        c = self.client()
        with patch.object(c, "call", return_value={"data": []}) as call, self.assertRaises(PaginationError):
            c.list_all("Invoice")
        self.assertEqual(call.call_count, 1)


class DatePresentation(unittest.TestCase):
    def test_all_fraction_widths_normalized_for_python310(self):
        from datetime import datetime

        class Python310Parser:
            @staticmethod
            def fromisoformat(text):
                # Model the old parser constraint even when the suite runs on newer Python.
                fraction = text.split(".", 1)[1].split("+", 1)[0].split("-", 1)[0]
                if len(fraction) not in (3, 6):
                    raise ValueError("unsupported fraction width")
                return datetime.fromisoformat(text)

        for width in range(1, 7):
            with self.subTest(width=width), patch.object(values, "datetime", Python310Parser):
                self.assertEqual(values.business_date("2026-11-12T23:59:00." + "5" * width + "+05:30"),
                                 date(2026, 11, 12))

    def test_unusable_order_date_is_listed_once(self):
        c = Reads([])
        original = c.list_all
        def read(entity, filters=None):
            if entity == "SalesOrder":
                return [{"id": "BAD-DATE", "number": "BAD-DATE", "date": "junk", "docstatus": 1,
                         "invoiced_status": "unbilled", "grand_total": 100}]
            return original(entity, filters)
        c.list_all = read
        result = report.build(c, report_date=D)
        self.assertEqual(report.to_markdown(result).count("BAD-DATE"), 1)
        self.assertTrue(result["sections"]["orders_not_invoiced"]["data_issues"])
