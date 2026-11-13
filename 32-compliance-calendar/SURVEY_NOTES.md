# Contract data survey — 3 Nov 2026

Read-only survey of contract records on both systems, before splitting the
first task. Nothing was written or changed.

## Headline

The data is in good shape. Every contract carries an end date, a notice
period, an owner and a status. Nothing is missing, so the first task is not
blocked on data quality.

Two decisions do need making before the table can be built, and both change
the answer rather than the formatting.

## Decision 1: there are two notice periods, not one

Each contract records a renewal notice period AND a termination notice
period, and on almost every contract the two are different numbers (121 of
124). One contract, for example, gives 60 days to renew and 90 days to
terminate.

They are different actions with different deadlines, so "the 90-day table"
is really two different tables depending on which rule is applied:

| rule used | Suryodaya | Keystone |
|---|---|---|
| renewal notice | 7 items | 4 items |
| termination notice | 9 items | 2 items |

Proposal: include both, as separate rows with the action named, because an
owner needs warning about whichever comes first. To be agreed with the seat
lead.

## Decision 2: which statuses belong in the calendar

Most contracts are not live:

| status | Suryodaya | Keystone |
|---|---|---|
| active | 5 | 11 |
| pending approval | 68 | 2 |
| draft | 24 | 1 |
| expired | 2 | 5 |
| other | 1 | 5 |

A draft contract has no obligation to give notice on, and an expired one is
finished. If the table is limited to active contracts, Suryodaya produces
roughly 2 rows; if contracts awaiting approval are included, 7 to 9.

Proposal: active only, with the rule stated in the output so a reader knows
what was excluded. To be agreed with the seat lead.

## What the task actually computes

The due date is not the end date. It is:

    due date = end date - notice period

A contract ending 31 January with 60 days' notice needs action by 2
December. By the end date itself it is already too late — the contract may
have renewed automatically, or the chance to renegotiate is gone.

## Checked and sound

The platform stores a "days to expiry" value on each contract. It was
compared against the end date on all 124 contracts and agreed every time, so
it can be relied on rather than recomputed. Worth recording because the
equivalent stored field on the helpdesk seat disagreed with the underlying
rows on 24 of 103 records.

## Still open

- TDS section rows are readable on Suryodaya but are product defaults that no
  CA has checked. Every rate and statutory date must be marked "to be
  verified" until confirmed. Keystone is a US company and has no TDS, so the
  table must treat "does not apply on this system" as a real answer rather
  than an empty cell.
- Owner is stored as an identifier and still needs resolving to a name.

## The tax-section master is versioned by date, not one row per section

The tax sections are readable on Suryodaya through the accounting read access
listed in this seat's README. They are read-only to us: the platform reports
no write and no delete permission, and every row is marked as a statutory
seed, meaning a product default shipped with the system rather than anything
this company entered.

The important shape: **a section code appears more than once.** Most sections
have an older row and a newer one, and one has three. Each row carries a
start date and, on the superseded ones, an end date. The thresholds and in
one case the rate differ between versions, because the law changed.

This has a direct consequence for the agent. It must select the row whose
date range contains the date of the payment being judged, not the row that
matches the section code. Matching on section code alone returns two or
three rows and whichever arrives first will be used, which is the older,
wrong one about half the time.

### The trap in the obvious filter

The natural way to pick the current row is to filter on the active flag.
That does not work here: **the active flag is set on every row, including
the superseded ones.** Nothing in that field distinguishes a row that is in
force from one that ended last year. The only reliable test is comparing the
payment date against the row's start and end dates.

This is the same class of problem as the two notice-period fields recorded
above: a field that looks authoritative, and is not.

### Three different pieces of arithmetic

The rows do not all compare a payment to a threshold the same way. There are
three modes, and each means a different calculation:

- compare the total paid across the year against the threshold;
- compare either the total for the year or any single payment, whichever
  trips first;
- deduct only on the amount above the threshold, not on the whole payment.

An agent that implements one of these and applies it to all rows will be
wrong on the others. The mode has to be read per row and honoured.

There is also a separate, higher rate for a payee with no PAN, as a distinct
field. The table must not quote a single rate per section as if it were the
only one.

## The rent threshold the course team flagged

The current rent rows hold an annual threshold equal to twelve times the
monthly figure the law actually states. Expressed that way it gives the right
answer for a full twelve-month tenancy and the wrong answer for a shorter
one.

