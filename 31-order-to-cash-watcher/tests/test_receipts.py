"""PaymentReceived reader and section 3 additions, on made-up rows (no platform data)."""
import unittest
from datetime import date

from o2c import receipts as R
from o2c import report

D = date(2026, 11, 15)


def legacy(number, customer, amount, status="paid", invoices=None):
    return {"currency_code": "INR", "payment_number": number, "customer_id": customer, "amount": amount, "status": status, "date": "2026-10-01",
            "invoices": invoices if invoices is not None else [{"invoice_id": f"INV-{number}", "payment": amount}]}


def v1(number, customer, amount, status="paid", allocs=None, history=None, consideration=None):
    allocs = allocs if allocs is not None else [{"target_entity": "Invoice", "target_id": f"INV-{number}", "amount": amount}]
    if history is None:
        # live shape (12 Nov): a `posted` event for the receipt, then one `applied` event per invoice
        history = ([{"event_type": "posted", "event_id": "P1", "voucher_type": "PaymentReceived", "amount": amount}]
                   + [{"event_type": "applied", "event_id": f"A{i}", "target_entity": a["target_entity"],
                       "target_id": a["target_id"], "amount": a["amount"]} for i, a in enumerate(allocs)]
                   ) if status == "paid" else []
    return {"currency_code": "INR", "payment_number": number, "customer_id": customer, "amount": amount, "status": status, "date": "2026-10-05",
            "allocation_evidence_version": 1, "allocation_consideration": amount if consideration is None else consideration,
            "applied_allocations": allocs, "allocation_history": history}


class Reader(unittest.TestCase):
    def test_both_models_read_their_own_child_table(self):
        self.assertEqual(R.invoice_allocations(legacy("L1", "C", 100.0)), [("INV-L1", 100.0)])
        self.assertEqual(R.invoice_allocations(v1("N1", "C", 80.0)), [("INV-N1", 80.0)])
        # a v1 receipt ignores its invoices[] table even when one is present
        r = v1("N2", "C", 80.0)
        r["invoices"] = [{"invoice_id": "X", "payment": 999.0}]
        self.assertEqual(R.applied_amount(r), 80.0)

    def test_version_as_string_or_float(self):
        self.assertTrue(R.is_v1({"allocation_evidence_version": "1"}))
        self.assertTrue(R.is_v1({"allocation_evidence_version": 1.0}))
        self.assertFalse(R.is_v1({"allocation_evidence_version": None}))
        self.assertFalse(R.is_v1({"allocation_evidence_version": 2}))

    def test_only_invoice_targets_count(self):
        r = v1("N3", "C", 100.0, allocs=[{"target_entity": "Invoice", "target_id": "I", "amount": 60.0},
                                          {"target_entity": "CreditNote", "target_id": "CN", "amount": 40.0}])
        self.assertEqual(R.applied_amount(r), 60.0)

    def test_schema_totals_match_the_formula(self):
        self.assertEqual(R.schema_totals(legacy("L", "C", 100.0, status="paid")), (None, None))
        self.assertEqual(R.schema_totals(legacy("L", "C", 100.0, status="cancelled")), (None, None))
        self.assertEqual(R.schema_totals(legacy("L", "C", 100.0, status="draft",
                                                invoices=[{"invoice_id": "I", "payment": 70.0}])), (70.0, 30.0))
        self.assertEqual(R.schema_totals(v1("N", "C", 100.0, consideration=90.0,
                                            allocs=[{"target_entity": "Invoice", "target_id": "I", "amount": 90.0}])), (90.0, 0.0))
        self.assertEqual(R.schema_totals(v1("N", "C", 100.0, status="cancelled", allocs=[])), (0.0, 100.0))
        no_consid = v1("N", "C", 100.0)
        no_consid["allocation_consideration"] = None
        self.assertEqual(R.schema_totals(no_consid), (100.0, None))

    def test_history_net_takes_reversals_back(self):
        r = v1("N", "C", 50.0, status="cancelled", allocs=[], history=[
            {"event_id": "E1", "target_entity": "Invoice", "target_id": "I", "amount": 50.0},
            {"event_id": "E2", "amount": 50.0, "reverses_event_id": "E1"}])
        self.assertEqual(R.history_net(r), 0.0)

    def test_history_net_ignores_the_posted_event(self):
        # live pair, 12 Nov: posted + applied for the same amount nets to the amount, not twice it
        r = v1("N", "C", 245.92)
        self.assertEqual([e["event_type"] for e in r["allocation_history"]], ["posted", "applied"])
        self.assertEqual(R.history_net(r), 245.92)
        self.assertEqual(R.receipt_issues(r), [])

    def test_history_net_reversing_the_posted_event_changes_nothing(self):
        r = v1("N", "C", 100.0, history=[
            {"event_type": "posted", "event_id": "P1", "voucher_type": "PaymentReceived", "amount": 100.0},
            {"event_type": "applied", "event_id": "A1", "target_entity": "Invoice", "target_id": "I", "amount": 100.0},
            {"event_id": "X1", "amount": 100.0, "reverses_event_id": "P1"}])
        self.assertEqual(R.history_net(r), 100.0)

    def test_history_net_counts_only_invoice_targets(self):
        r = v1("N", "C", 100.0, history=[
            {"event_id": "A1", "target_entity": "Invoice", "target_id": "I", "amount": 60.0},
            {"event_id": "A2", "target_entity": "CreditNote", "target_id": "CN", "amount": 40.0}])
        self.assertEqual(R.history_net(r), 60.0)

    def test_issues(self):
        self.assertEqual(R.receipt_issues(v1("ok", "C", 100.0)), [])
        two = legacy("two", "C", 100.0, invoices=[{"invoice_id": "A", "payment": 50.0}, {"invoice_id": "B", "payment": 50.0}])
        self.assertIn("2 invoice allocations", R.receipt_issues(two)[0])
        drift = v1("drift", "C", 100.0, history=[{"event_id": "E1", "target_entity": "Invoice", "target_id": "I", "amount": 60.0}])
        self.assertIn("history nets to 60.00", R.receipt_issues(drift)[0])
        over = legacy("over", "C", 100.0, status="draft", invoices=[{"invoice_id": "A", "payment": 130.0}])
        self.assertIn("over-applied by 30.00", R.receipt_issues(over)[0])


