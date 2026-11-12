"""Daily order-to-cash exception report.

The rules are pure functions over rows so they can be tested without the platform.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from .values import business_date, money, money_number, money_text, money_sum, currency_code

from . import receipts as receipts_mod

IST = timezone(timedelta(hours=5, minutes=30))
SUBMITTED = 1
CANCELLED = 2
NOT_INVOICED = ("unbilled", "partially_invoiced")
RECEIVABLE = "receivable"
PARTIALLY_PAID = "partially paid"
FIXTURE_MARKERS = ("test", "harness", "fixture")
ORDER_AGE_BUCKETS = ("0-7", "8-14", "15-30", "31-60", ">60")
AGE_BUCKETS = (("future", None, -1), ("0-30", 0, 30), ("31-60", 31, 60), ("61-90", 61, 90), ("90+", 91, None))


def today_ist():
    return datetime.now(IST).date()


def looks_like_fixture(row):
    text = " ".join(str(row.get(k) or "") for k in ("_party_id_display", "notes", "_deal_id_display")).lower()
    return any(m in text for m in FIXTURE_MARKERS)


UNKNOWN_CURRENCY = "currency not recorded"


def _code(value):
    return currency_code(value)


def currency_context(client, names=None):
    """Where currency is recorded on the platform (probed 11 Nov 2026).

    Sales orders have a `currency_code` field but it is empty on every submitted order, and
    payments have no currency field at all. The customer (`Party.currency_id`) and the company
    (`Company.default_currency`) do record one. Returns {"parties": {id: code}, "companies":
    {id: code}}; a source this login cannot read is left empty.
    """
    names = client.tool_names() if names is None else names
    parties = {p.get("id"): _code(p.get("currency_id")) for p in client.list_all("Party")} if "Party.list" in names else {}
    companies = {c.get("id"): _code(c.get("default_currency")) for c in client.list_all("Company")} if "Company.list" in names else {}
    return {"parties": parties, "companies": companies}


def resolve_currency(record_code, party_id, company_id, ctx):
    """(code, source): the record's own currency, else the customer's, else the company's default.

    Never guessed from the instance name or an exchange rate. With one company on the system its
    default applies when the row has no company_id. Returns (None, None) if nothing is recorded.
    """
    ctx = ctx or {}
    companies = ctx.get("companies") or {}
    company = companies.get(company_id) if company_id in companies else (
        next(iter(companies.values())) if len(companies) == 1 else None)
    for source, value in (("record", record_code), ("customer", (ctx.get("parties") or {}).get(party_id)),
                          ("company", company)):
        code = _code(value)
        if code:
            return code, source
    return None, None


def apply_currency(rows, ctx, issues=None):
    """Set `currency` and `currency_source` on report rows (which carry party_id/company_id)."""
    for r in rows:
        if r.get("currency") not in (None, "") and _code(r["currency"]) is None:
            _issue(issues, r, "currency", "invalid currency code; using verified fallback if available")
        r["currency"], r["currency_source"] = resolve_currency(r.get("currency"), r.get("party_id"), r.get("company_id"), ctx)
    return rows


def _as_date(value):
    return business_date(value)


def _issue(issues, row, field, reason):
    if issues is not None:
        issues.append({"id": row.get("id"), "number": row.get("number"), "field": field, "reason": reason})


def _date_value(row, field, issues, report_date=None):
    try:
        day = business_date(row.get(field))
    except ValueError:
        _issue(issues, row, field, "invalid date")
        return None
    if day is None:
        _issue(issues, row, field, "missing date")
    elif report_date is not None and day > report_date:
        _issue(issues, row, field, "future date; age unknown")
        return None
    return day


def _amount_value(row, field, issues):
    try:
        result = money_number(row.get(field))
        if result is None:
            _issue(issues, row, field, "missing amount")
        return result
    except ValueError:
        _issue(issues, row, field, "invalid or nonfinite amount")
        return None


def validate_days(days):
    """Reject invalid thresholds before a client or a report run is started."""
    if isinstance(days, bool) or not isinstance(days, int) or days < 0:
        raise ValueError("days must be a nonnegative integer")
    return days


def order_age_bucket(age_days):
    """Order-date age bucket; negative/unknown ages are not bucketed."""
    if age_days is None or age_days < 0:
        return None
    for maximum, label in zip((7, 14, 30, 60), ORDER_AGE_BUCKETS):
        if age_days <= maximum:
            return label
    return ORDER_AGE_BUCKETS[-1]


def _order_date(row):
    try:
        return _as_date(row.get("date"))
    except (ValueError, TypeError):
        return None


def order_date_issues(orders, report_date):
    """Unbilled submitted orders whose order dates cannot support an age check.

    These are diagnostics, not additional exception rows or financial totals.
    """
    issues = []
    for row in orders:
        if row.get("docstatus") != SUBMITTED or row.get("invoiced_status") not in NOT_INVOICED:
            continue
        day = _order_date(row)
        reason = None
        if day is None:
            reason = "missing order date" if not row.get("date") else "invalid order date"
        elif day > report_date:
            reason = "future order date"
        if reason:
            issues.append({"id": row.get("id"), "number": row.get("number"), "reason": reason})
    return sorted(issues, key=lambda r: (str(r["number"] or ""), str(r["id"] or "")))


def _order_sort_key(row):
    """Oldest first, then currency group, then descending value within the group."""
    currency = _code(row.get("currency"))
    try:
        amount = money(row.get("grand_total"))
    except ValueError:
        amount = None
    return (-row["age_days"], currency is None, currency or "", amount is None,
            amount.copy_negate() if amount is not None else Decimal(0), str(row.get("number") or ""), str(row.get("id") or ""))


def sort_orders(rows):
    """Sort again after currency resolution so fallback codes determine the groups too."""
    return sorted(rows, key=_order_sort_key)


def order_age_summary(rows):
    counts = dict.fromkeys(ORDER_AGE_BUCKETS, 0)
    for row in rows:
        bucket = order_age_bucket(row.get("age_days"))
        if bucket is not None:
            counts[bucket] += 1
    return counts


def orders_not_invoiced(orders, report_date, days, issues=None):
    """Submitted orders not fully invoiced, strictly older than N by order date.

    No verified deliverable-date field is agreed yet; delivery state is not used
    to invent one. Invalid/missing/future dates are surfaced by order_date_issues.
    """
    validate_days(days)
    out = []
    for o in orders:
        if o.get("docstatus") != SUBMITTED or o.get("invoiced_status") not in NOT_INVOICED:
            continue
        order_date = _date_value(o, "date", issues, report_date)
        if order_date is None:
            continue
        age = (report_date - order_date).days
        if age <= days:
            continue
        out.append({
            "number": o.get("number"),
            "id": o.get("id"),
            "customer": o.get("_party_id_display"),
            "party_id": o.get("party_id"),
            "company_id": o.get("company_id"),
            "order_date": order_date.isoformat(),
            "age_days": age,
            "age_basis": "order_date",
            "age_bucket": order_age_bucket(age),
            "deliverability_status": "unverified",
            "invoiced_status": o.get("invoiced_status"),
            "delivered_status": o.get("delivered_status"),
            "grand_total": _amount_value(o, "grand_total", issues),
            "currency": o.get("currency_code"),
            "fixture": looks_like_fixture(o),
        })
    return sort_orders(out)


def age_bucket(age_days):
    """Label for an age in days. A payment dated after the report date is 'future'; no date is 'unknown'."""
    if age_days is None:
        return "unknown"
    for label, lo, hi in AGE_BUCKETS:
        if (lo is None or age_days >= lo) and (hi is None or age_days <= hi):
            return label
    return "unknown"


def payments_not_applied(payments, report_date, issues=None):
    """Incoming payments (draft or submitted, not cancelled) with money not yet allocated to an invoice.

    These are Payment rows of type `receive`; applied receipts are a separate entity, PaymentReceived
    (instructor, 7 Nov). Drafts are kept: the instructor counts all 40 Suryodaya receive payments as
    unallocated. The status column shows which ones are drafts.
    """
    out = []
    for p in payments:
        if p.get("type") != "receive" or p.get("docstatus") == CANCELLED:
            continue
        unallocated = _amount_value(p, "unallocated", issues)
        if unallocated is None or unallocated <= 0:
            continue
        paid = _date_value(p, "date", issues)
        age = (report_date - paid).days if paid else None
        if age is not None and age < 0:
            _issue(issues, p, "date", "future payment date; classified as future")
        amount = _amount_value(p, "amount", issues)
        notes = []
        if p.get("status") == "reconciled" and amount is not None and abs(unallocated - amount) < 0.01:
            notes.append("reconciled but nothing allocated")
        out.append({
            "number": p.get("number"),
            "id": p.get("id"),
            "customer": p.get("_party_id_display"),
            "party_id": p.get("party_id"),
            "company_id": p.get("company_id"),
            "currency": None,   # Payment has no currency field; resolved from customer/company
            "payment_date": paid.isoformat() if paid else None,
            "age_days": age,
            "age_bucket": age_bucket(age),
            "amount": amount,
            "unallocated": unallocated,
            "status": p.get("status"),
            "docstatus": p.get("docstatus"),
            "notes": notes,
            "fixture": looks_like_fixture(p),
        })
    return sorted(out, key=lambda r: (-(r["age_days"] or 0), r["number"] or ""))


def _currency_order(codes):
    """Known currencies A-Z, then None (currency not recorded) last."""
    codes = set(codes)
    return sorted(c for c in codes if c) + ([None] if None in codes else [])


def payments_summary(rows):
    """Totals for section 3, always per currency: overall, by age bucket, by status and by customer.

    Amounts in different currencies are never added together (there is no conversion policy), so
    there is no single overall total: `by_currency` holds one total per currency, and each age,
    status and customer line is for one currency. Customers are ranked by amount only within
    their own currency.
    """
    def add(table, key, row):
        t = table.setdefault(key, {"count": 0, "unallocated": 0.0})
        t["count"] += 1
        t["unallocated"] = money_sum([money(t["unallocated"]), money(row["unallocated"])])

    totals, buckets, statuses, customers = {}, {}, {}, {}
    for r in rows:
        cur = r.get("currency")
        party = r.get("party_id") or r.get("customer") or "unknown"
        add(totals, cur, r)
        # Reports saved before #35 have age_days but no age_bucket/summary.
        add(buckets, (r.get("age_bucket", age_bucket(r.get("age_days"))), cur), r)
        add(statuses, (r["status"] or "unknown", cur), r)
        add(customers, (party, cur), r)
        customers[(party, cur)]["customer"] = r.get("customer")
    currencies = _currency_order(totals)
    rank = {c: i for i, c in enumerate(currencies)}
    order = [b[0] for b in AGE_BUCKETS] + ["unknown"]
    return {
        "count": len(rows),
        "by_currency": [{"currency": c, **totals[c]} for c in currencies],
        "by_age": [{"bucket": b, "currency": c, **buckets[(b, c)]} for b in order for c in currencies if (b, c) in buckets],
        "by_status": [{"status": st, "currency": c, **v} for (st, c), v in
                      sorted(statuses.items(), key=lambda kv: (kv[0][0], rank[kv[0][1]]))],
        "by_customer": sorted(({"party_id": p, "currency": c, **v} for (p, c), v in customers.items()),
                              key=lambda x: (rank[x["currency"]], -x["unallocated"], x.get("customer") or "")),
    }


def add_receipt_hints(rows, receipts, currencies=None):
    """Attach each unapplied payment's customer receipt history (PaymentReceived) to its row."""
    # Use the report's documented record/customer/company precedence for receipt currency.
    receipts = [dict(r) for r in receipts]
    for receipt in receipts:
        receipt["currency"], receipt["currency_source"] = resolve_currency(
            receipts_mod.receipt_currency(receipt), receipt.get("customer_id"), receipt.get("company_id"), currencies)
    history = receipts_mod.history_by_customer(receipts)
    for r in rows:
        r.update(receipts_mod.hint_for(r, history))
    return rows


