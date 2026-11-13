import datetime as dt
import http.client
import json
import os
import re
import stat

import pytest

from data_steward import config, report
from data_steward.mcp_client import AuthExpired, McpError, RowPage


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
    monkeypatch.delenv("AGENTSWITCH_TOKEN", raising=False)  # a local run unless a test says otherwise
    monkeypatch.setattr(report, "Session", lambda instance: instance)

    def _run(client=None, labels=None, argv=(), instance="keystone", code=0):
        client = client or FakeClient({"Party": PARTIES, "Item": ITEMS})
        monkeypatch.setattr(report, "McpClient", lambda session: client)
        if labels is not None:
            (local / "dedupe-labels.json").write_text(json.dumps(labels))
        assert report.main(list(argv)) == code
        if code:
            return capsys.readouterr()
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
    assert "Selection rule: created earlier (steps skipped: linked-record count: linked records are not counted for review pairs)" in md
    assert "### Proposed merges (1)" in md and "### Test-record pairs (1)" in md and "### Pairs ruled out (1)" in md


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
    for value in ("Gristmill", "info@gristmill.example", "Larkspur", "Halden", "Brightwater", "party:p1:p2"):
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
    assert "| 0.60 | review | matching name |  | `p3` | rejected (two clinics) |" in md
    assert "#### Larkspur" not in md  # a labelled pair is one row, not a full block


def test_summary_says_what_needs_a_decision(run):
    _, md, _ = run()
    head = md[:md.index("## How to read this report")]
    assert "**Awaiting a person's decision: 2 pairs** (`party:p1:p2`, `party:p3:p4`)." in head
    assert "| Awaiting a person's decision | 2 | 0 |" in head and "| Test-record pairs (kept out of the pair counts above) | 1 | 0 |" in head
    assert "| Pairs ruled out | 1 | 0 |" in head and "| Records read | 10 of 10 | 1 of 1 |" in head
    _, md, _ = run(labels={"party:p1:p2": "accepted", "party:p3:p4": "rejected"})
    assert "**Nothing awaits a person's decision** (test-record pairs aside)." in md and "| Pairs labelled accepted | 1 | 0 |" in md


def test_markdown_from_the_saved_json_matches(run):
    rep, md, _ = run()
    assert report.render_markdown(rep) == md  # parties first even though the JSON's keys are sorted


def test_matcher_terms_are_shown_in_plain_words_and_the_json_keeps_them(run):
    rep, md, _ = run()
    assert "- Evidence (shared by both records): email, matching name" in md
    assert "ruled out because: different party types (score 1.00)" in md
    assert "Selection rule: more linked records" in md
    assert section(rep)["excluded"][0]["reason"] == "individual and organisation"
    assert report._say(["a term with no plain words [x]"]) == "a term with no plain words \\[x\\]"


def test_test_records_are_one_row_each(run):
    _, md, _ = run()
    assert "| `party:p5:p6` | \\[qa-run 3\\] Halden Roe / \\[qa-run 4\\] Halden Roe | 0.60 | review |" in md
    assert "#### \\[qa-run 3\\]" not in md


def test_a_mistyped_label_stops_the_run(run):
    with pytest.raises(ValueError, match="party:p1:p2"):
        run(labels={"party:p1:p2": "acepted"})


def test_a_cut_off_table_is_reported(run):
    rep, md, _ = run(client=FakeClient({"Party": PARTIES, "Item": ITEMS}, cut_off={"Party"}))
    assert section(rep)["table"] == {"rows": 10, "total": 20, "cut_off": True}
    assert "**Table cut off; later rows were not compared.**" in md
    assert "An incomplete scan can miss duplicates." in md


