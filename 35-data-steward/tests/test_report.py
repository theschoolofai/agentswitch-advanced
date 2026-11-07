import datetime as dt
import http.client
import json
import os
import stat

import pytest

from data_steward import config, report
from data_steward.mcp_client import RowPage


def party(pid, name, **fields):
    return {"id": pid, "name": name, "privacy_state": "normal", "company_id": "c1", "roles": [],
            "created_at": f"2026-01-0{pid[-1]}", **fields}


PARTIES = [
    party("p1", "Gristmill Foods", email="info@gristmill.example"),
    party("p2", "Gristmill Foods Ltd", email="info@gristmill.example", website="gristmill.example"),
    party("p3", "Larkspur | Dental\nClinic"),
    party("p4", "Larkspur | Dental Clinic"),
    party("p5", "[qa-run 3] Halden Roe"),
    party("p6", "[qa-run 4] Halden Roe"),
    party("p7", "Ottervale Kennels", email="hidden@ottervale.example", privacy_state="restricted"),
    party("p8", "Ottervale Kennels", email="hidden@ottervale.example"),
    party("p9", "Brightwater Co", email="desk@brightwater.example", type="individual"),
    party("p0", "Brightwater Co", email="desk@brightwater.example", type="organization"),
]
ITEMS = [{"id": "i1", "name": "Pallet Wrap", "code": "PW-1", "company_id": "c1", "uom": "ea", "variants": []}]
REFS = {"SalesOrder": [{"id": "so1", "party_id": "p2"}], "GLEntry": [], "Payment": [], "Lead": [], "Deal": [],
        "PartyRelationship": [], "StockLedger": []}


class FakeClient:
    def __init__(self, tables, refs=REFS, cut_off=(), fail_refs=None):
        self.tables, self.refs, self.cut_off, self.fail_refs = tables, refs, set(cut_off), fail_refs

    def list_all(self, entity):
        page = RowPage(self.tables[entity])
        page.total = len(page) + (10 if entity in self.cut_off else 0)
        page.truncated = entity in self.cut_off
        return page

    def call(self, name, arguments):
        if self.fail_refs:
            raise self.fail_refs
        args = dict(arguments)
        limit, offset = args.pop("limit"), args.pop("offset")
        rows = [r for r in self.refs[name.removesuffix(".list")] if all(r.get(k) == v for k, v in args.items())]
        return {"data": rows[offset:offset + limit]}


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """main() against a fake client; returns (json report, markdown, stdout)."""
    local = tmp_path / "local"
    local.mkdir()
    (local / "test-tags.txt").write_text("# confirmed in the read\n\nqa-run  made-up test runs, read of 1 Nov\n")
    monkeypatch.setattr(config, "LOCAL_DIR", local)
    monkeypatch.setattr(config, "today", lambda: dt.date(2026, 11, 3))
    monkeypatch.setattr(config, "platform", lambda: None)
    monkeypatch.setattr(report, "Session", lambda instance: instance)

    def _run(client=None, labels=None, argv=(), instance="keystone"):
        client = client or FakeClient({"Party": PARTIES, "Item": ITEMS})
        monkeypatch.setattr(report, "McpClient", lambda session: client)
        if labels is not None:
            (local / "dedupe-labels.json").write_text(json.dumps(labels))
        assert report.main(list(argv)) == 0
        return (json.loads((local / f"dedupe-{instance}.json").read_text()), (local / f"dedupe-{instance}.md").read_text(),
                capsys.readouterr().out)

    return _run


def section(rep, entity="party"):
    return rep["sections"][entity]


def test_report_lists_bands_exclusions_and_counts(run):
    rep, md, _ = run()
    pairs = {tuple(p["ids"]): p for p in section(rep)["proposals"]}
    assert pairs[("p1", "p2")]["band"] == "propose"
    assert pairs[("p1", "p2")]["survivor"] == {"id": "p2", "rule": "more references", "skipped": []}
    assert pairs[("p3", "p4")]["band"] == "review"
    assert pairs[("p5", "p6")]["tagged"]
    assert [(p["ids"], p["reason"]) for p in section(rep)["excluded"]] == [(["p0", "p9"],
                                                                            "individual and organisation")]
    assert section(rep)["counts"]["withheld_private"] == 1
    assert section(rep)["table"] == {"rows": 10, "total": 10, "cut_off": False}
    assert rep["system"] == "keystone" and rep["date"] == "2026-11-03"
    assert "by older (skipped references: not counted for review pairs)" in md
    assert "### Proposed merges (1)" in md and "### Test records (1)" in md and "### Never proposed (1)" in md


def test_private_records_never_reach_the_report(run):
    rep, md, out = run()
    for text in (json.dumps(rep), md, out):
        assert "hidden@ottervale.example" not in text and "p7" not in text


def test_stdout_is_counts_only_and_tagged_pairs_are_left_out_of_band_totals(run):
    _, _, out = run()
    summary = json.loads(out[:out.rindex("}") + 1])
    assert summary["party"]["bands"] == {"propose": 1, "review": 1}
    assert summary["party"]["tagged_pairs"] == 1
    assert summary["party"]["excluded"] == {"individual and organisation": 1}
    for value in ("Gristmill", "info@gristmill.example", "Larkspur", "Halden", "Brightwater"):
        assert value not in out