def validated_receipts(receipts, issues, quarantined_customers=None):
    """Keep #35's allocation logic, but don't let bad raw amounts become zero/NaN.

    Unusable financial child rows quarantine that receipt from the hint input.
    A bad receipt date is diagnosed while its otherwise valid allocation facts
    remain usable, with no invented last-receipt date.
    """
    out = []
    for raw in receipts:
        row = dict(raw)
        valid = True
        for field in ("amount", "allocation_consideration"):
            if row.get(field) is not None:
                value = _amount_value(row, field, issues)
                valid = valid and value is not None
                row[field] = value
        for field, amount_key in (("applied_allocations", "amount"), ("invoices", "payment"), ("allocation_history", "amount")):
            children = [] if row.get(field) is None else row[field]
            if not isinstance(children, list) or any(not isinstance(c, dict) for c in children):
                _issue(issues, raw, "PaymentReceived." + field, "invalid receipt child records; receipt hint excluded")
                valid = False
                continue
            normalized = []
            for child in children:
                child = dict(child)
                relevant = (field != "allocation_history" or receipts_mod._targets_invoice(child) or child.get("reverses_event_id"))
                if relevant:
                    value = _amount_value(child, amount_key, None)
                    if value is None:
                        _issue(issues, raw, "PaymentReceived." + field + "." + amount_key,
                               "unusable receipt allocation amount; receipt hint excluded")
                        valid = False
                    child[amount_key] = value
                normalized.append(child)
            row[field] = normalized
        if row.get("date") not in (None, ""):
            day = _date_value(row, "date", issues)
            row["date"] = day.isoformat() if day else None
        if valid:
            out.append(row)
        elif quarantined_customers is not None:
            # None means attribution is unavailable: every customer's history may be incomplete.
            quarantined_customers.add(raw.get("customer_id") or None)
    return out


