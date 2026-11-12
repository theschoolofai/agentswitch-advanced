"""Synthetic report-rule and CLI checks; these are not graded course tasks."""
import contextlib
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from o2c import report
from o2c import __main__ as cli

D = date(2026, 11, 15)


def order(number, age=8, currency="INR", value=100, **extra):
    row = {"id": number, "number": number, "date": (D - timedelta(days=age)).isoformat(),
           "docstatus": 1, "invoiced_status": "unbilled", "currency_code": currency,
           "grand_total": value, "party_id": "P", "company_id": "CO", "_party_id_display": "Synthetic"}
    row.update(extra)
    return row


class ReadsOnly:
    def __init__(self, orders=(), invoice_access=True):
        self.orders = list(orders)
        self.invoice_access = invoice_access
        self.calls = []

    def tool_names(self):
        return {"SalesOrder.list", "Payment.list", "Party.list", "Company.list"} | (
            {"Invoice.list"} if self.invoice_access else set())

    def list_all(self, entity, filters=None):
        self.calls.append(entity)
        data = {"SalesOrder": self.orders, "Payment": [], "Invoice": [],
                "Party": [{"id": "P", "currency_id": "USD"}],
                "Company": [{"id": "CO", "default_currency": "INR"}]}
        if entity not in data:
            raise AssertionError("Unexpected read or write: " + entity)
        return [dict(r) for r in data[entity] if all(r.get(k) == v for k, v in (filters or {}).items())]

    def _rpc(self, *args, **kwargs):
        raise AssertionError("Report must not call a mutation transport")


class OrderRules(unittest.TestCase):
    def test_strict_threshold_and_zero(self):
        rows = [order("below", 6), order("equal", 7), order("above", 8)]
        self.assertEqual([r["id"] for r in report.orders_not_invoiced(rows, D, 7)], ["above"])
        self.assertEqual([r["id"] for r in report.orders_not_invoiced([order("today", 0), order("yesterday", 1)], D, 0)], ["yesterday"])

    def test_invalid_thresholds_rejected_even_with_empty_data(self):
        for days in (-1, 1.2, True, "7", None):
            with self.subTest(days=days), self.assertRaises(ValueError):
                report.orders_not_invoiced([], D, days)

    def test_drafts_cancelled_and_fully_invoiced_excluded(self):
        rows = [order("draft", docstatus=0), order("cancelled", docstatus=2),
                order("done", invoiced_status="invoiced"), order("partial", invoiced_status="partially_invoiced")]
        self.assertEqual([r["id"] for r in report.orders_not_invoiced(rows, D, 7)], ["partial"])

    def test_missing_bad_future_dates_diagnosed(self):
        rows = [order("missing", date=None), order("invalid", date="not-a-date"), order("future", -1),
                order("bad-draft", date="bad", docstatus=0), order("valid")]
        rep = report.build(ReadsOnly(rows), report_date=D)
        sec = rep["sections"]["orders_not_invoiced"]
        self.assertEqual([r["id"] for r in sec["rows"]], ["valid"])
        self.assertEqual({r["id"]: r["reason"] for r in sec["date_issues"]},
                         {"missing": "missing order date", "invalid": "invalid order date", "future": "future order date"})
        self.assertEqual(sum(sec["age_buckets"].values()), 1)

    def test_delivered_status_does_not_invent_a_date(self):
        row = report.orders_not_invoiced([order("delivered", delivered_status="delivered")], D, 7)[0]
        self.assertEqual((row["age_days"], row["age_basis"], row["deliverability_status"]),
                         (8, "order_date", "unverified"))

    def test_fixture_kept_and_input_not_mutated(self):
        raw = order("fixture", _party_id_display="[fixture] Synthetic")
        result = report.orders_not_invoiced([raw], D, 7)
        self.assertTrue(result[0]["fixture"])
        self.assertNotIn("age_basis", raw)

    def test_explicit_date_controls_age(self):
        raw = order("fixed", 8)
        with patch.object(report, "today_ist", side_effect=AssertionError("Host clock consulted")):
            result = report.build(ReadsOnly([raw]), report_date=D)
        self.assertEqual(result["sections"]["orders_not_invoiced"]["rows"][0]["age_days"], 8)


