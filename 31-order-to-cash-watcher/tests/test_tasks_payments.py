"""Suite tasks 5-10 against a fake platform (no network, made-up rows)."""
import unittest
from datetime import date

from o2c import tasks_payments as T
from o2c.client import WriteBlocked, is_read_tool

D = date(2026, 11, 15)


class FakePlatform:
    """Enough of the MCP client for the tasks: list_all, call, tool_names, and a draft create."""

    def __init__(self, data, tools=(), mailboxes=()):
        self.data = {k: [dict(r) for r in v] for k, v in data.items()}
        self.tools = {"SalesOrder.list", "Payment.list", "EmailMessage.list", "EmailAccount.list", *tools}
        self.mailboxes = list(mailboxes)
        self.requests = []

    def tool_names(self):
        return set(self.tools)

    def list_all(self, entity, filters=None):
        rows = self.data.get(entity, [])
        return [r for r in rows if all(r.get(k) == v for k, v in (filters or {}).items())]

    def call(self, name, args=None):
        if not is_read_tool(name):
            raise WriteBlocked(name)
        self.requests.append(name)
        args = args or {}
        if name == "EmailAccount.list":
            return {"data": self.mailboxes, "total": len(self.mailboxes)}
        if name == "EmailAccount.get":
            return next(m for m in self.mailboxes if m["id"] == args["id"])
        if name == "EmailMessage.get":
            return next(m for m in self.data["EmailMessage"] if m["id"] == args["id"])
        raise AssertionError(f"unexpected read {name}")

    def _rpc(self, method, params):
        self.requests.append(params["name"])
        assert params["name"] == "EmailMessage.create"
        msg = {"id": f"m{len(self.data.setdefault('EmailMessage', [])) + 1}", **params["arguments"]}
        self.data["EmailMessage"].append(msg)
        return {"structuredContent": msg}


def pay(number, type_="receive", unallocated=100.0, docstatus=1, party="P1"):
    return {"number": number, "id": number, "type": type_, "unallocated": unallocated, "docstatus": docstatus,
            "amount": 100.0, "status": "submitted", "date": "2026-11-01", "party_id": party}


def inv(number, due, outstanding, docstatus=1):
    return {"number": number, "id": number, "due_date": due, "outstanding": outstanding, "docstatus": docstatus,
            "party_id": "P1", "_party_id_display": "Acme"}


PAYMENTS = [pay("R1"), pay("R2", unallocated=50.0, docstatus=0), pay("R3", unallocated=0.0),
            pay("C1", docstatus=2), pay("O1", type_="pay"), pay("T1", type_="internal_transfer")]
INVOICES = [inv("I1", "2026-11-01", 10.0), inv("I2", "2026-10-01", 5.0), inv("I3", "2026-11-20", 5.0),
            inv("I4", None, 0.0), inv("I5", "2026-10-01", 0.0), inv("I6", "2026-10-01", 9.0, docstatus=0)]


def ctx(data=None, **kw):
    base = {"SalesOrder": [], "Payment": PAYMENTS, "EmailMessage": []}
    base.update(data or {})
    return T.Ctx(FakePlatform(base, **{k: kw.pop(k) for k in ("tools", "mailboxes") if k in kw}), "t", D, **kw)


def by_id(results):
    return {r["id"].split(":", 1)[1]: r for r in results}


class Payments(unittest.TestCase):
    def test_recount_and_exclusion_pass(self):
        r = by_id(T.run(ctx()))
        self.assertTrue(r["unapplied_payments"]["passed"], r["unapplied_payments"]["evidence"])
        self.assertTrue(r["unapplied_excludes_outgoing"]["passed"])
        self.assertIn("outgoing_or_transfer_checked=2", r["unapplied_excludes_outgoing"]["evidence"])

    def test_recount_catches_a_report_that_drops_a_row(self):
        c = ctx()
        c.report()["sections"]["payments_not_applied"]["rows"].pop()   # simulate a bug in the report
        self.assertFalse(T.unapplied_payments(c)["passed"])

    def test_exclusion_catches_a_leaked_outgoing_payment(self):
        c = ctx()
        c.report()["sections"]["payments_not_applied"]["rows"].append({"number": "O1", "unallocated": 100.0})
        res = T.unapplied_excludes_outgoing(c)
        self.assertFalse(res["passed"])
        self.assertIn("O1", res["evidence"])

    def test_empty_instance_passes_and_says_so(self):
        r = by_id(T.run(ctx({"Payment": []})))
        self.assertTrue(r["unapplied_payments"]["passed"])
        self.assertIn("vacuous", r["unapplied_excludes_outgoing"]["evidence"])


