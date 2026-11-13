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
Reads every party and item on one system and writes `local/dedupe-<instance>.json` (the record of truth) and
`local/dedupe-<instance>.md` (made from it), readable by you only. Nothing on the platform changes: a person decides,
and makes any change through the platform.

Two optional input files in `local/` (git-ignored; the run reads them and never writes them). To reproduce another
person's report, get both from them privately:

- `local/test-tags.txt`: confirmed test-run tags, one per line (the tag, then where it was seen). Without it, pairs of
  test-run records are not set apart and show up as pairs to review.
- `local/dedupe-labels.json`: a person's verdicts, `{"<pair id>": "accepted" | "rejected"}`. Without it, every pair
  shows as awaiting a decision.

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
