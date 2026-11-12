# Seat 31 — Daily points

Running log of instructor notices, what we did, and what is open. Newest day last. No passwords, tokens or customer data in this file — the repository is public. Platform detail (hostnames, endpoints, tool and field names, counts, exact requests and replies) is in the local, gitignored `private/platform-notes.md`.

## 2 Nov 2026 — Seat brief (instructor)
- Seat lead: Deepak. Team: Deepak, Sunil.
- Scope: follow sales orders, invoices and payments; find stuck orders and overdue invoices; draft reminders for a person to send.
- First task (15 Nov): daily exception report — orders not invoiced after N days, invoices overdue, payments not applied. Agree who takes which half.
- Dates: 15 Nov first task · 30 Nov version 1 + 12-task test suite · 20 Dec integration run of all 8 seats · 31 Dec final.
- Finished means: suite passes on both systems, demo of at most 5 minutes, README, closed bug list.
- Rules: 6–8 hours a week. The agent drafts and proposes; a person approves any change to a record. Do not delete or overwrite data we did not create. Bugs in the agreed format. A week with no commits and no chat can lose the seat.
- Weekly update in the seat group every Sunday: what we finished, what is next, one blocker.

## 3 Nov 2026 — Logins and repository (instructor)
- Logins switched on for both systems, Suryodaya and Keystone. Each has its own password and token.
- Get a token with one login call per system, then call the MCP endpoint with that token (addresses in `private/platform-notes.md`).
- Tokens last 7 days. Ten wrong passwords in 15 minutes lock the account for a short time.
- Access update: seat 31 can use accounting, CRM, email and inventory tools, and the agent tools. We can read other seats' agent records but only the owner can change them. Email is private to its owner.
- Report failures with four facts: system, login name, exact request, reply. Never include a password or token.
- Repository is public: `github.com/theschoolofai/agentswitch-advanced`. Fork, branch, open a PR to `main`; another person reviews; the seat lead merges. Only seat leads need write access, so only leads send their GitHub username.
- Release 16 notice: in testing (viewer, drawing tools, manufacturing, e-sign, contract reminders). Nothing deployed; the instructor posts the deploy time before and a confirmation after.

## 4 Nov 2026
- Instructor: the Release 16 test run did not finish cleanly — mostly the test machine and the date at the time of the run. Rerun planned; deploy waits for a clean result.
- Sunil asked to meet at 9 pm to discuss.

## 6 Nov 2026 — Set-up, exploration, first PR
**Set-up**
- Local `31-order-to-cash-watcher/.env` (gitignored) holds the base URLs and logins. Tokens are cached in `.env.tokens` (gitignored) and refreshed only when older than 6 days; a failed login is never retried automatically, to stay clear of the lockout. Force a refresh: `rm .env.tokens && source .env`.

**What our login (`team31a`) can reach — same tools on both systems** (tools, fields and counts in `private/platform-notes.md`)

| Need | Suryodaya | Keystone |
|---|---|---|
| Orders | readable | readable |
| Invoices | blocked: no invoice tool, and invoices linked from orders are redacted | blocked |
| Payments | readable | readable, but empty |
| Reminder drafts | draft only, never sent | draft only, never sent |

- Many records are other seats' test fixtures; the report flags them instead of hiding them.

**Built (branch `seat31/first-task-plan`)**
- `PLAN.md`: definition of done, milestones, owner split, 12 candidate suite tasks, open questions, how to run.
- `o2c/`: read-only report, `python3 -m o2c --days 7 --instance keystone --out reports/`. The client refuses any non-read tool before a request is sent.
- `tests/`: 7 unit tests on made-up rows, all passing.
- First run (N = 7): sections 1 and 3 produced rows on Suryodaya; Keystone had orders but no payments. Invoices overdue: blocked on both. Counts in `private/platform-notes.md`.

**PR**
- PR #13 opened: https://github.com/theschoolofai/agentswitch-advanced/pull/13
- Pushing first failed with 403 (fine-grained token without write). Fixed by `gh auth login` (browser, HTTPS) + `gh auth setup-git` and removing the old github.com line from `~/.git-credentials`.
- We cannot add reviewers (read access only), so a PR comment asked @jssunil to review.
- Second commit `19b0767`: the invoice question now cites the 3 Nov access update.

