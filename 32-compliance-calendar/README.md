# Seat 32: Compliance Calendar

## Scope
Statutory and contractual due dates (TDS/GST, sales tax, contract expiry and renewals), with a named owner for each.

## First task
The next 90 days of due items with an owner for each, from the tax-section master and contract end dates.

## Access
accounting (read), contracts, esign, scheduling

## Milestones
- 15 Nov 2026: first task delivered
- 30 Nov 2026: version 1, with a 12-task test suite
- 20 Dec 2026: integration run of all eight seats
- 31 Dec 2026: final

## Working rules
See the top-level README. Put your agent code, tests and notes in this folder; open a pull request for every change.

## How to run

Read-only. Nothing here writes to the platform.

```
python build.py --out /path/outside/this/repo/calendar.md
python build.py --days 120 --status active --status pending_approval
python tests/test_rules.py
```

Credentials come from the environment, never from this repository:
`AS_EMAIL_32`, `AS_PASSWORD_32_SURYODAYA`, `AS_PASSWORD_32_KEYSTONE`, or
point `AS_ENV_FILE` at a file outside the repo holding them.

**The generated table is not committed.** It contains live contract data,
and the repository rules forbid platform data here. The code is the
deliverable; the table goes to the seat lead and the course team directly.
`.gitignore` covers `calendar*.md` and `.env` so this cannot happen by
accident.

## What it computes

`due date = end date - notice period`, not the end date. Each contract has
a renewal notice period and a termination notice period, and they differ on
121 of 124 contracts, so one contract can produce two rows with different
dates and different actions.

Deadlines that have already passed on a contract that is still running are
reported in their own section rather than dropped for falling outside
"the next 90 days". That state - the notice window shut while the contract
is live - is the most urgent thing this calendar can find.

Statutory TDS dates are rules, not platform data, and every one is marked
"to be verified" until a chartered accountant confirms it. Keystone is a US
company, so TDS does not apply and the table says so in words rather than
leaving a blank.
