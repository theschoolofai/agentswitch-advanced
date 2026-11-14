"""Unit tests on made-up rows (no platform data)."""
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from o2c import report
from o2c.__main__ import write_report
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


def invoice(number, due, outstanding, docstatus=1, party="Acme"):
    return {"number": number, "id": number, "due_date": due, "outstanding": outstanding, "docstatus": docstatus,
            "grand_total": 1000.0, "amount_paid": 1000.0 - outstanding, "payment_terms": "Net 30",
            "_party_id_display": party}


class InvoicesOverdue(unittest.TestCase):
    def test_past_due_with_balance_only(self):
        overdue, _ = report.invoices_overdue([
            invoice("due_today", "2026-11-15", 100.0),
            invoice("late", "2026-11-14", 100.0),
            invoice("paid", "2026-10-01", 0.0),
            invoice("rounding", "2026-10-01", 0.001),
            invoice("draft", "2026-10-01", 100.0, docstatus=0),
            invoice("cancelled", "2026-10-01", 100.0, docstatus=2),
            invoice("future", "2026-12-01", 100.0),
        ], D)
        self.assertEqual([r["number"] for r in overdue], ["late"])  # due today is not yet overdue
        self.assertEqual(overdue[0]["days_overdue"], 1)

    def test_partially_paid_label(self):
        # Instructor answer 11: 100 invoiced, 90 received -> report the 10, age from due date, label "partially paid"
        part = dict(invoice("part", "2026-11-01", 10.0), grand_total=100.0, amount_paid=90.0)
        unpaid = dict(invoice("unpaid", "2026-11-01", 100.0), grand_total=100.0, amount_paid=0.0)
        overdue, _ = report.invoices_overdue([part, unpaid], D)
        rows = {r["number"]: r for r in overdue}
        self.assertEqual((rows["part"]["payment_state"], rows["part"]["outstanding"], rows["part"]["days_overdue"]),
                         ("partially paid", 10.0, 14))
        self.assertEqual(rows["unpaid"]["payment_state"], "unpaid")

    def test_markdown_counts_and_labels_partially_paid(self):
        part = dict(invoice("part", "2026-11-01", 10.0), grand_total=100.0, amount_paid=90.0)
        unpaid = dict(invoice("unpaid", "2026-11-01", 100.0), grand_total=100.0, amount_paid=0.0)
        overdue, no_due = report.invoices_overdue([part, unpaid], D)
        md = "\n".join(report._invoice_tables(overdue, no_due))
        self.assertIn("1 of 2 are **partially paid**", md)
        self.assertIn("| 10.00 currency not recorded | partially paid |", md)
        self.assertIn("| 100.00 currency not recorded | unpaid |", md)

    def test_supplier_bills_are_never_overdue_customer_invoices(self):
        # 11 Nov: Invoice also holds supplier bills (direction "payable"); they must not get a reminder
        bill = dict(invoice("bill", "2026-10-01", 100.0), direction="payable")
        bill_no_due = dict(invoice("bill2", None, 100.0), direction="payable")
        cust = dict(invoice("cust", "2026-10-01", 100.0), direction="receivable")
        overdue, no_due = report.invoices_overdue([bill, bill_no_due, cust, invoice("legacy", "2026-10-01", 5.0)], D)
        self.assertEqual([r["number"] for r in overdue], ["cust", "legacy"])  # no direction field: treated as a customer invoice
        self.assertEqual(no_due, [])

    def test_empty_due_date_listed_separately(self):
        overdue, no_due = report.invoices_overdue([
            invoice("none", None, 100.0), invoice("blank", "", 0.0), invoice("older", "2026-09-15", 50.0),
            invoice("newer", "2026-11-01", 50.0),
        ], D)
        self.assertEqual([r["number"] for r in overdue], ["older", "newer"])  # most overdue first
        self.assertEqual([r["number"] for r in no_due], ["blank", "none"])  # reported whatever the balance

    def test_markdown_shows_both_tables(self):
        overdue, no_due = report.invoices_overdue([invoice("late", "2026-11-01", 10.0), invoice("x", None, 5.0)], D)
        rep = {"instance": "t", "report_date": "2026-11-15", "days": 7, "generated_at": "x",
               "sections": {"orders_not_invoiced": {"status": "ok", "rule": "r", "rows": []},
                            "invoices_overdue": {"status": "ok", "rule": "r", "rows": overdue, "no_due_date": no_due},
                            "payments_not_applied": {"status": "ok", "rule": "r", "rows": []}}}
        md = report.to_markdown(rep)
        self.assertIn("## Invoices overdue (1)", md)
        self.assertIn("### Invoices with no due date (1)", md)
        self.assertIn("| late |", md)


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
        self.assertIn("## Invoices overdue (blocked)", md)  # never "(0)", which would read as "none overdue"
        self.assertIn("## Orders not invoiced (0)", md)