Worked example. A six-month office lease at a monthly rent above the monthly
limit: the law looks at the month and says deduct. The stored annual
threshold looks at the six-month total, finds it below the yearly figure, and
says do not deduct. A six-month lease is ordinary, so this is not a corner
case.

This is a platform finding and belongs in a bug report in the format in
`BUG_REPORT_FORMAT.md`, addressed to the course team, not something to work
around silently in our own table. Until a CA confirms the correct reading,
every rate and every statutory date we publish stays marked "to be verified".

## When this survey was taken, and why that is written down

Every figure above was read on **3 November 2026**, from Suryodaya, before
Release 16 was deployed.

Release 16 is in testing as this is written. Its announced scope includes
**contract reminders**, which is the subject of this seat. Its test gate had
not run at the time of writing and is scheduled conditionally, so the deploy
time is not known.

The reason for recording this: if a figure here later fails to match the
platform, there are two very different explanations and they look the same
from the outside. Either our reading was wrong, or the platform changed
underneath it. Without the date of the reading, the two cannot be told apart,
and the usual outcome is that a defect the platform already fixed gets
chased as if it were our bug.

### Which findings Release 16 could plausibly affect

Inside the announced scope, so treat as provisional and re-check after deploy:

- the two notice-period fields that disagree on 121 of 124 contracts
  (re-checked 9 Nov: unchanged, and no longer believed to be a defect -
  see the correction below)
- the due-date rule (end date minus notice period)
- the stored days-to-expiry value, checked sound on all 124

Outside the announced scope, so not expected to change — the announcement
covers the viewer, drawing tools, manufacturing, e-sign and contract
reminders, and says nothing about accounting or tax:

- the dated versioning of the statutory tax sections
- the active flag being set on superseded tax rows
- the annual-versus-monthly rent threshold
- the company tax rate cards and their duplicated date fields

### Re-check after Release 16 deploys

Re-run the contract survey and compare against the figures above. Report any
difference as a difference, naming both readings and both dates, rather than
silently replacing the old numbers.

## Re-check after Release 16 — 9 Nov 2026

Release 16 went live on both systems on 6 November 2026 at 15:48 IST. The
contract survey was re-run on 9 November, three days after the release, and
compared against the 3 November figures recorded above.

**Nothing in the contract data changed.**

| check | 3 Nov | 9 Nov re-read | |
|---|---|---|---|
| contracts | 124 | 124 | same |
| notice periods disagreeing | 121 of 124 | 121 of 124 | same |
| Suryodaya statuses | 5 / 68 / 24 / 2 / 1 | 5 / 68 / 24 / 2 / 1 | same |
| Suryodaya, 3 Nov window | 7 renewal, 9 termination | 7, 9 | same |
| Keystone, 3 Nov window | 4 renewal, 2 termination | 4, 2 | same |

Both readings use the 3 November window so that the comparison isolates
platform change from the calendar simply moving on. Against a window
starting 9 November the counts differ, as they should: Suryodaya renewal
rises 7 to 9 and Keystone renewal falls 4 to 3, both purely because six days
passed. Termination counts are unchanged either way.

One difference is in our own earlier note rather than in the platform.
Keystone now reads as 10 active plus 1 renewed where the 3 November note
recorded 11 active. The earlier note counted the renewed contract as active.
Recorded here rather than silently corrected above.

### What this settles

The contract figures are stable across the release, so the calendar can be
built on them.

### Correction: the two notice periods are not a defect

Earlier notes in this file treated the two notice-period fields disagreeing
on 121 of 124 contracts as a platform defect, and planned to report it once
Release 16 had been ruled out as the fix. That was wrong, and it is withdrawn
rather than quietly dropped.

A contract can legitimately require 60 days of notice to renew and 90 days to
terminate. Those are different actions with different deadlines. Two fields
holding different numbers is correct modelling, not two gates disagreeing.

The mistake was pattern-matching. A recurring lesson from the previous seat
was that two fields answering the same question will eventually disagree and
the disagreement surfaces as a problem nobody owns. That lesson is sound, but
it only applies when the two fields really are answering the same question.
Here they are answering different ones, and the pattern was applied without
checking that first.

What remains is a design decision, not a bug: which deadline the calendar
reports. It reports both, as separate rows naming the action, because an
owner needs warning of whichever falls first.

### The reminder question, now tested

