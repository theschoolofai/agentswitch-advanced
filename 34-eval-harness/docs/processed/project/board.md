# Task board

> Who is doing what. Keep **at most one card in Doing per person**. Take the top card from Ready only when you finish one. Each card names an owner and links its story in [plan.md](plan.md).

**Owners marked "(proposed)" are only suggestions.** Nothing has been agreed yet. The team will settle them together at the first meeting, and then the "(proposed)" labels come off.

Card format: `S34-NN | title | owner | milestone`. A card on this board already has its number. A new card takes the next free number (**S34-35** at the moment), claimed in the title of the pull request that adds it. Never reuse a number.

**Never delete a card, for traceability.** Every number from S34-01 up to the last one claimed stays on this board, exactly once. A card only moves between sections. A finished card goes to Done. A card merged into another, or no longer needed, goes to Done or Dropped with a one-line note saying why and which card took it over. To change a card, update its line in place; git history keeps the old wording.

## Backlog
- S34-10 | Score history file and regression report | Krishna (proposed) | M2
- S34-11 | Repeated trials (pass^k) and flaky-task flag | Krishna (proposed) | M2
- S34-12 | Rescore saved run records with a new verifier version | Krishna (proposed) | M2
- S34-13 | Fake platform for tests (no live calls) | Krishna (proposed) | M2
- S34-14 | Nightly schedule (location decided with instructor, Q5) | Krishna (proposed) | M3
- S34-15 | "Plug your suite into our runner" guide for other seats | Krishna (proposed) | M3
- S34-16 | Suites for seats 28, 29, 30, 32, 33 (split later) | to agree together | M3
- S34-20 | Grader "expected change": the agent was asked to make something; check it exists and is right (for example, an unsent draft reminder to a customer who really is overdue). Blocked (11 Nov): seat 31's mailbox exists since 10 Nov, but email is private to its owner and a harness run gives the agent our token, which has no email app; needs S34-22. Nothing lands on the platform for 15 Nov | Abhinav | M1
- S34-21 | Grader "proposal, not action": a proposal exists, and the records it is about are unchanged (for example, a merge proposal with both parties untouched). For version 1: the instructor recommends one approval request per merge proposal (seat 35 channel, 10 Nov); check first that our login can read approval requests. Not needed for 15 Nov | to agree together | M2
- S34-22 | Driver: start or call an agent that works under its own seat's login (platform agent task or A2A), wait for it, and record the job. Blocked on instructor question Q2 | to agree together | M1
- S34-23 | The "no writes" check also watches the agent's own login, not only ours (after S34-22) | to agree together | M1
- S34-24 | Count the agent's tokens and steps on our side, not only as the agent reports them | to agree together | M2
- S34-25 | Run the most telling tasks first when the budget is tight | to agree together | M2
- S34-26 | Demo recording, 5 minutes at most (a course "finished" item) | to agree together | M5
- S34-27 | Local dry run of the 12 M1 tasks, then the first official run on the course runner (needs S34-07, S34-08 and Q1) | to agree together | M1
- S34-28 | Final README (a course "finished" item) | to agree together | M5
- S34-29 | Integration run of all 8 seats (20 Dec): run it, record the results and share them | to agree together | M4
- S34-30 | Close the bug list: every bug fixed, won't fix, or closed with a reason (a course "finished" item) | to agree together | M5
- S34-31 | One task's crash while grading or saving its record becomes that task's infrastructure row; rows already finished always survive; a broken suite file still writes `results.json`; run-level tests for each case (found in the PR #12 review, 8 Nov) | to agree together | M1
- S34-32 | Every task always appears in `results.json`: list all tasks as "not reached" at the start, and check when the suite loads that it fits `timeout_minutes` (TASK_FORMAT: never silently dropped) | to agree together | M1
- S34-33 | Evidence text matches TASK_FORMAT and [principles.md](../evaluation/principles.md) (`verifier=`, `ended=`, `reason=`; a cut marked `…`); a setup failure uses the real system name, not a placeholder | to agree together | M1
- S34-34 | The "no writes" check reads only rows changed since the trial started: a server-side time filter if the list API takes one (check live first), otherwise a page cap that marks the check unevaluated. Today the list is one page, because our login has almost no writes (found in the PR #21 review, 10 Nov) | to agree together | M2

## Ready
- S34-17 | Verify the bug drafts in `docs/bugs/reports/` (BUG-34-001 to BUG-34-003), then file the real ones (BUG-34-003 narrowed on 10 Nov to what is still refused; a seat-group question may replace it) | Krishna | M0
- S34-08 | Seat 35 suite: 6 tasks, written by hand (start from the seat 35 titles in closed PR #12, reshaped to seat 35's first task, the duplicate report with merge proposals). For 15 Nov seat 35 writes nothing and the instructor scores their pairs file directly, so tasks check its safety promises with the existing graders; confirmation of this plan asked of the instructor (11 Nov) | Ranjani | M1

## Doing
- S34-01 | Seat foundations: `.gitignore`, uv project, wiki, plan, `AGENTS.md` (written; in PR #18, waiting for review) | Krishna | M0
- S34-02 | Live access probe (`scripts/probe_access.py`) and access map (written; ships in the same PR) | Krishna | M0
- S34-18 | Platform sync script and bug workflow (`scripts/platform_sync.py`, `docs/bugs/`) (written; ships in the same PR) | Krishna | M0
- S34-03 | Send instructor questions Q1–Q6; agree with seats 31 and 35 where their results land on the platform | Krishna | M0

## Review
- S34-07 | Seat 31 suite: 6 safety tasks in `suites/seat31/suite.toml`, graded with `records_unchanged` + `no_writes_since_start`. Agent line waits on seat 31 adding `--prompt` (instructor, 13 Nov). Local run with a do-nothing stand-in agent: 6/6 on Suryodaya and Keystone | Abhinav | M1
- S34-19 | Eval-harness scaffold + plumbing task, run end to end on both systems (covers S34-04/05/06/09). In PR #21; the instructor's 10 Nov review changes are done (harness mode uses only the given token and URLs; run-path tests). Abhinav's review (10 Nov) answered on 11 Nov: the time limit now stops the agent's whole process group, and records are scrubbed before scoring; the allowlist was already done; paging moved to S34-34. Waiting for re-review | Krishna | M1
- S34-04 | Platform client: read-only guard, login check, time limits, secret scrubbing (mcp SDK + httpx2) (built inside S34-19, as a GET-only REST reader; see decision 0009) | Krishna | M1
- S34-05 | Run record and scorer writing `results.json` (atomic, infrastructure rows) (built inside S34-19) | Krishna | M1
- S34-06 | Driver: start the agent under test with env and a timeout (built inside S34-19 for a local agent; agents under their own login are S34-22) | Krishna | M1
- S34-09 | `agentswitch-harness.toml` in the seat folder and a local dry run (built inside S34-19) | Krishna | M1

## Done
- (nothing merged yet)

## Dropped
- (none)
