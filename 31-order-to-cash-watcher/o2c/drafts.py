"""Reminder drafts for a person to review and send. The agent never sends.

    python -m o2c.drafts --instance suryodaya --out reports/            # propose: writes a review file, changes nothing
    python -m o2c.drafts --instance suryodaya --out reports/ --create --mailbox-id <id>
                                                                        # a person approves, then drafts are saved in their mailbox

Two kinds of draft:
- `accounts_digest`: one internal note to accounts listing orders not invoiced and payments
  not applied, with candidate matches for each payment.
- `overdue_reminder`: one polite reminder per customer with overdue invoices. It waits for
  Invoice.list (BUG-31-001); until then none are proposed.

Safety: DraftWriter can call exactly one tool, EmailMessage.create, and only with
folder="drafts" and is_draft=true. It never updates, deletes or sends. Every send tool
(endpoint.email.messages.send, EmailMessage.send_email, EmailMessage.record_sent,
EmailCampaign.send) is refused before a request is made.
"""
import argparse
import json
import os
from datetime import date
from pathlib import Path

from . import matching, report
from .client import Client, McpError, WriteBlocked

DRAFT_TOOL = "EmailMessage.create"
ACCOUNTS_PLACEHOLDER = "(accounts address: a person fills this in)"


def _money(v, currency=None):
    return f"{v:,.2f}{' ' + currency if currency else ''}" if isinstance(v, (int, float)) else ""


def accounts_digest(rep, matches, accounts_email=None):
    """One internal note covering sections 1 and 3. Returns None if there is nothing to say."""
    orders = rep["sections"]["orders_not_invoiced"]
    payments = rep["sections"]["payments_not_applied"]
    order_rows = orders["rows"] if orders["status"] == "ok" else []
    pay_rows = payments["rows"] if payments["status"] == "ok" else []
    if not order_rows and not pay_rows:
        return None
    by_payment = {m["payment"]: m for m in matches}
    lines = [
        "Hello,",
        "",
        f"This is the order-to-cash exception list for {rep.get('instance') or 'our company'} on {rep['report_date']}. "
        "Please check the items below. Nothing has been changed in the system.",
        "",
    ]
    if order_rows:
        lines += [f"Orders not invoiced more than {rep['days']} days after the order date ({len(order_rows)}):", ""]
        for r in order_rows:
            lines.append(f"- {r['number']}, {r['customer'] or 'unknown customer'}, ordered {r['order_date']} "
                         f"({r['age_days']} days), {r['invoiced_status']}, {_money(r['grand_total'], r['currency'])}"
                         f"{' [test data]' if r['fixture'] else ''}")
        lines += ["", "Please raise the invoice, or reply with the reason it is on hold.", ""]
    if pay_rows:
        lines += [f"Payments received but not applied to an invoice ({len(pay_rows)}):", ""]
        for r in pay_rows:
            m = by_payment.get(r["number"]) or {}
            cands = m.get("candidates") or []
            hint = ("; possible match: " + ", ".join(
                f"{c['kind']} {c['number']} ({_money(c['amount'])}{', same amount' if c['exact'] else ''})" for c in cands)
                    ) if cands else "; no candidate found"
            lines.append(f"- {r['number']}, {r['customer'] or 'unknown customer'}, received {r['payment_date'] or '?'}, "
                         f"{_money(r['unallocated'])} unallocated, {r['status']}{hint}{' [test data]' if r['fixture'] else ''}")
        lines += ["", "Please apply each payment to the right invoice. The matches are suggestions only.", ""]
    lines += ["Thank you."]
    return {
        "kind": "accounts_digest",
        "to": accounts_email or ACCOUNTS_PLACEHOLDER,
        "subject": f"Order-to-cash exceptions {rep['report_date']}: {len(order_rows)} orders not invoiced, "
                   f"{len(pay_rows)} payments not applied",
        "body_text": "\n".join(lines),
        "refs": [r["number"] for r in order_rows] + [r["number"] for r in pay_rows],
        "fixture": False,
        "status": "proposed",
    }