def invoices_overdue(invoices, report_date, issues=None):
    """Submitted invoices past their due date with a balance left, plus invoices with no due date.

    Due date and balance are read from the Invoice entity (`due_date`, `outstanding`), not
    derived (instructor, 7 Nov). Any submitted invoice with an empty `due_date` is reported
    separately, whatever its balance. Field names checked against Invoice.list on 11 Nov.

    Only customer invoices count: the Invoice entity also holds supplier bills (`direction` =
    "payable"; 165 of 487 on Suryodaya, 11 Nov), which must never appear here or get a reminder.
    Returns (overdue, no_due_date).
    """
    overdue, no_due = [], []
    for inv in invoices:
        if inv.get("docstatus") != SUBMITTED or inv.get("direction", RECEIVABLE) != RECEIVABLE:
            continue
        outstanding = _amount_value(inv, "outstanding", issues)
        paid = _amount_value(inv, "amount_paid", issues)
        due = _date_value(inv, "due_date", issues)
        row = {
            "number": inv.get("number"),
            "id": inv.get("id"),
            "customer": inv.get("_party_id_display"),
            "party_id": inv.get("party_id"),
            "company_id": inv.get("company_id"),
            "due_date": due.isoformat() if due else None,
            "days_overdue": (report_date - due).days if due else None,
            "payment_terms": inv.get("payment_terms"),
            "grand_total": _amount_value(inv, "grand_total", issues),
            "amount_paid": paid,
            "outstanding": outstanding,
            # Instructor answer 11 (10 Nov): money received and a balance left -> report the balance,
            # age it from the due date, and label it "partially paid".
            "payment_state": "unknown" if outstanding is None or paid is None else (
                PARTIALLY_PAID if paid > 0 and outstanding > 0 else ("unpaid" if outstanding > 0 else "paid")),
            "currency": inv.get("currency_code"),
            "fixture": looks_like_fixture(inv),
        }
        if due is None:
            no_due.append(row)
        elif due < report_date and outstanding is not None and outstanding > 0:
            overdue.append(row)
    overdue.sort(key=lambda r: (-r["days_overdue"], r["number"] or ""))
    no_due.sort(key=lambda r: r["number"] or "")
    return overdue, no_due