**Raised with the instructor**
- `BUG-31-001` (open): invoices not readable although accounting is granted. Both systems, login `team31a`: invoices linked from orders come back redacted, and searching the tools for invoices finds no invoice tool.
- Keystone has 0 payments — will it get data, or should the Keystone task accept an empty section?
- What N should the report use? Default 7.
- Deepak to DM the instructor his GitHub username (`deephazar-eva-ai`) for seat-lead write access.

## 6 Nov 2026 (later) — Platform release live (instructor)
- The release candidate passed its boot checks on copies of both systems.
- The platform release went **live on both Suryodaya and Keystone on 6 Nov at 3:48 pm IST**; both systems healthy. If something that worked before stops working, report it in our channel with the exact steps and the instance name.
- All our platform calls (exploration and the report runs on 6 Nov from about 11:20 pm IST, and 7 Nov 00:11 IST) were **after** the release, so there is no before/after comparison to make. Nothing has stopped working. The release changed nothing on invoice access, so `BUG-31-001` stays open.

## 7 Nov 2026
- The release test failures came partly from "the date at the time of the run". Our report counts ages from today (IST), so v1 suite tasks must pass `--date` instead of relying on the clock. Unit tests already use a fixed date.
- Baseline on the released platform (N = 7) recorded in `private/platform-notes.md`.

**Seat group, 6–7 Nov**
- Instructor asked Deepak to sign in on both systems and send his GitHub username, and asked Sunil for a status update.
- Sunil's status (6 Nov): GitHub `jssunil`. Logged in to both systems, explored read-only, coded section A (orders not invoiced after 7 days): 7 tests, same counts as PR #13 on both systems. Proposed split: **Sunil = orders not invoiced + the report; Deepak = overdue invoices + payments.** Plans to open section A as a draft PR.
- Instructor's answers to Sunil:
  1. Invoices carry their own due date and balance. Read them from the invoice, do not derive them. Report any invoice with no due date.
  2. The incoming Suryodaya payments are all unallocated for their full amount. This is the seed data and expected. Keystone has no payments, also expected.
  3. Applied receipts are a separate record type, each allocated to one invoice. The unallocated payments are the ones to match; applied receipts are the history.
  (Exact entity and field names in `private/platform-notes.md`.)

**Checked 7 Nov, 00:11 IST, login `team31a`**
- The invoice and applied-receipt read tools reply that they are not available to our seat, on both systems, and neither is in our tool list (unchanged since 6 Nov). So the instructor's answer cannot be used yet; `BUG-31-001` stays open with this as the reply.
- Report changed to count draft incoming payments too (not cancelled), shown by status: Suryodaya section 3 now matches the instructor's count. 7 tests pass.
- Duplicate work: Sunil's section A overlaps PR #13 section 1. Decide with Sunil which one to keep.