def overdue_reminders(invoice_rows, parties_by_id):
    """One reminder per customer with overdue invoices. Customers with no email are returned
    as skipped, so a person can follow up another way."""
    by_party = {}
    for r in invoice_rows:
        by_party.setdefault(r.get("party_id"), []).append(r)
    drafts, skipped = [], []
    for party_id, rows in sorted(by_party.items(), key=lambda kv: kv[1][0]["customer"] or ""):
        party = parties_by_id.get(party_id) or {}
        email = party.get("email")
        customer = rows[0]["customer"] or party.get("name") or "Customer"
        if not email:
            skipped.append({"customer": customer, "invoices": [r["number"] for r in rows], "reason": "no email on the customer record"})
            continue
        total = round(sum(r["outstanding"] for r in rows), 2)
        currency = rows[0].get("currency")
        lines = [f"Dear {customer},", "",
                 "Our records show the following invoice(s) past their due date with a balance outstanding:", ""]
        for r in rows:
            lines.append(f"- Invoice {r['number']}, due {r['due_date']}, {_money(r['outstanding'], r.get('currency'))} outstanding")
        lines += ["", f"Total outstanding: {_money(total, currency)}.", "",
                  "If you have already paid, please send us the payment details so we can apply it, and accept our thanks. "
                  "Otherwise we would be grateful for payment at your earliest convenience.", "", "Kind regards,"]
        drafts.append({
            "kind": "overdue_reminder",
            "to": email,
            "subject": f"Payment reminder: {len(rows)} overdue invoice{'s' if len(rows) > 1 else ''}, {_money(total, currency)}",
            "body_text": "\n".join(lines),
            "refs": [r["number"] for r in rows],
            "fixture": any(r["fixture"] for r in rows),
            "status": "proposed",
        })
    return drafts, skipped


def to_payload(draft, mailbox_id, company_id):
    """EmailMessage.create arguments for a draft. Always a draft, never sent."""
    return {
        "company_id": company_id,
        "mailbox_id": mailbox_id,
        "to": draft["to"],
        "subject": draft["subject"],
        "body_text": draft["body_text"],
        "folder": "drafts",
        "is_draft": True,
    }


class DraftWriter:
    """The only code in seat 31 that may write. It creates drafts and nothing else."""

    def __init__(self, client, mailbox_id, company_id):
        self.client, self.mailbox_id, self.company_id = client, mailbox_id, company_id

    def call(self, name, args):
        if name != DRAFT_TOOL:
            raise WriteBlocked(f"{name} refused: the draft writer can only call {DRAFT_TOOL}")
        if args.get("folder") != "drafts" or args.get("is_draft") is not True:
            raise WriteBlocked("refused: a message must be created as a draft (folder=drafts, is_draft=true)")
        if not args.get("to") or args["to"] == ACCOUNTS_PLACEHOLDER:
            raise WriteBlocked("refused: the draft has no recipient yet; a person must fill it in")
        result = self.client._rpc("tools/call", {"name": name, "arguments": args})
        if result.get("isError"):
            raise McpError(result["content"][0]["text"])
        return result.get("structuredContent") or json.loads(result["content"][0]["text"])

    def create(self, draft):
        return self.call(DRAFT_TOOL, to_payload(draft, self.mailbox_id, self.company_id))


def propose(client, report_date=None, days=7, instance=None, accounts_email=None):
    """Read-only: build the report, the matches and the proposed drafts."""
    rep = report.build(client, report_date=report_date, days=days, instance=instance)
    inv = rep["sections"]["invoices_overdue"]
    pay_rows = rep["sections"]["payments_not_applied"]["rows"]
    if inv["status"] == "ok":
        docs = matching.invoice_documents(client.list_all("Invoice", {"docstatus": 1}))
    else:
        docs = matching.order_documents(client.list_all("SalesOrder", {"docstatus": 1}))
    matches = matching.candidate_matches(pay_rows, docs)
    drafts, skipped = [], []
    digest = accounts_digest(rep, matches, accounts_email)
    if digest:
        drafts.append(digest)
    if inv["status"] == "ok" and inv["rows"]:
        parties = {p["id"]: p for p in client.list_all("Party")}
        reminders, skipped = overdue_reminders(inv["rows"], parties)
        drafts += reminders
    return {
        "instance": instance,
        "report_date": rep["report_date"],
        "days": days,
        "matched_against": "invoices" if inv["status"] == "ok" else "sales orders (invoices blocked, BUG-31-001)",
        "match_summary": matching.summary(matches),
        "matches": matches,
        "overdue_reminders": "ok" if inv["status"] == "ok" else f"waiting: {inv['status']} (BUG-31-001)",
        "drafts": drafts,
        "skipped": skipped,
    }