def build(client, report_date=None, days=7, instance=None, currencies=None):
    validate_days(days)
    report_date = report_date or today_ist()
    sections = {}
    names = client.tool_names()
    currencies = currencies if currencies is not None else currency_context(client, names)

    orders = client.list_all("SalesOrder", {"docstatus": SUBMITTED})
    order_issues = []
    sections["orders_not_invoiced"] = {
        "status": "ok",
        "rule": f"submitted, invoiced_status in {list(NOT_INVOICED)}, order date more than {days} days ago",
        "rows": sort_orders(apply_currency(orders_not_invoiced(orders, report_date, days, order_issues), currencies, order_issues)),
        "data_issues": order_issues,
    }
    order_section = sections["orders_not_invoiced"]
    order_section.update(
        age_basis="order_date",
        deliverability_status="unverified",
        unverified_deliverability_count=len(order_section["rows"]),
        age_buckets=order_age_summary(order_section["rows"]),
        date_issues=order_date_issues(orders, report_date),
    )

    if "Invoice.list" in names:
        invoice_issues = []
        overdue, no_due = invoices_overdue(client.list_all("Invoice", {"docstatus": SUBMITTED}), report_date, invoice_issues)
        apply_currency(overdue, currencies, invoice_issues)
        apply_currency(no_due, currencies, invoice_issues)
        sections["invoices_overdue"] = {
            "status": "ok",
            "rule": "customer invoices (receivable), submitted, due_date before the report date, outstanding > 0",
            "rows": overdue,
            "no_due_date": no_due,
            "data_issues": invoice_issues,
        }
    else:
        sections["invoices_overdue"] = {
            "status": "blocked",
            "reason": "this login has no invoice read tool (no Invoice.list; invoice nodes in "
                      "endpoint.make.thread are redacted). Tracked as BUG-31-001",
            "rows": [],
        }

    payments = client.list_all("Payment", {"type": "receive"})
    payment_issues = []
    pay_rows = apply_currency(payments_not_applied(payments, report_date, payment_issues), currencies, payment_issues)
    if "PaymentReceived.list" in names:
        receipt_issues = []
        source_receipts = client.list_all("PaymentReceived")
        quarantined_customers = set()
        add_receipt_hints(pay_rows, validated_receipts(source_receipts, receipt_issues, quarantined_customers), currencies)
        for row in pay_rows:
            affected = None in quarantined_customers or row.get("party_id") in quarantined_customers
            row["receipt_history_coverage"] = "partial" if affected else "complete"
            if affected:
                if row.get("hint") == "no_history":
                    row["hint"] = "unknown"
                # Known history remains useful, but its numeric total is not a complete total.
                row["receipts_applied_total"] = None
                for total in row.get("receipts_applied_by_currency", []):
                    total["applied_total"] = None
        payment_issues.extend(receipt_issues)
        history = {"status": "ok", "source": "PaymentReceived (applied receipts), joined on customer",
                   "coverage": "partial" if receipt_issues else "complete", "data_issues": receipt_issues}
    else:
        history = {"status": "blocked",
                   "reason": "this login has no PaymentReceived read tool, so receipt history is not shown. Tracked as BUG-31-001"}
    sections["payments_not_applied"] = {
        "status": "ok",
        "rule": "incoming (receive), not cancelled, unallocated > 0",
        "rows": pay_rows,
        "summary": payments_summary(pay_rows),
        "receipt_history": history,
        "note": None if payments else "no incoming payments on this instance (expected, instructor 7 Nov)",
        "data_issues": payment_issues,
    }
    for section in sections.values():
        section["coverage"] = ("blocked" if section["status"] != "ok" else
                               "partial" if section.get("data_issues") else "complete")

    return {
        "instance": instance,
        "report_date": report_date.isoformat(),
        "days": days,
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"),
        "sections": sections,
    }


