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


def inv_row(number, outstanding, party="P1", customer="Acme", due="2026-11-01", fixture=False, currency="INR"):
    return {"number": number, "party_id": party, "customer": customer, "due_date": due,
            "outstanding": outstanding, "currency": currency, "fixture": fixture}


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

    def test_supplier_bills_are_not_matchable(self):
        invs = [{"number": "C", "id": "C", "party_id": "P1", "docstatus": 1, "outstanding": 500.0, "direction": "receivable"},
                {"number": "B", "id": "B", "party_id": "P1", "docstatus": 1, "outstanding": 500.0, "direction": "payable"}]
        self.assertEqual([d["number"] for d in matching.invoice_documents(invs)], ["C"])

    def test_same_amount_needs_same_currency(self):
        ctx = {"parties": {}, "companies": {}}
        docs = matching.order_documents([dict(order("usd", 500.0), currency_code="USD"),
                                         dict(order("inr", 500.0), currency_code="INR"),
                                         dict(order("inr-near", 510.0), currency_code="INR")], ctx)
        p = dict(pay_row("PAY1", 500.0), currency="INR")
        m = matching.candidate_matches([p], docs)[0]
        self.assertEqual([(c["number"], c["exact"]) for c in m["candidates"]],
                         [("inr", True), ("inr-near", False), ("usd", False)])  # 500 USD is not "same amount"
        self.assertEqual(m["currency"], "INR")

    def test_documents_take_the_customer_currency(self):
        docs = matching.order_documents([order("A", 10)], {"parties": {"P1": "INR"}, "companies": {}})
        self.assertEqual(docs[0]["currency"], "INR")

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

    def test_reminder_says_partially_paid(self):
        part = dict(inv_row("INV-1", 10.0), amount_paid=90.0, payment_state="partially paid")
        body = drafts.overdue_reminders([part, inv_row("INV-2", 50.0)], {"P1": {"email": "ap@acme.example"}})[0][0]["body_text"]
        self.assertIn("- Invoice INV-1, due 2026-11-01, 10.00 INR outstanding (partially paid: 90.00 INR received, thank you)", body)
        self.assertIn("- Invoice INV-2, due 2026-11-01, 50.00 INR outstanding\n", body)
        self.assertIn("Total outstanding: 60.00 INR.", body)

    def test_payload_is_always_a_draft_with_sender_and_company(self):
        d = {"to": "x@y.example", "subject": "s", "body_text": "b"}
        p = drafts.to_payload(d, MAILBOX)
        self.assertEqual((p["folder"], p["is_draft"]), ("drafts", True))
        # EmailMessage.create requires company_id, from_email and to (schema read 11 Nov)
        self.assertEqual((p["company_id"], p["from_email"], p["to"], p["mailbox_id"]), ("CO", "me@x.example", "x@y.example", "MB"))
        self.assertNotIn("from_name", p)


MAILBOX = {"id": "MB", "company_id": "CO", "email": "me@x.example"}


class Reads:
    def __init__(self, boxes):
        self.boxes, self.calls = boxes, []

    def call(self, name, args):
        self.calls.append(name)
        if name == "Mailbox.list":
            return {"data": self.boxes, "total": len(self.boxes)}
        if name == "Mailbox.get":
            return next(b for b in self.boxes if b["id"] == args["id"])
        raise AssertionError(name)


class DraftsToSave(unittest.TestCase):
    PROP = {"drafts": [{"kind": "accounts_digest", "to": "ar@x.example"},
                       {"kind": "overdue_reminder", "to": "ap@acme.example"},
                       {"kind": "overdue_reminder", "to": drafts.ACCOUNTS_PLACEHOLDER}]}

    def test_all_kinds_skip_drafts_without_recipient(self):
        ready, skipped = drafts.drafts_to_save(self.PROP)
        self.assertEqual([d["kind"] for d in ready], ["accounts_digest", "overdue_reminder"])
        self.assertEqual(skipped, 1)

    def test_only_the_digest_keeps_customer_reminders_out(self):
        ready, skipped = drafts.drafts_to_save(self.PROP, "accounts_digest")
        self.assertEqual([d["to"] for d in ready], ["ar@x.example"])
        self.assertEqual(skipped, 0)