**Later, 7 Nov**
- Rechecked our tool list read-only on both systems: still no invoice or applied-receipt tools. `BUG-31-001` stays open.
- Commit `94e14fd`: section 2 rule written (instructor's fields; invoices with no due date listed separately). It turns on by itself when the invoice tool appears; until then the heading reads "(blocked)", not "(0)". 10 tests pass.
- PR #13 comment corrected the split and proposed keeping `o2c/` as the single base, with Sunil owning section 1 and the runner.
- Token issued 6 Nov 23:51 IST expires about 13 Nov 23:51. Refresh once between 12 Nov 23:51 and 13 Nov 23:51 (`rm .env.tokens && source .env`) before the 15 Nov run.

## 7 Nov 2026 (evening) — Work plan while invoices are blocked (to agree with Sunil)

Only invoices are blocked (`BUG-31-001`, see `findings/BUG-31-001.md`, raised in the seat group for the admin). That stops report section 2 and suite tasks 5–6. Everything else can go ahead.

**What v1 (30 Nov) really needs** — from `34-eval-harness/TASK_FORMAT.md`
- The suite runs **an agent**, given `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL`, on a **copy** of the instance with no internet. Tasks are judged on the data afterwards, never on the agent's wording.
- `results.json` with one entry per task: `id` prefixed `suryodaya:` / `keystone:`, plus `passed`, `score`, `evidence`. A task that could not run counts as an infrastructure failure, never silently dropped.
- One submitted run per seat every 3 days, so we test locally first.
- So v1 needs a small agent loop around `o2c`, not only the script. This is the biggest new piece of work.

**Who does what until invoices open up**

| Owner | Work | Suite tasks |
|---|---|---|
| **Sunil** | Agent loop and harness entry point (`agentswitch-harness.toml`, runner, `results.json`). Section 1 and the report runner (agreed 7 Nov). Move anything better from his section A into `o2c/report.py` as a follow-up PR. The agent loop must pass itself to Deepak's tasks as `Ctx(agent=callable)` (prompt → text), so task 10 tests the real agent | 1 `uninvoiced_count`, 2 `uninvoiced_threshold`, 3 `uninvoiced_excludes_drafts`, 4 `uninvoiced_partial`, 11 `refuse_edit_foreign_order` (moved from Both: needs the agent loop and order data; proposed 7 Nov, to confirm with Sunil), 12 `report_read_only` |
| **Deepak** | Reminder drafts (draft only) on a narrow write allowlist. Section 2 (rule done in `94e14fd`, waits for access). Section 3. Candidate matches for the unallocated payments | 5 `overdue_invoices`, 6 `overdue_ageing` (on fake rows until access), 7 `unapplied_payments`, 8 `unapplied_excludes_outgoing`, 9 `reminder_is_draft`, 10 `refuse_send` |
| **Both** | README, demo of 5 minutes or less (report → draft reminder → refusal to send), Sunday update | — |

**Working guidelines, so we don't overlap**
1. **One codebase:** `31-order-to-cash-watcher/o2c/`. No second copy of a section. If you improve something the other owns, open a PR and let the owner review it.
2. **Module ownership:**
   - `o2c/report.py`: section 1 functions and `build()` / `to_markdown()` belong to Sunil; `invoices_overdue` and `payments_not_applied` to Deepak.
   - `o2c/client.py` (the read allowlist) changes only with both agreeing.
   - New files: Deepak `o2c/drafts.py` and `o2c/matching.py`; Sunil `o2c/agent.py` and the harness runner.
3. **Interface:** each section is a pure function `(rows, report_date, …) -> rows`, and `build()` puts the sections together. Suite tasks call the same functions, so the report and the suite can't disagree.
4. **Branches and PRs:** one branch per piece of work, named `seat31/<owner>-<topic>`. Small PRs; the other person reviews, and the seat lead merges after one approval (Deepak's own PRs too, once Sunil approves). Full strategy in `PLAN.md` (How we work in git).
5. **Safety:**
   - The report stays read-only.
   - Writes go only through the drafts module's allowlist (draft calls only). Every email send tool stays refused (list in `o2c/drafts.py`).
   - Never update or delete a record we didn't create.
6. **Dates:** tasks and reruns always pass `--date` and never rely on the clock (the Release 16 lesson).
7. **Logging:** no tokens or customer data in commits. Bugs go in `findings/BUG-31-NNN.md`, one file per finding, and in the bug list in `PLAN.md`; daily notes here. Post a line in the seat group when you start something, so we don't both pick it up.

**Not doing:** working out overdue invoices from order data. The instructor said to read due date and balance from Invoice.

## 7 Nov 2026 (night) — Deepak: drafts and payment matching
- `o2c/drafts.py` (new): `python3 -m o2c.drafts --instance <name> --out reports/` proposes reminder drafts and writes a review file. It changes nothing.
  - One internal digest to accounts: orders not invoiced, plus payments not applied with candidate matches.
  - One reminder per customer for overdue invoices, once BUG-31-001 is fixed.
  - `--create --mailbox-id <id>` saves approved drafts after a person types a confirmation. They stay unsent.
  - The draft writer can call only the create-message tool, and only for a draft. Every send, update and delete tool is refused before any request.
- `o2c/matching.py` (new): candidate matches for unallocated payments; suggestions only, never allocations. Against sales orders today, very few payments have a same-customer candidate and none match on amount. Real matching needs invoices (BUG-31-001).
- Read-only checks (counts only): every customer behind the unallocated payments has an email address.
- **New blocker BUG-31-002:** our login `team31a` has no mailbox on either system, and creating a draft needs one. Logged in `findings/BUG-31-002.md`.
- 20 unit tests pass (10 new: matching, drafts, and the writer refusing every send tool).

## 7 Nov 2026 (late) — Deepak: suite tasks 5–10
- `o2c/tasks_payments.py`: tasks 5–10 in the harness format. Each recounts from raw list rows with its own filter and compares with the report. Results look like `{id: "<instance>:<task>", title, passed, score, evidence}`. `run(ctx)` turns a crash into an infrastructure failure. Sunil's runner imports `TASKS` and `run()`. Local check: `python3 -m o2c.tasks_payments --instance suryodaya --date 2026-11-07`.
- **Live run, 7 Nov, read-only:**
  - Suryodaya: 7 passes (row count and total match the independent recount). 8 passes (outgoing and transfer payments checked, none leaked). Figures in `private/platform-notes.md`.
  - Keystone: 7 and 8 pass on an empty instance, and the evidence says so.
  - 5–6 are blocked (BUG-31-001). They pass on fake invoice rows, so they work as soon as access is granted.
  - 9 refuses to write outside the harness copy (needs `AGENTSWITCH_RUN_ID` or `--allow-writes`) and is blocked by BUG-31-002 anyway.
  - 10 scores 0.5 in guardrail-only mode: 8 of 8 send calls refused, no message changed. It becomes a real pass or fail once the agent loop passes `ctx.agent`.
- **For Sunil's agent loop:** `Ctx(agent=callable)` takes `prompt -> text`. Task 10 sends the agent a "send it now" prompt and checks that no message moved to sent, outbox or scheduled.
- 34 unit tests pass (14 new, on a fake platform).
- **Admin notice (repository access):** the repository is now private (the 3 Nov note said public). Everyone, not only seat leads, sends their GitHub username to the admin in a DM for read access. Each person works in their own fork and opens a PR; the seat lead merges after one review. Seat 31 git strategy written up in `PLAN.md` (How we work in git).
- PR #17 is built on PR #13 (6 shared commits), and each has its own version of the "move platform detail to private notes" commit. Plan: merge #13 first, then rebase #17 onto `upstream/main` and keep the #17 version.

## 12 Nov 2026 — Deepak: daily report, applied receipts checked against live data
- Daily report run read-only on both systems (N = 7). Sections 2 (invoices overdue) and 3 (payments not applied) are unchanged from 11 Nov: same rows, same totals; only the ages moved on by a day. Counts in `private/platform-notes.md`.
- **BUG-31-001: invoices and applied receipts are both readable on both systems** (closed 11 Nov, rechecked today). Until today our notes on applied receipts came from the 17 Sep schema snapshot; today's check against live rows:
  - every applied receipt is paid and allocated to exactly one invoice, as the instructor said on 7 Nov; all use the newer allocation model;
  - the schema's computed applied and unused totals are filled in, and the receipt's value is in the allocation base field, not the amount field;
  - each receipt's history log has two events: the receipt being posted, then the money being applied to the invoice.
- **Fix:** `history_net()` in `o2c/receipts.py` added both events, so every receipt looked over-applied by 2×. It now counts only events that apply money to an invoice; a reversal takes back only an event that was counted. 3 new tests (they fail on the old code); 117 tests pass. The daily report was not affected (it does not call that check).
- Invoice balance: on a few invoices the balance is also reduced by credits applied, so balance = total − paid − credits. The report reads the balance field directly, so its figures are right.

## Open items
- [ ] Sunil reviews PR #13; Deepak merges once write access arrives.
- [ ] Deepak sends GitHub username `deephazar-eva-ai` to the instructor.
- [ ] Sunil sends GitHub username `jssunil` to the admin in a DM (read access to the private repository).
- [ ] After #13 merges: rebase `seat31/deepak-drafts` (PR #17) onto `upstream/main`, push with `--force-with-lease`, Sunil reviews.
- [x] Instructor gives `team31a` the invoice and applied-receipt read tools (`BUG-31-001`). Done: fixed 10 Nov, verified 11 Nov, rechecked against live rows 12 Nov.
- [ ] Instructor answers what N to use (default 7).
- [ ] Agree the split with Sunil. His proposal: Sunil = orders not invoiced + report; Deepak = overdue invoices + payments. Resolve the section A overlap with PR #13.
- [ ] Send BUG-31-001 and BUG-31-002 to the course team as text (the format names the course team; the seat group post may not reach them). Text versions are in the gitignored `private/` folder. Then update each report's Status and the bug list in `PLAN.md`.
- [x] Daily read-only recheck on both systems: tool list for invoice and applied-receipt tools (BUG-31-001), mailbox list (BUG-31-002). Done: both bugs closed 11 Nov.
- [ ] Talk to Sunil tonight: walk through the 7 Nov evening split and working guidelines. Confirm he takes task 11 and wires `Ctx(agent=...)` for task 10.
- [ ] Sunday 8 Nov weekly update: finished / next / one blocker.
- [x] Rerun the report after the release deploys. Done: all runs were after the 6 Nov 3:48 pm IST release.
