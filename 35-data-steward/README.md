# Seat 35: Data Steward

## Scope
Data quality: duplicate parties and items, missing required fields, orphan records. Proposes merges; a person approves them.

## First task
A duplicate-party and duplicate-item report with merge proposals and a confidence for each.

## Access
crm, inventory, accounting (read)

## Milestones
- 15 Nov 2026: first task delivered
- 30 Nov 2026: version 1, with a 12-task test suite
- 20 Dec 2026: integration run of all eight seats
- 31 Dec 2026: final

## Working rules
See the top-level README. Put your agent code, tests and notes in this folder; open a pull request for every change.

## Setup
```bash
uv sync
cp .env.example .env                   # paste both passwords; .env is git-ignored
uv run pytest                          # offline tests
uv run python -m data_steward.probe    # read-only login and tool list on both systems
```
The probe writes the full tool list to `local/`, which is git-ignored because it is platform-derived. See
[AGENTS.md](AGENTS.md) for what may run against the live systems.

## Duplicate report (first task)
```bash
uv run python -m data_steward.dedupe --instance keystone     # or suryodaya; read-only
```
Reads every party and item on one system and writes `local/dedupe-<instance>.json` (the record of truth),
`local/dedupe-<instance>.md` (made from it) and `local/dedupe-<instance>-pairs.json` (every listed pair as its pair
id, the two record ids, score and band, plus whether each table was cut off), readable by you only. Compare pairs
without regard to the order of the two ids. The pair list includes test-record pairs, which the summary leaves out of
its band counts, so it can hold more pairs than those counts add up to. The course harness adds `--prompt "<request>"`; the command accepts it
and runs the same scan whatever the request says (no model yet). Nothing on the platform changes: a person decides,
and makes any change through the platform.

The instructor scores `results/dedupe_pairs.json`, committed in a pull request. Make it from the saved reports,
with no platform call:
```bash
uv run python -m data_steward.results                        # both systems; or --instance suryodaya
```
One entry per proposed pair: `kind`, `id_a`, `id_b`, `confidence` and `reason`, and no names, emails or other record
values. Pairs a person labelled "rejected" are left out. Test-record pairs are listed, with "test-run records" at the
end of the reason: since 17 Nov, repeated test-run records count as duplicates. A review pair's confidence is capped
at 0.6, since a pair held at review can score 1.0; today every review pair gets 0.6. Standard output gives counts per
system and kind (listed, left out, written, test-record pairs written) and the number of rejected labels that match
no listed pair: check it is 0 before committing the file.

Example: the export of the made-up records in `tests/` (ids such as `p1` are made up; these are not pairs from
either system). `tests/test_results.py` checks that this block is what the exporter writes for those records.
```json
[
  {"kind": "party", "id_a": "p1", "id_b": "p2", "confidence": 1.0, "reason": "same email; matching name"},
  {"kind": "party", "id_a": "p3", "id_b": "p4", "confidence": 0.6, "reason": "matching name"},
  {"kind": "party", "id_a": "p5", "id_b": "p6", "confidence": 0.6, "reason": "matching name; test-run records"},
  {"kind": "party", "id_a": "q1", "id_b": "q2", "confidence": 0.6,
   "reason": "same email; matching name; held at review: different phone numbers"},
  {"kind": "item", "id_a": "i1", "id_b": "i2", "confidence": 0.6,
   "reason": "matching name; same unit of measure; held at review: different item codes"}
]
```
The first pair is proposed (score 0.9 or more) and keeps its score. The other four are review pairs, listed at 0.6;
`p5` and `p6` are test-run records, and `q1` and `q2` score 1.0 but are held at review because their phone numbers
differ.

The committed file, made from the 17 Nov reports, holds 63 pairs, all at review (0.6): 62 Keystone party pairs
between records left by earlier test runs, and 1 Suryodaya item pair. No pair reached propose. The 16 Suryodaya party
pairs at review are left out because they are labelled rejected. Pull request #25 gives the counts per system and
kind.

Two optional input files in `local/` (git-ignored; the run reads them and never writes them). To reproduce another
person's report, get both from them privately:

- `local/test-tags.txt`: confirmed test-run tags, one per line (the tag, then where it was seen). Without it, pairs of
  test-run records are not set apart and show up as pairs to review.
- `local/dedupe-labels.json`: a person's verdicts, `{"<pair id>": "accepted" | "rejected"}`. Without it, every pair
  shows as awaiting a decision, and `results` lists the pairs that person rejected.

Anyone with a seat 35 login can rerun the scan from this repository: everything that decides the pairs is committed,
and only `.env` and `local/` are not. The same commit (same rules version) run on unchanged data finds the same pairs
with the same scores and bands. Two runs write the same file only when the rows, the date, the labels and the test
tags all match, so a run on a later day, or after someone edits a record, differs.

What the Markdown report shows:

- A summary first: which pairs await a person's decision, and per table the records read, proposed merges, pairs to
  review, labels, test-record pairs and pairs ruled out.
- Confidence as a band from a rule score between 0 and 1: **propose** (0.90 or more, nothing holding the pair back),
  **review** (0.60 or more but below 0.90, or held back by conflicting values, different roles or names that are only
  similar). Pairs below 0.60 are counted, not listed.
- For each pair awaiting a decision: the evidence both records share, why it was held at review, a suggested record to
  keep if the merge is approved (with the rule that chose it), the fields that differ, and, for proposed pairs, how
  many linked records point at each side. Pairs a person has already labelled, and test-record pairs, are one row
  each; their full detail is in the JSON.
- Pairs ruled out, with the reason: different companies, different party types, different item types or units, one
  item a variant of the other, or marked as an allowed duplicate.

The report holds real party data, so it stays in `local/` and goes to the seat lead directly. Standard output is a
counts-only summary for the pull request. How each rule was chosen is in
[docs/first-task-plan.md](docs/first-task-plan.md). For readers who don't read code,
[docs/duplicate-rules.html](docs/duplicate-rules.html) explains the rules step by step, with diagrams, a score
calculator and made-up examples (download it and open it in a browser; GitHub shows only its source). Update it when
the rules version changes.
