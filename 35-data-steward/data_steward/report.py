"""Scan parties and items on one system and write the duplicate report. Read-only: nothing on the platform changes.

    uv run python -m data_steward.dedupe                      # Keystone, or the harness runner's instance
    uv run python -m data_steward.dedupe --instance keystone
    uv run python -m data_steward.dedupe --prompt "<request>"  # how the course harness runs it; the request is ignored

Writes local/dedupe-<instance>.json (the record of truth) and local/dedupe-<instance>.md (made from it). Both hold
real party data, which is why they go to the git-ignored local/. Also writes local/dedupe-<instance>-pairs.json: every
listed pair as its pair id, the two record ids, score and band, and nothing else about the records. Standard output
carries counts only. A failure exits 1 with one plain error line on standard error; only a local run (not under the
harness runner) shows a traceback for an error this command does not expect. A failed scan leaves earlier files as
they were; a failed write removes all three, so old and new files are never mixed.

Inputs read from local/, never written: test-tags.txt (one confirmed test-run tag per line: the tag is the
first word, and the rest of the line, if any, says where the read showed it came from) and dedupe-labels.json
({"<pair id>": "accepted" | "rejected"}, or {"<pair id>": {"label": ..., "note": ...}}).
"""
import argparse
import html
import http.client
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

from . import config, dedupe, proposals
from .mcp_client import AuthExpired, McpClient, McpError, Session

TABLES = {"party": "Party", "item": "Item"}
LABELS = ("accepted", "rejected")

# Plain words for the matcher's and proposals' short values, for the Markdown only: the values themselves stay as
# they are in the JSON. A value missing here is shown as it is.
SAY = {
    # evidence: a value both records share
    "customer_code": "customer code", "email": "email", "phone": "phone", "website": "website",
    "city_postal": "city and postal code", "name": "matching name", "near_name": "similar names", "code": "code or SKU",
    "category": "category", "uom": "unit of measure",
    # held at review
    "names differ slightly": "similar names without a matching customer code", "roles differ": "different roles",
    "customer_code differs": "different customer codes", "email differs": "different emails",
    "phone differs": "different phone numbers", "code differs": "different item codes", "sku differs": "different SKUs",
    # ruled out
    "flagged as an allowed duplicate": "marked as an allowed duplicate",
    "different companies": "records belong to different companies",
    "individual and organisation": "different party types", "different kinds": "different item types",
    "different units": "different units of measure", "variant of the other item": "one item is a variant of the other",
    # rule that chose the record to keep, and the steps it skipped
    "more references": "more linked records", "older": "created earlier", "more fields filled": "more fields filled",
    "smaller id": "first ID in text order", "references": "linked-record count", "age": "creation date",
}

NOTES = [
    "Confidence groups (bands):\n"
    f"  - **propose**: score {dedupe.PROPOSE:.2f} or higher, with no rule holding the pair back.\n"
    f"  - **review**: score {dedupe.REVIEW:.2f} or higher, but below {dedupe.PROPOSE:.2f} or held back by a rule. "
    "Each held-back pair gives the reason.\n"
    f"  - Below {dedupe.REVIEW:.2f}: counted, not listed.\n"
    "  - Scores run from 0 to 1. They come from rules, not probabilities.",
    "Accuracy was checked only on made-up data held back for testing (plan, step 7):\n"
    "  - No wrong proposals in that check; review pairs were right about two times in three.\n"
    "  - These results do not predict accuracy on live records.",
    "Each pair suggests which record to keep if the merge is approved. It is only a suggestion; a person decides.\n"
    "  - A person must make every record change through the platform, with approval.\n"
    "  - This report changed nothing.",
    "Missing pairs do not prove that records are distinct.\n"
    "  - If a table was cut off, rows beyond the cut were never compared. An incomplete scan can miss duplicates.",
]


def load_test_tags(path: Path) -> dict[str, str | None]:
    """tag -> where it came from, as far as the read showed it (None when the line gives no source). A tag is one
    word: "qa run" is the tag "qa" with the source "run"."""
    if not path.exists():
        return {}
    tags = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tag, _, source = line.partition(" ")
            tags[tag] = source.strip() or None
    return tags


