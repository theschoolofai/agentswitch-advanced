"""Reminder drafts for a person to review and send. The agent never sends.

    python -m o2c.drafts --instance suryodaya --out reports/            # propose: writes a review file, changes nothing
    python -m o2c.drafts --instance suryodaya --out reports/ --accounts-email <address> --create [--mailbox-id <id>]
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


def _plain(v, width=None):
    """Record text for a plain-text table cell: one line, optionally cut to `width` characters."""
    text = " ".join(str(v if v is not None else "").split())
    return text if width is None or len(text) <= width else text[:width - 1] + "…"


def text_table(headers, rows, right=()):
    """A plain-text table with aligned columns (the digest is a plain-text email body).

    `right` holds the indexes of columns to right-align (amounts and counts).
    """
    cells = [[_plain(c) for c in row] for row in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(headers)]

    def line(values):
        return "  ".join(v.rjust(w) if i in right else v.ljust(w) for i, (v, w) in enumerate(zip(values, widths))).rstrip()

    return [line(headers), line(["-" * w for w in widths])] + [line(r) for r in cells]


def _totals(rows, amount_key):
    """Per-currency totals as text, e.g. '100.00 INR; 50.00 USD'. Never added across currencies."""
    return "; ".join(_amount(t, c) for c, _, t in by_currency(rows, amount_key)) or "0.00"


CUSTOMER_WIDTH = 40


def accounts_digest(rep, matches, accounts_email=None):
    """The daily report as one internal draft to accounts (instructor answers 3 and 9, 10 Nov).

    A short summary, then one table per exception type: orders not invoiced, invoices overdue,
    payments not applied. Amounts are per currency and never added across currencies. Returns
    None if there is nothing to report.
    """
    secs = rep["sections"]
    orders, invoices, payments = secs["orders_not_invoiced"], secs["invoices_overdue"], secs["payments_not_applied"]
    order_rows = orders["rows"] if orders["status"] == "ok" else []
    inv_rows = invoices["rows"] if invoices["status"] == "ok" else []
    pay_rows = payments["rows"] if payments["status"] == "ok" else []
    if not order_rows and not inv_rows and not pay_rows:
        return None
    by_payment = {m["payment"]: m for m in matches}
    partly = sum(1 for r in inv_rows if r.get("payment_state") == report.PARTIALLY_PAID)
    inv_count = str(len(inv_rows)) if invoices["status"] == "ok" else "not available"
    test = lambda r: "test data" if r.get("fixture") else ""

    lines = [
        "Hello,",
        "",
        f"This is the order-to-cash exception report for {rep.get('instance') or 'our company'} on {rep['report_date']} "
        f"(orders count after {rep['days']} days). Nothing has been changed in the system.",
        "",
        "Summary",
        f"- Orders not invoiced: {len(order_rows)}" + (f", total {_totals(order_rows, 'grand_total')}" if order_rows else ""),
        f"- Invoices overdue: {inv_count}" + (f", {_totals(inv_rows, 'outstanding')} outstanding" if inv_rows else "")
        + (f" ({partly} partially paid)" if partly else ""),
        f"- Payments not applied: {len(pay_rows)}" + (f", {_totals(pay_rows, 'unallocated')} unallocated" if pay_rows else ""),
        "Amounts in different currencies are shown separately, never added together.",
        "",
        f"1. Orders not invoiced more than {rep['days']} days after the order date ({len(order_rows)})",
        "",
    ]
    if order_rows:
        lines += text_table(
            ["Order", "Customer", "Ordered", "Age (days)", "Invoiced", "Total", ""],
            [[r["number"], _plain(r["customer"] or "unknown customer", CUSTOMER_WIDTH), r["order_date"], r["age_days"],
              r["invoiced_status"], _amount(r["grand_total"], r.get("currency")), test(r)] for r in order_rows],
            right={3, 5})
        lines += ["", "Please raise the invoice, or reply with the reason it is on hold.", ""]
    else:
        lines += ["None.", ""]

    lines += [f"2. Invoices overdue ({inv_count})", ""]
    if inv_rows:
        lines += text_table(
            ["Invoice", "Customer", "Due", "Days overdue", "Outstanding", "Payment", ""],
            [[r["number"], _plain(r["customer"] or "unknown customer", CUSTOMER_WIDTH), r["due_date"], r["days_overdue"],
              _amount(r["outstanding"], r.get("currency")), r.get("payment_state") or "", test(r)] for r in inv_rows],
            right={3, 4})
        lines += ["", "A reminder draft is proposed for each customer with an email address; a person reviews and sends it.", ""]
    elif invoices["status"] == "ok":
        lines += ["None.", ""]
    else:
        lines += ["Not available: invoice data cannot be read by this login.", ""]

    lines += [f"3. Payments not applied ({len(pay_rows)})", ""]
    if pay_rows:
        rows = []
        for r in pay_rows:
            cands = (by_payment.get(r["number"]) or {}).get("candidates") or []
            match = ", ".join(f"{c['kind']} {c['number']} ({_amount(c['amount'], c.get('currency'))}"
                              f"{', same amount' if c['exact'] else ''})" for c in cands) or "no candidate found"
            if r.get("hint") == "same_amount":   # receipt history (PaymentReceived), when readable
                match += f"; CHECK: same amount already recorded as applied receipt {', '.join(r['same_amount_receipts'])}"
            elif r.get("hint") == "has_history":
                match += f"; customer has {r['receipts_paid']} applied receipts"
            rows.append([r["number"], _plain(r["customer"] or "unknown customer", CUSTOMER_WIDTH), r["payment_date"] or "?",
                         _amount(r["unallocated"], r.get("currency")), r["status"], match, test(r)])
        lines += text_table(["Payment", "Customer", "Received", "Unallocated", "Status", "Possible match", ""], rows, right={3})
        lines += ["", "Please apply each payment to the right invoice. The matches are suggestions only.", ""]
    else:
        lines += ["None.", ""]
    lines += ["Thank you."]
    return {
        "kind": "accounts_digest",
        "to": accounts_email or ACCOUNTS_PLACEHOLDER,
        "subject": f"Order-to-cash exceptions {rep['report_date']}: {len(order_rows)} orders not invoiced, "
                   f"{inv_count} invoices overdue, {len(pay_rows)} payments not applied",
        "body_text": "\n".join(lines),
        "refs": [r["number"] for r in order_rows] + [r["number"] for r in inv_rows] + [r["number"] for r in pay_rows],
        "fixture": False,
        "status": "proposed",
    }


UNKNOWN_CURRENCY = report.UNKNOWN_CURRENCY


def _currency(row):
    """The row's currency code, or None if the record has none. Never guessed."""
    code = (row.get("currency") or "").strip().upper()
    return code or None