def _report(orders=(), invoices=(), payments=()):
    overdue, no_due = report.invoices_overdue(list(invoices), D)
    return {"instance": "t", "report_date": "2026-11-15", "days": 7, "generated_at": "x",
            "sections": {"orders_not_invoiced": {"status": "ok", "rule": "r",
                                                 "rows": report.orders_not_invoiced(list(orders), D, 7)},
                         "invoices_overdue": {"status": "ok", "rule": "r", "rows": overdue, "no_due_date": no_due},
                         "payments_not_applied": {"status": "ok", "rule": "r",
                                                  "rows": report.payments_not_applied(list(payments), D)}}}


def _tables(md):
    """Each Markdown table as a list of its lines (header, rule, rows)."""
    tables, cur = [], []
    for line in md.splitlines():
        if line.startswith("|"):
            cur.append(line)
        elif cur:
            tables.append(cur)
            cur = []
    return tables + ([cur] if cur else [])


def _columns(line):
    """Column count of a Markdown table row, ignoring escaped pipes."""
    return line.replace("\\\\", "").replace("\\|", "").count("|") - 1


class MarkdownEscaping(unittest.TestCase):
    """Review #13: a pipe or line break in record text must not add a column or split a row."""
    NASTY = "Acme | North\r\nDivision\\"

    def test_cell_escapes_pipes_backslashes_and_line_breaks(self):
        self.assertEqual(report.cell("Acme | North\nDivision"), "Acme \\| North Division")
        self.assertEqual(report.cell("a\r\nb\rc"), "a b c")
        self.assertEqual(report.cell("ends with \\"), "ends with \\\\")  # cannot escape the next |
        self.assertEqual(report.cell(None), "")

    def test_every_table_keeps_its_columns(self):
        rep = _report(orders=[order("SO|1", "2026-10-01", party=self.NASTY)],
                      invoices=[invoice("INV\\n1", "2026-11-01", 10.0, party=self.NASTY),
                                invoice("INV2", None, 5.0, party=self.NASTY)],
                      payments=[payment("PAY|1", "2026-11-01", 20.0, party=self.NASTY)])
        md = report.to_markdown(rep)
        tables = _tables(md)
        self.assertGreaterEqual(len(tables), 4)
        for t in tables:  # every line of every table (summaries included) matches its header
            for line in t:
                self.assertEqual(_columns(line), _columns(t[0]), line)
        records = [l for t in tables for l in t if l.startswith(("| SO", "| INV", "| PAY"))]
        self.assertEqual(len(records), 4)  # one line per record: no row was split
        self.assertIn("Acme \\| North Division\\\\", md)


class Utf8Output(unittest.TestCase):
    """Review #13: report files are UTF-8 even when the machine default is cp1252 (Windows)."""

    def test_non_latin_customer_written_under_cp1252_default(self):
        rep = _report(orders=[order("SO-1", "2026-10-01", party="客户 Ltd")],
                      payments=[payment("PAY-1", "2026-11-01", 20.0, party="客户 Ltd")])
        md = report.to_markdown(rep)
        real = Path.write_text

        def cp1252_default(self, data, encoding=None, errors=None, newline=None):
            return real(self, data, encoding=encoding or "cp1252", errors=errors, newline=newline)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(Path, "write_text", cp1252_default):
            stem = write_report(rep, md, Path(tmp), "t")
            self.assertIn("客户 Ltd", (Path(tmp) / f"{stem}.md").read_text(encoding="utf-8"))
            self.assertIn("客户 Ltd".encode("unicode_escape").decode(),
                          (Path(tmp) / f"{stem}.json").read_text(encoding="utf-8"))


