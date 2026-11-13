from data_steward import dedupe, proposals
from data_steward.mcp_client import McpError


def party(pid, name, **fields):
    return {"id": pid, "name": name, "privacy_state": "normal", "company_id": "c1", "roles": [], **fields}


class FakeClient:
    """`call` over in-memory tables, paging with limit and offset. A table missing from `tables` is refused, as
    McpClient.call refuses a tool it cannot use. `ignores` names tables whose filter has no effect, `no_offset` those
    whose offset has no effect, `cap` the server's page size, and `total` what the reply reports as its total
    ("filtered", "table" for the unfiltered size, or None)."""

    def __init__(self, tables, ignores=(), no_offset=(), cap=None, total="filtered"):
        self.tables, self.ignores, self.no_offset, self.cap, self.total = tables, set(ignores), set(no_offset), cap, total
        self.calls = []

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        table = name.removesuffix(".list")
        if table not in self.tables:
            raise McpError("refused", f"{name} is not available")
        args = dict(arguments)
        limit, offset = args.pop("limit"), args.pop("offset")
        rows = self.tables[table]
        if table not in self.ignores:
            rows = [r for r in rows if all(r.get(k) == v for k, v in args.items())]
        start = 0 if table in self.no_offset else offset
        page = rows[start:start + min(limit, self.cap or limit)]
        total = {"filtered": len(rows), "table": len(self.tables[table]), None: None}[self.total]
        return {"data": page, "total": total}


TABLES = {
    "SalesOrder": [{"id": "so1", "party_id": "p1"}, {"id": "so2", "party_id": "p1"}, {"id": "so3", "party_id": "p2"}],
    "Payment": [],
    "GLEntry": [{"id": "g1", "party_id": "p1"}],
    "Lead": [],
    "Deal": [{"id": "d1", "party_id": "p2", "contact_id": "p1"}],
    "PartyRelationship": [{"id": "r1", "from_party_id": "p3", "to_party_id": "p1"}],
    "StockLedger": [{"id": "s1", "item_id": "i1"}, {"id": "s2", "item_id": "i1"}],
}


def test_reference_counts_add_every_link_from_either_side():
    counts = proposals.count_references(FakeClient(TABLES), "party", "p1")
    assert counts["total"] == 5  # 2 orders, 1 ledger entry, 1 deal as contact, 1 relationship pointing at p1
    assert counts["by_source"]["Deal.list contact_id"] == 1
    assert counts["by_source"]["Payment.list party_id"] == 0  # read and empty is zero, not unknown
    assert proposals.count_references(FakeClient(TABLES), "item", "i1") == {
        "total": 2, "by_source": {"StockLedger.list item_id": 2}}


def test_a_source_that_cannot_be_read_is_unknown_never_zero():
    tables = {k: v for k, v in TABLES.items() if k != "Lead"}
    counts = proposals.count_references(FakeClient(tables), "party", "p1")
    assert counts["by_source"]["Lead.list party_id"] is None
    assert counts["by_source"]["SalesOrder.list party_id"] == 2
    assert counts["total"] is None


def test_an_ignored_filter_or_a_cut_off_read_is_unknown():
    ignored = proposals.count_references(FakeClient(TABLES, ignores={"SalesOrder"}), "party", "p1")
    assert ignored["by_source"]["SalesOrder.list party_id"] is None  # so3 belongs to p2: the filter did nothing
    assert ignored["total"] is None
    client = FakeClient(TABLES, no_offset={"GLEntry"})
    no_offset = proposals.count_references(client, "party", "p1")
    assert no_offset["by_source"]["GLEntry.list party_id"] is None  # the same row on every page
    assert sum(name == "GLEntry.list" for name, _ in client.calls) == 2  # stopped at the repeat, not the ceiling


def test_rows_are_counted_whatever_the_total_says_and_however_the_server_pages(monkeypatch):
    for total in ("table", None):  # a filter that narrows the rows but not the total, or no total at all
        assert proposals.count_references(FakeClient(TABLES, total=total), "party", "p1")["total"] == 5
    many = {**TABLES, "GLEntry": [{"id": f"g{n}", "party_id": "p1"} for n in range(450)]}
    capped = FakeClient(many, cap=50)  # the server returns fewer rows than asked for, on every page
    assert proposals.count_references(capped, "party", "p1")["by_source"]["GLEntry.list party_id"] == 450
    monkeypatch.setattr(proposals, "LIST_ALL_MAX_ROWS", 400)
    assert proposals.count_references(FakeClient(many), "party", "p1")["by_source"]["GLEntry.list party_id"] is None


def test_a_reply_without_rows_is_unknown():
    class NoRows(FakeClient):
        def call(self, name, arguments):
            return {"text": "temporarily unavailable"}

    assert proposals.count_references(NoRows(TABLES), "item", "i1")["total"] is None


def test_field_differences_list_disagreements_and_one_sided_fields():
    a = party("p1", "Halden Roe", email="Ops@Halden.example ", phone="5552013344", website="N/A", tags=[],
              created_at="2026-01-01", _display="Halden Roe")
    b = party("p2", "Halden & Roe", email="ops@halden.example", phone="", website="halden.example",
              created_at="2026-02-01")
    diffs = {d["field"]: d for d in proposals.field_differences(a, b)}
    assert "email" not in diffs  # case and outer spaces only
    assert diffs["name"] == {"field": "name", "kind": "differs", "a": "Halden Roe", "b": "Halden & Roe"}
    assert diffs["phone"] == {"field": "phone", "kind": "only_a", "a": "5552013344", "b": None}
    assert diffs["website"] == {"field": "website", "kind": "only_b", "a": None, "b": "halden.example"}
    assert not {"id", "created_at", "company_id", "_display", "tags"} & diffs.keys()