TITLES = {
    "orders_not_invoiced": "Orders not invoiced",
    "invoices_overdue": "Invoices overdue",
    "payments_not_applied": "Payments not applied",
}


def _money(v):
    return money_text(v)


def _cur(r):
    """Currency label for a table cell: the code, or an explicit 'currency not recorded'."""
    return r.get("currency") or UNKNOWN_CURRENCY


def currency_sources(report):
    """Count rows by where their currency came from, across every section."""
    counts = {}
    for sec in report["sections"].values():
        for r in sec.get("rows", []) + sec.get("no_due_date", []):
            key = r.get("currency_source") or "not recorded"
            counts[key] = counts.get(key, 0) + 1
    return counts


def cell(v):
    """Text from a platform record, safe inside a Markdown table cell.

    Escapes backslashes and pipes (so a name like `Acme | North` stays one column) and turns
    CR/LF into spaces (so a line break cannot split the row). None becomes an empty cell.
    """
    if v is None:
        return ""
    text = str(v).replace("\\", "\\\\").replace("|", "\\|")
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip()


def _invoice_rows(rows):
    out = ["| Invoice | Customer | Due | Days overdue | Terms | Total | Paid | Outstanding | Payment | |",
           "|---|---|---|---:|---|---:|---:|---:|---|---|"]
    for r in rows:
        out.append(f"| {cell(r['number'])} | {cell(r['customer'])} | {cell(r['due_date'])} | "
                   f"{r['days_overdue'] if r['days_overdue'] is not None else ''} | {cell(r['payment_terms'])} | "
                   f"{_money(r['grand_total'])} | {_money(r['amount_paid'])} | {_money(r['outstanding'])} {cell(_cur(r))} | "
                   f"{cell(r.get('payment_state'))} | {'fixture' if r['fixture'] else ''} |")
    return out