def test_two_runs_on_the_same_data_write_the_same_files(run):
    first = run()
    assert run()[:2] == first[:2]


def test_report_files_are_readable_by_their_owner_only(run):
    for name in ("dedupe-keystone.json", "dedupe-keystone.md"):
        (config.LOCAL_DIR / name).write_text("an older report")
        os.chmod(config.LOCAL_DIR / name, 0o644)
    run()
    for name in ("dedupe-keystone.json", "dedupe-keystone.md"):
        assert stat.S_IMODE((config.LOCAL_DIR / name).stat().st_mode) == 0o600


def test_a_symlink_in_place_of_the_report_is_replaced_not_followed(run, tmp_path):
    target = tmp_path / "public.json"
    target.write_text("untouched")
    (config.LOCAL_DIR / "dedupe-keystone.json").symlink_to(target)
    run()
    report_file = config.LOCAL_DIR / "dedupe-keystone.json"
    assert target.read_text() == "untouched"
    assert not report_file.is_symlink() and stat.S_IMODE(report_file.stat().st_mode) == 0o600
    assert not [f for f in config.LOCAL_DIR.iterdir() if f.name.startswith(".")]  # no temporary file left


def test_ids_cannot_break_out_of_their_code_span(run):
    _, md, _ = run(labels={"x` ![i](https://tracker.example/p.png) `y": "accepted"})
    assert "`x' ![i](https://tracker.example/p.png) 'y`" in md and "` ![i](" not in md


def test_labels_are_shown_and_change_nothing(run):
    plain, _, _ = run()
    rep, md, _ = run(labels={"party:p1:p2": "accepted", "party:p3:p4": {"label": "rejected", "note": "two clinics"},
                             "party:x:y": "accepted"})
    labelled = {p["id"]: p for p in section(rep)["proposals"]}
    for p in section(plain)["proposals"]:
        assert {k: v for k, v in labelled[p["id"]].items() if k != "label"} == {k: v for k, v in p.items()
                                                                               if k != "label"}
    assert labelled["party:p1:p2"]["label"] == {"label": "accepted", "note": None}
    assert rep["labels"] == {"applied": 2, "not_in_this_run": ["party:x:y"]}
    assert "- Label: rejected (two clinics)" in md


def test_a_mistyped_label_stops_the_run(run):
    with pytest.raises(ValueError, match="party:p1:p2"):
        run(labels={"party:p1:p2": "acepted"})


def test_a_cut_off_table_is_reported(run):
    rep, md, _ = run(client=FakeClient({"Party": PARTIES, "Item": ITEMS}, cut_off={"Party"}))
    assert section(rep)["table"] == {"rows": 10, "total": 20, "cut_off": True}
    assert "**The table was cut off.**" in md
    assert "an incomplete scan does not mean there are no duplicates" in md


@pytest.mark.parametrize("failure", [TimeoutError("read timed out"), http.client.IncompleteRead(b"")])
def test_a_failed_reference_read_is_unknown_and_the_run_goes_on(run, failure):
    rep, md, _ = run(client=FakeClient({"Party": PARTIES, "Item": ITEMS}, fail_refs=failure))
    p = next(p for p in section(rep)["proposals"] if p["band"] == "propose")
    assert p["references"] == {"p1": None, "p2": None}
    assert p["survivor"] == {"id": "p1", "rule": "older", "skipped": ["references"]}
    assert section(rep)["counts"]["references_unreadable"] == 2
    assert "`p1` unknown" in md
    assert "by older (skipped references: a count is unknown)" in md


def test_markdown_cells_cannot_break_the_table(run):
    _, md, _ = run()
    assert "#### Larkspur \\| Dental Clinic / Larkspur \\| Dental Clinic" in md  # pipe escaped, line break folded
    assert "Dental\nClinic" not in md
    assert "| name | Larkspur" not in md  # a line break inside a name is spacing, not a difference


def test_record_text_is_literal_markdown(run):
    rows = [party("p1", "Ottervale ![x](https://tracker.example/p.png)", email="a@ottervale.example",
                  **{"note|source": "<img src=x onerror=alert(1)> **bold** [link](https://e.example)"}),
            party("p2", "Ottervale ![x](https://tracker.example/p.png)", email="a@ottervale.example")]
    _, md, _ = run(client=FakeClient({"Party": rows, "Item": ITEMS}))
    assert "![x](" not in md and "<img" not in md and "**bold**" not in md and "[link](" not in md
    assert "| note\\|source | &lt;img src=x onerror=alert\\(1\\)&gt; \\*\\*bold\\*\\*" in md


def test_test_tags_are_shown_with_where_they_came_from(run):
    rep, md, _ = run()
    assert rep["test_tags"] == [{"tag": "qa-run", "source": "made-up test runs, read of 1 Nov"}]
    assert "Tags: qa-run (made-up test runs, read of 1 Nov)." in md


def test_the_runner_chooses_the_instance(run, monkeypatch):
    monkeypatch.setattr(config, "platform", lambda: {"instance": "suryodaya", "base": "b", "token": "t"})
    rep, _, _ = run(instance="suryodaya")
    assert rep["system"] == "suryodaya"


def test_the_report_cannot_be_sent_outside_local(run):
    with pytest.raises(SystemExit):
        run(argv=["--out", "."])