def load_labels(path: Path) -> dict[str, dict]:
    """A label that is not "accepted" or "rejected" stops the run: a typo must not read as no decision."""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name}: expected an object of pair id -> label")
    labels, bad = {}, []
    for pair_id, value in raw.items():
        entry = value if isinstance(value, dict) else {"label": value}
        if entry.get("label") not in LABELS:
            bad.append(pair_id)
            continue
        labels[pair_id] = {"label": entry["label"], "note": entry.get("note")}
    if bad:
        raise ValueError(f"{path.name}: labels must be one of {LABELS}; fix {sorted(bad)}")
    return labels


def scan(client, entity: str, test_tags) -> dict:
    """One table: rows read, the matcher's result, and a proposal per listed pair."""
    rows = client.list_all(TABLES[entity])
    result = dedupe.find_duplicates(entity, rows, test_tags=test_tags)
    refs, unreadable = {}, 0
    for rid in proposals.proposed_ids(result):
        try:
            refs[rid] = proposals.count_references(client, entity, rid)
        except (OSError, http.client.HTTPException):
            # A dropped connection or a timeout: this id's count is unknown, and the rest of the report still runs.
            refs[rid] = None
            unreadable += 1
    by_id = proposals.lookup(result, rows)
    excluded = [{**p, "names": {rid: by_id[rid].get("name") for rid in p["ids"]}} for p in result["excluded"]]
    return {
        "table": {"rows": len(rows), "total": rows.total, "cut_off": rows.truncated},
        "counts": {k: result[k] for k in ("withheld_private", "repeated_ids", "ignored_shared", "skipped_blocks",
                                          "dropped")} | {"references_unreadable": unreadable},
        "proposals": proposals.build_proposals(result, rows, refs),
        "excluded": excluded,
    }


def build_report(instance: str, date: str, sections: dict, labels: dict, test_tags: dict | None = None) -> dict:
    """Labels are shown beside their pair and never change its score, band or survivor."""
    listed = set()
    for section in sections.values():
        for p in section["proposals"]:
            p["label"] = labels.get(p["id"])
            listed.add(p["id"])
    return {
        "system": instance,
        "date": date,
        "rules_version": dedupe.RULES_VERSION,
        "notes": NOTES,
        "test_tags": [{"tag": t, "source": src} for t, src in sorted((test_tags or {}).items())],
        "sections": sections,
        "labels": {"applied": len(listed & labels.keys()), "not_in_this_run": sorted(labels.keys() - listed)},
    }


def summary(report: dict) -> dict:
    """Counts only, for the pull request description: no record data. Tagged pairs are counted apart and left out
    of the band totals."""
    out = {"system": report["system"], "date": report["date"], "rules_version": report["rules_version"]}
    for entity, s in report["sections"].items():
        untagged = [p for p in s["proposals"] if not p["tagged"]]
        out[entity] = {
            "rows": s["table"]["rows"], "total": s["table"]["total"], "cut_off": s["table"]["cut_off"],
            "bands": dict(sorted(Counter(p["band"] for p in untagged).items())),
            "tagged_pairs": len(s["proposals"]) - len(untagged),
            "excluded": dict(sorted(Counter(p["reason"] for p in s["excluded"]).items())),
            **s["counts"],
        }
    return out


def pair_list(report: dict) -> dict:
    """The pairs alone, for a grader: pair id (which names the entity), the two record ids, score and band. No names
    or other record data. Every listed pair is here, propose and review, test-record pairs included (the runner has no
    test tags to tell them by), parties first and then items, each by band and then pair id; pairs ruled out are not. The score and the band are both kept: a pair held at review can still score 1.0. Each
    table says whether it was cut off, so a short list from an incomplete scan is not read as "no more duplicates"."""
    return {
        "system": report["system"], "date": report["date"], "rules_version": report["rules_version"],
        "tables": {entity: s["table"] for entity, s in report["sections"].items()},
        "pairs": [{k: p[k] for k in ("id", "ids", "score", "band")}
                  for s in report["sections"].values() for p in s["proposals"]],
    }


_MARKDOWN = re.compile(r"([\\`*_\[\]()!|~#])")
# Text a GitHub-style renderer turns into a link or a mention by itself, escapes or not.
_AUTOLINK = re.compile(r"(?i)://|\b(?:mailto|xmpp):|www\.|@")


