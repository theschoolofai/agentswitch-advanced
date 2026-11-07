# Task board

> Who is doing what. Keep **at most one card in Doing per person**. Take the top card from Ready only when you finish one. Each card names an owner and links its story in [plan.md](plan.md).

**Owners marked "(proposed)" are only suggestions.** Nothing has been agreed yet. The team will settle them together at the first meeting, and then the "(proposed)" labels come off.

Card format: `S34-NN | title | owner | milestone`. A card on this board already has its number. A new card takes the next free number (S34-19 at the moment), claimed in the title of the pull request that adds it. Never reuse a number.

## Backlog
- S34-10 | Score history file and regression report | Krishna (proposed) | M2
- S34-11 | Repeated trials (pass^k) and flaky-task flag | Krishna (proposed) | M2
- S34-12 | Rescore saved run records with a new verifier version | Krishna (proposed) | M2
- S34-13 | Fake platform for tests (no live calls) | Krishna (proposed) | M2
- S34-14 | Nightly schedule (location decided with instructor, Q5) | Krishna (proposed) | M3
- S34-15 | "Plug your suite into our runner" guide for other seats | Krishna (proposed) | M3
- S34-16 | Suites for seats 28, 29, 30, 32, 33 (split later) | to agree together | M3

## Ready
- S34-17 | Verify the seed bug drafts in `docs/bugs/reports/`, then file the real ones | Krishna | M0
- S34-04 | Platform client: read-only guard, login check, time limits, secret scrubbing (mcp SDK + httpx2) | Krishna (proposed) | M1
- S34-05 | Run record and scorer writing `results.json` (atomic, infrastructure rows) | Krishna (proposed) | M1
- S34-06 | Driver: start the agent under test with env and a timeout | Krishna (proposed) | M1
- S34-07 | Seat 31 suite: 6 tasks, written by hand | Abhinav (proposed) | M1
- S34-08 | Seat 35 suite: 6 tasks, written by hand | Ranjani (proposed) | M1
- S34-09 | `agentswitch-harness.toml` in the seat folder and a local dry run | Krishna (proposed) | M1

## Doing
- S34-01 | Seat foundations: `.gitignore`, uv project, wiki, plan, `AGENTS.md` (written; waiting on the lead's commit and PR) | Krishna | M0
- S34-02 | Live access probe (`scripts/probe_access.py`) and access map (written; ships in the same PR) | Krishna | M0
- S34-18 | Platform sync script and bug workflow (`scripts/platform_sync.py`, `docs/bugs/`) (written; ships in the same PR) | Krishna | M0
- S34-03 | Send instructor questions Q1–Q6; agree with seats 31 and 35 where their results land on the platform | Krishna | M0

## Review
- (none)

## Done
- (nothing merged yet)
