# What we are building

> The parts of the seat 34 harness, how they fit together, and why. The code starts in Milestone 1. This page is the design, and it changes when we learn something new.

## The job, in one sentence
For each seat, run a small set of hand-written tasks against its agent on both companies. Decide pass or fail only from what changed on the platform. Write the course's `results.json`. Keep a history so we notice when something that used to pass starts failing.

## The parts
```
suite file ──► driver ──► run record ──► verifier ──► scorer ──► results.json
 (tasks)     (runs the   (saved to      (reads the   (adds up)      │
             agent)       disk first)    platform)                  ▼
                                                                history
```

Each part is one small module, with no framework.

1. **Suite file** (one per seat, written by people). Each task has:
   - `id` (stable, for example `suryodaya:t31_unsent_reminders`), `title`, the instances it runs on, and its type (normal, refusal, integrity or missing resource);
   - a version number and the author's name;
   - the request to give the agent;
   - the verifier to use, and its settings.
2. **Driver.** It starts the agent under test with the command the suite names, the environment variables the course runner provides, and a time limit. How exactly another seat's agent gets started is still an open question (see risks, Q2).
3. **Run record.** It is saved to `runs/<run_id>/<task>.json` **before** scoring. It holds:
   - the manifest: git commit, task and verifier versions, model, instance;
   - the start time, taken from the server's clock;
   - the before and after snapshots;
   - timings and errors.

   `runs/` is git-ignored, because records may contain customer data.
4. **Verifiers.** These are read-only functions. Each one looks at the snapshots and the platform, and returns a verdict (approve, revise or unevaluated), a score from 0 to 1, and a reason. Kinds:
   - **Expected change.** The right new records exist, and they are found by the platform's audit fields, never by ids the agent reports. Example: a reminder exists as an unsent draft to a customer who really is overdue.
   - **No change.** For refusal and read-only tasks, nothing was created, changed or deleted by the run's login since the start, and the protected records are untouched.
   - **Proposal, not action.** A proposal record exists, and the records it is about are unchanged.
5. **Scorer.** It reads the run records and writes `results.json` in the course format. It can rescore old records without running the agent again. It also writes the infrastructure failures as failures, with the reason given.
6. **History.**
   - Each run appends one line per task to `history/<seat>.jsonl`: date, run id, instance, task id, task version, verdict, score and a short reason. No customer data goes in. This file is committed, so the history is visible.
   - The **regression report** lists tasks that went from pass to fail.
   - A **flaky** task is flagged and kept out of the alarm.
7. **Nightly run.** One command runs every suite on both systems and updates the history. Where it runs on a schedule is decided in Milestone 3.

## Safety built in
- The platform client refuses, before sending, any tool that is not marked read-only. Verifiers cannot change data.
- The client checks the login before any task, so an expired token cannot look like a clean run.
- Secrets (tokens, passwords, model keys) are removed from every record and log.
- Every platform call has a time limit, and low parallelism (about two at a time per system).

## Technology
- **Language and installer:** Python 3.11, installed and run with **uv**. The course runner installs packages with internet first, then runs offline.
- **Libraries:**
  - the official **`mcp`** SDK for MCP;
  - **`httpx2`** for REST (it is the HTTP library the `mcp` SDK itself uses);
  - **`pydantic`** for data shapes;
  - **`pydantic-settings`** for `.env`;
  - the **`openai`** SDK, only when we need a model, for example a model-based grader where a code check cannot judge.
- **Concurrency:** `asyncio`, so the two systems run at the same time.
- **Quality checks:** `ruff format`, `ruff check`, `mypy --strict`, and `pytest` with a fake platform, so tests make no live calls.

## The course harness file
`agentswitch-harness.toml` lives in `34-eval-harness/` for now. The course runner expects it at the root of a repository, and this repository is shared by 8 seats, so that question is open with the instructor (risks, Q1).

## Known gaps (7 Nov)
- **Some data our checks need is not readable yet.** This covers parts of seat 31's and seat 35's data. Details are in the local platform notes.
- **Seats 31 and 35 keep their results in local files**, which leaves our verifiers nothing on the platform to check.

These are tracked in [../project/risks.md](../project/risks.md). Until they are fixed, the affected tasks report **unevaluated** or **infrastructure** honestly. We do not invent a pass.