class BucketsAndOrdering(unittest.TestCase):
    def test_all_bucket_edges_and_unknown(self):
        ages = [0, 7, 8, 14, 15, 30, 31, 60, 61]
        self.assertEqual([report.order_age_bucket(a) for a in ages],
                         ["0-7", "0-7", "8-14", "8-14", "15-30", "15-30", "31-60", "31-60", ">60"])
        self.assertIsNone(report.order_age_bucket(None))
        self.assertIsNone(report.order_age_bucket(-1))

    def test_buckets_only_count_exceptions(self):
        raw = [order(str(a), a) for a in [7, 8, 14, 15, 30, 31, 60, 61]]
        sec = report.build(ReadsOnly(raw), report_date=D)["sections"]["orders_not_invoiced"]
        self.assertEqual(sec["age_buckets"], {"0-7": 0, "8-14": 2, "15-30": 2, "31-60": 2, ">60": 1})
        self.assertEqual(sec["unverified_deliverability_count"], 7)
        self.assertEqual(len({r["id"] for r in sec["rows"]}), 7)

    def test_changing_threshold_does_not_change_bucket_edges(self):
        raw = [order(str(a), a) for a in [14, 15, 30, 31, 61]]
        for days, expected in [(14, {"0-7": 0, "8-14": 0, "15-30": 2, "31-60": 1, ">60": 1}),
                               (30, {"0-7": 0, "8-14": 0, "15-30": 0, "31-60": 1, ">60": 1})]:
            sec = report.build(ReadsOnly(raw), report_date=D, days=days)["sections"]["orders_not_invoiced"]
            self.assertEqual(sec["age_buckets"], expected)

    def test_oldest_precedes_value_and_currency(self):
        rows = [order("new-large", 8, "INR", 100000), order("old-small", 9, "USD", 1)]
        self.assertEqual([r["id"] for r in report.orders_not_invoiced(rows, D, 7)], ["old-small", "new-large"])

    def test_equal_age_currency_groups_then_value(self):
        raw = [order("usd", currency="USD", value=9999), order("inr-low", value=10),
               order("unknown", currency=None, value=999999), order("inr-high", currency=" inr ", value=100)]
        self.assertEqual([r["id"] for r in report.orders_not_invoiced(raw, D, 7)],
                         ["inr-high", "inr-low", "usd", "unknown"])

    def test_resolved_currency_controls_build_order(self):
        raw = [order("a-fallback-usd", currency=None, value=999), order("z-record-inr", currency="INR", value=1)]
        rows = report.build(ReadsOnly(raw), report_date=D)["sections"]["orders_not_invoiced"]["rows"]
        self.assertEqual([r["id"] for r in rows], ["z-record-inr", "a-fallback-usd"])
        self.assertEqual((rows[1]["currency"], rows[1]["currency_source"]), ("USD", "customer"))

    def test_values_strings_missing_zero_and_nonfinite(self):
        raw = [order("missing", value=None), order("zero", value=0), order("numeric-string", value="10.50"),
               order("bad", value="bad"), order("nan", value=float("nan"))]
        self.assertEqual([r["id"] for r in report.orders_not_invoiced(raw, D, 7)],
                         ["numeric-string", "zero", "bad", "missing", "nan"])

    def test_stable_number_then_id_without_input_order_dependency(self):
        raw = [order("same", id="b"), order("same", id="a"), order("aaa")]
        expected = ["aaa", "a", "b"]
        for data in (raw, list(reversed(raw))):
            self.assertEqual([r["id"] for r in report.orders_not_invoiced(data, D, 7)], expected)

    def test_values_equal_at_cent_precision_use_stable_tie_break(self):
        raw = [order("a-low", value="1.000000000000000000000000000001"),
               order("z-high", value="1.000000000000000000000000000002")]
        # Monetary normalization is shared by sorting/rendering: fractions below
        # the documented cent precision must not create invisible value ordering.
        self.assertEqual([r["id"] for r in report.orders_not_invoiced(raw, D, 7)], ["a-low", "z-high"])