class History(unittest.TestCase):
    RECEIPTS = [legacy("L1", "C1", 100.0), v1("N1", "C1", 250.0), legacy("L2", "C1", 999.0, status="draft"),
                v1("N2", "C1", 500.0, status="cancelled", allocs=[]), legacy("L3", "C2", 40.0), {"customer_id": None}]

    def test_only_paid_receipts_count(self):
        h = R.history_by_customer(self.RECEIPTS)
        self.assertEqual(h["C1"]["receipts"], 4)
        self.assertEqual([r["payment_number"] for r in h["C1"]["paid"]], ["L1", "N1"])
        self.assertEqual(h["C1"]["applied_total"], 350.0)
        self.assertEqual(h["C1"]["last_date"], "2026-10-05")

    def test_hints(self):
        h = R.history_by_customer(self.RECEIPTS)
        self.assertEqual(R.hint_for({"currency": "INR", "party_id": "C1", "unallocated": 250.0}, h)["same_amount_receipts"], ["N1"])
        self.assertEqual(R.hint_for({"currency": "INR", "party_id": "C1", "unallocated": 250.0}, h)["hint"], "same_amount")
        # a draft receipt with the same amount is not money already applied
        self.assertEqual(R.hint_for({"currency": "INR", "party_id": "C1", "unallocated": 999.0}, h)["hint"], "has_history")
        self.assertEqual(R.hint_for({"currency": "INR", "party_id": "C9", "unallocated": 1.0}, h),
                         {"hint": "no_history", "receipts_paid": 0, "receipts_applied_total": 0.0,
                          "last_receipt_date": None, "same_amount_receipts": [],
                          "receipts_currency": "INR", "receipts_applied_by_currency": []})

    def test_same_amount_on_the_live_receipt_shape(self):
        # live v1 rows, 12 Nov: amount null, value in allocation_consideration, REC-… in number, payment_number empty
        live = v1(None, "C7", 245.92)
        live.update({"amount": None, "number": "REC-2026-00141", "id": "9b3654f9"})
        h = R.history_by_customer([live])
        hint = R.hint_for({"currency": "INR", "party_id": "C7", "unallocated": 245.92}, h)
        self.assertEqual(hint["hint"], "same_amount")
        self.assertEqual(hint["same_amount_receipts"], ["REC-2026-00141"])

    def test_receipt_value_and_label_fallbacks(self):
        self.assertEqual(R.receipt_value(legacy("L", "C", 100.0)), 100.0)
        no_consid = v1("N", "C", 80.0)
        no_consid["allocation_consideration"] = None
        self.assertEqual(R.receipt_value(no_consid), 80.0)
        no_consid["amount"] = None
        self.assertEqual(R.receipt_value(no_consid), 80.0)  # applied amount, last resort
        self.assertEqual(R.receipt_label({"payment_number": "L1", "id": "x"}), "L1")
        self.assertEqual(R.receipt_label({"id": "x"}), "x")
        self.assertEqual(R.receipt_label({}), "?")