def _invoice_tables(rows, no_due):
    partly = sum(1 for r in rows if r.get("payment_state") == PARTIALLY_PAID)
    lines = ([f"{partly} of {len(rows)} are **partially paid** (some money received, a balance left); "
              "they show the balance and are aged from the due date.", ""] if partly else [])
    lines += (_invoice_rows(rows) if rows else ["None."]) + [""]
    lines += [f"### Invoices with no due date ({len(no_due)})", ""]
    lines += (_invoice_rows(no_due) if no_due else ["None."]) + [""]
    return lines


HINT_LABELS = {"same_amount": "**check: same amount**", "has_history": "has history", "no_history": "no history",
               "unknown": "history incomplete"}


def _payment_tables(sec):
    rows, hist = sec["rows"], sec.get("receipt_history") or {}
    summ = sec.get("summary") or payments_summary(rows)
    totals = "; ".join(f"{_money(t['unallocated'])} {cell(_cur(t))}" for t in summ["by_currency"])
    several = len(summ["by_currency"]) > 1
    lines = [f"**{summ['count']} payments, {totals} unallocated"
             f"{' (one total per currency; not added together)' if several else ''}.**", "",
             "| Age (days) | Payments | Unallocated |", "|---|---:|---:|"]
    lines += [f"| {b['bucket']} | {b['count']} | {_money(b['unallocated'])} {cell(_cur(b))} |" for b in summ["by_age"]]
    lines += ["", "| Status | Payments | Unallocated |", "|---|---:|---:|"]
    lines += [f"| {cell(b['status'])} | {b['count']} | {_money(b['unallocated'])} {cell(_cur(b))} |" for b in summ["by_status"]]
    for t in summ["by_currency"]:   # largest customers within each currency; amounts are not compared across currencies
        same = [c for c in summ["by_customer"] if c["currency"] == t["currency"]]
        top = same[:5]
        lines += ["", f"Largest customers{' in ' + _cur(t) if several else ''} ({len(top)} of {len(same)}):", "",
                  "| Customer | Payments | Unallocated |", "|---|---:|---:|"]
        lines += [f"| {cell(c.get('customer'))} | {c['count']} | {_money(c['unallocated'])} {cell(_cur(c))} |" for c in top]
    lines.append("")
    if hist.get("status") == "ok":
        lines += [f"Receipt history: {hist['source']}.", ""]
        lines += ["Receipt-history hints compare customer/amount only; they do not allocate money or prove that an invoice is paid.", ""]
        if hist.get("coverage") == "partial":
            lines += ["Receipt-history coverage is partial; invalid receipt data was excluded or diagnosed.", ""]
    else:
        lines += [f"Receipt history: **{hist.get('status', 'blocked').upper()}**: {hist.get('reason', '')}", ""]
    show_hist = hist.get("status") == "ok"
    head = "| Payment | Customer | Date | Age (days) | Bucket | Amount | Unallocated | Status |"
    rule = "|---|---|---|---:|---|---:|---:|---|"
    if show_hist:
        head += " Receipt history |"
        rule += "---|"
    lines += [head + " |", rule + "---|"]
    for r in rows:
        line = (f"| {cell(r['number'])} | {cell(r['customer'])} | {cell(r['payment_date'])} | "
                f"{r['age_days'] if r['age_days'] is not None else ''} | {cell(r.get('age_bucket'))} | {_money(r['amount'])} | "
                f"{_money(r['unallocated'])} {cell(_cur(r))} | {cell(r['status'])}"
                f"{cell(' (' + '; '.join(r['notes']) + ')') if r.get('notes') else ''} |")
        if show_hist:
            same = f" {cell(', '.join(r['same_amount_receipts']))}" if r.get("same_amount_receipts") else ""
            paid_label = "verified paid" if hist.get("coverage") == "partial" else "paid"
            line += f" {HINT_LABELS.get(r.get('hint'), '')}{same} ({r.get('receipts_paid', 0)} {paid_label}) |"
        lines.append(line + f" {'fixture' if r['fixture'] else ''} |")
    return lines


