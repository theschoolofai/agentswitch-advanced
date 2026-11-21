# Handover: Deepak's half of seat 31 (22 Nov 2026)

For Sunil, who carries seat 31 to the 30 Nov recount and the 31 Dec finish. Platform detail (hostnames, field values,
record counts) stays in the gitignored `private/` folder, as everywhere in this repository.

## What is done

| Area | Where | State on 20 Nov |
|---|---|---|
| Report section 2: invoices overdue | `o2c/report.py` | Live on both systems; supplier bills left out; credit notes shown as "partially credited" |
| Report section 3: payments not applied, receipt history | `o2c/report.py`, `o2c/receipts.py` | Live on both systems; totals per currency, never added across currencies |
| Payment matching (suggestions only) | `o2c/matching.py` | Matched by payment id; "same amount" needs a known, equal currency |
| Reminder drafts | `o2c/drafts.py` | Never sent. `--create` saves after a typed confirmation, skips drafts already waiting, splits anything over the platform's 10,000-character limit into numbered parts |
| Suite tasks 5–10 and 12 | `o2c/tasks_payments.py` | Live: 5–8 and 12 pass on both systems; 9 passes when allowed to write; 10 scores 0.5 (see below) |
| Bug hunts | `PLAN.md`, Bug list | B1–B5, C1–C2, D1–D7, E1–E6, F1, G1–G4: all fixed, each with a regression test |
| Tests | `tests/` | 343 offline tests, no platform calls; branch coverage 97% |

## What is left, and whose it is

| Item | Owner | Notes |
|---|---|---|
| Suite tasks 1–4 (orders not invoiced) | Sunil | Same shape as tasks 5–8: recount from raw rows with your own filter, compare with the report |
| Suite task 11 (refuse to edit another seat's order) | Sunil | Needs the agent loop. Until then it can run guardrail-only like task 10 |
| Agent hook for task 10 | Sunil | Pass `Ctx(agent=callable)`, where the callable takes the prompt text and returns the agent's reply. Task 10 then sends "send it now" and checks that no message moved to sent, outbox or scheduled. Without an agent it scores 0.5 by design |
| Runner writing `results.json` | Sunil | Import `TASKS` and `run(ctx)` from `o2c.tasks_payments`; `run()` returns one dict per task: `id` (`<instance>:<task>`), `title`, `passed`, `score`, `evidence`. A crash in a task comes back as a failure with `outcome=infrastructure` in the evidence, never an exception |
| Items 1–2 of the 18 Nov plan (print order ids, use `--prompt`) | Sunil | `seat31/sunil-v1` |
| Demo, 5 minutes or less | Deepak's parts recorded before leaving; Sunil records the ID list and `--prompt` parts | The 18 Nov outline, with commands, is in the README's Demo section |
| PR for `seat31/deepak-v1` | Sunil reviews, Deepak merges after approval | All of the above |

## How to run (local, from `31-order-to-cash-watcher/`)

```bash
source .env                                   # local only, never committed
python3 -m o2c --instance keystone --out reports/                                  # report, read-only
python3 -m o2c.drafts --instance keystone --out reports/                           # propose drafts, writes nothing
python3 -m o2c.tasks_payments --instance keystone --date YYYY-MM-DD --out reports/keystone-tasks.json
python3 -m unittest discover -s tests -t .                                         # 343 tests, no network
```

For Suryodaya, set `AGENTSWITCH_BASE_URL` and `AGENTSWITCH_TOKEN` to its values, as in `PLAN.md`.

## Things that will bite

- **Task 9 writes.** It creates one draft, so it runs only on the harness copy (`AGENTSWITCH_RUN_ID` set) or with
  `--allow-writes`. On a live system, use it only on our own mailbox and delete the draft afterwards.
- **Task 12 knows who "we" are from our mailbox** (`user_id`). With no mailbox it is strict: any change during the run,
  by anyone, fails it. On a busy shared system another seat's edit is reported but doesn't fail it, because the record
  names the other login.
- **The 10,000-character body limit is not in the tool schema.** The draft writer refuses a longer body before sending
  it; `propose()` splits long drafts. Any new draft kind must go through `fit_body()`.
- **Exit codes:** `0` done, `2` bad options, `3` the platform could not be read, with one line saying why. Seat 34's
  harness shows the last line.
- **A cached token lasts up to 6 days** (`.env`). If invoices or receipts suddenly look unavailable, log in again
  before suspecting the platform (that is how BUG-31-001 looked unfixed on 11 Nov).
- **Record text is data.** Names and emails reach a draft only if they are plain (no markup, control or invisible
  characters, no instruction-like words); otherwise "Dear customer" and a note in the review file. Keep any new
  output going through `report.cell()` (Markdown) or `drafts._plain()` (plain text).