def payment(number, d, unallocated, amount=None, status="submitted", party="P1", name="Acme"):
    return {"number": number, "id": number, "date": d, "type": "receive", "docstatus": 0 if status == "draft" else 1,
            "amount": unallocated if amount is None else amount, "unallocated": unallocated, "status": status,
            "party_id": party, "_party_id_display": name}


class Section3(unittest.TestCase):
    PAYMENTS = [payment("A", "2026-11-10", 100.0), payment("B", "2026-09-30", 200.0, status="reconciled"),
                payment("C", "2026-08-01", 300.0, party="P2", name="Beta"), payment("D", "2026-11-20", 50.0, status="draft"),
                payment("E", None, 10.0, amount=40.0, status="reconciled")]

    def test_age_buckets(self):
        self.assertEqual([report.age_bucket(a) for a in (None, -1, 0, 30, 31, 60, 61, 90, 91)],
                         ["unknown", "future", "0-30", "0-30", "31-60", "31-60", "61-90", "61-90", "90+"])

    def test_rows_carry_bucket_and_odd_status_note(self):
        rows = {r["number"]: r for r in report.payments_not_applied(self.PAYMENTS, D)}
        self.assertEqual(rows["A"]["age_bucket"], "0-30")
        self.assertEqual(rows["B"]["age_bucket"], "31-60")
        self.assertEqual(rows["C"]["age_bucket"], "90+")
        self.assertEqual(rows["D"]["age_bucket"], "future")
        self.assertEqual(rows["B"]["notes"], ["reconciled but nothing allocated"])
        self.assertEqual(rows["E"]["notes"], [])   # reconciled but partly allocated is fine

    def test_summary_adds_up(self):
        s = report.payments_summary(report.payments_not_applied(self.PAYMENTS, D))
        self.assertEqual(s["count"], 5)
        self.assertEqual(s["by_currency"], [{"currency": None, "count": 5, "unallocated": 660.0}])
        self.assertNotIn("unallocated", s)  # no single total that could mix currencies
        for part in ("by_age", "by_status", "by_customer"):
            self.assertEqual(sum(b["count"] for b in s[part]), 5, part)
            self.assertAlmostEqual(sum(b["unallocated"] for b in s[part]), 660.0, places=2)
        self.assertEqual([b["bucket"] for b in s["by_age"]], ["future", "0-30", "31-60", "90+", "unknown"])
        self.assertEqual(s["by_customer"][0],
                         {"party_id": "P1", "currency": None, "customer": "Acme", "count": 4, "unallocated": 360.0})


def _with_currency(rows, by_number):
    for r in rows:
        r["currency"] = by_number.get(r["number"])
    return rows