def to_markdown(report):
    lines = [
        f"# Order-to-cash exceptions — {report.get('instance') or ''} {report['report_date']}",
        "",
        f"N = {report['days']} days. Generated {report['generated_at']} (IST). Read-only; nothing was changed.",
        "Rows marked **fixture** look like test data from other seats.",
        "Currency: the record's own, else the customer's currency, else the company default; never converted or added "
        "across currencies. Rows by source: "
        + (", ".join(f"{k} {v}" for k, v in sorted(currency_sources(report).items())) or "none") + ".",
        "",
    ]
    for key, title in TITLES.items():
        sec = report["sections"][key]
        rows = sec["rows"]
        lines.append(f"## {title} ({len(rows) if sec['status'] == 'ok' else sec['status']})")
        lines.append("")
        if sec["status"] != "ok":
            lines += [f"**{sec['status'].upper()}:** {sec['reason']}", ""]
            continue
        lines += [f"Rule: {sec['rule']}.", ""]
        display_issues = [r for r in sec.get("data_issues", [])
                          if not (key == "orders_not_invoiced" and r.get("field") == "date")]
        if display_issues:
            lines += [f"Data validation: **{len(display_issues)} issue(s)**; coverage is partial. "
                      "Valid exceptions are retained; unknown values are not zero.", ""]
            lines += [f"- {cell(r.get('number') or r.get('id') or '(unnamed record)')}: "
                      f"{cell(r['field'])}: {cell(r['reason'])}" for r in display_issues]
            lines.append("")
        if key == "invoices_overdue":
            lines += _invoice_tables(rows, sec.get("no_due_date", []))
            continue
        if key == "orders_not_invoiced":
            # Compute from canonical rows as well for reports built by older callers.
            counts = order_age_summary(rows)
            lines += ["Age basis: **order date**, not a verified deliverable date. "
                      f"Deliverability unverified: **{len(rows)}** order(s), already included above; not an extra total.",
                      "Oldest first; equal ages grouped by currency (unknown last), then value descending within each currency.",
                      "Order-age buckets (exception rows only): "
                      + "; ".join(f"{label}: {count}" for label, count in counts.items()) + ".",
                      "The strict age > N filter still applies; buckets do not add younger orders.", ""]
            issues = sec.get("date_issues", [])
            if issues:
                lines += [f"### Orders with unusable dates ({len(issues)})", "",
                          "Excluded from age-based exception rows and bucket counts; review these date issues separately.", ""]
                lines += [f"- {cell(r.get('number') or r.get('id') or '(unnamed order)')}: {cell(r['reason'])}" for r in issues]
                lines += ["", "### Age-based exception rows", ""]
        if not rows:
            lines += [f"None{' (' + sec['note'] + ')' if sec.get('note') else ''}.", ""]
            continue
        if key == "orders_not_invoiced":
            lines += ["| Order | Customer | Date | Age (days) | Invoiced | Delivered | Total | |",
                      "|---|---|---|---:|---|---|---:|---|"]
            for r in rows:
                lines.append(f"| {cell(r['number'])} | {cell(r['customer'])} | {cell(r['order_date'])} | {r['age_days']} | "
                             f"{cell(r['invoiced_status'])} | {cell(r['delivered_status'])} | {_money(r['grand_total'])} {cell(_cur(r))} | "
                             f"{'fixture' if r['fixture'] else ''} |")
        else:
            lines += _payment_tables(sec)
        lines.append("")
    return "\n".join(lines)