class OutputAndCLI(unittest.TestCase):
    def test_empty_report_explains_age_basis(self):
        rep = report.build(ReadsOnly(), report_date=D)
        md = report.to_markdown(rep)
        self.assertIn("## Orders not invoiced (0)", md)
        self.assertIn("Age basis: **order date**", md)
        self.assertIn("Deliverability unverified: **0**", md)
        self.assertIn("0-7: 0", md)

    def test_legacy_report_without_metadata_still_renders(self):
        rep = report.build(ReadsOnly([order("legacy")]), report_date=D)
        sec = rep["sections"]["orders_not_invoiced"]
        for key in ["age_basis", "deliverability_status", "unverified_deliverability_count", "age_buckets", "date_issues"]:
            sec.pop(key)
        self.assertIn("## Orders not invoiced (1)", report.to_markdown(rep))

    def test_date_issue_only_report_is_visible_and_escaped(self):
        rep = report.build(ReadsOnly([order("bad|record\nname", date="invalid")]), report_date=D)
        md = report.to_markdown(rep)
        self.assertIn("Orders with unusable dates (1)", md)
        self.assertIn("bad\\|record name: invalid order date", md)
        self.assertIn("### Age-based exception rows", md)
        self.assertEqual(rep["sections"]["orders_not_invoiced"]["rows"], [])

    def test_build_rejects_bad_days_before_any_read(self):
        client = ReadsOnly()
        with self.assertRaises(ValueError):
            report.build(client, report_date=D, days=-1)
        self.assertEqual(client.calls, [])

    def test_cli_invalid_arguments_before_client_creation(self):
        for value in ("-1", "bad", "1.5"):
            with self.subTest(value=value), patch.object(cli, "Client") as client, \
                    patch("sys.argv", ["o2c", "--days", value]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    cli.main()
                self.assertEqual(exc.exception.code, 2)
                client.assert_not_called()

    def test_cli_invalid_environment_threshold_before_client(self):
        with patch.dict(os.environ, {"O2C_DAYS": "-5"}), patch.object(cli, "Client") as client, \
                patch("sys.argv", ["o2c"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main()
            client.assert_not_called()

    def test_cli_utf8_outputs_metadata_blocked_status_and_readonly(self):
        client = ReadsOnly([order("SO|1", _party_id_display="客户 | North\nDivision")], invoice_access=False)
        with tempfile.TemporaryDirectory() as tmp, patch.object(cli, "Client", return_value=client), \
                patch("sys.argv", ["o2c", "--days", "7", "--date", "2026-11-15", "--out", tmp, "--instance", "synthetic"]), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            cli.main()
            rep = json.loads((Path(tmp) / "synthetic-2026-11-15.json").read_text(encoding="utf-8"))
            md = (Path(tmp) / "synthetic-2026-11-15.md").read_text(encoding="utf-8")
        row = rep["sections"]["orders_not_invoiced"]["rows"][0]
        self.assertEqual((row["age_basis"], row["age_bucket"], row["deliverability_status"]), ("order_date", "8-14", "unverified"))
        self.assertIn("客户 \\| North Division", md)
        self.assertIn("invoices_overdue=blocked", output.getvalue())
        self.assertTrue(set(client.calls) <= {"SalesOrder", "Invoice", "Payment", "Party", "Company"})

    def test_report_render_has_no_cross_currency_total(self):
        md = report.to_markdown(report.build(ReadsOnly([order("INR", value=100), order("USD", currency="USD", value=50)]), report_date=D))
        self.assertIn("100.00 INR", md)
        self.assertIn("50.00 USD", md)
        self.assertNotIn("150.00", md)


if __name__ == "__main__":
    unittest.main()