class FindMailbox(unittest.TestCase):
    """The draft mailbox is a Mailbox record (BUG-31-002 fix, 10 Nov); EmailAccount stays empty."""

    def test_single_mailbox(self):
        r = Reads([MAILBOX])
        self.assertEqual(drafts.find_mailbox(r)["id"], "MB")
        self.assertEqual(r.calls, ["Mailbox.list"])

    def test_none(self):
        self.assertIsNone(drafts.find_mailbox(Reads([])))

    def test_default_wins_and_inactive_or_deleted_are_skipped(self):
        boxes = [dict(MAILBOX, id="A"), dict(MAILBOX, id="B", is_default=True), dict(MAILBOX, id="C", is_active=False),
                 dict(MAILBOX, id="D", deleted_at="2026-11-01")]
        self.assertEqual(drafts.find_mailbox(Reads(boxes))["id"], "B")

    def test_several_and_no_default_needs_a_person(self):
        with self.assertRaises(drafts.NoMailbox):
            drafts.find_mailbox(Reads([dict(MAILBOX, id="A"), dict(MAILBOX, id="B")]))

    def test_explicit_id(self):
        r = Reads([dict(MAILBOX, id="A"), dict(MAILBOX, id="B")])
        self.assertEqual(drafts.find_mailbox(r, "B")["id"], "B")
        self.assertEqual(r.calls, ["Mailbox.get"])


ACME = {"P1": {"email": "ap@acme.example"}, "P2": {"email": "ap@beta.example"}}


def _reminder(rows):
    made, _ = drafts.overdue_reminders(rows, ACME)
    return made


class CrossCurrencyReminders(unittest.TestCase):
    """Review of #17: invoices in different currencies are grouped and subtotalled separately,
    never added into one total labelled with the first invoice's currency."""

    def test_two_currencies_are_not_added_together(self):
        d = _reminder([inv_row("INV-1", 100.0, currency="INR"), inv_row("INV-2", 50.0, currency="USD")])[0]
        self.assertNotIn("150.00", d["subject"] + d["body_text"])
        self.assertEqual(d["subject"], "Payment reminder: 2 overdue invoices, 100.00 INR + 50.00 USD")
        self.assertEqual(d["subtotals"], [{"currency": "INR", "outstanding": 100.0},
                                          {"currency": "USD", "outstanding": 50.0}])
        self.assertIn("Subtotal (INR): 100.00 INR", d["body_text"])
        self.assertIn("Subtotal (USD): 50.00 USD", d["body_text"])
        self.assertIn("Total outstanding by currency (not added together): 100.00 INR; 50.00 USD.", d["body_text"])
        self.assertNotIn("Total outstanding: ", d["body_text"])

    def test_each_line_sits_under_its_own_currency_heading(self):
        body = _reminder([inv_row("INV-1", 100.0, currency="USD"), inv_row("INV-2", 25.0, currency="INR"),
                          inv_row("INV-3", 10.0, currency="USD")])[0]["body_text"]
        inr, usd = body.index("Invoices in INR:"), body.index("Invoices in USD:")
        self.assertLess(inr, usd)  # groups A-Z
        self.assertTrue(inr < body.index("INV-2, ") < usd)
        self.assertTrue(usd < body.index("INV-1, ") < body.index("INV-3, "))  # due order kept inside a group
        self.assertIn("Subtotal (USD): 110.00 USD", body)
        self.assertIn("Subtotal (INR): 25.00 INR", body)

    def test_three_invoices_two_currencies_subtotals(self):
        d = _reminder([inv_row("A", 100.0), inv_row("B", 50.0, currency="USD"), inv_row("C", 25.5)])[0]
        self.assertEqual(d["subtotals"], [{"currency": "INR", "outstanding": 125.5},
                                          {"currency": "USD", "outstanding": 50.0}])
        self.assertEqual(d["refs"], ["A", "B", "C"])  # one reminder per customer still

    def test_subtotals_are_rounded_per_currency(self):
        d = _reminder([inv_row("A", 0.1, currency="EUR"), inv_row("B", 0.2, currency="EUR"),
                       inv_row("C", 1.005, currency="USD")])[0]
        self.assertEqual(d["subtotals"][0], {"currency": "EUR", "outstanding": 0.3})

    def test_missing_currency_is_its_own_group_never_guessed(self):
        d = _reminder([inv_row("A", 100.0, currency="INR"), inv_row("B", 40.0, currency=None),
                       inv_row("C", 2.0, currency="  ")])[0]
        self.assertEqual(d["subtotals"], [{"currency": "INR", "outstanding": 100.0},
                                          {"currency": None, "outstanding": 42.0}])
        self.assertIn("Invoices in currency not recorded:", d["body_text"])
        self.assertIn("42.00 (currency not recorded)", d["body_text"])
        self.assertNotIn("140.00", d["body_text"])
        self.assertNotIn("142.00", d["body_text"])

    def test_currency_code_case_and_spaces_do_not_split_a_group(self):
        d = _reminder([inv_row("A", 100.0, currency="inr"), inv_row("B", 50.0, currency=" INR ")])[0]
        self.assertEqual(d["subtotals"], [{"currency": "INR", "outstanding": 150.0}])
        self.assertIn("Total outstanding: 150.00 INR.", d["body_text"])

    def test_single_currency_reminder_is_unchanged(self):
        d = _reminder([inv_row("INV-1", 100.0), inv_row("INV-2", 50.0)])[0]
        self.assertEqual(d["subject"], "Payment reminder: 2 overdue invoices, 150.00 INR")
        self.assertIn("Total outstanding: 150.00 INR.", d["body_text"])
        self.assertNotIn("Subtotal", d["body_text"])

    def test_currencies_are_per_customer(self):
        made = _reminder([inv_row("A", 100.0, currency="INR"),
                          inv_row("B", 50.0, party="P2", customer="Beta", currency="USD")])
        self.assertEqual([m["subtotals"] for m in made], [[{"currency": "INR", "outstanding": 100.0}],
                                                          [{"currency": "USD", "outstanding": 50.0}]])

    def test_by_currency_helper(self):
        groups = drafts.by_currency([inv_row("A", 1.0, currency="USD"), inv_row("B", 2.0, currency=None),
                                     inv_row("C", 3.0, currency="EUR"), inv_row("D", 4.0, currency="USD")])
        self.assertEqual([(c, [r["number"] for r in rows], t) for c, rows, t in groups],
                         [("EUR", ["C"], 3.0), ("USD", ["A", "D"], 5.0), (None, ["B"], 2.0)])


