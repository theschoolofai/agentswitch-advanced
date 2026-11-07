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
`local/dedupe-<instance>.md` (made from it), readable by you only. Each pair has a rule score from 0 to 1 and a band:
**propose** (0.9 or more, no conflict), **review** (0.6 to 0.9, or held back by a conflict, a role difference or names that are only near), or
dropped and only counted. Each pair also lists its evidence, a suggested survivor with the rule that chose it, the
fields that differ, and, for proposed pairs, how many records point at each side. Pairs that must never merge
(different companies, an individual and an organisation, different kinds or units, variants) are listed with the
reason. Nothing on the platform changes: a person decides, and makes any change through the platform.

The report holds real party data, so it stays in `local/` and goes to the seat lead directly. Standard output is a
counts-only summary for the pull request. How each rule was chosen is in
[docs/first-task-plan.md](docs/first-task-plan.md).
