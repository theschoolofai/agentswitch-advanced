# AGENTS.md

Instructions for AI coding agents working in the seat 35 folder. The top-level [README](../README.md) rules apply as
well; the seat brief is in [README.md](README.md).

## The seat

- **Scope:** data quality across parties and items: duplicates, missing required fields, orphan records. The agent
  proposes merges with a confidence for each; a person approves them.
- **First task (15 Nov 2026):** a duplicate-party and duplicate-item report with merge proposals and a confidence
  for each.
- **Later:** version 1 with a 12-task test suite (30 Nov), integration run of all eight seats (20 Dec), final
  (31 Dec). Finished means the test suite passes on both systems, a demo recording of at most 5 minutes, a README,
  and a closed bug list.
- **Team:** Dheeraj (seat lead, merges pull requests) and Pravin.

## Live systems: ask before running

Suryodaya (`https://agentswitch.theschoolofai.in`) and Keystone (`https://class.agentswitch.theschoolofai.in`) are
live, shared instances. Reading code and running the offline tests need no confirmation. Ask the person you are
working for before anything else that calls them. The exception is `python -m data_steward.probe` (login,
`initialize`, `tools/list`; no writes), but do not repeat it after a login failure.

- The agent proposes; it never changes a record. A person approves every change.
- The seat's login can call more than it should use: update tools for parties and items are visible. Never call
  them. `McpClient.call` refuses, before sending, any tool the platform does not mark both read-only and
  non-destructive (`McpClient.allows`). Do not weaken or bypass that check; a later step that must write gets its
  own reviewed path.
- Approval requests, todos and bug reports are themselves records on a shared system: ask before creating any.
- Never delete or overwrite data this seat did not create.
- Ten wrong passwords in 15 minutes lock the login, so a failed login is never retried automatically.
- Usage is monitored and heavy use can be limited without notice, so keep live reads few and small. Harness
  submissions are limited to one run per seat every 3 days. Never submit a run without being asked.

## The repository is public

- No passwords, tokens, keys or `.env` in commits. `.env` and `.tokens/` are git-ignored.
- No AgentSwitch source code, schemas, database files or screenshots of internal screens. Anything derived from the
  platform (tool lists, input schemas, field maps, probe dumps) goes in `local/`, which is git-ignored. Check
  `local/tools-<instance>.json` for a tool's arguments instead of guessing them.

## Git workflow

Work on a branch in your fork (`origin`) and open a pull request into `theschoolofai/agentswitch-advanced` `main`
(`upstream`). One review from another person on this seat or the Eval Harness seat, then the seat lead merges. Never
push to `upstream`, never merge your own pull request. Fill in the pull request template's checklist. Commits are
the record of the seat's work, so make one per logical change.

## Layout

| Path | What it is |
|---|---|
| `data_steward/config.py` | instance URLs, `.env` loading, credentials, harness-runner detection |
| `data_steward/mcp_client.py` | `Session` (login, token cache, re-login), `McpClient` (JSON-RPC calls, `list_all`) |
| `data_steward/probe.py` | read-only login and tool list per system |
| `data_steward/dedupe.py` | the duplicate matcher: normalize, group, score, band, exclusions. Pure functions, no network |
| `data_steward/proposals.py` | merge proposals: suggested survivor, field differences, reference counts (read-only calls) |
| `data_steward/report.py` | the scan and the JSON and Markdown report behind `python -m data_steward.dedupe` |
| `docs/first-task-plan.md` | the first-task plan: decisions, signals, exclusions, build steps |
| `tests/` | offline tests; every network call is faked. `tests/data/dedupe_tuning.json` is the made-up tuning set |
| `local/` | git-ignored platform-derived output: tool lists, reads, reports, test tags, labels |

## Commands

```bash
uv sync
cp .env.example .env                   # both passwords; .env is git-ignored
uv run pytest                          # offline tests
uv run ruff check .
uv run python -m data_steward.probe    # read-only: what tools this seat sees on each system
uv run python -m data_steward.probe --instance keystone
uv run python -m data_steward.dedupe --instance keystone   # read-only scan; ask first (see "Live systems")
```

## The duplicate report

- `python -m data_steward.dedupe` reads every party and item on one system (the harness runner's, else the one
  given, else Keystone) and writes `local/dedupe-<instance>.json` and `.md`, owner-only. It always writes to
  `local/`: the report holds real party data. Standard output is counts only, safe for a pull request description.
- It reads `local/test-tags.txt` (one confirmed test-run tag per line, the tag first, then where it came from) and
  `local/dedupe-labels.json` (`{"<pair id>": "accepted" | "rejected"}`). It never writes either. Add a tag only when
  a read has confirmed it; never hard-code one in the repository.
- Scores are rule scores, not probabilities. Changing anything that can affect which pairs are found, their scores,
  bands or exclusions after step 7's freeze voids the held-back check (see the plan).

## Environment and logins

- The login is `SEAT35_EMAIL` in `.env`: a username from the course team (no mail is sent), kept out of the
  repository. Each system has its own password (`SEAT35_PASSWORD_SURYODAYA`, `SEAT35_PASSWORD_KEYSTONE` in `.env`)
  and its own token, cached in
  `.tokens/seat35-<instance>.token`. A token lasts 7 days; on a 401 the client logs in once and retries.
- `OPENAI_*` in `.env` are only for local runs once a model is in the loop; nothing reads them yet.
- Python 3.11 locally; runtime code (`data_steward/`) must also run on 3.10 because the harness runner does not say
  which Python it uses. `.env` values win over the shell, except under the harness runner (`AGENTSWITCH_TOKEN` set),
  where `.env` is not read at all and the runner's `AGENTSWITCH_*` and `OPENAI_*` values are used.

## Harness contract

The course harness runs a suite against a throwaway copy of one instance with no internet, and reads `results.json`.
The format (harness toml, environment variables, `results.json` fields, limits) is in
[../34-eval-harness/TASK_FORMAT.md](../34-eval-harness/TASK_FORMAT.md). A task passes only when a check on the
resulting data confirms it, never because of the agent's wording.

## Reporting problems

Use the format in [../BUG_REPORT_FORMAT.md](../BUG_REPORT_FORMAT.md), one report per finding, sent to the course team
as text. Never include a password, token or customer data. Reports that hold platform data stay out of the
repository.

## Platform quirks

- JSON-RPC errors arrive as HTTP 200: every MCP call inspects the envelope.
- Reads are retried on 502/503/504; writes never are. Whether a tool is a read comes from its annotations, the same
  test the guard uses, not from its name.
- The MCP endpoint may answer as JSON or as server-sent events; `_decode` handles both.
- `.list` tools page with `limit` and `offset` (the cap is in `local/`). `McpClient.list_all` marks a result `truncated` whenever
  rows may have been left behind, and raises on a reply without a rows list rather than returning an empty table.
- Reference counts do not use `list_all` or the reported total: they page every filtered row until an empty page,
  because a server may cap a page below the requested limit, and check that every row carries the filter value.

## Code style

Match the existing code: double quotes, ~120-char lines, PEP 604 unions and builtin generics, plain dicts as the
data interchange format, stdlib → third-party → local imports. Ruff checks correctness rules only; no formatter is
run. Comments explain why the platform behaves oddly, not what the code does.