def _cell(value) -> str:
    """Record text as literal Markdown: one line, at most 200 characters, with HTML and Markdown syntax escaped, so a
    value can neither break a table nor render as a link, an image or markup. A value a renderer would link by itself
    (a web address, an email, an @mention) becomes a code span, where nothing is linked."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = " ".join(str(text).split())
    text = text if len(text) <= 200 else text[:199] + "…"
    if _AUTOLINK.search(text):
        return _code(text)
    return _MARKDOWN.sub(r"\\\1", html.escape(text, quote=False))


def _code(value) -> str:
    """An id as a code span. Escapes do not work inside one, so a backtick, which would end it early, is replaced,
    and a pipe, which would end a table cell, is too."""
    text = " ".join(str(value).split()).replace("`", "'").replace("|", "/")
    return f"`{text}`"


def _pair_md(p) -> list[str]:
    a, b = p["ids"]
    lines = [f"#### {_cell(p['names'][a])} / {_cell(p['names'][b])}", "",
             f"- Pair {_code(p['id'])}: score {p['score']:.2f}; confidence **{p['band']}**",
             f"- Evidence (shared by both records): {_say(p['signals']) or 'none'}"]
    if p["caps"]:
        lines.append(f"- Held at review because: {_say(p['caps'])}")
    if p["shared_record"]:
        lines.append("- A record also appears in another pair. Review those pairs together.")
    s = p["survivor"]
    why = {"references": "linked records are not counted for review pairs" if p["references"] is None
           else "a linked-record count is unknown",
           "age": "a creation date is missing"}
    steps = "; ".join(f"{_say([step])}: {why[step]}" for step in s["skipped"])
    skipped = f" (steps skipped: {steps})" if steps else ""
    lines.append(f"- Suggested record to keep if approved: {_code(s['id'])}. Selection rule: {_say([s['rule']])}"
                 + skipped)
    if p["references"] is not None:
        totals = {rid: (r or {}).get("total") for rid, r in p["references"].items()}
        lines.append("- Linked records (references): " + ", ".join(f"{_code(rid)}: {'unknown' if n is None else n}"
                                                   for rid, n in totals.items()))
    lines.append(f"- Person's label: {_label_text(p)}")
    if p["differences"]:
        lines += ["", f"| Field | {_code(a)} | {_code(b)} |", "|---|---|---|"]
        lines += [f"| {_cell(d['field'])} | {_or_empty(d['a'])} | {_or_empty(d['b'])} |" for d in p["differences"]]
    else:
        lines += ["", "No differences in the compared fields. Hidden and bookkeeping fields are not shown."]
    return lines + [""]


def _say(values) -> str:
    return ", ".join(_cell(SAY.get(v, v)) for v in values)


def _shared(counts: dict) -> str:
    return ", ".join(f"{_say([key])}: {n}" for key, n in sorted(counts.items())) or "none"


def _or_empty(value) -> str:
    return "(empty)" if value is None else _cell(value)


def _label_text(p) -> str:
    label = p.get("label")
    if not label:
        return "none yet"
    return label["label"] + (f" ({_cell(label['note'])})" if label.get("note") else "")


def _rows_md(pairs) -> list[str]:
    """One row per pair, for pairs a person has already labelled and for test records. The full detail of each is in
    the JSON report."""
    lines = ["| Pair | Records | Score | Confidence | Evidence | Why held at review | Suggested to keep | Person's label |",
             "|---|---|---|---|---|---|---|---|"]
    for p in pairs:
        a, b = p["ids"]
        lines.append(f"| {_code(p['id'])} | {_cell(p['names'][a])} / {_cell(p['names'][b])} | {p['score']:.2f} | "
                     f"{p['band']} | {_say(p['signals']) or 'none'} | {_say(p['caps'])} | "
                     f"{_code(p['survivor']['id'])} | {_label_text(p)} |")
    return lines + [""]


def _awaiting(pairs) -> list[dict]:
    return [p for p in pairs if not p["tagged"] and not p.get("label")]


def _sections(report: dict) -> dict:
    """Parties first, then items, also when the report was read back from its JSON (whose keys are sorted)."""
    return {e: report["sections"][e] for e in sorted(report["sections"], key=list(TABLES).index)}


def _summary_md(report: dict) -> list[str]:
    sections = _sections(report)
    waiting = [p["id"] for s in sections.values() for p in _awaiting(s["proposals"])]
    proposed = sum(p["band"] == "propose" and not p["tagged"] for s in sections.values() for p in s["proposals"])
    lines = ["## Summary", ""]
    lines.append(f"**Awaiting a person's decision: {len(waiting)} pair{'s' if len(waiting) != 1 else ''}** "
                 f"({', '.join(_code(i) for i in waiting)})." if waiting
                 else "**Nothing awaits a person's decision** (test-record pairs aside).")
    if not proposed:
        lines[-1] += " No merge is proposed outside test records."
    lines += ["", "| | " + " | ".join(e.capitalize() for e in sections) + " |", "|---" * (len(sections) + 1) + "|"]

    def row(title, fn):
        return f"| {title} | " + " | ".join(str(fn(s)) for s in sections.values()) + " |"

    def count(s, band=None, label=None, tagged=False):
        return sum(p["tagged"] == tagged and (band is None or p["band"] == band)
                   and (label is None or (p.get("label") or {}).get("label") == label) for p in s["proposals"])

    def rows_read(s):
        t = s["table"]
        total = t["total"] if t["total"] is not None else "unknown"
        return f"{t['rows']} of {total}" + (" (**cut off**)" if t["cut_off"] else "")

    lines += [row("Records read", rows_read),
              row("Proposed merges (propose)", lambda s: count(s, band="propose")),
              row("Pairs to review (review)", lambda s: count(s, band="review")),
              row("Awaiting a person's decision", lambda s: len(_awaiting(s["proposals"]))),
              row("Pairs labelled accepted", lambda s: count(s, label="accepted")),
              row("Pairs labelled rejected", lambda s: count(s, label="rejected")),
              row("Test-record pairs (kept out of the pair counts above)", lambda s: count(s, tagged=True)),
              row("Pairs ruled out", lambda s: len(s["excluded"])), ""]
    return lines


def render_markdown(report: dict) -> str:
    lines = [f"# Possible duplicate records: {report['system']}, {report['date']}", "",
             f"Rules version {report['rules_version']}. Made from the JSON file with the same name.", ""]
    lines += _summary_md(report)
    lines += ["## How to read this report", ""] + [f"- {n}" for n in report["notes"]] + [""]
    for entity, s in _sections(report).items():
        t, c = s["table"], s["counts"]
        lines += [f"## {entity.capitalize()} records", "",
                  f"Records read: {t['rows']} of {t['total'] if t['total'] is not None else 'an unknown total'}"
                  + (". **Table cut off; later rows were not compared.**" if t["cut_off"]
                     else ". Whole table read."), ""]
        untagged = [p for p in s["proposals"] if not p["tagged"]]
        tagged = [p for p in s["proposals"] if p["tagged"]]
        for band, title in (("propose", "Proposed merges"), ("review", "Pairs to review")):
            pairs = [p for p in untagged if p["band"] == band]
            lines += [f"### {title} ({len(pairs)})", ""] + ([] if pairs else ["None.", ""])
            for p in _awaiting(pairs):
                lines += _pair_md(p)
            labelled = sorted((p for p in pairs if p.get("label")),
                              key=lambda p: (LABELS.index(p["label"]["label"]), -p["score"], p["id"]))
            if labelled:
                lines += [f"Already labelled by a person ({len(labelled)}). Full details are in the JSON report:",
                          ""] + _rows_md(labelled)
        lines += [f"### Test-record pairs ({len(tagged)})", "",
                  "At least one record name has a confirmed test-run tag. These pairs use the same scoring and "
                  "confidence rules. Each gets one row; full details are in the JSON report. Confirmed tags, "
                  "with where each was seen: "
                  + ("; ".join(_cell(t["tag"]) + (f" ({_cell(t['source'])})" if t["source"] else "")
                               for t in report["test_tags"]) or "none") + ".", ""]
        lines += _rows_md(tagged) if tagged else ["None.", ""]
        lines += [f"### Pairs ruled out ({len(s['excluded'])})", ""] + ([] if s["excluded"] else ["None."])
        lines += [f"- {_code(p['id'])} {_cell(p['names'][p['ids'][0]])} / {_cell(p['names'][p['ids'][1]])}: "
                  f"ruled out because: {_say([p['reason']])} (score {p['score']:.2f})" for p in s["excluded"]]
        lines += ["", "### Omissions and limits", "",
                  f"- Pairs below the review threshold, not listed: {c['dropped']}",
                  f"- Records withheld for privacy; details omitted: {c['withheld_private']}",
                  f"- Repeated record IDs; first copy kept: {c['repeated_ids']}",
                  f"- Values shared too widely to count as evidence: {_shared(c['ignored_shared'])}",
                  f"- Groups not compared because they are too common: {c['skipped_blocks']}",
                  f"- Records whose linked-record counts could not be read: {c['references_unreadable']}", ""]
    stale = report["labels"]["not_in_this_run"]
    lines += ["## Saved labels", "", f"Labels shown beside pairs: {report['labels']['applied']}. "
              f"Labels with no matching pair in this report: {len(stale)}"
              + (f" ({', '.join(_code(i) for i in stale)})" if stale else "") + "."]
    return "\n".join(lines) + "\n"


def _write_private(path: Path, text: str) -> None:
    """Real party data, readable by this user only. Written to a new private file that then replaces the report, so
    an existing file's looser mode, an open reader of it, or a symlink in its place never sees the new data."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")  # created 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instance", choices=sorted(config.INSTANCES),
                        help="default: the harness runner's instance, else keystone")
    # The course harness appends --prompt "<request>" to the command. There is no model yet, so every request gets
    # the same read-only duplicate scan; the text is neither printed nor saved.
    parser.add_argument("--prompt", help="the harness's request; ignored for now")
    args = parser.parse_args(argv)
    try:
        return _run(args.instance)
    except Exception as e:
        line = _error_line(e)
        if line is None:
            if not config.on_platform():
                raise  # a local run keeps the traceback, for debugging
            # Under the harness a traceback's last line can quote a record value: name the error type only.
            line = f"internal error: {type(e).__name__}"
        print(line, file=sys.stderr)
        return 1


