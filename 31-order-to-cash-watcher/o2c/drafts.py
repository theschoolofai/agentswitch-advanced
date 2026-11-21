"""Reminder drafts for a person to review and send. The agent never sends.

    python -m o2c.drafts --instance suryodaya --out reports/            # propose: writes a review file, changes nothing
    python -m o2c.drafts --instance suryodaya --out reports/ --accounts-email <address> --create [--mailbox-id <id>]
                                                                        # a person approves, then the accounts digest is saved in their mailbox
    python -m o2c.drafts --instance suryodaya --out reports/ --create --only overdue_reminder
                                                                        # customer reminders are saved only when asked for by name

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
from collections import Counter
import json
import re
import os
from datetime import date
from pathlib import Path

from . import matching, report
from .client import Client, McpError, WriteBlocked, platform_failure, tool_result
from .values import display_text, has_unsafe_text, money, money_sum, money_text
from .output import days_option, instance_label, report_stem, safe_console, write_pair

DRAFT_TOOL = "EmailMessage.create"
ACCOUNTS_PLACEHOLDER = "(accounts address: a person fills this in)"


def _money(v, currency=None):
    return money_text(v) + (" " + currency if currency else "")


def _plain(v, width=None):
    """Record text for a plain-text table cell: one line, optionally cut to `width` characters."""
    text = " ".join(display_text(v if v is not None else "").split())   # E2: no control characters
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
    text = "; ".join(_amount(t, c) for c, _, t in by_currency(rows, amount_key)) or "0.00"
    unknown = sum(r.get(amount_key) is None for r in rows)
    return text + (f"; {unknown} amount(s) unknown" if unknown else "")


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
    no_due = invoices.get("no_due_date", []) if invoices["status"] == "ok" else []
    pay_rows = payments["rows"] if payments["status"] == "ok" else []
    diagnostics = [r for sec in secs.values() for r in sec.get("data_issues", [])]
    if not order_rows and not inv_rows and not pay_rows and not no_due and not diagnostics:
        return None
    # Bug hunt E3 (20 Nov): look a payment's matches up by its id. Keyed by number, two payments with
    # no number (or the same one) shared one entry, so one customer's payment showed another
    # customer's invoice as "same amount". A number is used only when it is unique.
    by_id = {m["payment_id"]: m for m in matches if m.get("payment_id") is not None}
    numbers = Counter(m.get("payment") for m in matches)
    by_number = {m["payment"]: m for m in matches if m.get("payment") is not None and numbers[m["payment"]] == 1}

    def match_for(r):
        return (by_id.get(r.get("id")) if r.get("id") is not None else None) or by_number.get(r.get("number"))
    partly = sum(1 for r in inv_rows if r.get("payment_state") == report.PARTIALLY_PAID)
    credited = sum(1 for r in inv_rows if r.get("payment_state") == report.PARTIALLY_CREDITED)
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
        + (f" ({'; '.join(t for t in (f'{partly} partially paid' if partly else '', f'{credited} partially credited' if credited else '') if t)})"
           if partly or credited else ""),
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
        held = held_customers(inv_rows, pay_rows)
        lines += ["", "A reminder draft is proposed for each customer with an email address"
                  + (", except those held back below" if held else "") + "; a person reviews and sends it.", ""]
        if held:
            lines += [f"Reminders held back ({len(held)}): these customers have overdue invoices, but we also hold a "
                      "payment from them that is not applied yet. Please apply it first, then decide whether a reminder is needed.", ""]
            for party_id, pays in sorted(held.items(), key=lambda kv: str(kv[1][0].get("customer") or "")):
                invs = [_ref(r.get("number")) for r in inv_rows if r.get("party_id") == party_id]
                lines.append(f"- {_plain(pays[0].get('customer') or 'unknown customer', CUSTOMER_WIDTH)}: "
                             f"payment {', '.join(_payment_text(p) for p in pays)}; overdue {', '.join(invs)}")
            lines.append("")
    elif invoices["status"] == "ok":
        lines += ["None.", ""]
    else:
        lines += ["Not available: invoice data cannot be read by this login.", ""]

    if no_due:
        lines += [f"Invoices with no usable due date ({len(no_due)}): investigate; not counted as overdue.", ""]
        lines += text_table(["Invoice", "Customer", "Outstanding"],
                            [[r["number"], _plain(r.get("customer"), CUSTOMER_WIDTH),
                              _amount(r.get("outstanding"), r.get("currency"))] for r in no_due], right={2})
        lines.append("")

    lines += [f"3. Payments not applied ({len(pay_rows)})", ""]
    if pay_rows:
        rows = []
        for r in pay_rows:
            cands = (match_for(r) or {}).get("candidates") or []
            match = ", ".join(f"{c['kind']} {c['number']} ({_amount(c['amount'], c.get('currency'))}"
                              f"{', same amount' if c['exact'] else ''})" for c in cands) or "no candidate found"
            if r.get("hint") == "same_amount":   # receipt history (PaymentReceived), when readable
                match += f"; CHECK: same amount already recorded as applied receipt {', '.join(map(str, r['same_amount_receipts']))}"
            elif r.get("hint") == "has_history":
                match += f"; customer has {r['receipts_paid']} applied receipts"
            rows.append([r["number"], _plain(r["customer"] or "unknown customer", CUSTOMER_WIDTH), r["payment_date"] or "?",
                         _amount(r["unallocated"], r.get("currency")), r["status"], match, test(r)])
        lines += text_table(["Payment", "Customer", "Received", "Unallocated", "Status", "Possible match", ""], rows, right={3})
        lines += ["", "Please apply each payment to the right invoice. The matches are suggestions only.", ""]
    else:
        lines += ["None.", ""]
    if diagnostics:
        lines += ["Data validation warnings: coverage is partial; valid exceptions are retained."]
        lines += [f"- {_plain(r.get('number') or r.get('id'))}: {_plain(r['field'])}: {_plain(r['reason'])}" for r in diagnostics]
        lines.append("")
    lines += ["Thank you."]
    return {
        "kind": "accounts_digest",
        "to": accounts_email or ACCOUNTS_PLACEHOLDER,
        "subject": f"Order-to-cash exceptions {rep['report_date']}: {len(order_rows)} orders not invoiced, "
                   f"{inv_count} invoices overdue, {len(pay_rows)} payments not applied",
        "body_text": "\n".join(lines),
        "refs": [r["number"] for r in order_rows] + [r["number"] for r in inv_rows] + [r["number"] for r in no_due] + [r["number"] for r in pay_rows],
        "fixture": False,
        "status": "proposed",
    }


UNKNOWN_CURRENCY = report.UNKNOWN_CURRENCY

# Live test F1 (20 Nov): the platform refuses a message body over 10,000 characters ("Body Text is too
# long (max 10000 chars)"); the limit is not in the tool schema. Suryodaya's digest was well over
# it, so it could never be saved. A longer draft is split into numbered parts.
BODY_MAX = 10000
_PART_MARGIN = 200        # room for the "(Part i of n.)" and "(continued)" lines
_RULE_RE = re.compile(r"-+(?:  +-+)*")
_HEADING_RE = re.compile(r"\d+\. \S|Invoices in \S+:|Data validation warnings")


def _pack(lines, budget):
    """Line chunks of at most `budget` characters (newlines counted). A cut prefers the last blank
    line in the second half of a chunk; a cut inside a text table repeats its header lines."""
    chunks, cur, size, header = [], [], 0, None
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and _RULE_RE.fullmatch(lines[i + 1].strip() or "x"):
            header = None       # a new table starts here; its header is set on the rule line
        if _RULE_RE.fullmatch(line.strip() or "x") and i > 0:
            header = [lines[i - 1], line]
        elif not line.strip():
            header = None if cur and cur[-1].strip() == "" else header
        while len(line) > budget:           # one line longer than a part (never seen): hard cut
            chunks.append(cur + [line[:budget]]) if not cur else chunks.extend([cur, [line[:budget]]])
            cur, size, line = [], 0, line[budget:]
        if cur and size + len(line) + 1 > budget:
            blanks = [j for j, l in enumerate(cur) if not l.strip() and j >= len(cur) // 2]
            # Best: just before a section heading ("2. Invoices overdue", "Invoices in USD:"), so a
            # heading never ends a part with its table in the next one.
            before_heading = [j for j in blanks if j + 1 < len(cur) and _HEADING_RE.match(cur[j + 1])]
            if not before_heading and _HEADING_RE.match(line) and cur[-1].strip() == "":
                before_heading = [len(cur) - 1]
            blanks = before_heading or blanks
            cut = blanks[-1] + 1 if blanks else len(cur)
            chunks.append(cur[:cut])
            cur = cur[cut:]
            if header and not blanks and line.strip():
                cur = [header[0] + " (continued)", header[1]] + cur
            size = sum(len(l) + 1 for l in cur)
        cur.append(line)
        size += len(line) + 1
    if cur:
        chunks.append(cur)
    return chunks


def fit_body(draft, limit=BODY_MAX):
    """[draft], or the draft as numbered parts that each fit the platform's body limit (F1).
    Every part keeps the recipient; the subject says "(part i of n)", so D4 sees each part once."""
    if len(draft["body_text"]) <= limit:
        return [draft]
    chunks = _pack(draft["body_text"].split("\n"), limit - _PART_MARGIN)
    n = len(chunks)
    parts = []
    for i, chunk in enumerate(chunks, 1):
        while chunk and not chunk[0].strip():
            chunk = chunk[1:]
        body = "\n".join([f"(Part {i} of {n}.)", ""] + chunk).rstrip()
        parts.append({**draft, "subject": f"{draft['subject']} (part {i} of {n})", "body_text": body, "part": [i, n]})
    return parts


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
    result = []
    for k in order:
        amounts = []
        for row in groups[k]:
            try:
                amount = money(row.get(amount_key))
                if amount is not None:
                    amounts.append(amount)
            except ValueError:
                pass  # The report carries diagnostics; invalid amounts never become zero.
        try:
            subtotal = money_sum(amounts)
        except ValueError:
            subtotal = None
        result.append((k, groups[k], subtotal))
    return result


def _amount(v, currency):
    return _money(v, currency) if currency else f"{_money(v)} ({UNKNOWN_CURRENCY})"


NAME_MAX = 80
# Text in a record that reads like an instruction to a model, not like a company name.
_INSTRUCTION_RE = re.compile(r"(?i)\b(?:ignore|disregard|instructions?|prompt|override|assistant)\b|\bsystem\s*:")
_UNSAFE_NAME_CHARS = set("`<>{}[]\\")
_EMAIL_RE = re.compile(r"[^@\s<>,;:\"'()\[\]]+@[^@\s<>,;:\"'()\[\]]+\.[A-Za-z]{2,}")


def safe_name(raw):
    """(name, note): the customer name to put in a reminder, or (None, why it was left out).

    Bug hunt C1 (19 Nov), seat 33 case O01: record text reaches a customer-facing draft. A name
    is copied only if it looks like a name: one line, at most NAME_MAX characters, no markup
    characters, no URL, no address, and no instruction-like words. Otherwise the reminder says
    "Dear customer" and the review file says why, so outside text is never quoted.
    """
    text = "" if raw is None else str(raw)
    one_line = _plain(text)
    if not one_line:
        return None, None
    if (one_line != text.strip() or len(one_line) > NAME_MAX or any(c in _UNSAFE_NAME_CHARS for c in one_line)
            or "://" in one_line or "@" in one_line or any(ord(c) < 32 for c in text if c not in "\n\r\t")
            or has_unsafe_text(text)   # E2: direction overrides, zero-width marks, C1 controls
            or _INSTRUCTION_RE.search(one_line)):
        return None, "customer name not copied into the draft: it has line breaks, markup or instruction-like text"
    return one_line, None


def safe_email(raw):
    """The one address to draft to, or None: never a list, a display name or anything else."""
    text = "" if raw is None else str(raw).strip()
    # E2: an address with invisible or control characters is not a plain address.
    return text if _EMAIL_RE.fullmatch(text) and not has_unsafe_text(text) else None


def _ref(v):
    """A record number (invoice, payment) as it may appear in a draft: one line, short."""
    return _plain(v, 40) or "?"


def _reminder_line(r, cur):
    """One invoice line in a customer reminder; a partly paid invoice says so (instructor answer 11)."""
    line = f"- Invoice {_ref(r['number'])}, due {_ref(r['due_date'])}, {_amount(r['outstanding'], cur)} outstanding"
    credit = r.get("credits_applied")
    credit_text = f"credit of {_amount(credit, cur)} applied" if credit is not None and credit > 0 else ""
    if r.get("payment_state") == report.PARTIALLY_PAID:
        line += f" (partially paid: {_amount(r.get('amount_paid'), cur)} received, thank you"
        line += f"; {credit_text})" if credit_text else ")"
    elif r.get("payment_state") == report.PARTIALLY_CREDITED and credit_text:
        line += f" ({credit_text})"   # bug hunt B4: a credit note is not "unpaid"
    return line


HELD_REASON = "held: we hold a payment from this customer that is not applied yet; apply it before sending a reminder"


def _payment_text(p):
    return f"{_ref(p.get('number'))} ({_amount(p.get('unallocated'), _currency(p))}, received {p.get('payment_date') or '?'})"


def held_customers(invoice_rows, payment_rows):
    """party_id -> unapplied payment rows, for customers who have overdue invoices AND a payment
    we have not applied yet (bug hunt B1, 12 Nov).

    Their reminder is held back for a person: asking them to pay, or to "send the payment
    details", is wrong while we hold their money. A payment with no customer is never matched.
    """
    overdue = {r.get("party_id") for r in invoice_rows if r.get("party_id")}
    held = {}
    for p in payment_rows or ():
        if p.get("party_id") in overdue:
            held.setdefault(p["party_id"], []).append(p)
    return held


def overdue_reminders(invoice_rows, parties_by_id, payment_rows=(), report_date=None):
    """One reminder per customer with overdue invoices. Customers with no email, or with a
    payment not applied yet (`payment_rows`, section 3), are returned as skipped, so a person
    can follow up another way.

    A customer with invoices in more than one currency gets one section per currency, each
    with its own subtotal, and no grand total (review of #17: 100 INR + 50 USD is not 150 INR).
    """
    by_party = {}
    for r in invoice_rows:
        by_party.setdefault(r.get("party_id"), []).append(r)
    held = held_customers(invoice_rows, payment_rows)
    drafts, skipped = [], []
    # str(): a record value of another type must not break the sort (bug hunt D7).
    for party_id, rows in sorted(by_party.items(), key=lambda kv: str(kv[1][0].get("customer") or "")):
        party = parties_by_id.get(party_id) or {}
        raw_email = party.get("email")
        email = safe_email(raw_email)
        raw_name = rows[0]["customer"] or party.get("name")
        name, name_note = safe_name(raw_name)
        customer = _plain(raw_name, NAME_MAX) or "unknown customer"   # for the review file only
        if party_id in held:
            skipped.append({"customer": customer, "invoices": [r["number"] for r in rows], "held": True,
                            "payments": [p.get("number") for p in held[party_id]],
                            "reason": HELD_REASON + " (" + "; ".join(_payment_text(p) for p in held[party_id]) + ")"})
            continue
        if not email:
            reason = ("no email on the customer record" if not raw_email
                      else "the customer record's email is not a single plain address")
            skipped.append({"customer": customer, "invoices": [r["number"] for r in rows], "reason": reason})
            continue
        groups = by_currency(rows)
        subtotals = [(cur, total) for cur, _, total in groups]
        lines = [f"Dear {name or 'customer'},", "",
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
            # The report date makes each day's reminder its own draft for D4's duplicate check (review of #54):
            # without it, yesterday's unsent reminder with the same count and amount blocked today's.
            "subject": f"Payment reminder{' ' + report_date if report_date else ''}: "
                       f"{len(rows)} overdue invoice{'s' if len(rows) > 1 else ''}, "
                       + " + ".join(_amount(t, c) for c, t in subtotals),
            "body_text": "\n".join(lines),
            "refs": [r["number"] for r in rows],
            "subtotals": [{"currency": c, "outstanding": t} for c, t in subtotals],
            "fixture": any(r["fixture"] for r in rows),
            "review_notes": [name_note] if name_note else [],
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
        box = client.call("Mailbox.get", {"id": mailbox_id})
        # Bug hunt G1 (20 Nov): a named mailbox must still be usable; drafts in a closed one are lost.
        if not isinstance(box, dict) or box.get("is_active") is False or box.get("deleted_at"):
            raise NoMailbox(f"mailbox {mailbox_id} is inactive or deleted; choose another with --mailbox-id")
        return box
    page = client.call("Mailbox.list", {"limit": 20})
    page = page if isinstance(page, dict) else {}
    listed = [b for b in page.get("data") or [] if isinstance(b, dict)]
    if isinstance(page.get("total"), int) and page["total"] > len(listed):
        # G1: more mailboxes than one page; picking from a partial list could pick the wrong one.
        raise NoMailbox(f"{page['total']} mailboxes, more than one page; choose one with --mailbox-id")
    boxes = [b for b in listed if b.get("is_active", True) is not False and not b.get("deleted_at")]
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
        if len(args.get("body_text") or "") > BODY_MAX:   # F1: the platform would refuse it anyway
            raise WriteBlocked(f"refused: the body is over {BODY_MAX} characters; split it with fit_body()")
        # Never retried by the client: a retried create could save the same draft twice.
        return tool_result(self.client._rpc("tools/call", {"name": name, "arguments": args}), name)

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
        drafts += fit_body(digest)
    if inv["status"] == "ok" and inv["rows"]:
        parties = {p.get("id"): p for p in client.list_all("Party") if p.get("id") is not None}   # D7
        reminders, skipped = overdue_reminders(inv["rows"], parties, pay_rows, rep["report_date"])
        drafts += [part for r in reminders for part in fit_body(r)]
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


def _fence(body):
    """A code fence longer than any backtick run in the body, so record text cannot close it (C1)."""
    longest = max((len(m) for m in re.findall(r"`+", body or "")), default=0)
    return "`" * max(3, longest + 1)


def _md_inline(v):
    """Record text on one Markdown line: no line breaks, and markup characters shown as text."""
    return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", _plain(v))


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
        fence = _fence(d["body_text"])
        lines += [f"### {i}. {d['kind']}{' (test data)' if d['fixture'] else ''}", "",
                  f"**To:** {_md_inline(d['to'])}  ", f"**Subject:** {_md_inline(d['subject'])}", ""]
        lines += [f"**Check:** {_md_inline(n)}" for n in d.get("review_notes") or []]
        lines += [fence + "text", d["body_text"], fence, ""]
    if prop["skipped"]:
        lines += [f"## Not drafted ({len(prop['skipped'])})", ""]
        for k in prop["skipped"]:
            lines.append(f"- {_md_inline(k['customer'])}: {_md_inline(', '.join(map(str, k['invoices'])))}: {_md_inline(k['reason'])}")
        lines.append("")
    return "\n".join(lines)


DRAFT_KINDS = ("accounts_digest", "overdue_reminder")


def drafts_to_save(prop, only=None):
    """(ready, skipped): the proposed drafts --create would save, and [(draft, reason)] it won't.

    Without `only`, only the internal accounts digest is saved. Customer reminders are addressed
    to the customer's own email, so saving them needs an explicit `only="overdue_reminder"`
    (bug hunt B2, 12 Nov). Drafts without a recipient, and drafts built on rows that look like
    other seats' test data, are never saved.
    """
    kind = only or "accounts_digest"
    ready, skipped = [], []
    for d in prop["drafts"]:
        if d["kind"] != kind:
            continue
        if d["to"] == ACCOUNTS_PLACEHOLDER:
            skipped.append((d, "no recipient yet (set --accounts-email)"))
        elif d.get("fixture"):
            skipped.append((d, "built on test data"))
        else:
            ready.append(d)
    return ready, skipped


def _draft_key(to, subject):
    """What makes two drafts the same draft: the recipient (case ignored) and the subject."""
    return str(to or "").strip().lower(), " ".join(str(subject or "").split())


def existing_drafts(client, mailbox):
    """Keys of the unsent drafts already in this mailbox (bug hunt D4, 19 Nov). Read-only.

    A message that was sent, or deleted, does not count: a new reminder after it is legitimate.
    """
    box = (mailbox or {}).get("id")
    keys = set()
    for m in client.list_all("EmailMessage", {"mailbox_id": box} if box else None):
        if m.get("deleted_at") or (box and m.get("mailbox_id") not in (None, box)):
            continue
        if m.get("is_draft") is True or m.get("folder") == "drafts":
            keys.add(_draft_key(m.get("to"), m.get("subject")))
    return keys


_FAMILY_RE = re.compile(r"(Payment reminder|Order-to-cash exceptions)\b")
SUBJECT_FAMILY = {"accounts_digest": "Order-to-cash exceptions", "overdue_reminder": "Payment reminder"}


def older_drafts(current, existing, kind=None):
    """Unsent drafts of this kind already in the mailbox that are not one of this run's drafts: an earlier day's
    reminder or digest, a digest whose figures or number of parts changed, or a reminder to a customer who gets
    none today (paid since, or now held back because we hold their payment, B1). They are not touched; the
    person is told to check them before sending (review of #54).

    `current` is every draft this run would save, including those already in the mailbox (D4 duplicates).
    Comparing against all of them, not one at a time, means the parts of one split draft never count as
    "older" than each other (second review of #54: after a failed save, the rerun named the saved part 1).
    Any recipient counts, not only this run's: a stale reminder to a customer who has since paid is the one
    that must not go out."""
    mine = {_draft_key(d["to"], d["subject"]) for d in current}
    families = ({SUBJECT_FAMILY[kind]} if kind in SUBJECT_FAMILY
                else {m.group(1) for _, subject in mine if (m := _FAMILY_RE.match(subject))})
    return sorted(key for key in existing if key not in mine and any(key[1].startswith(f) for f in families))


def without_duplicates(ready, existing):
    """(new, duplicates): drafts not already in the mailbox, and not repeated within this batch."""
    seen, new, duplicates = set(existing), [], []
    for d in ready:
        key = _draft_key(d["to"], d["subject"])
        (duplicates if key in seen else new).append(d)
        seen.add(key)
    return new, duplicates


def recipient_domains(ready):
    """'example.com (2), x.example (1)': where the drafts would be addressed, for the confirmation."""
    counts = {}
    for d in ready:
        domain = str(d["to"]).rpartition("@")[2].lower() or "?"
        counts[domain] = counts.get(domain, 0) + 1
    return ", ".join(f"{k} ({n})" for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def main():
    ap = argparse.ArgumentParser(prog="o2c.drafts", description="Propose reminder drafts (never sends)")
    ap.add_argument("--days", type=days_option, default=os.environ.get("O2C_DAYS", "7"))   # E5
    ap.add_argument("--date", type=date.fromisoformat)
    ap.add_argument("--instance", default=os.environ.get("AGENTSWITCH_INSTANCE"))
    ap.add_argument("--out", type=Path, required=True, help="folder for <instance>-<date>-drafts.md/.json (gitignored)")
    ap.add_argument("--accounts-email", default=os.environ.get("O2C_ACCOUNTS_EMAIL"))
    ap.add_argument("--create", action="store_true", help="after a person confirms, save the drafts in the mailbox (never sends)")
    ap.add_argument("--only", choices=DRAFT_KINDS,
                    help="with --create, the kind of draft to save (default accounts_digest); customer "
                         "reminders are saved only with --only overdue_reminder")
    ap.add_argument("--mailbox-id", default=os.environ.get("O2C_MAILBOX_ID"),
                    help="only needed if this login has several mailboxes and no default one")
    args = ap.parse_args()
    safe_console()   # bug hunt G4: before anything can print a failure (D6)
    try:
        instance_label(args.instance)
    except ValueError as e:
        ap.error(str(e))

    try:
        client = Client()
        prop = propose(client, report_date=args.date, days=args.days, instance=args.instance, accounts_email=args.accounts_email)
    except McpError as e:
        platform_failure("o2c.drafts", e)
    basename = report_stem(args.instance, prop["report_date"], "-drafts")
    write_pair(args.out, basename, json.dumps(prop, indent=2, allow_nan=False), to_markdown(prop))
    stem = args.out / basename
    s = prop["match_summary"]
    print(f"wrote {stem}.md ({len(prop['drafts'])} drafts proposed; {s['with_candidates']}/{s['payments']} payments with a candidate)")

    if not args.create:
        return
    try:
        mailbox = find_mailbox(client, args.mailbox_id)
    except NoMailbox as e:
        raise SystemExit(str(e))
    except McpError as e:
        platform_failure("o2c.drafts", e)
    if not mailbox:
        raise SystemExit("this login has no mailbox; nothing created")
    writer = DraftWriter(client, mailbox)
    kind = args.only or "accounts_digest"
    ready, skipped = drafts_to_save(prop, kind)
    reminders = sum(d["kind"] == "overdue_reminder" for d in prop["drafts"])
    if kind != "overdue_reminder" and reminders:
        print(f"{reminders} customer reminder(s) are not saved; review them in {stem}.md and use --only overdue_reminder to save them.")
    for d, reason in skipped:
        print(f"not saved ({reason}): {d['subject']}")
    if not ready:
        raise SystemExit(f"no {kind} draft to save; nothing created")
    # D4: running --create again (a retry after a crash, a second person) must not save the same drafts twice.
    try:
        existing = existing_drafts(client, mailbox)
        current = list(ready)
        ready, duplicates = without_duplicates(ready, existing)
    except McpError as e:
        platform_failure("o2c.drafts", e)
    for d in duplicates:
        print(f"not saved (already in the mailbox as an unsent draft): {d['subject']}")
    for to, subject in older_drafts(current, existing, kind):
        print(f"check: an older unsent draft to {to.rpartition('@')[2] or '?'} is still in the mailbox "
              f"({subject!r}); delete it or check it before sending")
    if not ready:
        raise SystemExit(f"every {kind} draft is already in the mailbox as an unsent draft; nothing created")
    print(f"About to save {len(ready)} {kind} draft(s) in mailbox {mailbox.get('id')}, "
          f"addressed to {recipient_domains(ready)}. They stay unsent.")
    try:
        answer = input("Type 'save drafts' to confirm: ")
    except (EOFError, KeyboardInterrupt):   # E5: no input, or Ctrl-C, is "not confirmed"
        answer = ""
    if answer.strip() != "save drafts":
        raise SystemExit("not confirmed; nothing created")
    for i, d in enumerate(ready):
        try:
            created = writer.create(d)
        except McpError as e:
            # The create may have reached the platform before the failure: say so, never retry blindly.
            platform_failure("o2c.drafts", f"{e}. Saved {i} of {len(ready)} drafts before this. The failed one may "
                                           "still have been created: check the mailbox before running --create again")
        print(f"saved draft {created.get('id') if isinstance(created, dict) else '?'}: {d['subject']}")


if __name__ == "__main__":
    main()