class DraftsMarkdownEscaping(unittest.TestCase):
    """Carried from the #13 review: the matches table escapes customer text."""

    def test_pipe_and_newline_in_customer_keep_the_row(self):
        p = pay_row("PAY|1", 500.0, customer="Acme | North\nDivision")
        prop = {"instance": "t", "report_date": "2026-11-15", "overdue_reminders": "x", "matched_against": "x",
                "match_summary": matching.summary(matching.candidate_matches([p], [])),
                "matches": matching.candidate_matches([p], []), "drafts": [], "skipped": []}
        md = drafts.to_markdown(prop)
        row = next(line for line in md.splitlines() if line.startswith("| PAY"))
        self.assertEqual(row.replace("\\|", "").count("|") - 1, 4)
        self.assertIn("Acme \\| North Division", row)


def order_row(number, total, currency="INR", customer="Acme"):
    return {"number": number, "customer": customer, "order_date": "2026-10-01", "age_days": 45, "invoiced_status": "unbilled",
            "grand_total": total, "currency": currency, "fixture": False}


def full_rep(order_rows=(), inv_rows=(), pay_rows=(), invoices_status="ok"):
    return {"instance": "t", "report_date": "2026-11-15", "days": 7, "sections": {
        "orders_not_invoiced": {"status": "ok", "rows": list(order_rows)},
        "invoices_overdue": {"status": invoices_status, "rows": list(inv_rows)},
        "payments_not_applied": {"status": "ok", "rows": list(pay_rows)}}}