def by_currency(rows, amount_key="outstanding"):
    """Group rows by currency, keeping row order inside each group.

    Returns [(currency or None, rows, subtotal)], known currencies A-Z, then rows with no
    currency last. Amounts in different currencies are never added together: there is no
    conversion policy, so each currency gets its own subtotal.
    """
    groups = {}
    for r in rows:
        groups.setdefault(_currency(r), []).append(r)
    order = sorted(k for k in groups if k) + ([None] if None in groups else [])
    return [(k, groups[k], round(sum(float(r.get(amount_key) or 0) for r in groups[k]), 2)) for k in order]


def _amount(v, currency):
    return _money(v, currency) if currency else f"{_money(v)} ({UNKNOWN_CURRENCY})"


def _reminder_line(r, cur):
    """One invoice line in a customer reminder; a partly paid invoice says so (instructor answer 11)."""
    line = f"- Invoice {r['number']}, due {r['due_date']}, {_amount(r['outstanding'], cur)} outstanding"
    if r.get("payment_state") == report.PARTIALLY_PAID:
        line += f" (partially paid: {_amount(round(float(r.get('amount_paid') or 0), 2), cur)} received, thank you)"
    return line


def overdue_reminders(invoice_rows, parties_by_id):
    """One reminder per customer with overdue invoices. Customers with no email are returned
    as skipped, so a person can follow up another way.

    A customer with invoices in more than one currency gets one section per currency, each
    with its own subtotal, and no grand total (review of #17: 100 INR + 50 USD is not 150 INR).
    """
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
        groups = by_currency(rows)
        subtotals = [(cur, total) for cur, _, total in groups]
        lines = [f"Dear {customer},", "",
                 "Our records show the following invoice(s) past their due date with a balance outstanding:", ""]
        if len(groups) == 1:
            cur, _, total = groups[0]
            for r in rows:
                lines.append(_reminder_line(r, cur))
            lines += ["", f"Total outstanding: {_amount(total, cur)}."]
        else:
            for cur, group, total in groups:
                lines.append(f"Invoices in {cur or UNKNOWN_CURRENCY}:")
                for r in group:
                    lines.append(_reminder_line(r, cur))
                lines += [f"Subtotal ({cur or UNKNOWN_CURRENCY}): {_amount(total, cur)}", ""]
            lines.append("Total outstanding by currency (not added together): "
                         + "; ".join(_amount(t, c) for c, t in subtotals) + ".")
        lines += ["",
                  "If you have already paid, please send us the payment details so we can apply it, and accept our thanks. "
                  "Otherwise we would be grateful for payment at your earliest convenience.", "", "Kind regards,"]
        drafts.append({
            "kind": "overdue_reminder",
            "to": email,
            "subject": f"Payment reminder: {len(rows)} overdue invoice{'s' if len(rows) > 1 else ''}, "
                       + " + ".join(_amount(t, c) for c, t in subtotals),
            "body_text": "\n".join(lines),
            "refs": [r["number"] for r in rows],
            "subtotals": [{"currency": c, "outstanding": t} for c, t in subtotals],
            "fixture": any(r["fixture"] for r in rows),
            "status": "proposed",
        })
    return drafts, skipped


