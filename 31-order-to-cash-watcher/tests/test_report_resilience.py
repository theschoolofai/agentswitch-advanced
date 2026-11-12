"""Shared-value, mixed-source and output-publication regressions, invented rows only."""
import contextlib
from datetime import date
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from o2c import report, drafts
from o2c import __main__ as cli
from o2c.client import Client
from o2c.output import instance_label
from o2c.values import business_date, money, money_number, money_text

D = date(2026, 11, 15)


def order(number, **kw):
    row = dict(id=number, number=number, docstatus=1, invoiced_status="unbilled",
               date="2026-11-01", grand_total="100.50", currency_code="INR")
    row.update(kw)
    return row


def invoice(number, **kw):
    row = {"id": number, "number": number, "docstatus": 1, "direction": "receivable",
           "due_date": "2026-11-01", "outstanding": "10.00", "amount_paid": "90.00",
           "grand_total": "100.00", "currency_code": "INR", "party_id": "P"}
    row.update(kw)
    return row


def payment(number, **kw):
    row = {"id": number, "number": number, "type": "receive", "docstatus": 1,
           "date": "2026-11-01", "amount": "50.50", "unallocated": "50.50", "currency_code": "INR"}
    row.update(kw)
    return row


class StrictValues(unittest.TestCase):
    def test_valid_dates_and_full_timestamps(self):
        for raw in ("2026-11-01", "2026-11-01T12:30", "2026-11-01 12:30:59",
                    "2026-11-01T23:30:59.123456Z", "2026-11-01T23:30:59+05:30", date(2026, 11, 1)):
            with self.subTest(raw=raw):
                self.assertEqual(business_date(raw), date(2026, 11, 1))

    def test_no_date_prefix_or_invalid_timestamp_is_accepted(self):
        for raw in ("2026-11-01not-a-date", "2026-02-30", "2026-11-01T25:00", "2026-11-01T12:00:00junk",
                    "20261101", "2026-W44-7", "2026-11-01X12:00", " 2026-11-01", "2026-11-01T12:00+99:00", 42, True):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                business_date(raw)
        self.assertIsNone(business_date(None))
        self.assertIsNone(business_date(""))

    def test_numeric_strings_zero_negative_and_decimal_inputs(self):
        for raw in ("100.50", Decimal("100.50"), 100.5):
            self.assertEqual(money_number(raw), 100.5)
            self.assertEqual(money_text(raw), "100.50")
        self.assertEqual(money_number(0), 0)
        self.assertEqual(money_number("-10.25"), -10.25)
        self.assertIsNone(money_number(None))
        self.assertEqual(money_text(None), "unknown")

    def test_nonfinite_and_malformed_money_never_formats_as_nan(self):
        for raw in ("bad", "NaN", "Infinity", float("nan"), float("inf"), -float("inf"), True, {}, "1,000", "1e100000"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    money_number(raw)
                self.assertEqual(money_text(raw), "unknown")

    def test_half_even_cent_policy_is_explicit(self):
        self.assertEqual(money_number("1.005"), 1.00)
        self.assertEqual(money_number("1.015"), 1.02)

    def test_formatter_used_by_report_and_drafts(self):
        self.assertEqual(report._money("100.50"), "100.50")
        self.assertEqual(drafts._money("100.50", "INR"), "100.50 INR")
        self.assertEqual(report._money(float("nan")), "unknown")


class MixedReport(unittest.TestCase):
    def client(self):
        """Exercise the actual pagination client across every business source."""
        client = Client(base_url="https://synthetic.invalid", token="synthetic")
        a = order("SO-OK")
        bad_date = order("SO-BAD-DATE"); bad_date["date"] = "2026-11-01junk"
        bad_amount = order("SO-BAD-AMOUNT"); bad_amount["grand_total"] = "NaN"
        bad_currency = order("SO-BAD-CURRENCY"); bad_currency["currency_code"] = "not-a-code"
        data = {
            "SalesOrder": [a, bad_date, bad_amount, bad_currency],
            "Invoice": [invoice("INV-OK"), invoice("INV-BAD-DATE", due_date="2026-02-30"),
                        invoice("INV-NO-DATE", due_date=None), invoice("INV-BAD-AMOUNT", outstanding="bad"),
                        invoice("BILL", direction="payable")],
            "Payment": [payment("PAY-OK"), payment("PAY-BAD-DATE", date="bad"),
                        payment("PAY-BAD-AMOUNT", unallocated="NaN"), payment("PAY-OUT", type="pay")],
            "Party": [{"id": "P", "email": "customer@synthetic.example", "currency_id": "USD"}],
            "Company": [{"id": "CO", "default_currency": "INR"}],
        }
        calls = []

        def rpc(method, params):
            if method == "tools/list":
                return {"tools": [{"name": entity + ".list"} for entity in data]}
            name, args = params["name"], params["arguments"]
            calls.append(name)
            if not name.endswith(".list"):
                raise AssertionError("Unexpected write: " + name)
            entity = name[:-5]
            filtered = [r for r in data[entity] if all(r.get(k) == v for k, v in args.items() if k not in ("limit", "offset", "sort_by", "sort_order"))]
            filtered.sort(key=lambda row: row[args["sort_by"]], reverse=args["sort_order"] == "desc")
            # One record per page, even though the client asks for up to 500.
            offset = args["offset"]
            return {"structuredContent": {"data": filtered[offset:offset + 1], "total": len(filtered)}}
        client._rpc = rpc
        return client, calls

    def test_mixed_build_retains_valid_rows_and_diagnoses_bad_inputs(self):
        client, calls = self.client()
        result = report.build(client, report_date=D, instance="synthetic")
        sections = result["sections"]
        # The invalid record currency falls back to verified company INR; equal
        # values then tie by number, while the unknown amount sorts last.
        self.assertEqual([r["id"] for r in sections["orders_not_invoiced"]["rows"]], ["SO-BAD-CURRENCY", "SO-OK", "SO-BAD-AMOUNT"])
        self.assertEqual([r["id"] for r in sections["invoices_overdue"]["rows"]], ["INV-OK"])
        self.assertEqual({r["id"] for r in sections["invoices_overdue"]["no_due_date"]}, {"INV-BAD-DATE", "INV-NO-DATE"})
        self.assertEqual({r["id"] for r in sections["payments_not_applied"]["rows"]}, {"PAY-OK", "PAY-BAD-DATE"})
        for sec in sections.values():
            self.assertEqual(sec["coverage"], "partial")
            self.assertTrue(sec["data_issues"])
        self.assertIsNone(next(r for r in sections["orders_not_invoiced"]["rows"] if r["id"] == "SO-BAD-AMOUNT")["grand_total"])
        self.assertIsNone(next(r for r in sections["payments_not_applied"]["rows"] if r["id"] == "PAY-BAD-DATE")["age_days"])
        md = report.to_markdown(result)
        self.assertIn("100.50 INR", md)
        self.assertIn("coverage is partial", md)
        self.assertIn("INV-NO-DATE", md)
        json.dumps(result, allow_nan=False)
        self.assertTrue(all(name.endswith(".list") for name in calls))

    def test_complete_cli_outputs_agree_even_with_bad_records(self):
        client, calls = self.client()
        with tempfile.TemporaryDirectory() as tmp, patch.object(cli, "Client", return_value=client), \
                patch("sys.argv", ["o2c", "--instance", "synthetic", "--date", "2026-11-15", "--out", tmp]), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            cli.main()
            data = json.loads((Path(tmp) / "synthetic-2026-11-15.json").read_text(encoding="utf-8"))
            md = (Path(tmp) / "synthetic-2026-11-15.md").read_text(encoding="utf-8")
        for sec in data["sections"].values():
            for row in sec["rows"] + sec.get("no_due_date", []):
                self.assertIn(row["number"], md)
        self.assertIn("partial coverage", stdout.getvalue())

    def test_proposal_does_not_crash_on_raw_invalid_invoice_amounts(self):
        client, calls = self.client()
        prop = drafts.propose(client, report_date=D, instance="synthetic", accounts_email="accounts@synthetic.example")
        digest = next(d for d in prop["drafts"] if d["kind"] == "accounts_digest")
        self.assertIn("INV-NO-DATE", digest["refs"])
        self.assertIn("coverage is partial", digest["body_text"])
        self.assertTrue(all(name.endswith(".list") for name in calls))
        json.dumps(prop, allow_nan=False)

    def test_negative_and_zero_balances_do_not_become_receivable_exceptions(self):
        overdue, _ = report.invoices_overdue([invoice("zero", outstanding=0), invoice("credit", outstanding=-10)], D)
        self.assertEqual(overdue, [])
        self.assertEqual(report.payments_not_applied([payment("zero", unallocated=0), payment("negative", unallocated=-10)], D), [])

    def test_valid_timestamps_normalize_each_report_section(self):
        stamp = "2026-11-01T23:30:59+05:30"
        self.assertEqual(report.orders_not_invoiced([order("O", date=stamp)], D, 7)[0]["order_date"], "2026-11-01")
        self.assertEqual(report.invoices_overdue([invoice("I", due_date=stamp)], D)[0][0]["due_date"], "2026-11-01")
        self.assertEqual(report.payments_not_applied([payment("P", date=stamp)], D)[0]["payment_date"], "2026-11-01")


class SafeOutput(unittest.TestCase):
    def report(self):
        return {"report_date": "2026-11-15", "text": "客户"}

    def test_safe_instances_and_omitted_default(self):
        for value in ("keystone", "seat31_demo", "A-1"):
            self.assertEqual(instance_label(value), value)
        self.assertEqual(instance_label(None), "report")

    def test_instance_traversal_and_blank_values_rejected_before_files(self):
        for value in ("../../outside", "/tmp/out", r"C:\outside", r"..\outside", "a/b", "a\\b", "", " ", "a b", "a:b"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "new"
                with self.assertRaises(ValueError):
                    cli.write_report(self.report(), "md", target, value)
                self.assertFalse(target.exists())

    def test_bad_instance_cli_fails_before_client_creation(self):
        for main in (cli, drafts):
            with patch.object(main, "Client") as client, patch("sys.argv", ["o2c", "--instance", "../bad", "--out", "unused"]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main.main()
                client.assert_not_called()

    def test_malicious_report_date_cannot_escape_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "new"
            with self.assertRaises(ValueError):
                cli.write_report({"report_date": "../../outside"}, "md", target, "synthetic")
            self.assertFalse(target.exists())

    def test_second_write_failure_preserves_existing_pair_and_cleans_staging(self):
        original = Path.write_text

        def fail_markdown(path, *args, **kw):
            if path.name.endswith(".md.new"):
                raise OSError("synthetic markdown failure")
            return original(path, *args, **kw)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            targets = [out / "synthetic-2026-11-15.json", out / "synthetic-2026-11-15.md"]
            for target in targets:
                target.write_text("previous", encoding="utf-8")
            with patch.object(Path, "write_text", fail_markdown), self.assertRaises(OSError):
                cli.write_report(self.report(), "new md", out, "synthetic")
            self.assertEqual([p.read_text() for p in targets], ["previous", "previous"])
            self.assertEqual(set(out.iterdir()), set(targets))

    def test_replace_failure_rolls_back_previous_pair(self):
        original = os.replace
        count = 0

        def fail_once(src, dest):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("synthetic replace failure")
            return original(src, dest)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            targets = [out / "synthetic-2026-11-15.json", out / "synthetic-2026-11-15.md"]
            for target in targets:
                target.write_text("previous", encoding="utf-8")
            with patch("o2c.output.os.replace", fail_once), self.assertRaises(OSError):
                cli.write_report(self.report(), "new md", out, "synthetic")
            self.assertEqual([p.read_text() for p in targets], ["previous", "previous"])
            self.assertEqual(set(out.iterdir()), set(targets))

    def test_second_write_failure_creates_neither_new_final_file(self):
        original = Path.write_text

        def fail_markdown(path, *args, **kw):
            if path.name.endswith(".md.new"):
                raise OSError("synthetic failure")
            return original(path, *args, **kw)
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, "write_text", fail_markdown):
            with self.assertRaises(OSError):
                cli.write_report(self.report(), "md", Path(tmp), "synthetic")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_replace_failure_removes_a_new_json_without_previous_pair(self):
        original = os.replace
        count = 0

        def fail_once(src, dest):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("synthetic replacement failure")
            return original(src, dest)
        with tempfile.TemporaryDirectory() as tmp, patch("o2c.output.os.replace", fail_once):
            with self.assertRaises(OSError):
                cli.write_report(self.report(), "md", Path(tmp), "synthetic")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_success_writes_utf8_and_no_temp_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli.write_report(self.report(), "客户", Path(tmp), "synthetic")
            self.assertEqual(len(list(Path(tmp).iterdir())), 2)
            self.assertEqual((Path(tmp) / "synthetic-2026-11-15.md").read_text(encoding="utf-8"), "客户")


if __name__ == "__main__":
    unittest.main()
