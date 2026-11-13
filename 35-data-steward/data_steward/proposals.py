"""Turn scored pairs into merge proposals: a suggested survivor, the fields the two records disagree on, and how many
records point at each side. Suggestions only: a person decides, and nothing here changes a record.

Reference counts are the one part that reads the platform, through `McpClient.call` (read-only tools only).
"""
from .dedupe import ORDINARY_PRIVACY, blank
from .mcp_client import LIST_ALL_MAX_ROWS, McpError

PAGE = 200

# Records that point at a party or an item, as (tool, filter field). Every link counts, from either side of a
# relationship: a merge would have to move each one.
REFERENCES = {
    "party": (("SalesOrder.list", "party_id"), ("Payment.list", "party_id"), ("GLEntry.list", "party_id"),
              ("Lead.list", "party_id"), ("Deal.list", "party_id"), ("Deal.list", "contact_id"),
              ("PartyRelationship.list", "from_party_id"), ("PartyRelationship.list", "to_party_id")),
    "item": (("StockLedger.list", "item_id"),),
}

# Bookkeeping, not content: these always differ between two records and say nothing about which one to keep.
META = {"id", "company_id", "created_at", "created_by", "updated_at", "updated_by"}
# Never compared or shown, even when a system does not mark them redacted: a report goes to people.
SENSITIVE = {"tax_id", "pan", "tin", "gst_no", "gstin", "bank_details", "vendor_bank_account_number"}


def _count_rows(client, tool: str, field: str, rid: str) -> int | None:
    """Filtered rows, counted page by page until an empty page. The reported total is not used: on some systems a
    filter narrows the rows but not the total, and a short page may only mean the server caps the page size.

    None when the count cannot be trusted: a reply without a rows list, a row without the filter value (the filter
    was ignored), a row seen twice (the offset was ignored), or more rows than the ceiling.
    """
    count, offset, seen = 0, 0, set()
    while True:
        try:
            res = client.call(tool, {"limit": PAGE, "offset": offset, field: rid})
        except McpError:
            return None
        batch = res.get("data") if isinstance(res, dict) else res
        if not isinstance(batch, list):
            return None
        if not batch:
            return count
        for row in batch:
            if not isinstance(row, dict) or str(row.get(field)) != rid:
                return None
            if row.get("id") is not None:
                if str(row["id"]) in seen:
                    return None
                seen.add(str(row["id"]))
        count += len(batch)
        offset += len(batch)
        if count > LIST_ALL_MAX_ROWS:
            return None


def count_references(client, entity: str, rid: str) -> dict:
    """{"total": n or None, "by_source": {"Tool.list field": n or None}}. A source that cannot be read is None,
    never 0, and then so is the total."""
    by_source = {f"{tool} {field}": _count_rows(client, tool, field, rid) for tool, field in REFERENCES[entity]}
    known = by_source.values()
    return {"total": None if None in known else sum(known), "by_source": by_source}


def _hidden(a, b) -> set[str]:
    redacted = set()
    for row in (a, b):
        marked = row.get("_redacted_fields")
        if isinstance(marked, list):
            redacted.update(f for f in marked if isinstance(f, str))
    return SENSITIVE | redacted


def _fields(row, hidden) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_") and k not in META and k not in hidden}


def _empty(value) -> bool:
    return blank(value) or value in ([], {})


def _same(key, va, vb) -> bool:
    """Case and outer spaces never make a difference. Inner spacing does only outside names: the matcher reads a
    code or an email with its inner spaces, so "PW 1" and "PW  1" conflict there and must differ here."""
    if isinstance(va, str) and isinstance(vb, str):
        if key == "name":
            return " ".join(va.split()).casefold() == " ".join(vb.split()).casefold()
        return va.strip().casefold() == vb.strip().casefold()
    return va == vb


def field_differences(a, b) -> list[dict]:
    """Fields where the records disagree: both filled and different, or filled on one side only. See _same
    for what counts as the same value. Redacted and sensitive fields are left out, by name."""
    hidden = _hidden(a, b)
    fa, fb = _fields(a, hidden), _fields(b, hidden)
    out = []
    for key in sorted(fa.keys() | fb.keys()):
        va, vb = fa.get(key), fb.get(key)
        ea, eb = _empty(va), _empty(vb)
        if ea and eb:
            continue
        if ea or eb:
            out.append({"field": key, "kind": "only_b" if ea else "only_a", "a": None if ea else va,
                        "b": None if eb else vb})
        elif not _same(key, va, vb):
            out.append({"field": key, "kind": "differs", "a": va, "b": vb})
    return out


def _filled(row, hidden) -> int:
    return sum(not _empty(v) for v in _fields(row, hidden).values())


def suggest_survivor(a, b, refs_a=None, refs_b=None) -> dict:
    """More references, then older, then more fields filled, then the smaller id. A step whose value is unknown on
    either side is skipped and named in `skipped`, so the reader sees what the suggestion did not use."""
    ida, idb = str(a["id"]), str(b["id"])
    skipped = []
    if refs_a is None or refs_b is None:
        skipped.append("references")
    elif refs_a != refs_b:
        return {"id": ida if refs_a > refs_b else idb, "rule": "more references", "skipped": skipped}
    ca, cb = a.get("created_at"), b.get("created_at")
    if blank(ca) or blank(cb):
        skipped.append("age")
    elif str(ca) != str(cb):
        # ISO timestamps from one system sort as text.
        return {"id": ida if str(ca) < str(cb) else idb, "rule": "older", "skipped": skipped}
    hidden = _hidden(a, b)
    na, nb = _filled(a, hidden), _filled(b, hidden)
    if na != nb:
        return {"id": ida if na > nb else idb, "rule": "more fields filled", "skipped": skipped}
    return {"id": min(ida, idb), "rule": "smaller id", "skipped": skipped}


def lookup(result: dict, rows: list[dict]) -> dict[str, dict]:
    """id -> the row the matcher used: the first copy of each id, after the parties it withholds for privacy, so a
    private copy of a repeated id never supplies a name or a field."""
    by_id = {}
    for row in rows:
        if result["entity"] == "party" and row.get("privacy_state") != ORDINARY_PRIVACY:
            continue
        by_id.setdefault(str(row["id"]), row)
    return by_id


def build_proposals(result: dict, rows: list[dict], refs: dict | None = None) -> list[dict]:
    """One proposal per listed pair of a `find_duplicates` result, in the result's order.

    refs: id -> `count_references` result, for the ids of proposed pairs. Review pairs are not counted (the plan
    reads references for proposed pairs only), so their survivor suggestion skips the reference step, even when an id
    of theirs was counted for a proposed pair.
    """
    by_id = lookup(result, rows)
    refs = refs or {}
    out = []
    for pair in result["pairs"]:
        ida, idb = pair["ids"]
        a, b = by_id[ida], by_id[idb]
        proposed = pair["band"] == "propose"
        ra, rb = (refs.get(ida), refs.get(idb)) if proposed else (None, None)
        out.append({
            **pair,
            "names": {ida: a.get("name"), idb: b.get("name")},
            "references": {ida: ra, idb: rb} if proposed else None,
            "survivor": suggest_survivor(a, b, ra and ra["total"], rb and rb["total"]),
            "differences": field_differences(a, b),
        })
    return out


def proposed_ids(result: dict) -> list[str]:
    """The ids whose references are counted: both sides of every proposed pair, once each."""
    return sorted({rid for p in result["pairs"] if p["band"] == "propose" for rid in p["ids"]})