def to_markdown(prop):
    s = prop["match_summary"]
    lines = [
        f"# Reminder drafts for review: {prop.get('instance') or ''} {prop['report_date']}",
        "",
        "Proposed only. Nothing has been created or sent. A person reviews each draft; "
        "`--create` saves approved drafts in their mailbox as drafts, still unsent.",
        "",
        f"Overdue-invoice reminders: {prop['overdue_reminders']}.",
        "",
        f"## Payment matches ({s['payments']} payments; {s['with_candidates']} with a candidate; "
        f"{s['with_exact_match']} with the same amount)",
        "",
        f"Matched against {prop['matched_against']}. Suggestions only; the agent never allocates a payment.",
        "",
    ]
    if prop["matches"]:
        lines += ["| Payment | Customer | Unallocated | Candidates |", "|---|---|---:|---|"]
        for m in prop["matches"]:
            cands = ", ".join(f"{c['kind']} {c['number']} {_money(c['amount'])}{' (same amount)' if c['exact'] else ''}"
                              for c in m["candidates"]) or "none"
            lines.append(f"| {m['payment']} | {m['customer'] or ''} | {_money(m['unallocated'])} | {cands} |")
        lines.append("")
    lines += [f"## Drafts ({len(prop['drafts'])})", ""]
    for i, d in enumerate(prop["drafts"], 1):
        lines += [f"### {i}. {d['kind']}{' (test data)' if d['fixture'] else ''}", "",
                  f"**To:** {d['to']}  ", f"**Subject:** {d['subject']}", "", "```text", d["body_text"], "```", ""]
    if prop["skipped"]:
        lines += [f"## Not drafted ({len(prop['skipped'])})", ""]
        for k in prop["skipped"]:
            lines.append(f"- {k['customer']}: {', '.join(k['invoices'])}: {k['reason']}")
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(prog="o2c.drafts", description="Propose reminder drafts (never sends)")
    ap.add_argument("--days", type=int, default=int(os.environ.get("O2C_DAYS", 7)))
    ap.add_argument("--date", type=date.fromisoformat)
    ap.add_argument("--instance", default=os.environ.get("AGENTSWITCH_INSTANCE"))
    ap.add_argument("--out", type=Path, required=True, help="folder for <instance>-<date>-drafts.md/.json (gitignored)")
    ap.add_argument("--accounts-email", default=os.environ.get("O2C_ACCOUNTS_EMAIL"))
    ap.add_argument("--create", action="store_true", help="after a person confirms, save the drafts in the mailbox (never sends)")
    ap.add_argument("--mailbox-id", default=os.environ.get("O2C_MAILBOX_ID"))
    args = ap.parse_args()

    client = Client()
    prop = propose(client, report_date=args.date, days=args.days, instance=args.instance, accounts_email=args.accounts_email)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / f"{args.instance or 'report'}-{prop['report_date']}-drafts"
    stem.with_suffix(".json").write_text(json.dumps(prop, indent=2))
    stem.with_suffix(".md").write_text(to_markdown(prop))
    s = prop["match_summary"]
    print(f"wrote {stem}.md ({len(prop['drafts'])} drafts proposed; {s['with_candidates']}/{s['payments']} payments with a candidate)")

    if not args.create:
        return
    if not args.mailbox_id:
        raise SystemExit("--create needs --mailbox-id (or O2C_MAILBOX_ID): a mailbox this login owns")
    mailbox = client.call("EmailAccount.get", {"id": args.mailbox_id})
    writer = DraftWriter(client, args.mailbox_id, mailbox.get("company_id"))
    ready = [d for d in prop["drafts"] if d["to"] != ACCOUNTS_PLACEHOLDER]
    print(f"About to save {len(ready)} draft(s) in mailbox {args.mailbox_id}. They stay unsent.")
    if input("Type 'save drafts' to confirm: ").strip() != "save drafts":
        raise SystemExit("not confirmed; nothing created")
    for d in ready:
        created = writer.create(d)
        print(f"saved draft {created.get('id')}: {d['subject']}")


if __name__ == "__main__":
    main()
