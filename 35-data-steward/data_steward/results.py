"""Write results/dedupe_pairs.json, the file the instructor scores for the first task (asked for 10 Nov). Offline: it
reads the saved reports in local/ and calls nothing on the platform.

    uv run python -m data_steward.results                         # both systems' saved reports
    uv run python -m data_steward.results --instance suryodaya    # one system

One entry per proposed pair, in the instructor's format: {"kind", "id_a", "id_b", "confidence", "reason"}. The file is
committed to the public repository, so it holds the two record ids and nothing else about the records: the reason is
made only from this module's fixed wording for the matcher's signals and caps, and a signal or cap without wording
stops the export rather than pass an unknown value through.

Which pairs: every propose and review pair in the reports, except a pair a person labelled "rejected" (labels are
read now from local/dedupe-labels.json, not from the report, whose copy is as old as the scan) and a test-record pair
(either record carries a confirmed test-run tag). Ruled-out and low-scoring pairs are never in a report's list.

Confidence: a propose pair's score; a review pair's score capped at the review cut (0.6), since a pair held at review
can score 1.0. Scores are rule scores, not probabilities.

Standard output is counts only. A failure exits 1 with one line on standard error and leaves any earlier file as it
was.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys
import tempfile

from . import config, dedupe, report

RESULTS = config.ROOT / "results" / "dedupe_pairs.json"

# Evidence the two records share.
SIGNALS = {
    "customer_code": "same customer code", "email": "same email", "phone": "same phone", "website": "same website",
    "city_postal": "same city and postal code", "name": "matching name", "near_name": "similar names",
    "code": "same code or SKU", "category": "same category", "uom": "same unit of measure",
}
# Why a pair is held at review.
CAPS = {
    "names differ slightly": "similar names without a matching customer code", "roles differ": "different roles",
    "customer_code differs": "different customer codes", "email differs": "different emails",
    "phone differs": "different phone numbers", "code differs": "different item codes", "sku differs": "different SKUs",
}


class ExportError(Exception):
    """A problem this module found itself. Its message is fixed text: it never quotes a value from a report or the
    labels file, record ids included."""


def _check_pair(p) -> None:
    """The fields the export reads, checked before any is used: a report is a file on disk, and a value of the wrong
    kind could otherwise reach the public file or change which pairs are written."""
    ok = (isinstance(p, dict) and isinstance(p.get("id"), str) and isinstance(p.get("tagged"), bool)
          and p.get("band") in ("propose", "review")
          and isinstance(p.get("score"), (int, float)) and not isinstance(p.get("score"), bool)
          and math.isfinite(p["score"]) and 0 <= p["score"] <= 1
          and isinstance(p.get("ids"), list) and len(p["ids"]) == 2 and p["ids"][0] != p["ids"][1]
          and all(isinstance(i, str) and i for i in p["ids"])
          and isinstance(p.get("signals"), list) and isinstance(p.get("caps"), list))
    if not ok:
        raise ExportError("a pair in a report is malformed")
    if p["band"] == "propose" and p["caps"]:
        raise ExportError("a pair in a report is in propose although held at review")


def confidence(pair: dict) -> float:
    """A review pair always scores 0.6 or more, so today every review pair gets exactly 0.6."""
    return pair["score"] if pair["band"] == "propose" else min(pair["score"], dedupe.REVIEW)


def reason(pair: dict) -> str:
    known = all(isinstance(s, str) and s in SIGNALS for s in pair["signals"]) and \
        all(isinstance(c, str) and c in CAPS for c in pair["caps"])
    if not known or not pair["signals"]:
        raise ExportError("a pair in a report has a signal or cap with no wording here")
    text = "; ".join(SIGNALS[s] for s in pair["signals"])
    if pair["caps"]:
        text += "; held at review: " + ", ".join(CAPS[c] for c in pair["caps"])
    return text


def entries(saved: dict, labels: dict) -> tuple[list[dict], dict, set]:
    """One report's entries, its counts per kind (listed, rejected, test records, written) and its pair ids."""
    out, counts, ids = [], {}, set()
    for kind in report.TABLES:
        listed = saved["sections"][kind]["proposals"]
        if not isinstance(listed, list):
            raise ExportError("a report's pair list is malformed")
        n = {"listed": len(listed), "left_out_rejected": 0, "left_out_test_records": 0, "written": 0}
        for p in listed:
            _check_pair(p)
            ids.add(p["id"])
            if labels.get(p["id"], {}).get("label") == "rejected":
                n["left_out_rejected"] += 1
            elif p["tagged"]:
                n["left_out_test_records"] += 1
            else:
                id_a, id_b = sorted(p["ids"])
                out.append({"kind": kind, "id_a": id_a, "id_b": id_b, "confidence": confidence(p),
                            "reason": reason(p)})
                n["written"] += 1
        counts[kind] = n
    return out, counts, ids