class DigestTables(unittest.TestCase):
    """Instructor answer 3: a short summary, then one table per exception type, saved as a draft only."""

    def digest(self, **kw):
        return drafts.accounts_digest(full_rep(**kw), [])

    def test_three_tables_in_order_with_headers(self):
        d = self.digest(order_rows=[order_row("SO-1", 100.0)],
                        inv_rows=[dict(inv_row("INV-1", 10.0), days_overdue=14, amount_paid=90.0, payment_state="partially paid")],
                        pay_rows=[dict(pay_row("PAY1", 500.0), currency="INR")])
        body = d["body_text"]
        heads = [body.index(h) for h in ("Summary", "1. Orders not invoiced", "2. Invoices overdue (1)", "3. Payments not applied (1)")]
        self.assertEqual(heads, sorted(heads))
        for header in ("Order  ", "Invoice  ", "Payment  "):
            self.assertIn(header, body)
        self.assertIn("- Invoices overdue: 1, 10.00 INR outstanding (1 partially paid)", body)
        self.assertRegex(body, r"INV-1 +Acme +2026-11-01 +14 +10.00 INR +partially paid")
        self.assertEqual(d["subject"], "Order-to-cash exceptions 2026-11-15: 1 orders not invoiced, 1 invoices overdue, 1 payments not applied")
        self.assertEqual(d["refs"], ["SO-1", "INV-1", "PAY1"])
        self.assertEqual(d["status"], "proposed")

    def test_summary_totals_are_per_currency(self):
        d = self.digest(order_rows=[order_row("A", 100.0, "INR"), order_row("B", 50.0, "USD"), order_row("C", 25.0, "INR")])
        self.assertIn("- Orders not invoiced: 3, total 125.00 INR; 50.00 USD", d["body_text"])
        self.assertNotIn("175.00", d["body_text"])

    def test_empty_and_blocked_sections_are_explicit(self):
        body = self.digest(order_rows=[order_row("A", 1.0)], invoices_status="blocked")["body_text"]
        self.assertIn("2. Invoices overdue (not available)", body)
        self.assertIn("Not available: invoice data cannot be read by this login.", body)
        self.assertIn("3. Payments not applied (0)\n\nNone.", body)

    def test_only_invoices_is_still_a_digest(self):
        d = self.digest(inv_rows=[dict(inv_row("INV-1", 10.0), days_overdue=3, payment_state="unpaid")])
        self.assertIsNotNone(d)
        self.assertIn("1. Orders not invoiced more than 7 days after the order date (0)\n\nNone.", d["body_text"])

    def test_columns_line_up_and_long_or_multiline_names_stay_on_one_line(self):
        rows = [order_row("SO-1", 100.0, customer="A very long customer name that keeps going and going Ltd"),
                order_row("SO-22", 5.0, customer="Two\nlines")]
        body = self.digest(order_rows=rows)["body_text"]
        table = body.split("after the order date (2)\n\n")[1].split("\n\nPlease raise")[0].splitlines()
        self.assertEqual(len(table), 4)  # header, rule, two rows: nothing split
        self.assertIn("Two lines", table[3])
        self.assertIn("…", table[2])
        self.assertEqual(table[2].index("100.00 INR") + len("100.00 INR"), table[3].index("5.00 INR") + len("5.00 INR"))  # right-aligned

    def test_text_table(self):
        out = drafts.text_table(["A", "Amount"], [["x", "1.00"], ["longer", "10.00"]], right={1})
        self.assertEqual(out, ["A       Amount", "------  ------", "x         1.00", "longer   10.00"])


class DraftWriterSafety(unittest.TestCase):
    """The writer refuses before any request: the fake client fails the test if it is called."""

    class NoCalls:
        def _rpc(self, *a):
            raise AssertionError("a request was made")

    def setUp(self):
        self.w = drafts.DraftWriter(self.NoCalls(), MAILBOX)

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

    def test_draft_without_sender_or_company_is_refused(self):
        for box in ({"id": "MB", "company_id": "CO"}, {"id": "MB", "email": "me@x.example"}):
            with self.assertRaises(WriteBlocked):
                drafts.DraftWriter(self.NoCalls(), box).create({"to": "x@y.example", "subject": "s", "body_text": "b"})

    def test_draft_without_recipient_is_refused(self):
        with self.assertRaises(WriteBlocked):
            self.w.create({"to": drafts.ACCOUNTS_PLACEHOLDER, "subject": "s", "body_text": "b"})


if __name__ == "__main__":
    unittest.main()