def test_inner_spacing_differs_outside_names():
    # The matcher reads codes and emails with their inner spaces, so a conflict it caps on must be listed here.
    a = party("p1", "Halden\nRoe", customer_code="HR 1")
    b = party("p2", "Halden Roe", customer_code="HR  1")
    assert [d["field"] for d in proposals.field_differences(a, b)] == ["customer_code"]


def test_redacted_and_sensitive_fields_are_never_shown():
    a = party("p1", "Halden Roe", pan="AAAPL1234C", gst_no="27AAAPL1234C1Z5", _redacted_fields=["gst_no"])
    b = party("p2", "Halden Roe", pan="BBBPL9876D", gst_no="29BBBPL9876D1Z2")
    assert proposals.field_differences(a, b) == []


def test_gst_number_is_never_shown_even_unredacted():
    a = party("p1", "Halden Roe", gst_no="27AAAPL1234C1Z5", gstin="27AAAPL1234C1Z5")
    b = party("p2", "Halden Roe", gst_no="29BBBPL9876D1Z2", gstin="29BBBPL9876D1Z2")
    assert proposals.field_differences(a, b) == []


def test_survivor_rule_order():
    old = party("p2", "Kestrel", created_at="2025-01-01", email="k@kestrel.example")
    new = party("p1", "Kestrel", created_at="2026-01-01", email="k@kestrel.example", phone="5552013344")
    assert proposals.suggest_survivor(old, new, 1, 3) == {"id": "p1", "rule": "more references", "skipped": []}
    assert proposals.suggest_survivor(old, new, 2, 2)["rule"] == "older"
    assert proposals.suggest_survivor(old, new) == {"id": "p2", "rule": "older", "skipped": ["references"]}
    assert proposals.suggest_survivor(old, new, 5, None)["skipped"] == ["references"]  # one side unknown
    undated = {**old, "created_at": None}
    assert proposals.suggest_survivor(undated, new) == {"id": "p1", "rule": "more fields filled",
                                                         "skipped": ["references", "age"]}
    twin = {**new, "id": "p0"}
    assert proposals.suggest_survivor(new, twin, 0, 0)["id"] == "p0"  # tie on everything: smaller id


def test_proposals_count_references_for_proposed_pairs_only():
    rows = [party("p1", "Gristmill Foods", email="info@gristmill.example", created_at="2026-01-01"),
            party("p2", "Gristmill Foods Ltd", email="info@gristmill.example", created_at="2026-03-01"),
            party("p3", "Larkspur Dental", created_at="2026-01-01"),
            party("p4", "Larkspur Dental", created_at="2026-02-01")]
    result = dedupe.find_duplicates("party", rows)
    assert [(p["ids"], p["band"]) for p in result["pairs"]] == [(["p1", "p2"], "propose"), (["p3", "p4"], "review")]
    assert proposals.proposed_ids(result) == ["p1", "p2"]
    client = FakeClient(TABLES)
    refs = {rid: proposals.count_references(client, "party", rid) for rid in proposals.proposed_ids(result)}
    out = proposals.build_proposals(result, rows, refs)
    assert [p["id"] for p in out] == [p["id"] for p in result["pairs"]]
    assert out[0]["survivor"] == {"id": "p1", "rule": "more references", "skipped": []}  # 5 links against 2
    assert out[0]["references"]["p2"]["total"] == 2
    assert out[1]["references"] is None
    assert out[1]["survivor"] == {"id": "p3", "rule": "older", "skipped": ["references"]}
    assert {args[field] for _, args in client.calls for field in args if field.endswith("_id")} == {"p1", "p2"}


def test_a_review_pair_never_uses_reference_counts_even_when_its_ids_were_counted():
    # p1-p2 and p2-p3 share an email and a name; p1-p3 share only the name, so that pair is review.
    rows = [party("p1", "Gristmill Foods", email="info@gristmill.example", created_at="2026-03-01"),
            party("p2", "Gristmill Foods", email="info@gristmill.example", phone="5552013344",
                  created_at="2026-02-01"),
            party("p3", "Gristmill Foods", phone="5552013344", created_at="2026-01-01")]
    result = dedupe.find_duplicates("party", rows)
    bands = {tuple(p["ids"]): p["band"] for p in result["pairs"]}
    assert bands == {("p1", "p2"): "propose", ("p2", "p3"): "propose", ("p1", "p3"): "review"}
    refs = {"p1": {"total": 9, "by_source": {}}, "p2": {"total": 0, "by_source": {}},
            "p3": {"total": 0, "by_source": {}}}
    out = {tuple(p["ids"]): p for p in proposals.build_proposals(result, rows, refs)}
    assert out[("p1", "p2")]["survivor"]["rule"] == "more references"  # a total of 0 is a count, not unknown
    assert out[("p1", "p3")]["survivor"] == {"id": "p3", "rule": "older", "skipped": ["references"]}


def test_a_private_copy_of_a_repeated_id_never_reaches_a_proposal():
    rows = [party("p1", "Gristmill Foods", email="secret@private.example", privacy_state="restricted"),
            party("p1", "Gristmill Foods", email="info@gristmill.example"),
            party("p2", "Gristmill Foods", email="info@gristmill.example", phone="5552013344")]
    result = dedupe.find_duplicates("party", rows)
    out = proposals.build_proposals(result, rows)
    assert len(out) == 1 and "secret@private.example" not in repr(out)
