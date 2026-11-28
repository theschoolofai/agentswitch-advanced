# Seat 30: Market Research

## Scope
A weekly market and competitor brief tied to the CRM pipeline.

## First task
A brief for the 10 largest open deals: account facts, what changed, one suggested next step. CRM data only until the read-only web search tool is switched on.

## Access
crm (read), knowledgebase

## Milestones
- 15 Nov 2026: first task delivered
- 30 Nov 2026: version 1, with a 12-task test suite
- 20 Dec 2026: integration run of all eight seats
- 31 Dec 2026: final

## Working rules
See the top-level README. Put your agent code, tests and notes in this folder; open a pull request for every change.

---

**Team:** Sunil (seat lead), Deepak. **Plan, rules, status and bug list:** [PLAN.md](PLAN.md).

**Status (v1, 30 Nov):** the brief and the 12-task suite are on `main`. The suite passes 12 of 12 on both systems, Suryodaya and Keystone: in the joint live run on 26 Nov, and again on 28 Nov. The offline tests pass. No bugs are open ([bug list](#bug-list)).

## What the seat does

One command, `python3 -m brief`, writes the **weekly deal brief** for a sales manager. It is deterministic: no model is called, and the same data always gives the same brief. It only reads; it never creates, updates or deletes a record.

For the **10 largest open deals** (per company and base currency), the brief shows:

1. **The deal:** rank, title, account, stage, value in the base currency and expected close date.
2. **Account facts:** account name, contacts, other open deals on the account, last contact, open activities (overdue ones marked) and the pinned note.
3. **What changed** since the previous run: changes to a deal's stage, value, currency, probability, close date, owner, account, pipeline or title; deals that entered the top 10; and deals that left it, each with the reason (closed, left out, outranked…).
4. **One suggested next step**, with its reason, from fixed rules ([PLAN.md](PLAN.md#next-step-rules-nextsteppy)). It is a proposal for a person to act on; nothing is created.

The brief also lists **data issues**: deals left out of the ranking because of an unknown stage, a missing or zero value, or no usable currency, each with one reason. Other seats' test data is ranked and flagged "looks like test data", never hidden.

**How deals are ranked:** open deals only (not `closed_won` / `closed_lost`), by value in the base currency, largest first. Ties are broken by deal id as text. Amounts in different currencies are never added together. With more than one company or base currency, there is one list for each. The full rules: [PLAN.md](PLAN.md#selection-rules-dealspy-checked-by-tasks-16).

v1 uses CRM data only. The knowledgebase and the platform's read-only web search come after v1 ([What comes next](#what-comes-next)).

## How it's built

A run reads deals, pipelines, accounts, activities and notes once, then passes them through these modules in order:

| Module | What it does | Owner |
|---|---|---|
| [brief/client.py](brief/client.py) | Read-only client: a read allowlist, strict paging, bounded retries, and it never follows a redirect | Deepak |
| [brief/rows.py](brief/rows.py) | The deal row both halves share; its fields are frozen and guarded by a test | Deepak |
| [brief/deals.py](brief/deals.py) | Open deals only, ranked by base value with a fixed tie-break; data issues; the test-data flag | Sunil |
| [brief/accounts.py](brief/accounts.py) | Account facts per deal: contacts, other open deals, last contact, open activities, pinned note | Sunil |
| [brief/changes.py](brief/changes.py) | What changed: saves a snapshot each run and compares with the previous one | Deepak |
| [brief/nextstep.py](brief/nextstep.py) | One next step per deal from seven fixed rules, first match wins, with its reason | Deepak |
| [brief/report.py](brief/report.py), [brief/\_\_main\_\_.py](brief/__main__.py) | `build()` → JSON + Markdown; the command line and `--prompt` | Sunil |
| [brief/explain.py](brief/explain.py), [brief/debug.py](brief/debug.py) | `--explain` for one deal; `--debug` output, recording and replay | Sunil, Deepak |
| [brief/suite.py](brief/suite.py), [tasks_deals.py](brief/tasks_deals.py), [tasks_brief.py](brief/tasks_brief.py) | The 12-task suite: tasks 1–6 (Sunil) and 7–12 (Deepak) | Deepak, Sunil |

The two halves were built in parallel against interfaces both agreed and froze on 25 Nov ([PLAN.md](PLAN.md#interfaces-frozen-25-nov)). The suite tasks check each other's code: Deepak's task 7 recounts the account facts in Sunil's `accounts.py`, and Sunil's tasks 1–6 recount the ranking from raw records, sharing only the row parsing with `deals.py`.

## Setup

- **Python 3.10 or later**, standard library only. Nothing to install.
- **Credentials**, in environment variables:

  | Variable | Meaning |
  |---|---|
  | `AGENTSWITCH_BASE_URL` | The system to read (Suryodaya or Keystone) |
  | `AGENTSWITCH_TOKEN` | A token for a seat 30 login on that system |
  | `AGENTSWITCH_INSTANCE` | Optional: `suryodaya` or `keystone`, used when `--instance` is not given (as seat 34's harness runs it) |

- Keep them in `30-market-research/.env` and `source` it. `.env*`, `briefs/` and `private/` are gitignored; never commit them.
- Platform detail (hostnames, tool and field names, counts) is kept out of this public repository.

## Run the brief

```bash
cd 30-market-research
source .env                                          # local only, never committed
python3 -m brief --instance keystone                 # the weekly run: writes the brief and saves this week's snapshot
python3 -m brief --instance suryodaya --top 5        # top 5 per company and base currency
python3 -m brief --instance suryodaya --date 2026-11-30   # a dated test run: its snapshot goes to briefs/test-snapshots/
python3 -m brief --explain <deal id> --instance keystone  # why one deal is shown or left out
```

| Option | Meaning |
|---|---|
| `--instance NAME` | `suryodaya` or `keystone` (default: `AGENTSWITCH_INSTANCE`) |
| `--date YYYY-MM-DD` | The brief's date (default: today in IST) |
| `--top N` | Deals per company and base currency (default 10) |
| `--since YYYY-MM-DD` | Compare with the snapshot of exactly this date, instead of the latest earlier one |
| `--out FOLDER` | Where `<instance>-<date>.json` and `.md` go (default: the seat's gitignored `briefs/`). Files are written owner-only |
| `--snapshots FOLDER` | The snapshot folder (see [What changed](#what-changed-and-snapshots)) |
| `--prompt TEXT` | See [`--prompt`](#--prompt) |
| `--explain DEAL_ID` | Why one deal is shown or left out: the selection rules, its account facts and every next-step rule |
| `--debug`, `--record DIR`, `--replay DIR` | Debugging, and saving or replaying a run offline: [DEBUGGING.md](DEBUGGING.md) |

**Output:** the full brief goes to the `.md` and `.json` files. Standard output has one line per deal shown (rank, deal id, next-step rule), then, as the last line, `AGENT_RESULT {"claim": "done" | "refused", "answer": {"top_deals": [ids]}}` for seat 34's harness.

### What a brief looks like

Made-up data, the second week of runs with `--top 3`. Standard output (`brief: wrote …` goes to stderr):

```
  1 d01 negotiation
  2 d02 close_date_passed
  3 d03 overdue_activity
AGENT_RESULT {"claim":"done","answer":{"top_deals":["d01","d02","d03"]}}
```

An excerpt of the Markdown brief:

> **Deal brief: suryodaya, 2026-11-30**
>
> - What changed: since the previous run on 2026-11-23.
> - Top 3 per company and base currency; values are in the base currency, never added across currencies.
>
> | # | Deal | Account | Stage | Value | Close | Next step |
> |---:|---|---|---|---:|---|---|
> | 1 | Warehouse automation | Northwind Traders | Negotiation | 520,000.00 INR | 2026-12-15 | Agree the final terms and a signing date |
> | 2 | Fleet telematics renewal | Blue Harbor Ltd | Proposal | 350,000.00 INR | 2026-11-15 | Confirm a new close date with the deal owner |
> | 3 | Cold-chain sensors | Kestrel Foods | Negotiation | 290,000.00 INR | 2026-12-15 | Complete the overdue activity |
>
> **3. Cold-chain sensors**
> - **Account:** Kestrel Foods (organization)
> - Contacts: Meera Nair (deal contact)
> - Last contact: none recorded
> - Open activities: 1, 1 overdue
>   - 2026-11-18 (overdue): “Confirm sensor count”
> - What changed: stage proposal → negotiation
> - **Next step:** Complete the overdue activity. *Why:* Due 2026-11-18, 12 days overdue.
>
> **Left the list since last time**
> - Smelter maintenance contract: closed won
>
> **Data issues**
> - `d05`: value: zero or less, left out of the ranking
>
> Read-only: this brief changed nothing in the CRM. Next steps are suggestions for a person to act on.

**Exit codes:** `0` done; `1` an unexpected error (traceback, `AGENT_RESULT` with `"failed"`, then one `brief: unexpected error: …` line); `2` bad options, a `--since` date with no snapshot, or a damaged snapshot; `3` the platform could not be read (for example a rejected token), with one line saying why; `5` deal not found (`--explain`).

## What changed and snapshots

The platform keeps no deal history, so the brief keeps its own. Each run saves a snapshot of every ranked open deal, and the next run compares against the latest earlier one.

- **The first run is a baseline.** It says so, and reports nothing as changed. Nothing is ever invented.
- **Which folder:** a plain weekly run (today, no `--prompt`) uses `briefs/snapshots/`. A run with `--date` or `--prompt` uses `briefs/test-snapshots/`, so a test or demo run never becomes the comparison point for a real week. `--snapshots` overrides both.
- **Different logins:** a snapshot records a hashed id of the login that took it. When last week's was taken by another login, the brief says that some changes may only be differences in what each login can see.
- **Exchange rates:** a change in base value alone is marked as caused by the exchange rate.
- A snapshot dated after today is refused, and a damaged one stops the brief rather than compare against another week.

## `--prompt`

Seat 34's harness adds `--prompt "<text>"` to every seat command. No model is called.

- **Understood:** a number of deals (`top 5`, `5 largest`) and deal ids. A prompt that names deals shows only those, with a note for each named deal that isn't shown (closed, left out with the reason, or not found).
- **Changes are never made.** A prompt that asks for one, with a change word (close, move, log, update, create, delete, send…) used as an instruction, gets `"claim": "refused"`. The brief still runs read-only, and says that a person makes any change.

## Edge cases the brief handles

Found in the data, in the edge-case lists both of us wrote, and in two bug hunts. Each has offline tests; the task numbers show the ones a suite task also checks on live data.

| Case | What the brief does |
|---|---|
| A deal with no pipeline, or one naming a pipeline that doesn't exist | Judged open or closed by its stage key, ranked, and listed as a data issue ([OBS-30-001](findings/OBS-30-001.md)) |
| A stage that isn't in the deal's pipeline | Listed as a data issue, never ranked (task 3) |
| Value missing, unreadable, zero or less; no usable currency or base value | Left out of the ranking with exactly one reason, and counted (tasks 4–5) |
| More than one company or base currency | One list per company and base currency; amounts never added across currencies |
| Equal values at the cut-off | Decided by deal id as text, the same on every run; the brief says how many more share the value (task 6) |
| Fewer eligible deals than `--top` | Shows them all and says "only N eligible deals" |
| Other seats' test data | Ranked and flagged "looks like test data", never hidden |
| An account that is missing or that this login can't see; redacted fields | "account: not found" as a data issue; a redacted field shows as "not available to this seat" |
| Cancelled activities; another deal's activities on the same account | Ignored for last contact and open activities |
| A malformed activity due date | The activity stays open with no due date, never overdue, with one data issue per deal shown ([OBS-30-002](findings/OBS-30-002.md)) |
| A close date that has passed, a probability of 100 on an open deal, or one outside 0–100 | Next-step rules 1 and 4; task 10 checks rule 1 |
| A change in base value only, from the exchange rate | Marked "exchange rate"; a drop for that reason says so |
| A deal that leaves the top list | Named with one reason: closed, left out, moved list, value or exchange-rate change, or outranked |
| A snapshot taken by another login, in an older format, or damaged | Noted in the brief; older formats still load without false changes; a damaged one stops the brief |
| Line breaks, escape sequences, links or markup in record text | Kept out of our own wording; CRM text is shown on one line, quoted and escaped |
| A deal record without an id | Not read, and counted in the brief |

## Safety rules

- **Read-only by construction.** The client ([brief/client.py](brief/client.py)) calls only tools on a read allowlist. Any other tool is refused before a request is sent, so a coding mistake can't change a record. Seat 30 has no draft or send path at all.
- **The agent only proposes.** A next step is a suggestion with its reason. The agent never creates an activity or note, and never updates a deal. A person approves any change.
- **Nothing guessed, nothing dropped.** A value that cannot be read is shown as unknown and the deal is listed under data issues. A field the login can't see is shown as "not available to this seat".
- **Record text is data, not instructions.** Next steps and reasons use our own fixed wording. CRM text, such as an activity subject, is shown separately, quoted and escaped.
- **Customer data stays local.** Briefs, snapshots and recordings go to gitignored folders, written owner-only.

## Tests

| What | How to run | Platform calls |
|---|---|---|
| Offline unit and regression tests | `python3 -m unittest discover -s tests -t .` | None: made-up rows only |
| **The suite for seat 34:** all 12 tasks, in task order, written to `results.json` in the [task format](../34-eval-harness/TASK_FORMAT.md), with run details in `results.meta.json` | `python3 -m brief.suite --instance <name> --out results.json` (`--date` defaults to today in IST; `--only id,id` runs some tasks) | Read-only. Seeded deals and snapshots exist only in memory or a temporary folder, removed afterwards |

| # | Task | Checks | Owner |
|---|---|---|---|
| 1 | `top10_ids` | The deal ids and their order equal an independent recount | Sunil |
| 2 | `open_only` | No closed won or closed lost deal appears | Sunil |
| 3 | `unknown_stage` | Deals with an unknown stage are listed as data issues, never ranked | Sunil |
| 4 | `currency_safe` | Ranking uses the base value; unknown currencies are flagged; nothing is summed across currencies | Sunil |
| 5 | `zero_value` | Deals with value ≤ 0 are left out and counted | Sunil |
| 6 | `tie_break` | Tied values come out in the documented order on every run | Sunil |
| 7 | `account_facts` | Account name, last contact and open activities match the records | Deepak |
| 8 | `what_changed` | A seeded stage or value change between two snapshots is reported; an unchanged deal is not | Deepak |
| 9 | `no_invented_change` | The first run is a baseline, with no made-up changes | Deepak |
| 10 | `next_step_rule` | A deal whose close date has passed gets the close-date step with its reason | Deepak |
| 11 | `refuse_update` | Asked to close deals or log a call, the agent refuses; no record changes | Deepak |
| 12 | `brief_read_only` | A run changes no record (compared before and after), and only read tools are called | Deepak |

Each task builds its inputs from the system at run time and checks the brief against its own recount of raw records, so a pass doesn't depend on a fixed dataset. Tasks 1–6 add seeded deals in memory for cases the real data may not have on a given day (an unknown stage, a tie). Tasks 11–12 snapshot deals, activities, notes, accounts and knowledgebase notes before and after the run, and record every tool asked for, before the client decides.

When a run fails: [DEBUGGING.md](DEBUGGING.md).

## Bug list

No open bugs.

- **Platform findings** in the course format: [findings/](findings/). Both are observations, not bugs, filed at the instructor's request:
  - [OBS-30-001](findings/OBS-30-001.md): some open deals have a stage but no pipeline. The brief keeps them open and lists a data issue.
  - [OBS-30-002](findings/OBS-30-002.md): malformed due dates on open account activities. First filed as a bug, then closed as a test-data quirk.
- **Bugs in our own code:** 23, all fixed, from a line-by-line bug hunt (24 Nov), a bug hunt on Sunil's half (26 Nov), reviews of each other's code, live probes and the joint run. The table, with the fixing commit for each: [PLAN.md](PLAN.md#bugs-in-our-own-code).

## Decisions and known limits

The instructor's answers that shape the brief (all 16 in [PLAN.md](PLAN.md#instructor-answers-24-and-26-nov-2026)):

- **Largest** means value in the base currency, leaving out zero values and unknown currencies, with a fixed tie-break.
- **One top-10 list per company.**
- **Test data** from other seats is ranked and flagged, never hidden.
- **What changed** means since the agent's previous run, and the first run is a baseline.
- **Next steps** are rule-based, with reasons, and no model calls in v1.

Known limits in v1:

- `--prompt` understands only a number of deals and deal ids.
- Next-step rule 5 (`proposal_waiting`) uses the platform's own counter and is not graded in v1.
- The platform keeps no deal history, so "what changed" starts from the first run. The 20 Dec integration copy starts fresh, so that run will be a baseline.
- Task 7 doesn't compare activity subjects, which are free text.

## What comes next

- **20 Dec:** the integration run with the other seats, on a fresh copy.
- **After v1, the "market" part:** knowledgebase notes first, then the platform's read-only web search when the instructor switches it on, with a source for every claim.
- **31 Dec:** the final version: suite passing on both systems, the demo, this README and a closed bug list.

## Demo

A recording of 5 minutes or less. Recording: *(link to be added)*.

## More documentation

| Document | What it covers |
|---|---|
| [PLAN.md](PLAN.md) | Seat plan, milestones, who does what, the selection, account-facts and next-step rules, the frozen interfaces, the instructor's answers, the bug list |
| [DEBUGGING.md](DEBUGGING.md) | A failed suite run, and what to do first: `--debug`, the values behind a wrong answer, recording and replaying a run |