# The kinds McpError works out itself. Any other kind is the reply's own "code" field, which can be a record's (an
# item's SKU is its "code"), so it is never shown.
_KNOWN_KINDS = {"permission_denied", "unknown_tool"}


def _error_line(e: Exception) -> str | None:
    """One line for the harness to show as the reason (its "last error line"), which may be shared beyond this seat.
    A platform error's own message can quote the platform's reply, record data included, so it is never shown, and its
    kind only when it is one of _KNOWN_KINDS. RuntimeError messages are printed: the package's own settings and login
    messages name no token, password or login name. None means unforeseen."""
    if isinstance(e, McpError):
        try:
            kind = e.kind if e.kind in _KNOWN_KINDS else "error"
        except Exception:  # a malformed reply (a message that is not text) must not end in a traceback that quotes it
            kind = "error"
        return f"platform problem: a tool call failed ({kind})"
    if isinstance(e, AuthExpired):
        return "platform problem: the token was rejected"
    if isinstance(e, (OSError, http.client.HTTPException)):
        reason = getattr(e, "strerror", None)
        return f"connection or file problem: {type(e).__name__}" + (f" ({' '.join(str(reason).split())})" if reason else "")
    if isinstance(e, RuntimeError):
        return f"could not run: {' '.join(str(e).split())}"
    return None