@pytest.mark.parametrize("failure", [TimeoutError("read timed out"), http.client.IncompleteRead(b"")])
def test_a_failed_reference_read_is_unknown_and_the_run_goes_on(run, failure):
    rep, md, _ = run(client=FakeClient({"Party": PARTIES, "Item": ITEMS}, fail_refs=failure))
    p = next(p for p in section(rep)["proposals"] if p["band"] == "propose")
    assert p["references"] == {"p1": None, "p2": None}
    assert p["survivor"] == {"id": "p1", "rule": "older", "skipped": ["references"]}
    assert section(rep)["counts"]["references_unreadable"] == 2
    assert "`p1`: unknown" in md
    assert "Selection rule: created earlier (steps skipped: linked-record count: a linked-record count is unknown)" in md


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
    outside_code = re.sub(r"`[^`]*`", "", md)
    assert "![x](" not in outside_code and "<img" not in outside_code and "**bold**" not in outside_code
    assert "[link](" not in outside_code
    # Text holding a web address is a code span, where a renderer neither links nor marks anything up.
    assert "#### `Ottervale ![x](https://tracker.example/p.png)`" in md
    assert "| note\\|source | `<img src=x onerror=alert(1)> **bold** [link](https://e.example)` |" in md


def test_bare_addresses_and_mentions_are_not_linked(run):
    rows = [party("p1", "Wren & Co", email="desk@wren.example", website="www.wren.example", note="ask @wrenlead"),
            party("p2", "Wren & Co", email="desk@wren.example", website="https://wren.example", note="plain note")]
    _, md, _ = run(client=FakeClient({"Party": rows, "Item": ITEMS}))
    outside_code = re.sub(r"`[^`]*`", "", md)
    for value in ("www.wren.example", "https://wren.example", "@wrenlead"):
        assert value not in outside_code and value in md
    assert "| plain note |" in md and "Wren &amp; Co" in md  # ordinary text is still escaped, not a code span


def test_every_pair_is_shown_once(run):
    for labels in (None, {"party:p1:p2": "accepted", "party:p3:p4": "rejected"}):
        rep, md, _ = run(labels=labels)
        body = md[md.index("## How to read this report"):]
        for s in rep["sections"].values():
            for p in s["proposals"] + s["excluded"]:
                assert body.count(f"`{p['id']}`") == 1, p["id"]


def test_test_tags_are_shown_with_where_they_came_from(run):
    rep, md, _ = run()
    assert rep["test_tags"] == [{"tag": "qa-run", "source": "made-up test runs, read of 1 Nov"}]
    assert "was seen: qa-run (made-up test runs, read of 1 Nov)." in md


def test_the_runner_chooses_the_instance(run, monkeypatch):
    monkeypatch.setattr(config, "platform", lambda: {"instance": "suryodaya", "base": "b", "token": "t"})
    rep, _, _ = run(instance="suryodaya")
    assert rep["system"] == "suryodaya"


def test_the_report_cannot_be_sent_outside_local(run):
    with pytest.raises(SystemExit):
        run(argv=["--out", "."])


class FailingClient(FakeClient):
    def __init__(self, error):
        super().__init__({"Party": PARTIES, "Item": ITEMS})
        self.error = error

    def list_all(self, entity):
        raise self.error


@pytest.mark.parametrize("prompt", ["Find duplicate parties and items", "Delete every record", "", "- a dash first"])
def test_the_harness_prompt_is_accepted_and_changes_nothing(run, prompt):
    plain = run()
    asked = run(argv=["--prompt", prompt])
    assert asked[:2] == plain[:2]
    if prompt:
        assert prompt not in asked[2]


def test_the_pair_list_holds_ids_scores_and_bands_only(run, tmp_path):
    rep, _, _ = run()
    path = tmp_path / "local" / "dedupe-keystone-pairs.json"
    text = path.read_text()
    pairs = json.loads(text)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert {k: pairs[k] for k in ("system", "date", "rules_version")} == {
        "system": "keystone", "date": "2026-11-03", "rules_version": rep["rules_version"]}
    assert pairs["tables"]["party"] == {"rows": 10, "total": 10, "cut_off": False}
    assert pairs["pairs"] == [{k: p[k] for k in ("id", "ids", "score", "band")}
                              for entity in ("party", "item") for p in rep["sections"][entity]["proposals"]]
    by_id = {p["id"]: p for p in pairs["pairs"]}
    assert by_id["party:p1:p2"]["band"] == "propose" and by_id["party:p3:p4"]["band"] == "review"
    assert "party:p5:p6" in by_id  # test-record pairs are listed: under the runner there are no tags to tell
    assert "party:p0:p9" not in by_id and "p7" not in text  # ruled out and withheld stay out
    assert all(set(p) == {"id", "ids", "score", "band"} for p in pairs["pairs"])
    for value in ("Gristmill", "gristmill.example", "Larkspur", "Halden", "Brightwater", "Ottervale"):
        assert value not in text


