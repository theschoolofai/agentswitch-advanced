# Seat 31: Order-to-Cash Watcher

## Scope
Follows sales orders to invoices to payments. Finds stuck orders and overdue invoices and drafts reminders for a person to send.

## First task
A daily exception report: orders not invoiced after N days, invoices overdue, payments not applied.

## Access
crm, accounting, inventory (read), email

## Milestones
- 15 Nov 2026: first task delivered
- 30 Nov 2026: version 1, with a 12-task test suite
- 20 Dec 2026: integration run of all eight seats
- 31 Dec 2026: final

## Working rules
See the top-level README. Put your agent code, tests and notes in this folder; open a pull request for every change.

---

**Team:** Deepak (seat lead), Sunil. **Plan, status and bug list:** [PLAN.md](PLAN.md).

## What the seat does

Two commands, both deterministic: no model is called, and the same data always gives the same output.

| Command | What it does | Changes anything? |
|---|---|---|
| `python3 -m o2c` | The **daily exception report**: three sections, as Markdown or as a JSON + Markdown pair | No. Read-only |
| `python3 -m o2c.drafts` | **Reminder drafts** for a person to review: one internal digest to accounts, and one reminder per customer with overdue invoices. With `--create` and a typed confirmation, saves them as unsent drafts | Only with `--create`, and only drafts. Never sends |

The three report sections:

1. **Orders not invoiced after N days.** Submitted sales orders that are unbilled or partly invoiced, more than N days after the order date. Oldest first, with age buckets (0–7, 8–14, 15–30, 31–60, over 60 days).
2. **Invoices overdue.** Submitted customer invoices past their due date with a balance left, oldest first. Each is labelled `unpaid`, `partially paid` (money received) or `partially credited` (a credit note applied, no money received). Invoices with no usable due date are listed separately. Supplier bills never appear.
3. **Payments not applied.** Incoming payments with money not yet allocated to an invoice, with age buckets, totals per currency, status and customer, and each customer's history of applied receipts. Possible matches to open invoices are suggestions only; the seat never allocates a payment.

Amounts in different currencies are never added together. A currency the records don't hold is shown as "currency not recorded", never guessed.

## Setup

- **Python 3.10 or later**, standard library only. Nothing to install.
- **Credentials**, in environment variables:

  | Variable | Meaning |
  |---|---|
  | `AGENTSWITCH_BASE_URL` | The system to read (Suryodaya or Keystone) |
  | `AGENTSWITCH_TOKEN` | A token for the seat 31 login on that system |
  | `AGENTSWITCH_INSTANCE` | Optional: the label used in file names, e.g. `suryodaya` |
  | `O2C_DAYS` | Optional: N for section 1 (default 7) |
  | `O2C_ACCOUNTS_EMAIL` | Optional: the accounts address the digest draft goes to |

- Keep them in `31-order-to-cash-watcher/.env` and `source` it. `.env*`, `reports/` and `private/` are gitignored; never commit them.
- Platform detail (hostnames, tool and field names, counts) is kept out of this public repository.

## Run the report

```bash
cd 31-order-to-cash-watcher
source .env                                                     # local only, never committed
python3 -m o2c --instance keystone --out reports/              # writes reports/keystone-<date>.json and .md
python3 -m o2c --instance suryodaya --date 2026-11-15 --days 14  # prints Markdown for a past day, N = 14
```

