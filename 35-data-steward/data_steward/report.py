"""Scan parties and items on one system and write the duplicate report. Read-only: nothing on the platform changes.

    uv run python -m data_steward.dedupe                      # Keystone, or the harness runner's instance
    uv run python -m data_steward.dedupe --instance keystone

Writes local/dedupe-<instance>.json (the record of truth) and local/dedupe-<instance>.md (made from it). Both hold
real party data, which is why they go to the git-ignored local/. Standard output carries counts only.

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
import tempfile
from collections import Counter
from pathlib import Path

from . import config, dedupe, proposals
from .mcp_client import McpClient, Session

TABLES = {"party": "Party", "item": "Item"}
LABELS = ("accepted", "rejected")

NOTES = [
    "Scores are rule scores from 0 to 1, not probabilities.",
    "How often each band is right has not been checked yet (step 7 of the plan): every band is unchecked.",
    "Survivors are suggestions. A person decides, and any change to a record is made by a person, through the "
    "platform, with approval. This report changed nothing.",
    "A pair not listed is not proof that two records are distinct. If a table was cut off, the rows beyond the cut "
    "were never compared: an incomplete scan does not mean there are no duplicates.",
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


_MARKDOWN = re.compile(r"([\\`*_\[\]()!|~#])")


def _cell(value) -> str:
    """Record text as literal Markdown: one line, at most 200 characters, with HTML and Markdown syntax escaped, so a
    value can neither break a table nor render as a link, an image or markup."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = " ".join(str(text).split())
    text = text if len(text) <= 200 else text[:199] + "…"
    return _MARKDOWN.sub(r"\\\1", html.escape(text, quote=False))


def _code(value) -> str:
    """An id as a code span. Escapes do not work inside one, so a backtick, which would end it early, is replaced,
    and a pipe, which would end a table cell, is too."""
    text = " ".join(str(value).split()).replace("`", "'").replace("|", "/")
    return f"`{text}`"


def _pair_md(p) -> list[str]:
    a, b = p["ids"]
    lines = [f"#### {_cell(p['names'][a])} / {_cell(p['names'][b])}", "",
             f"- Pair {_code(p['id'])}: score {p['score']:.2f}, band **{p['band']}**",
             f"- Evidence: {', '.join(p['signals']) or 'none'}"]
    if p["caps"]:
        lines.append(f"- Held at review: {', '.join(p['caps'])}")
    if p["shared_record"]:
        lines.append("- A record here is in another pair too: review those pairs together.")
    s = p["survivor"]
    why = {"references": "not counted for review pairs" if p["references"] is None else "a count is unknown",
           "age": "a creation date is missing"}
    skipped = f" (skipped {'; '.join(f'{step}: {why[step]}' for step in s['skipped'])})" if s["skipped"] else ""
    lines.append(f"- Suggested survivor: {_code(s['id'])}, by {s['rule']}{skipped}")
    if p["references"] is not None:
        totals = {rid: (r or {}).get("total") for rid, r in p["references"].items()}
        lines.append("- References: " + ", ".join(f"{_code(rid)} {'unknown' if n is None else n}"
                                                   for rid, n in totals.items()))
    label = p.get("label")
    lines.append(f"- Label: {label['label'] + (' (' + _cell(label['note']) + ')' if label.get('note') else '')}"
                 if label else "- Label: none yet")
    if p["differences"]:
        lines += ["", f"| Field | {_code(a)} | {_code(b)} |", "|---|---|---|"]
        lines += [f"| {_cell(d['field'])} | {'' if d['a'] is None else _cell(d['a'])} | "
                  f"{'' if d['b'] is None else _cell(d['b'])} |" for d in p["differences"]]
    else:
        lines += ["", "No field differences outside the hidden and bookkeeping fields."]
    return lines + [""]


def render_markdown(report: dict) -> str:
    lines = [f"# Duplicate report: {report['system']}, {report['date']}", "",
             f"Rules version {report['rules_version']}. Made from the JSON report of the same name.", ""]
    lines += [f"- {n}" for n in report["notes"]] + [""]
    for entity, s in report["sections"].items():
        t, c = s["table"], s["counts"]
        lines += [f"## {entity.capitalize()} records", "",
                  f"Rows read: {t['rows']} of {t['total'] if t['total'] is not None else 'an unknown total'}"
                  + (". **The table was cut off.**" if t["cut_off"] else ", the whole table."), ""]
        untagged = [p for p in s["proposals"] if not p["tagged"]]
        tagged = [p for p in s["proposals"] if p["tagged"]]
        for band, title in (("propose", "Proposed merges"), ("review", "For review")):
            pairs = [p for p in untagged if p["band"] == band]
            lines += [f"### {title} ({len(pairs)})", ""] + ([] if pairs else ["None.", ""])
            for p in pairs:
                lines += _pair_md(p)
        lines += [f"### Test records ({len(tagged)})", "",
                  "Pairs where either name carries a confirmed test-run tag. Scored and banded like the rest. Tags: "
                  + ("; ".join(_cell(t["tag"]) + (f" ({_cell(t['source'])})" if t["source"] else "")
                               for t in report["test_tags"]) or "none") + ".", ""]
        lines += [] if tagged else ["None.", ""]
        for p in tagged:
            lines += _pair_md(p)
        lines += [f"### Never proposed ({len(s['excluded'])})", ""] + ([] if s["excluded"] else ["None."])
        lines += [f"- {_code(p['id'])} {_cell(p['names'][p['ids'][0]])} / {_cell(p['names'][p['ids'][1]])}: "
                  f"{p['reason']} (score {p['score']:.2f})" for p in s["excluded"]]
        lines += ["", "### Not listed", "",
                  f"- Pairs below review: {c['dropped']}",
                  f"- Records withheld for privacy (details left out): {c['withheld_private']}",
                  f"- Repeated ids (first copy kept): {c['repeated_ids']}",
                  f"- Values too widely shared to count as evidence: {c['ignored_shared'] or 'none'}",
                  f"- Groups too common to compare: {c['skipped_blocks']}",
                  f"- Records whose references could not be read: {c['references_unreadable']}", ""]
    stale = report["labels"]["not_in_this_run"]
    lines += ["## Labels", "", f"Applied: {report['labels']['applied']}. Not in this run: {len(stale)}"
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
    args = parser.parse_args(argv)
    platform = config.platform()
    instance = args.instance or (platform["instance"] if platform else "keystone")
    test_tags = load_test_tags(config.LOCAL_DIR / "test-tags.txt")
    labels = load_labels(config.LOCAL_DIR / "dedupe-labels.json")

    client = McpClient(Session(instance))
    sections = {entity: scan(client, entity, tuple(test_tags)) for entity in TABLES}
    report = build_report(instance, config.today().isoformat(), sections, labels, test_tags)

    # Always local/, which is git-ignored: the report holds real party data and the repository is public.
    config.LOCAL_DIR.mkdir(exist_ok=True)
    stem = config.LOCAL_DIR / f"dedupe-{instance}"
    _write_private(stem.with_suffix(".json"), json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    _write_private(stem.with_suffix(".md"), render_markdown(report))
    print(json.dumps(summary(report), indent=2, sort_keys=True))
    print(f"report: {stem.with_suffix('.json')} and {stem.with_suffix('.md')}")
    return 0