class NoMailbox(Exception):
    pass


def find_mailbox(client, mailbox_id=None):
    """The mailbox this login saves drafts in, or None if it has none.

    The instructor added one mailbox per seat login on 10 Nov (BUG-31-002). It is a `Mailbox` record;
    `EmailAccount.list` stays empty. With several active mailboxes, the single default one is used;
    otherwise a person must pick one with --mailbox-id.
    """
    if mailbox_id:
        return client.call("Mailbox.get", {"id": mailbox_id})
    boxes = [b for b in client.call("Mailbox.list", {"limit": 20}).get("data", [])
             if b.get("is_active", True) is not False and not b.get("deleted_at")]
    if len(boxes) <= 1:
        return boxes[0] if boxes else None
    default = [b for b in boxes if b.get("is_default")]
    if len(default) == 1:
        return default[0]
    raise NoMailbox(f"{len(boxes)} mailboxes and no single default one; choose one with --mailbox-id")


def to_payload(draft, mailbox):
    """EmailMessage.create arguments for a draft. Always a draft, never sent.

    The platform requires company_id, from_email and to; the sender and company come from the mailbox.
    """
    return {
        "company_id": mailbox.get("company_id"),
        "mailbox_id": mailbox.get("id"),
        "from_email": mailbox.get("email"),
        **({"from_name": mailbox["display_name"]} if mailbox.get("display_name") else {}),
        "to": draft["to"],
        "subject": draft["subject"],
        "body_text": draft["body_text"],
        "folder": "drafts",
        "is_draft": True,
    }


class DraftWriter:
    """The only code in seat 31 that may write. It creates drafts and nothing else."""

    def __init__(self, client, mailbox):
        self.client, self.mailbox = client, mailbox or {}

    def call(self, name, args):
        if name != DRAFT_TOOL:
            raise WriteBlocked(f"{name} refused: the draft writer can only call {DRAFT_TOOL}")
        if args.get("folder") != "drafts" or args.get("is_draft") is not True:
            raise WriteBlocked("refused: a message must be created as a draft (folder=drafts, is_draft=true)")
        if not args.get("to") or args["to"] == ACCOUNTS_PLACEHOLDER:
            raise WriteBlocked("refused: the draft has no recipient yet; a person must fill it in")
        if not args.get("from_email") or not args.get("company_id"):
            raise WriteBlocked("refused: the draft needs the mailbox's address and company (from_email, company_id)")
        result = self.client._rpc("tools/call", {"name": name, "arguments": args})
        if result.get("isError"):
            raise McpError(result["content"][0]["text"])
        return result.get("structuredContent") or json.loads(result["content"][0]["text"])

    def create(self, draft):
        return self.call(DRAFT_TOOL, to_payload(draft, self.mailbox))