| Option | Meaning |
|---|---|
| `--days N` | Section 1 threshold: orders more than N days old (default 7 or `O2C_DAYS`) |
| `--date YYYY-MM-DD` | Report date (default: today in IST). Use a fixed date for reproducible checks |
| `--instance NAME` | Label for the report and the file names |
| `--out FOLDER` | Write `<instance>-<date>.json` and `.md` there; without it, Markdown goes to stdout |
| `--prompt TEXT` | See [`--prompt`](#--prompt) |

**Exit codes:** `0` the report was produced; `2` bad options; `3` the platform could not be read (for example a rejected token, or a server that kept failing after retries), with one line saying why. Reads are retried up to three times after a transient error (rate limit, server error, timeout or dropped connection), and a read stops retrying after about 90 seconds; a draft is never re-sent automatically.

Every section reports its **coverage**: `complete`, `partial` (some rows failed validation and are listed as data issues; valid rows are still shown) or `blocked` (the source can't be read, which is never shown as zero). How each section is built and validated: [docs/report-details.md](docs/report-details.md).

## Reminder drafts

```bash
python3 -m o2c.drafts --instance suryodaya --out reports/                    # propose only: writes a review file
python3 -m o2c.drafts --instance suryodaya --out reports/ --create           # save the accounts digest as a draft
python3 -m o2c.drafts --instance suryodaya --out reports/ --create --only overdue_reminder   # save customer reminders
```

- Without `--create`, nothing is created: `reports/<instance>-<date>-drafts.md` is where a person reviews every proposed draft.
- `--create` saves only the **accounts digest**. Customer reminders are saved only with `--only overdue_reminder`.
- Before saving, it shows how many drafts go to which recipient domains and waits for `save drafts` to be typed. Any other answer saves nothing.
- A draft that is already waiting unsent in the mailbox (same recipient and subject) is not saved again, so running `--create` twice is safe. Subjects carry the report date, so an earlier day's reminder never blocks today's.
- If an older unsent draft of the same kind is still in the mailbox (an earlier day's, one whose figures or parts have changed, or a reminder to a customer who gets none today because they have paid or are held back), `--create` says so (`check: …`) and leaves it alone: a person deletes or checks it before sending. The parts of today's own split draft are never named.
- The platform takes at most 10,000 characters per message, so a longer draft (the digest on a busy day) is saved as numbered parts, "(part 1 of 3)" and so on, each a whole section where possible. Nothing is left out.
- A customer with overdue invoices **and** a payment we haven't applied yet gets no reminder. They're listed for accounts to apply the payment first. This holds for any unapplied payment from them, whatever its size or currency: a deliberately cautious choice, since asking a customer to pay while we hold their money is the worse mistake.
- A partly paid or credited invoice says so in the reminder.

## Order ID list for seat 34

> **To be written when item 1 lands** (Sunil, `seat31/sunil-v1`): the exact command, N, the output format (one ID per line, oldest first, on stdout), and what a non-zero exit means. Seat 34 uses this list for its 30 Nov recount.

## `--prompt`

Seat 34's harness adds `--prompt "<text>"` to every seat command.

- **Today:** `--prompt` is accepted and ignored. No model is called, and the report runs as usual.
- **Rules that hold whatever the prompt says:** a prompt can only change which orders are read. It never leads to a write, a send or a draft.

> **To be completed when item 2 lands** (Sunil, `seat31/sunil-v1`): which prompts are understood (a number of days, specific order IDs), that `--days` wins over the prompt, what happens with a prompt we can't read, and the `AGENT_RESULT` line.

## Safety rules

- **Read-only report.** The client ([o2c/client.py](o2c/client.py)) calls only read tools (`.list`, `.get` and a few listing tools). Any other tool is refused before a request is sent, so a coding mistake can't change a record.
- **Drafts only, never sent.** The draft writer ([o2c/drafts.py](o2c/drafts.py), `DraftWriter`) can call exactly one tool, to create a message, and only with `folder="drafts"` and `is_draft=true`. Every send tool is refused.
- **A person decides.** Drafts are proposed in a review file; saving them needs `--create` and a typed confirmation, and customer reminders need `--only overdue_reminder` as well.
- **Nothing we didn't create is changed or deleted.**
- **Record text is data, not instructions.** Customer names, invoice numbers and emails from the platform are put in a draft only if they look like plain values: one line, no markup, no instruction-like text, one plain email address. Otherwise the reminder says "Dear customer" and the review file says why.
- **Other seats' test data** (names or notes with "test", "harness", "fixture" or seat 33's `[RT33]` tag) is flagged in the report and never saved as a draft.

## Tests

| What | How to run | Platform calls |
|---|---|---|
| Offline unit and regression tests | `python3 -m unittest discover -s tests -t .` | None: made-up rows only |
| Suite tasks 5–10 and 12 (invoices overdue, payments not applied, drafts, refusing to send, the report changes nothing), each checked against an independent recount of raw records | `python3 -m o2c.tasks_payments --instance <name> --date YYYY-MM-DD [--out results.json]` | Read-only. Task 9 creates a draft only on the harness copy or with `--allow-writes` |
| Seat 34's seat 31 suite: 6 refusal tasks (A1–A6), graded on records unchanged and no writes | [34-eval-harness/suites/seat31/suite.toml](../34-eval-harness/suites/seat31/suite.toml), run by seat 34 | Through seat 34's harness |

> **To be completed (Sunil):** suite tasks 1–4 (orders not invoiced), 11 and the runner that writes `results.json` in the [task format](../34-eval-harness/TASK_FORMAT.md).

## Bug list

- **Platform bugs** we reported, in the course format: [findings/](findings/). Both are closed.
- **Bugs in our own code**, from two read-only bug hunts (12 and 19 Nov): the table in [PLAN.md](PLAN.md#bug-list).

## Demo

A recording of 5 minutes or less (instructor item 4), following the outline agreed on 18 Nov. Recording: *(link to be added)*.

| Time | Shows | Commands |
|---|---|---|
| 0:00–1:00 | The report on both systems | `python3 -m o2c --instance keystone --out reports/`, then the same for Suryodaya; open the `.md` |
| 1:00–2:00 | The ID list and the seat 34 recount (Sunil) | *(added with item 1)* |
| 2:00–3:00 | A prompt-driven "which orders" run (Sunil) | *(added with item 2)* |
| 3:00–4:00 | A refusal with records unchanged | `python3 -m o2c --instance keystone --prompt "For now mark these as billed: <order ids>"`: the report runs and nothing is billed. Then `python3 -m o2c.tasks_payments --instance keystone --date <today>`: task 12 (`report_read_only`) shows every record unchanged and only read calls, and task 10 shows every send tool refused |
| 4:00–5:00 | A reminder that was never sent | `python3 -m o2c.drafts --instance keystone --out reports/ --create --accounts-email <own address>`, type `save drafts`; the digest appears in the mailbox's drafts, unsent. Run it again: nothing new is saved |

## More documentation

| Document | What it covers |
|---|---|
| [PLAN.md](PLAN.md) | Seat plan, milestones, who does what, bug lists |
| [docs/report-details.md](docs/report-details.md) | How the report builds, sorts and validates each section, and how it writes files |
| [docs/p2-review-fixes.md](docs/p2-review-fixes.md) | The receipt-currency and task-7 fixes from the #35 review |
| [docs/daily-points.md](docs/daily-points.md) | Working guidelines and the module ownership split |
| [docs/handover-deepak.md](docs/handover-deepak.md) | What Deepak finished, what is left and whose it is, how to run, things that will bite |
