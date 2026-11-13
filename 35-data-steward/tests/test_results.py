import datetime as dt
import json

import pytest

from data_steward import config, dedupe, report, results
from tests.test_report import PARTIES, FakeClient, party

QUILLON = [
    # Same name and email, different phones: scores 1.0 and is held at review.
    party("q1", "Quillon Books", email="desk@quillon.example", phone="+91 98765 43210"),
    party("q2", "Quillon Books", email="desk@quillon.example", phone="+91 91234 56789"),
]
ITEMS = [
    {"id": "i1", "name": "Pallet Wrap", "code": "PW-1", "company_id": "c1", "uom": "ea", "variants": []},
    {"id": "i2", "name": "Pallet Wrap", "code": "PW-2", "company_id": "c1", "uom": "ea", "variants": []},
]
RECORD_VALUES = [v for row in PARTIES + QUILLON + ITEMS for k, v in row.items()
                 if k in ("name", "email", "phone", "website", "code")]


@pytest.fixture
def setup(tmp_path, monkeypatch, capsys):
    """Saves a keystone report from a fake scan; returns run(argv, code) -> (entries or None, captured)."""
    local = tmp_path / "local"
    local.mkdir()
    (local / "test-tags.txt").write_text("qa-run made-up test runs\n")
    monkeypatch.setattr(config, "LOCAL_DIR", local)
    monkeypatch.setattr(config, "today", lambda: dt.date(2026, 11, 9))
    monkeypatch.setattr(config, "platform", lambda: None)
    monkeypatch.delenv("AGENTSWITCH_TOKEN", raising=False)
    monkeypatch.setattr(report, "Session", lambda instance: instance)
    out = tmp_path / "results" / "dedupe_pairs.json"
    monkeypatch.setattr(results, "RESULTS", out)
    monkeypatch.setattr(results.config, "ROOT", tmp_path)

    def scan(instance="keystone", parties=PARTIES + QUILLON, items=ITEMS):
        monkeypatch.setattr(report, "McpClient", lambda session: FakeClient({"Party": parties, "Item": items}))
        assert report.main(["--instance", instance]) == 0
        capsys.readouterr()

    def run(argv=("--instance", "keystone"), code=0):
        assert results.main(list(argv)) == code
        captured = capsys.readouterr()
        return (json.loads(out.read_text()) if out.exists() else None), captured

    scan()
    assert not out.exists()  # a scan never writes the committed file
    return local, out, scan, run


def by_pair(found):
    return {(e["id_a"], e["id_b"]): e for e in found}


def test_entries_follow_the_instructors_format(setup):
    _, _, _, run = setup
    found, captured = run()
    assert all(list(e) == ["kind", "id_a", "id_b", "confidence", "reason"] for e in found)
    assert all(e["kind"] in ("party", "item") and 0 <= e["confidence"] <= 1 for e in found)
    pairs = by_pair(found)
    assert pairs[("p1", "p2")]["confidence"] == 1.0  # propose keeps its score
    assert pairs[("p3", "p4")] == {"kind": "party", "id_a": "p3", "id_b": "p4", "confidence": 0.6,
                                   "reason": "matching name"}
    # a capped pair scoring 1.0 claims no more than a review pair
    assert pairs[("q1", "q2")]["confidence"] == dedupe.REVIEW
    assert pairs[("q1", "q2")]["reason"].endswith("held at review: different phone numbers")
    assert pairs[("i1", "i2")]["kind"] == "item"
    assert [e["kind"] for e in found] == sorted((e["kind"] for e in found), key=["party", "item"].index)
    counts = json.loads(captured.out[:captured.out.rindex("}") + 1])
    assert counts["keystone"]["party"] == {"listed": 4, "left_out_rejected": 0, "left_out_test_records": 1,
                                           "written": 3}


def test_test_record_excluded_and_private_pairs_are_left_out(setup):
    _, _, _, run = setup
    pairs = by_pair(run()[0])
    assert ("p5", "p6") not in pairs  # test-run records
    assert ("p0", "p9") not in pairs  # ruled out: individual and organisation
    assert not any("p7" in key for key in pairs)  # restricted privacy state


def test_no_record_value_reaches_the_file_or_the_output(setup):
    _, out, _, run = setup
    _, captured = run()
    text = out.read_text() + captured.out + captured.err
    for value in RECORD_VALUES:
        assert value not in text, value


def test_rejected_pairs_are_left_out_using_labels_newer_than_the_scan(setup):
    local, _, _, run = setup
    (local / "dedupe-labels.json").write_text(json.dumps({
        "party:p3:p4": "rejected", "party:q1:q2": {"label": "accepted", "note": "NOTE-SENTINEL"},
        "party:zz:zz9": "rejected"}))  # a rejected label that matches no listed pair
    found, captured = run()
    pairs = by_pair(found)
    assert ("p3", "p4") not in pairs and ("q1", "q2") in pairs
    assert "NOTE-SENTINEL" not in out_text(setup) + captured.out
    assert json.loads(captured.out[:captured.out.rindex("}") + 1])["rejected_labels_matching_no_pair"] == 1