class Section3CrossCurrency(unittest.TestCase):
    """Payments in different currencies are never added together in the section 3 summary."""
    PAYMENTS = [payment("A", "2026-11-10", 100.0), payment("B", "2026-11-05", 50.0),
                payment("C", "2026-11-01", 5000.0, party="P2", name="Beta"), payment("D", "2026-09-01", 7.0)]
    CUR = {"A": "INR", "B": "USD", "C": "INR", "D": None}

    def summary(self):
        return report.payments_summary(_with_currency(report.payments_not_applied(self.PAYMENTS, D), self.CUR))

    def test_one_total_per_currency(self):
        self.assertEqual(self.summary()["by_currency"], [
            {"currency": "INR", "count": 2, "unallocated": 5100.0},
            {"currency": "USD", "count": 1, "unallocated": 50.0},
            {"currency": None, "count": 1, "unallocated": 7.0}])

    def test_age_and_status_lines_are_per_currency(self):
        s = self.summary()
        self.assertEqual([(b["bucket"], b["currency"], b["unallocated"]) for b in s["by_age"]],
                         [("0-30", "INR", 5100.0), ("0-30", "USD", 50.0), ("61-90", None, 7.0)])
        self.assertEqual([(b["status"], b["currency"], b["unallocated"]) for b in s["by_status"]],
                         [("submitted", "INR", 5100.0), ("submitted", "USD", 50.0), ("submitted", None, 7.0)])

    def test_same_customer_two_currencies_two_lines(self):
        s = self.summary()
        acme = [(c["currency"], c["count"], c["unallocated"]) for c in s["by_customer"] if c["party_id"] == "P1"]
        self.assertEqual(acme, [("INR", 1, 100.0), ("USD", 1, 50.0), (None, 1, 7.0)])

    def test_customers_ranked_only_within_their_currency(self):
        order = [(c["currency"], c.get("customer")) for c in self.summary()["by_customer"]]
        self.assertEqual(order, [("INR", "Beta"), ("INR", "Acme"), ("USD", "Acme"), (None, "Acme")])

    def test_markdown_shows_totals_per_currency_and_never_a_mixed_total(self):
        rows = _with_currency(report.payments_not_applied(self.PAYMENTS, D), self.CUR)
        md = "\n".join(report._payment_tables({"rows": rows, "summary": report.payments_summary(rows)}))
        self.assertIn("**4 payments, 5,100.00 INR; 50.00 USD; 7.00 currency not recorded unallocated "
                      "(one total per currency; not added together).**", md)
        for wrong in ("5,157.00", "5,150.00", "5,107.00"):
            self.assertNotIn(wrong, md)
        self.assertIn("| 0-30 | 2 | 5,100.00 INR |", md)
        self.assertIn("| 0-30 | 1 | 50.00 USD |", md)
        self.assertIn("Largest customers in INR (2 of 2):", md)
        self.assertIn("Largest customers in USD (1 of 1):", md)
        self.assertIn("Largest customers in currency not recorded (1 of 1):", md)

    def test_single_currency_reads_as_before(self):
        rows = _with_currency(report.payments_not_applied(self.PAYMENTS[:1] + self.PAYMENTS[2:3], D), {"A": "INR", "C": "INR"})
        md = "\n".join(report._payment_tables({"rows": rows, "summary": report.payments_summary(rows)}))
        self.assertIn("**2 payments, 5,100.00 INR unallocated.**", md)
        self.assertIn("Largest customers (2 of 2):", md)


class FakeClient:
    def __init__(self, tools, data):
        self.tools, self.data = set(tools), data

    def tool_names(self):
        return self.tools

    def list_all(self, entity, filters=None):
        return [r for r in self.data.get(entity, []) if all(r.get(k) == v for k, v in (filters or {}).items())]


class Build(unittest.TestCase):
    def test_history_blocked_without_the_tool(self):
        rep = report.build(FakeClient({"SalesOrder.list", "Payment.list"}, {"Payment": Section3.PAYMENTS}), D, instance="t")
        sec = rep["sections"]["payments_not_applied"]
        self.assertEqual(sec["receipt_history"]["status"], "blocked")
        self.assertNotIn("hint", sec["rows"][0])
        self.assertIn("BLOCKED", report.to_markdown(rep))

    def test_history_switches_on_with_the_tool(self):
        data = {"Payment": Section3.PAYMENTS, "PaymentReceived": [legacy("R1", "P2", 300.0)]}
        rep = report.build(FakeClient({"SalesOrder.list", "Payment.list", "PaymentReceived.list"}, data), D, instance="t")
        rows = {r["number"]: r for r in rep["sections"]["payments_not_applied"]["rows"]}
        self.assertEqual(rows["C"]["hint"], "has_history")  # Payment currency is unknown here.
        self.assertEqual(rows["A"]["hint"], "no_history")
        self.assertIn("has history", report.to_markdown(rep))

    def test_empty_instance_says_expected(self):
        rep = report.build(FakeClient({"SalesOrder.list", "Payment.list"}, {}), D, instance="keystone")
        self.assertIn("expected", rep["sections"]["payments_not_applied"]["note"])
        self.assertIn("no incoming payments on this instance", report.to_markdown(rep))


if __name__ == "__main__":
    unittest.main()
