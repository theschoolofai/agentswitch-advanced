# Seat 34 plan

> Goal, what "done" means, and the milestones up to 31 Dec 2026. We fix the dates and change the scope; we do not move the dates.

## Goal
Every advanced seat has a small suite of hand-written tasks that is judged only by what changed on the platform. It runs on both companies, on a schedule, and keeps a history, so a regression is noticed within a day.

## What "finished" means for the seat (from the course brief)
- The test suite passes on both systems (Suryodaya and Keystone).
- A demo recording of at most 5 minutes.
- A README.
- A closed bug list.

## Definition of done for any card
A card is done only when all of these are true:
- [ ] Its acceptance criteria pass.
- [ ] Tests are added or updated, and `uv run pytest` passes.
- [ ] `uv run ruff format --check`, `uv run ruff check` and `uv run mypy` pass. (`mypy` reads its folder list from `pyproject.toml`.)
- [ ] No secrets, platform code, schemas or customer data are in the change.
- [ ] Docs are updated: the wiki page, plus a decision record if the change made a lasting choice.
- [ ] One review by a teammate, and the seat lead has merged it.
- [ ] `status.md` and `board.md` are updated.

## Milestones
Owners in brackets are proposals until the team agrees them together (see [team.md](team.md)).

Each milestone ends with something that runs end to end. We build a thin working slice first, then widen it, and never build all of one layer before the next.

### M0 Foundations: 7–9 Nov (Krishna)
**Outcome:** a safe repository, this wiki, a live access map, this plan, instruction files for agents, and the instructor questions sent.

- **Story:** As a new teammate or coding agent, I want one place that explains the seat, the rules and the next step, so that I can start without reading old chats.
  - Given a fresh session in `34-eval-harness/`, when it reads `AGENTS.md` and `status.md`, then it can say what the seat does, what is next and what is blocked.
- **Story:** As the seat lead, I want our real access checked live, so that we plan from facts, not from chat.
  - Given `.env`, when `scripts/platform_sync.py` runs, then `data/platform/access-summary.md` lists what is reachable and blocked on both systems, and no secret appears in any file.

### M1 First task: 10–15 Nov (proposed: Krishna core; Abhinav seat 31; Ranjani seat 35)
**Outcome:** a thin end-to-end slice. It has a platform client, a driver, run records, verifiers, a scorer, and `results.json` for 12 tasks for seats 31 and 35 on both systems. Blocked tasks report unevaluated or infrastructure honestly. One local dry run and one official run.

- **Story:** As the course runner, I want `results.json` in the course format, so that our suite can be scored.
  - Given a run, when it ends (even after a crash or timeout), then `results.json` has one row per task with `passed`, `score` and `evidence`, and infrastructure failures are marked as such.
- **Story:** As a seat owner, I want my agent judged by platform changes, so that a confident but wrong answer cannot pass.
  - Given a refusal task, when the agent runs, then the verdict depends only on before and after snapshots of the platform.
- **Dates.** A local dry run by **12 Nov**. An official run needs the harness file registered with the course, and that waits on instructor question Q1 ([decision 0006](../decisions/0006-harness-file-in-seat-folder.md)). If Q1 is answered in time, submit by about 12 Nov, which leaves the 3-day window open for a retry on 15 Nov. If not, deliver the first task with the local dry-run results and say so.
- **Suite size.** The first task is **12 tasks in total**: 6 for seat 31 and 6 for seat 35, each run on both systems.

### M2 Version 1: 16–30 Nov (everyone)
**Outcome:**
- the suite re-aimed at the seats' real first outputs (expected around 22–25 Nov);
- repeated trials (pass^k);
- rescoring of saved records;
- score history and a regression report;
- tests against a fake platform;
- a README that runs from top to bottom.

- **Story:** As the seat lead, I want to rescore old run records after a verifier fix, so that we never spend model calls to correct a score.
  - Given saved run records, when the scorer runs with a new verifier version, then results change without any agent run, and the history records the verifier version.
- **Story:** As a seat owner, I want to see which of my tasks regressed, so that I can fix them quickly.
  - Given two runs, when a task passed before and fails now, then the regression report lists it with the reason.

### M3 Nightly run and more seats: 1–19 Dec (split per seat, to agree together)
**Outcome:** a scheduled nightly run; suites for seats 28, 29, 30, 32 and 33; regression notes sent to the owning seats in the bug format.

- **Story:** As any seat, I want my suite run every night, so that I learn about breakage the next morning.
  - Given the schedule, when a night passes, then the history has a new line per task, and any regression is reported.

### M4 Integration run: 20 Dec (proposed: Krishna)
**Outcome:** the integration run of all 8 seats has been run, and the results are recorded and shared.

### M5 Final: 21–31 Dec (everyone)
**Outcome:** the suite passes on both systems; a demo of at most 5 minutes; the README; a closed bug list; a handover note.

## Weekly rhythm
See [team.md](team.md).
