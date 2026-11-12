"""Candidate matches for payments that are not applied to any invoice.

These are suggestions for a person to check, never allocations. The agent does not
allocate a payment. Today the only documents our login can read are sales orders, so
candidates come from invoiced or partially invoiced orders of the same customer. Once
Invoice.list is granted (BUG-31-001), pass invoices instead, with `outstanding` as the amount.
"""

from . import report
from .values import business_date, money_number

INVOICED = ("invoiced", "partially_invoiced")


def _doc_currency(row, currencies):
    return report.resolve_currency(row.get("currency_code"), row.get("party_id"), row.get("company_id"), currencies)[0]


def _amount(value):
    try:
        return money_number(value)
    except ValueError:
        return None


def _date(value):
    try:
        day = business_date(value)
        return day.isoformat() if day else None
    except ValueError:
        return None


def order_documents(orders, currencies=None):
    """Submitted, (partly) invoiced orders as matchable documents."""
    return [
        {"kind": "order", "number": o.get("number"), "id": o.get("id"), "party_id": o.get("party_id"),
         "date": _date(o.get("date")), "amount": _amount(o.get("grand_total")),
         "currency": _doc_currency(o, currencies)}
        for o in orders
        if o.get("docstatus") == 1 and o.get("invoiced_status") in INVOICED and o.get("party_id")
        and _amount(o.get("grand_total")) is not None
    ]


def invoice_documents(invoices, currencies=None):
    """Submitted customer invoices with a balance left. Supplier bills (direction "payable") are not
    matchable against a customer's payment."""
    return [
        {"kind": "invoice", "number": i.get("number"), "id": i.get("id"), "party_id": i.get("party_id"),
         "date": _date(i.get("date")), "amount": _amount(i.get("outstanding")),
         "currency": _doc_currency(i, currencies)}
        for i in invoices
        if i.get("docstatus") == 1 and _amount(i.get("outstanding")) is not None
        and _amount(i.get("outstanding")) > 0 and i.get("party_id")
        and i.get("direction", "receivable") == "receivable"
    ]


def candidate_matches(payment_rows, documents, limit=3, tolerance=0.01):
    """For each unapplied payment row (from report.payments_not_applied), list same-customer
    documents. Exact amount matches come first, then the closest amounts.

    "Same amount" also needs the same currency: 50 USD is not the same as 50 INR. Documents in a
    different currency from the payment rank after those in the same currency."""
    by_party = {}
    for d in documents:
        by_party.setdefault(d["party_id"], []).append(d)
    out = []
    for p in payment_rows:
        amount, cur = p["unallocated"], p.get("currency")
        docs = by_party.get(p.get("party_id"), [])

        def exact(d):
            return abs(d["amount"] - amount) <= tolerance and d.get("currency") == cur

        ranked = sorted(docs, key=lambda d: (not exact(d), d.get("currency") != cur, abs(d["amount"] - amount), d["number"] or ""))
        out.append({
            "payment": p["number"],
            "customer": p.get("customer"),
            "unallocated": amount,
            "currency": cur,
            "candidates": [{**d, "exact": exact(d)} for d in ranked[:limit]],
        })
    return out


def summary(matches):
    return {
        "payments": len(matches),
        "with_candidates": sum(1 for m in matches if m["candidates"]),
        "with_exact_match": sum(1 for m in matches if any(c["exact"] for c in m["candidates"])),
    }