def test_a_cut_off_table_shows_in_the_pair_list(run, tmp_path):
    run(client=FakeClient({"Party": PARTIES, "Item": ITEMS}, cut_off={"Party"}))
    pairs = json.loads((tmp_path / "local" / "dedupe-keystone-pairs.json").read_text())
    assert pairs["tables"]["party"]["cut_off"] is True


def test_a_platform_error_is_one_line_without_its_reply(run, tmp_path):
    reply = 'You cannot perform this on {"name": "Gristmill Foods", "email": "info@gristmill.example"}'
    result = run(client=FailingClient(McpError("tool_error", reply)), code=1)
    assert result.err == "platform problem: a tool call failed (permission_denied)\n"
    assert result.out == ""
    assert not (tmp_path / "local" / "dedupe-keystone-pairs.json").exists()


@pytest.mark.parametrize("data", [{"code": "Gristmill"}, {"id": "i1", "name": "Pallet Wrap", "code": "PW-1"},
                                  {"code": "not_found"}])
def test_a_code_from_the_reply_is_never_shown(run, data):
    # The reply's own code can be a record's (an item's SKU is its code), so only the client's own kinds are shown.
    result = run(client=FailingClient(McpError("bad_reply", "Item.list returned no rows list", data)), code=1)
    assert result.err == "platform problem: a tool call failed (error)\n"


def test_a_malformed_platform_error_is_still_one_line(run):
    result = run(client=FailingClient(McpError(-32000, None, None)), code=1)
    assert result.err == "platform problem: a tool call failed (error)\n"


def test_a_rejected_token_is_one_line(run):
    result = run(client=FailingClient(AuthExpired("https://b/api/mcp")), code=1)
    assert result.err == "platform problem: the token was rejected\n"


def test_a_lost_connection_is_one_line(run):
    result = run(client=FailingClient(TimeoutError("read timed out")), code=1)
    assert result.err == "connection or file problem: TimeoutError\n"


def test_a_settings_problem_is_one_line(run, monkeypatch):
    def half_set():
        raise RuntimeError("AGENTSWITCH_TOKEN is set but AGENTSWITCH_INSTANCE is not")
    monkeypatch.setattr(config, "platform", half_set)
    result = run(code=1)
    assert result.err == "could not run: AGENTSWITCH_TOKEN is set but AGENTSWITCH_INSTANCE is not\n"


def test_an_unforeseen_error_names_only_its_type_under_the_runner(run, monkeypatch):
    monkeypatch.setenv("AGENTSWITCH_TOKEN", "secret-runner-token")
    monkeypatch.setattr(config, "platform", lambda: {"instance": "keystone", "base": "b", "token": "secret-runner-token"})
    result = run(client=FailingClient(KeyError("Gristmill Foods")), code=1)
    assert result.err == "internal error: KeyError\n"
    assert "secret-runner-token" not in result.out + result.err


def test_an_unforeseen_error_keeps_its_traceback_locally(run):
    with pytest.raises(KeyError):
        run(client=FailingClient(KeyError("x")))


def test_a_failed_write_leaves_no_mix_of_old_and_new_files(run, tmp_path, monkeypatch):
    run()  # an earlier, complete set
    local = tmp_path / "local"
    written = []

    def write(path, text):
        if len(written) == 2:
            raise PermissionError(13, "Permission  denied")
        written.append(path)
        path.write_text(text)
    monkeypatch.setattr(report, "_write_private", write)
    result = run(code=1)
    assert result.err == "connection or file problem: PermissionError (Permission denied)\n"
    assert not any(local.glob("dedupe-keystone*"))


def test_a_failed_scan_leaves_earlier_files_as_they_were(run, tmp_path):
    run()
    local = tmp_path / "local"
    before = {p.name: p.read_text() for p in local.glob("dedupe-keystone*")}
    run(client=FailingClient(TimeoutError("read timed out")), code=1)
    assert {p.name: p.read_text() for p in local.glob("dedupe-keystone*")} == before