class FakeReads:
    """Just enough of the client for report.build: tool_names and list_all on made-up rows."""

    def __init__(self, data, tools):
        self.data, self.tools = data, set(tools)

    def tool_names(self):
        return self.tools

    def list_all(self, entity, filters=None):
        return [r for r in self.data.get(entity, []) if all(r.get(k) == v for k, v in (filters or {}).items())]


CTX = {"parties": {"P-INR": "INR", "P-USD": "USD", "P-NONE": None}, "companies": {"CO": "INR"}}


class CurrencyLookup(unittest.TestCase):
    """Follow-up to the #17 review: currency comes from a recorded source, never a guess
    (live probe 11 Nov 2026: order currency_code empty, payments have none; Party.currency_id and
    Company.default_currency are set)."""

    def test_record_then_customer_then_company(self):
        self.assertEqual(report.resolve_currency("usd", "P-INR", "CO", CTX), ("USD", "record"))
        self.assertEqual(report.resolve_currency(None, "P-USD", "CO", CTX), ("USD", "customer"))
        self.assertEqual(report.resolve_currency("  ", "P-NONE", "CO", CTX), ("INR", "company"))
        self.assertEqual(report.resolve_currency(None, "unknown-party", None, CTX), ("INR", "company"))  # one company

    def test_nothing_recorded_stays_unknown(self):
        self.assertEqual(report.resolve_currency(None, "P-NONE", None, {"parties": {}, "companies": {}}), (None, None))
        two = {"parties": {}, "companies": {"A": "INR", "B": "USD"}}
        self.assertEqual(report.resolve_currency(None, None, None, two), (None, None))  # which company? not guessed
        self.assertEqual(report.resolve_currency(None, None, "B", two), ("USD", "company"))

    def test_context_skips_sources_this_login_cannot_read(self):
        c = FakeReads({"Party": [{"id": "P", "currency_id": "inr"}], "Company": [{"id": "CO", "default_currency": "INR"}]},
                      tools={"Party.list"})
        self.assertEqual(report.currency_context(c), {"parties": {"P": "INR"}, "companies": {}})

    def test_build_fills_order_and_payment_currency_with_source(self):
        orders = [dict(order("SO-1", "2026-10-01"), party_id="P-USD", company_id="CO"),
                  dict(order("SO-2", "2026-10-01"), party_id="P-NONE", company_id="CO", currency_code="eur")]
        pays = [dict(payment("PAY-1", "2026-11-01", 20.0), party_id="P-NONE", company_id="CO")]
        c = FakeReads({"SalesOrder": orders, "Payment": pays,
                       "Party": [{"id": "P-USD", "currency_id": "USD"}, {"id": "P-NONE", "currency_id": None}],
                       "Company": [{"id": "CO", "default_currency": "INR"}]},
                      tools={"SalesOrder.list", "Payment.list", "Party.list", "Company.list"})
        rep = report.build(c, report_date=D, days=7, instance="t")
        got = {r["number"]: (r["currency"], r["currency_source"])
               for k in ("orders_not_invoiced", "payments_not_applied") for r in rep["sections"][k]["rows"]}
        self.assertEqual(got, {"SO-1": ("USD", "customer"), "SO-2": ("EUR", "record"), "PAY-1": ("INR", "company")})
        md = report.to_markdown(rep)
        self.assertIn("100.00 EUR", md)
        self.assertIn("20.00 INR", md)  # payments now show a currency
        self.assertIn("Rows by source: company 1, customer 1, record 1.", md)

    def test_unknown_currency_is_labelled_in_tables(self):
        c = FakeReads({"SalesOrder": [order("SO-1", "2026-10-01")]}, tools={"SalesOrder.list", "Payment.list"})
        md = report.to_markdown(report.build(c, report_date=D, days=7))
        self.assertIn("100.00 currency not recorded", md)
        self.assertIn("Rows by source: not recorded 1.", md)


if __name__ == "__main__":
    unittest.main()
