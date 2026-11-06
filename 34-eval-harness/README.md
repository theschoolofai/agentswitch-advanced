# Seat 34 — Eval Harness

Golden-task suites with verified-pass checks for the seat agents, plus a nightly regression run and a score history.

## What this is

A harness repo in the format defined by TASK_FORMAT.md: agentswitch-harness.toml at the root, a runner that writes results.json, and task suites that judge the resulting data, not the agent's wording.

## Harness contract

agentswitch-harness.toml contains:

    install = "pip install -r requirements.txt"
    run     = "python -m harness.runner --out results.json"
    results = "results.json"
    instances = ["suryodaya", "keystone"]
    timeout_minutes = 20

## Environment (set by the run, never committed)

- AGENTSWITCH_BASE_URL — copy of the instance under test
- AGENTSWITCH_TOKEN — short-lived token for the seat under test
- AGENTSWITCH_INSTANCE — suryodaya or keystone
- AGENTSWITCH_RUN_ID — run id
- OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_MODEL — model endpoint

No internet during a run. Packages install first via install.

## Run

    pip install -r requirements.txt
    AGENTSWITCH_BASE_URL=... AGENTSWITCH_TOKEN=... AGENTSWITCH_INSTANCE=suryodaya python -m harness.runner --out results.json

## Layout

    agentswitch-harness.toml
    requirements.txt
    harness/runner.py        discovers tasks, writes results.json
    harness/client.py        MCP client (tools/list, tools.search, tools/call)
    harness/tasks/           12 tasks: seats 31 (order-to-cash) + 35 (data-steward)
    probe.sh                 MCP probe

## Task suites

Seat 31 — order-to-cash-watcher (6 tasks, 1 refusal):
1. Reconcile invoice with matching payment
2. Flag sales orders missing a PO
3. Close fully-shipped orders
4. Refuse to delete customer master data (refusal)
5. Recalculate order total after discount
6. Route high-value orders to approval queue

Seat 35 — data-steward (6 tasks, 1 refusal):
1. Deduplicate partner records by email
2. Fill missing country from address
3. Normalize phone numbers to E.164
4. Refuse to drop or truncate records (refusal)
5. Merge duplicate partner records
6. Flag records missing required fields

Each task drives the seat agent, reads the resulting data, and judges it. passed is true only on a verified check of data. Timeouts and model errors are reported as infrastructure failures, never dropped.

## Status

- [x] Harness format, runner, MCP client, 12 task stubs
- [x] Runner verified end-to-end (0/12 with stubs)
- [ ] Verifiers judging resulting data — blocked pending seat drive tool + read access (reported to Rohan)
- [ ] Negative test per verifier
- [ ] Nightly regression + score history (v1 milestone, 30 Nov)

## Rules

- Every change is a pull request.
- Never commit passwords, tokens or keys.
- Do not delete or overwrite data you did not create.
- Commits and bug IDs are the record of work.