def propose(client, report_date=None, days=7, instance=None, accounts_email=None):
    """Read-only: build the report, the matches and the proposed drafts."""
    currencies = report.currency_context(client)
    rep = report.build(client, report_date=report_date, days=days, instance=instance, currencies=currencies)
    inv = rep["sections"]["invoices_overdue"]
    pay_rows = rep["sections"]["payments_not_applied"]["rows"]
    if inv["status"] == "ok":
        docs = matching.invoice_documents(client.list_all("Invoice", {"docstatus": 1}), currencies)
    else:
        docs = matching.order_documents(client.list_all("SalesOrder", {"docstatus": 1}), currencies)
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
        "`--create` saves approved drafts in their mailbox as drafts, still unsent. "
        "Without `--create`, this file is where the drafts are reviewed.",
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
            cands = ", ".join(f"{c['kind']} {c['number']} {_amount(c['amount'], c.get('currency'))}{' (same amount)' if c['exact'] else ''}"
                              for c in m["candidates"]) or "none"
            lines.append(f"| {report.cell(m['payment'])} | {report.cell(m['customer'])} | {_amount(m['unallocated'], m.get('currency'))} | "
                         f"{report.cell(cands)} |")
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


DRAFT_KINDS = ("accounts_digest", "overdue_reminder")


def drafts_to_save(prop, only=None):
    """(ready, skipped_count): the proposed drafts --create would save, optionally one kind only.

    Drafts without a recipient are never saved. `only="accounts_digest"` saves just the internal
    note to accounts, so a first test does not put customer reminders into the shared data.
    """
    chosen = [d for d in prop["drafts"] if only is None or d["kind"] == only]
    ready = [d for d in chosen if d["to"] != ACCOUNTS_PLACEHOLDER]
    return ready, len(chosen) - len(ready)


def main():
    ap = argparse.ArgumentParser(prog="o2c.drafts", description="Propose reminder drafts (never sends)")
    ap.add_argument("--days", type=int, default=int(os.environ.get("O2C_DAYS", 7)))
    ap.add_argument("--date", type=date.fromisoformat)
    ap.add_argument("--instance", default=os.environ.get("AGENTSWITCH_INSTANCE"))
    ap.add_argument("--out", type=Path, required=True, help="folder for <instance>-<date>-drafts.md/.json (gitignored)")
    ap.add_argument("--accounts-email", default=os.environ.get("O2C_ACCOUNTS_EMAIL"))
    ap.add_argument("--create", action="store_true", help="after a person confirms, save the drafts in the mailbox (never sends)")
    ap.add_argument("--only", choices=DRAFT_KINDS,
                    help="with --create, save only this kind of draft (e.g. accounts_digest for a first test)")
    ap.add_argument("--mailbox-id", default=os.environ.get("O2C_MAILBOX_ID"),
                    help="only needed if this login has several mailboxes and no default one")
    args = ap.parse_args()

    client = Client()
    prop = propose(client, report_date=args.date, days=args.days, instance=args.instance, accounts_email=args.accounts_email)
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / f"{args.instance or 'report'}-{prop['report_date']}-drafts"
    stem.with_suffix(".json").write_text(json.dumps(prop, indent=2), encoding="utf-8")
    stem.with_suffix(".md").write_text(to_markdown(prop), encoding="utf-8")
    s = prop["match_summary"]
    print(f"wrote {stem}.md ({len(prop['drafts'])} drafts proposed; {s['with_candidates']}/{s['payments']} payments with a candidate)")

    if not args.create:
        return
    try:
        mailbox = find_mailbox(client, args.mailbox_id)
    except NoMailbox as e:
        raise SystemExit(str(e))
    if not mailbox:
        raise SystemExit("this login has no mailbox; nothing created")
    writer = DraftWriter(client, mailbox)
    ready, skipped = drafts_to_save(prop, args.only)
    if not ready:
        raise SystemExit("no draft to save" + (f" of kind {args.only}" if args.only else "") + "; nothing created")
    print(f"About to save {len(ready)} draft(s){' (' + args.only + ' only)' if args.only else ''} "
          f"in mailbox {mailbox.get('id')}. They stay unsent."
          + (f" {skipped} draft(s) have no recipient yet (set --accounts-email) and are not saved." if skipped else ""))
    if input("Type 'save drafts' to confirm: ").strip() != "save drafts":
        raise SystemExit("not confirmed; nothing created")
    for d in ready:
        created = writer.create(d)
        print(f"saved draft {created.get('id')}: {d['subject']}")


if __name__ == "__main__":
    main()
