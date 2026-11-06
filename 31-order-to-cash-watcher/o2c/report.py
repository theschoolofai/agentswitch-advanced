"""Daily order-to-cash exception report.

The rules are pure functions over rows so they can be tested without the platform.
"""
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
SUBMITTED = 1
CANCELLED = 2
NOT_INVOICED = ("unbilled", "partially_invoiced")
FIXTURE_MARKERS = ("test", "harness", "fixture")


def today_ist():
    return datetime.now(IST).date()


def looks_like_fixture(row):
    text = " ".join(str(row.get(k) or "") for k in ("_party_id_display", "notes", "_deal_id_display")).lower()
    return any(m in text for m in FIXTURE_MARKERS)


def _as_date(value):
    return date.fromisoformat(str(value)[:10]) if value else None


def orders_not_invoiced(orders, report_date, days):
    """Submitted orders not (fully) invoiced more than `days` days after the order date."""
    out = []
    for o in orders:
        if o.get("docstatus") != SUBMITTED or o.get("invoiced_status") not in NOT_INVOICED:
            continue
        order_date = _as_date(o.get("date"))
        if order_date is None:
            continue
        age = (report_date - order_date).days
        if age <= days:
            continue
        out.append({
            "number": o.get("number"),
            "id": o.get("id"),
            "customer": o.get("_party_id_display"),
            "order_date": order_date.isoformat(),
            "age_days": age,
            "invoiced_status": o.get("invoiced_status"),
            "delivered_status": o.get("delivered_status"),
            "grand_total": o.get("grand_total"),
            "currency": o.get("currency_code"),
            "fixture": looks_like_fixture(o),
        })
    return sorted(out, key=lambda r: (-r["age_days"], r["number"] or ""))


def payments_not_applied(payments, report_date):
    """Incoming payments (draft or submitted, not cancelled) with money not yet allocated to an invoice.

    Drafts are kept: the instructor counts all 40 Suryodaya receive payments as unallocated.
    The status column shows which ones are drafts.
    """
    out = []
    for p in payments:
        if p.get("type") != "receive" or p.get("docstatus") == CANCELLED:
            continue
        unallocated = round(float(p.get("unallocated") or 0), 2)
        if unallocated <= 0:
            continue
        paid = _as_date(p.get("date"))
        out.append({
            "number": p.get("number"),
            "id": p.get("id"),
            "customer": p.get("_party_id_display"),
            "payment_date": paid.isoformat() if paid else None,
            "age_days": (report_date - paid).days if paid else None,
            "amount": p.get("amount"),
            "unallocated": unallocated,
            "status": p.get("status"),
            "fixture": looks_like_fixture(p),
        })
    return sorted(out, key=lambda r: (-(r["age_days"] or 0), r["number"] or ""))


def build(client, report_date=None, days=7, instance=None):
    report_date = report_date or today_ist()
    sections = {}

    orders = client.list_all("SalesOrder", {"docstatus": SUBMITTED})
    sections["orders_not_invoiced"] = {
        "status": "ok",
        "rule": f"submitted, invoiced_status in {list(NOT_INVOICED)}, order date more than {days} days ago",
        "rows": orders_not_invoiced(orders, report_date, days),
    }

    names = client.tool_names()
    if "Invoice.list" in names:
        sections["invoices_overdue"] = {"status": "todo", "reason": "Invoice.list is now available; rule not written yet", "rows": []}
    else:
        sections["invoices_overdue"] = {
            "status": "blocked",
            "reason": "this login has no invoice read tool (no Invoice.list; invoice nodes in endpoint.make.thread are redacted)",
            "rows": [],
        }

    payments = client.list_all("Payment", {"type": "receive"})
    sections["payments_not_applied"] = {
        "status": "ok",
        "rule": "incoming (receive), not cancelled, unallocated > 0",
        "rows": payments_not_applied(payments, report_date),
    }

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
    return f"{v:,.2f}" if isinstance(v, (int, float)) else ""


def to_markdown(report):
    lines = [
        f"# Order-to-cash exceptions — {report.get('instance') or ''} {report['report_date']}",
        "",
        f"N = {report['days']} days. Generated {report['generated_at']} (IST). Read-only; nothing was changed.",
        "Rows marked **fixture** look like test data from other seats.",
        "",
    ]
    for key, title in TITLES.items():
        sec = report["sections"][key]
        rows = sec["rows"]
        lines.append(f"## {title} ({len(rows)})")
        lines.append("")
        if sec["status"] != "ok":
            lines += [f"**{sec['status'].upper()}:** {sec['reason']}", ""]
            continue
        lines += [f"Rule: {sec['rule']}.", ""]
        if not rows:
            lines += ["None.", ""]
            continue
        if key == "orders_not_invoiced":
            lines += ["| Order | Customer | Date | Age (days) | Invoiced | Delivered | Total | |",
                      "|---|---|---|---:|---|---|---:|---|"]
            for r in rows:
                lines.append(f"| {r['number']} | {r['customer'] or ''} | {r['order_date']} | {r['age_days']} | "
                             f"{r['invoiced_status']} | {r['delivered_status'] or ''} | {_money(r['grand_total'])} {r['currency'] or ''} | "
                             f"{'fixture' if r['fixture'] else ''} |")
        else:
            lines += ["| Payment | Customer | Date | Age (days) | Amount | Unallocated | Status | |",
                      "|---|---|---|---:|---:|---:|---|---|"]
            for r in rows:
                lines.append(f"| {r['number']} | {r['customer'] or ''} | {r['payment_date'] or ''} | {r['age_days'] if r['age_days'] is not None else ''} | "
                             f"{_money(r['amount'])} | {_money(r['unallocated'])} | {r['status']} | {'fixture' if r['fixture'] else ''} |")
        lines.append("")
    return "\n".join(lines)