def _run(instance: str | None) -> int:
    platform = config.platform()
    instance = instance or (platform["instance"] if platform else "keystone")
    test_tags = load_test_tags(config.LOCAL_DIR / "test-tags.txt")
    labels = load_labels(config.LOCAL_DIR / "dedupe-labels.json")

    client = McpClient(Session(instance))
    sections = {entity: scan(client, entity, tuple(test_tags)) for entity in TABLES}
    report = build_report(instance, config.today().isoformat(), sections, labels, test_tags)

    # Always local/, which is git-ignored: the report holds real party data and the repository is public. Record ids
    # are platform data too, so the pair list goes there as well and never to standard output.
    stem = config.LOCAL_DIR / f"dedupe-{instance}"
    pairs = config.LOCAL_DIR / f"dedupe-{instance}-pairs.json"
    files = {  # every text made before the first write, so a failure while making one changes no file
        stem.with_suffix(".json"): json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        stem.with_suffix(".md"): render_markdown(report),
        pairs: json.dumps(pair_list(report), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    }
    config.LOCAL_DIR.mkdir(exist_ok=True)
    try:
        for path, text in files.items():
            _write_private(path, text)
    except BaseException:
        # A partly written set would put new files beside old ones, which a reader cannot tell apart: remove all three.
        for path in files:
            path.unlink(missing_ok=True)
        raise
    print(json.dumps(summary(report), indent=2, sort_keys=True))
    print(f"report: {stem.with_suffix('.json')} and {stem.with_suffix('.md')}; pairs: {pairs}")
    return 0
