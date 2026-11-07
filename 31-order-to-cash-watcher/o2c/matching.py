"""Candidate matches for payments that are not applied to any invoice.

These are suggestions for a person to check, never allocations. The agent does not
allocate a payment. Today the only documents our login can read are sales orders, so
candidates come from invoiced or partially invoiced orders of the same customer. Once
Invoice.list is granted (BUG-31-001), pass invoices instead, with `outstanding` as the amount.
"""

INVOICED = ("invoiced", "partially_invoiced")


def order_documents(orders):
    """Submitted, (partly) invoiced orders as matchable documents."""
    return [
        {"kind": "order", "number": o.get("number"), "id": o.get("id"), "party_id": o.get("party_id"),
         "date": str(o.get("date") or "")[:10] or None, "amount": round(float(o.get("grand_total") or 0), 2)}
        for o in orders
        if o.get("docstatus") == 1 and o.get("invoiced_status") in INVOICED and o.get("party_id")
    ]


def invoice_documents(invoices):
    """Submitted invoices with a balance left, for when Invoice.list is available."""
    return [
        {"kind": "invoice", "number": i.get("number"), "id": i.get("id"), "party_id": i.get("party_id"),
         "date": str(i.get("date") or "")[:10] or None, "amount": round(float(i.get("outstanding") or 0), 2)}
        for i in invoices
        if i.get("docstatus") == 1 and float(i.get("outstanding") or 0) > 0 and i.get("party_id")
    ]


def candidate_matches(payment_rows, documents, limit=3, tolerance=0.01):
    """For each unapplied payment row (from report.payments_not_applied), list same-customer
    documents. Exact amount matches come first, then the closest amounts."""
    by_party = {}
    for d in documents:
        by_party.setdefault(d["party_id"], []).append(d)
    out = []
    for p in payment_rows:
        amount = p["unallocated"]
        docs = by_party.get(p.get("party_id"), [])
        ranked = sorted(docs, key=lambda d: (abs(d["amount"] - amount) > tolerance, abs(d["amount"] - amount), d["number"] or ""))
        out.append({
            "payment": p["number"],
            "customer": p.get("customer"),
            "unallocated": amount,
            "candidates": [{**d, "exact": abs(d["amount"] - amount) <= tolerance} for d in ranked[:limit]],
        })
    return out


def summary(matches):
    return {
        "payments": len(matches),
        "with_candidates": sum(1 for m in matches if m["candidates"]),
        "with_exact_match": sum(1 for m in matches if any(c["exact"] for c in m["candidates"])),
    }