def out_text(setup):
    return setup[1].read_text()


def test_two_exports_are_identical_and_two_systems_merge(setup):
    _, out, scan, run = setup
    run()
    first = out.read_bytes()
    run()
    assert out.read_bytes() == first
    scan("suryodaya", parties=[party("s1", "Tamarind Hall"), party("s2", "Tamarind Hall")], items=[])
    found, _ = run(argv=())
    assert ("s1", "s2") in by_pair(found) and ("p3", "p4") in by_pair(found)


def _break_report(local, change):
    path = local / "dedupe-keystone.json"
    saved = json.loads(path.read_text())
    change(saved)
    path.write_text(json.dumps(saved))


def _set_signal(saved):
    saved["sections"]["party"]["proposals"][0]["signals"] = ["desk@quillon.example"]


def _set_version(saved):
    saved["rules_version"] = "2"


def _set_cut_off(saved):
    saved["sections"]["item"]["table"]["cut_off"] = True


def _pair(saved):
    return saved["sections"]["party"]["proposals"][0]


SENTINEL = "desk@quillon.example"
BAD_REPORTS = [
    (_set_signal, "with no wording"),
    (lambda s: s["sections"]["party"]["proposals"][-1].update(caps=[SENTINEL]), "with no wording"),  # a review pair
    (lambda s: _pair(s).update(signals=[]), "with no wording"),
    (_set_version, "another rules version"),
    (lambda s: s.update(rules_version=SENTINEL), "another rules version"),
    (_set_cut_off, "item table was cut off"),
    (lambda s: s["sections"]["item"]["table"].update(cut_off=None), "does not hold both tables"),
    (lambda s: s["sections"].pop("item"), "does not hold both tables"),
    (lambda s: s.update(system="suryodaya"), "is not the keystone report"),
    (lambda s: s.update(date=SENTINEL), "no valid date"),
    (lambda s: _pair(s).update(score=SENTINEL), "malformed"),
    (lambda s: _pair(s).update(score=float("nan")), "malformed"),
    (lambda s: _pair(s).update(score=1.5), "malformed"),
    (lambda s: _pair(s).update(score=True), "malformed"),
    (lambda s: _pair(s).update(tagged="false"), "malformed"),
    (lambda s: _pair(s).update(ids=SENTINEL[:2]), "malformed"),
    (lambda s: _pair(s).update(ids=[SENTINEL, SENTINEL]), "malformed"),
    (lambda s: _pair(s).update(band=SENTINEL), "malformed"),
    (lambda s: _pair(s).update(caps=["email differs"]), "held at review"),  # propose pair with a cap
    (lambda s: s["sections"]["party"].update(proposals={}), "pair list is malformed"),
    (lambda s: s["sections"]["party"]["proposals"].append(dict(_pair(s))), "listed twice"),
]


@pytest.mark.parametrize("change, says", BAD_REPORTS)
def test_a_bad_report_fails_and_leaves_the_earlier_file(setup, change, says):
    local, out, _, run = setup
    run()
    before = out.read_bytes()
    _break_report(local, change)
    _, captured = run(code=1)
    assert out.read_bytes() == before
    assert captured.err.startswith("could not export:") and says in captured.err and captured.err.count("\n") == 1
    assert SENTINEL not in captured.err and "p1" not in captured.err


def test_a_report_that_is_not_an_object_or_bad_labels_fail_on_one_line(setup):
    local, out, _, run = setup
    run()
    before = out.read_bytes()
    (local / "dedupe-labels.json").write_text(json.dumps({"party:p1:p2": SENTINEL}))
    _, captured = run(code=1)
    assert "dedupe-labels.json is not valid" in captured.err and "p1" not in captured.err
    (local / "dedupe-labels.json").unlink()
    (local / "dedupe-keystone.json").write_text(json.dumps([SENTINEL]))
    _, captured = run(code=1)
    assert captured.err.count("\n") == 1 and SENTINEL not in captured.err
    assert out.read_bytes() == before


def test_a_failed_write_leaves_the_earlier_file(setup, monkeypatch):
    local, out, _, run = setup
    run()
    before = out.read_bytes()
    (local / "dedupe-labels.json").write_text(json.dumps({"party:p3:p4": "rejected"}))

    def fail(src, dst):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(results.os, "replace", fail)
    _, captured = run(code=1)
    assert out.read_bytes() == before
    assert captured.err == "could not export: OSError (No space left on device)\n"
    assert [p.name for p in out.parent.iterdir()] == [out.name]  # no temporary file left behind


def test_a_missing_report_or_a_pair_in_two_systems_fails(setup):
    _, out, scan, run = setup
    _, captured = run(argv=("--instance", "suryodaya"), code=1)
    assert "no saved report for suryodaya" in captured.err and not out.exists()
    scan("suryodaya")  # the same records under both systems
    _, captured = run(argv=(), code=1)
    assert "same pair is in two systems" in captured.err and not out.exists()