def load_report(instance: str) -> dict:
    path = config.LOCAL_DIR / f"dedupe-{instance}.json"
    if not path.exists():
        raise ExportError(f"no saved report for {instance}: run the scan first")
    saved = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(saved, dict) or saved.get("system") != instance:
        raise ExportError(f"{path.name} is not the {instance} report")
    if saved.get("rules_version") != dedupe.RULES_VERSION:
        raise ExportError(f"{path.name} was made with another rules version than {dedupe.RULES_VERSION}: scan again")
    try:
        dt.date.fromisoformat(saved.get("date"))
    except (TypeError, ValueError):
        raise ExportError(f"{path.name} has no valid date") from None
    sections = saved.get("sections")
    if not isinstance(sections, dict) or set(sections) != set(report.TABLES) or not all(
            isinstance(s, dict) and isinstance(s.get("table"), dict) and isinstance(s["table"].get("cut_off"), bool)
            for s in sections.values()):
        raise ExportError(f"{path.name} does not hold both tables")
    cut = [kind for kind, s in sections.items() if s["table"]["cut_off"]]
    if cut:
        raise ExportError(f"{path.name}: the {' and '.join(sorted(cut))} table was cut off, so pairs may be missing")
    return saved


def build(instances: list[str], labels: dict) -> tuple[list[dict], dict]:
    out, counts, all_ids = [], {}, set()
    for instance in instances:
        saved = load_report(instance)
        found, counts[instance], ids = entries(saved, labels)
        if ids & all_ids:
            raise ExportError("the same pair is in two systems' reports; export one system at a time")
        all_ids |= ids
        counts[instance]["date"] = saved["date"]
        out += found
    if len({(e["kind"], e["id_a"], e["id_b"]) for e in out}) != len(out):
        raise ExportError("a pair is listed twice")
    # A rejected label whose pair is in no report loaded here (a typo, or a later scan without that pair) would
    # otherwise go unnoticed, and the pair it meant could be listed.
    counts["rejected_labels_matching_no_pair"] = sum(
        1 for pid, entry in labels.items() if entry["label"] == "rejected" and pid not in all_ids)
    out.sort(key=lambda e: (list(report.TABLES).index(e["kind"]), e["id_a"], e["id_b"]))
    return out, counts


def write(path, text: str) -> None:
    """Replace the file in one step, so a failed write leaves the earlier file whole."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)  # a committed file: mkstemp's owner-only mode would be odd in a checkout
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instance", action="append", choices=sorted(config.INSTANCES),
                        help="a system whose saved report to use; repeat for more (default: all)")
    args = parser.parse_args(argv)
    instances = sorted(set(args.instance or config.INSTANCES))
    try:
        try:
            labels = report.load_labels(config.LOCAL_DIR / "dedupe-labels.json")
        except ValueError:  # its message lists the pair ids at fault: fixed text instead
            raise ExportError("dedupe-labels.json is not valid: each label must be accepted or rejected") from None
        found, counts = build(instances, labels)
        text = json.dumps(found, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        write(RESULTS, text)
    except (ExportError, OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        # Local only: never run by the harness. The line names the problem, never a value from the input.
        detail = str(e) if isinstance(e, ExportError) else type(e).__name__
        if isinstance(e, OSError) and e.strerror:
            detail += f" ({e.strerror})"
        print(f"could not export: {detail}", file=sys.stderr)
        return 1
    print(json.dumps(counts, indent=2, sort_keys=True))
    print(f"results: {RESULTS.relative_to(config.ROOT)} ({len(found)} pairs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