The open question was whether the platform's own reminder feature picks one
of the two notice periods. It was tested on 9 November. It picks neither.

`ContractPreferences.renewal_reminder_days` is a single company-wide value
of 60, and the Contract entity carries no per-contract override. Every
contract is reminded 60 days before its end date regardless of the notice
period it actually requires.

On Keystone every one of the 24 contracts requires 90 days of termination
notice, so the deadline falls 90 days before the end date and the reminder
arrives 60 days before it. The reminder fires 30 days after the deadline it
exists to warn about, on all 24 contracts including all 10 active ones. On
Suryodaya the same defect affects 1 of 100.

A second defect turned up beside it: `is_expiring_soon` is false on all 24
Keystone contracts, including the five whose status field reads
`expiring_soon`, one of which expires today.

Both are filed. Both were measured after release 16 went live, and release
16 listed contract reminders in its scope.

This is worth noting as a method point. The withdrawn finding was wrong, but
the question it left behind was the one that found the real defect. Writing
down "we have not checked this" is what made it findable later; deleting the
withdrawn claim outright would have taken the open question with it.

The tax findings were outside the release's announced scope and are
unaffected by this re-check. Three of them were re-verified on 9 November
after the release and all three persist.

### Note on method

The release notices arrived out of order over six days: in testing, then a
correction saying the test gate had not started, then the original text
again, then "not live, no date set", then "live since 6 November". Taking any
single notice at face value would have given the wrong answer about whether
the platform had changed. Re-measuring against a dated baseline gave the
right one regardless of which notice was current. Keep doing that.

## Course team response to the five bug reports - 9 Nov 2026

All five confirmed against live data and code. Two of them corrected our
account of the cause, and one of those corrections was our own error rather
than a difference of reading.

| id | verdict | in the next release |
|---|---|---|
| efe134ed rent threshold stored as annual | confirmed | no |
| bb192de2 jurisdiction ids do not resolve | confirmed, cause corrected | yes |
| d9ea7033 validity stored twice | confirmed | yes |
| 51e44831 contract reminder | half confirmed, our error | yes |
| e05dd7f5 is_expiring_soon false on all | confirmed | yes |

### Our error on 51e44831

We reported that the reminder sweep uses a single company-wide 60 days and
ignores each contract's own notice period. That is wrong. The sweep does use
each contract's own renewal notice days. What it ignores is the TERMINATION
notice, so that deadline is never warned on at all.

The real defect is narrower than we claimed and still real.

Why we got it wrong, because the shape of the mistake matters more than the
mistake. On Keystone every contract holds renewal notice 60, and the
company-wide preference is also 60. The same number. A sweep reading each
contract and a sweep reading the global default therefore produce identical
output on Keystone, and no observation there can separate them.

Suryodaya spreads renewal notice across 46 distinct values from 1 to 90. The
two explanations predict completely different behaviour there, and we had
that data in hand the whole time. We built the theory on the system where it
could not be falsified and never tested it on the system where it could.

A coincidence of two equal numbers was read as a mechanism. The check that
would have caught it costs one line: before explaining a value, confirm the
value varies.

### The corrected cause on bb192de2

We reported the TaxJurisdiction table as empty. It is not. It holds 40 rows,
and they carry no company, so a tenant login sees none of them. The
observation was right - our login genuinely sees an empty table and 83
records pointing nowhere - but the cause is a missing tenant link, not
missing data. We could not have seen the difference from our seat, which is
itself the reason to describe what was observed and let the fix be diagnosed
by someone who can see more.

## The two scope decisions, settled

Both answered by the course team on 9 November and implemented.

1. Emit renewal and termination as separate rows. A termination deadline is
   its own date. This is what the calendar already did.

2. For the 15 November delivery the main tables carry `active` and
   `expiring_soon`. Contracts awaiting approval are listed in their own
   section as not yet in force, switchable with `--no-pending`. Both choices
   are printed in the output as stated assumptions.

Adding `expiring_soon` was not cosmetic. The Keystone missed-deadline
section went from 1 row to 9. Three of those contracts end within the next
month - 22 November, 29 November and 7 December - and on each one both the
renewal and the termination window have already closed.

Those contracts were invisible twice over: the platform never flagged them,
because `is_expiring_soon` requires status `active` and these are status
`expiring_soon`; and our own earlier default excluded them for the same
reason. Two independent filters, the same blind spot, and the contracts
nearest to expiry sitting inside it.
