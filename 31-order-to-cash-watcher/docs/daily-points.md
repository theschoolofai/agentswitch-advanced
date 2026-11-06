# Seat 31 — Daily points

Running log of instructor notices, what we did, and what is open. Newest day last. No passwords, tokens or customer data in this file — the repository is public.

## 2 Nov 2026 — Seat brief (instructor)
- Seat lead: Deepak. Team: Deepak, Sunil.
- Scope: follow sales orders, invoices and payments; find stuck orders and overdue invoices; draft reminders for a person to send.
- First task (15 Nov): daily exception report — orders not invoiced after N days, invoices overdue, payments not applied. Agree who takes which half.
- Dates: 15 Nov first task · 30 Nov version 1 + 12-task test suite · 20 Dec integration run of all 8 seats · 31 Dec final.
- Finished means: suite passes on both systems, demo of at most 5 minutes, README, closed bug list.
- Rules: 6–8 hours a week. The agent drafts and proposes; a person approves any change to a record. Do not delete or overwrite data we did not create. Bugs in the agreed format. A week with no commits and no chat can lose the seat.
- Weekly update in the seat group every Sunday: what we finished, what is next, one blocker.

## 3 Nov 2026 — Logins and repository (instructor)
- Logins switched on for both systems: Suryodaya (`agentswitch.theschoolofai.in`) and Keystone (`class.agentswitch.theschoolofai.in`). Each has its own password and token.
- Get a token with one login call per system (`POST /api/auth/login`); call MCP at `/api/mcp` with JSON-RPC 2.0 and `Authorization: Bearer <token>`.
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

**What our login (`team31a`) can reach — same tools on both systems**

| Need | Tool | Suryodaya | Keystone |
|---|---|---|---|
| Orders | `SalesOrder.list` (`invoiced_status`, `date`, `docstatus`) | 324 orders | 171 orders |
| Invoices | No `Invoice` tool; `endpoint.make.thread` shows the Invoice node as `redacted` | blocked | blocked |
| Payments | `Payment.list` (`type`, `unallocated`, `against`) | 100 (40 incoming) | 0 |
| Reminder drafts | `EmailMessage` / `EmailReminder` (draft only; never `endpoint.email.messages.send`) | | |

- Many records are other seats' test fixtures (e.g. parties named `[team07-test …]`); the report flags them instead of hiding them.

**Built (branch `seat31/first-task-plan`)**
- `PLAN.md`: definition of done, milestones, owner split, 12 candidate suite tasks, open questions, how to run.
- `o2c/`: read-only report, `python -m o2c --days 7 --instance keystone --out reports/`. The client refuses any non-read tool before a request is sent.
- `tests/`: 7 unit tests on made-up rows, all passing.
- First run (N = 7): Suryodaya — 60 orders not invoiced, 36 payments not applied. Keystone — 9 orders not invoiced, 0 payments. Invoices overdue: blocked on both.

**PR**
- PR #13 opened: https://github.com/theschoolofai/agentswitch-advanced/pull/13
- Pushing first failed with 403 (fine-grained token without write). Fixed by `gh auth login` (browser, HTTPS) + `gh auth setup-git` and removing the old github.com line from `~/.git-credentials`.
- We cannot add reviewers (read access only), so a PR comment asked @jssunil to review.
- Second commit `19b0767`: the invoice question now cites the 3 Nov access update.

**Raised with the instructor**
- `BUG-31-001` (open): invoices not readable although accounting is granted. Both systems, login `team31a`, `endpoint.make.thread` on an invoiced order returns `{"entity": "Invoice", "redacted": true}` (also `WorkOrder` and `DeliveryChallan`); `tools.search` "invoice" returns only `endpoint.make.thread`.
- Keystone has 0 payments — will it get data, or should the Keystone task accept an empty section?
- What N should the report use? Default 7.
- Deepak to DM the instructor his GitHub username (`deephazar-eva-ai`) for seat-lead write access.

## 6 Nov 2026 (later) — Platform release live (instructor)
- The release candidate passed its boot checks on copies of both systems.
- The platform release went **live on both Suryodaya and Keystone on 6 Nov at 3:48 pm IST**; both systems healthy. If something that worked before stops working, report it in our channel with the exact steps and the instance name.
- All our platform calls (exploration and the report runs on 6 Nov from about 11:20 pm IST, and 7 Nov 00:11 IST) were **after** the release, so there is no before/after comparison to make. Nothing has stopped working. The release changed nothing on invoice access, so `BUG-31-001` stays open.

## 7 Nov 2026
- The release test failures came partly from "the date at the time of the run". Our report counts ages from today (IST), so v1 suite tasks must pass `--date` instead of relying on the clock. Unit tests already use a fixed date.
- Baseline on the released platform (N = 7): Suryodaya 60 orders not invoiced / 40 payments not applied; Keystone 9 / 0.

**Seat group, 6–7 Nov**
- Instructor asked Deepak to sign in on both systems and send his GitHub username, and asked Sunil for a status update.
- Sunil's status (6 Nov): GitHub `jssunil`. Logged in to both systems, explored read-only, coded section A (orders not invoiced after 7 days): 7 tests, 60 orders on Suryodaya and 9 on Keystone. Same numbers as PR #13. Proposed split: **Sunil = orders not invoiced + the report; Deepak = overdue invoices + payments.** Plans to open section A as a draft PR.
- Instructor's answers to Sunil:
  1. The Invoice entity has `due_date`, `payment_terms`, `amount_paid` and `outstanding`. Read due date and balance from it, do not derive them. Report any row where `due_date` is empty.
  2. The 40 Suryodaya `receive` payments all have an empty `against` list, so each is unallocated for its full amount. This is the seed data and expected. Keystone has no Payment rows, also expected.
  3. Applied receipts are a separate entity, `PaymentReceived` (215 on Suryodaya, 141 on Keystone), each allocated to one invoice. To match receipts to invoices: the 40 unallocated Payment rows are the ones to match; `PaymentReceived` is the applied history.

**Checked 7 Nov, 00:11 IST, login `team31a`**
- `Invoice.list` and `PaymentReceived.list` reply `tool_not_available` ("This tool is not available to your seat; it is not in your tools/list") on both systems. Neither appears in `tools/list` (unchanged since 6 Nov) or `tools.search`. So the instructor's answer cannot be used yet; `BUG-31-001` stays open with this as the reply.
- Report changed to count draft incoming payments too (not cancelled), shown by status: Suryodaya section 3 is now 40, matching the instructor. 7 tests pass.
- Duplicate work: Sunil's section A overlaps PR #13 section 1. Decide with Sunil which one to keep.

## Open items
- [ ] Sunil reviews PR #13; Deepak merges once write access arrives.
- [ ] Deepak sends GitHub username `deephazar-eva-ai` to the instructor.
- [ ] Instructor gives `team31a` the Invoice and PaymentReceived read tools (`BUG-31-001`).
- [ ] Instructor answers what N to use (default 7).
- [ ] Agree the split with Sunil. His proposal: Sunil = orders not invoiced + report; Deepak = overdue invoices + payments. Resolve the section A overlap with PR #13.
- [ ] Sunday 8 Nov weekly update: finished / next / one blocker.
- [x] Rerun the report after the release deploys. Done: all runs were after the 6 Nov 3:48 pm IST release.