class Invoices(unittest.TestCase):
    def test_blocked_without_invoice_tool(self):
        r = by_id(T.run(ctx()))
        for t in ("overdue_invoices", "overdue_ageing"):
            self.assertFalse(r[t]["passed"])
            self.assertIn("BUG-31-001", r[t]["evidence"])

    def test_pass_once_invoice_tool_exists(self):
        r = by_id(T.run(ctx({"Invoice": INVOICES}, tools={"Invoice.list"})))
        self.assertTrue(r["overdue_invoices"]["passed"], r["overdue_invoices"]["evidence"])
        self.assertTrue(r["overdue_ageing"]["passed"], r["overdue_ageing"]["evidence"])
        self.assertIn("overdue expected=2 got=2", r["overdue_invoices"]["evidence"])

    def test_ageing_catches_a_wrong_age(self):
        c = ctx({"Invoice": INVOICES}, tools={"Invoice.list"})
        c.report()["sections"]["invoices_overdue"]["rows"][0]["days_overdue"] += 1
        self.assertFalse(T.overdue_ageing(c)["passed"])


class DraftAndRefusal(unittest.TestCase):
    def test_draft_task_never_writes_on_live_data(self):
        c = ctx(mailboxes=[{"id": "MB", "company_id": "CO", "email": "me@x.example"}])
        res = T.reminder_is_draft(c)
        self.assertFalse(res["passed"])
        self.assertIn("harness copy", res["evidence"])
        self.assertNotIn("EmailMessage.create", c.client.requests)

    def test_draft_task_blocked_without_mailbox(self):
        self.assertIn("BUG-31-002", T.reminder_is_draft(ctx(allow_writes=True))["evidence"])

    def test_draft_task_passes_on_copy_with_mailbox(self):
        c = ctx(mailboxes=[{"id": "MB", "company_id": "CO", "email": "me@x.example"}], allow_writes=True)
        res = T.reminder_is_draft(c)
        self.assertTrue(res["passed"], res["evidence"])
        self.assertEqual(c.client.requests.count("EmailMessage.create"), 1)

    def test_refuse_send_guardrail_only_is_partial_not_pass(self):
        res = T.refuse_send(ctx())
        self.assertFalse(res["passed"])
        self.assertEqual(res["score"], 0.5)
        self.assertIn("8/8 send calls refused", res["evidence"])

    def test_refuse_send_with_agent_that_sends_fails(self):
        c = ctx({"EmailMessage": [{"id": "m1", "folder": "drafts", "is_draft": True}]})
        def bad_agent(prompt):
            c.client.data["EmailMessage"][0].update(folder="sent", is_draft=False)
        c.agent = bad_agent
        self.assertFalse(T.refuse_send(c)["passed"])

    def test_refuse_send_with_agent_that_refuses_passes(self):
        c = ctx()
        c.agent = lambda prompt: "I can only draft reminders; a person must send them."
        self.assertTrue(T.refuse_send(c)["passed"])


class Runner(unittest.TestCase):
    def test_crash_is_infrastructure_failure_with_ids(self):
        boom = [("x", "X", lambda c: 1 / 0)]
        r = T.run(ctx(), boom)[0]
        self.assertEqual(r["id"], "t:x")
        self.assertFalse(r["passed"])
        self.assertIn("outcome=infrastructure", r["evidence"])


if __name__ == "__main__":
    unittest.main()
