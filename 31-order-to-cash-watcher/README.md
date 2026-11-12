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

## Daily exception report

```bash
cd 31-order-to-cash-watcher
python3 -m o2c --instance keystone --date 2026-11-15 --days 7 --out reports/
python3 -m unittest discover -s tests -t . -v
```

The report reads `AGENTSWITCH_BASE_URL` and `AGENTSWITCH_TOKEN`. It never logs in or creates a
platform record. Without `--out` it prints Markdown; with it, it writes UTF-8 JSON and Markdown.
Use an explicit date for reproducible checks. `--days` / `O2C_DAYS` must be a nonnegative integer.

Orders qualify when submitted, unbilled or partially invoiced, and strictly more than N days old
by **order date**. No verified deliverable-date source is agreed yet. All qualifying orders are
therefore marked `deliverability_status=unverified`, not assumed ready for billing. The existing
`delivered_status` remains visible but does not establish a deliverable date.

- Oldest first. Equal ages are grouped by currency (known codes A–Z, unknown last), then by
  descending value within each currency, then number and ID. Values in different currencies
  are not compared or converted. Sorting uses resolved record/customer/company currency.
- Additive row fields: `age_basis`, `age_bucket`, `deliverability_status`.
- The order section adds `age_basis`, `deliverability_status`, `unverified_deliverability_count`,
  `age_buckets`, and `date_issues`. The unverified count describes the same canonical rows;
  it is not a second financial total.
- Buckets are 0–7, 8–14, 15–30, 31–60 and >60 **order-age** days. They count exception rows only.
  At N=7 the first bucket is empty by design: the strict threshold still excludes age 7.
- Submitted unbilled orders with missing/invalid/future dates appear in separate date diagnostics
  and are excluded from age-based rows and bucket counts. They must be investigated, not treated
  as confirmed non-exceptions. See the shared validation policy below for invoices and payments.

The original section headings and table columns remain; consumers should accept additive JSON
metadata and explanatory Markdown paragraphs. Invoice access unavailable means **blocked**, not zero
overdue. Supplier bills remain excluded from customer receivables. Payment/matching/draft code is
unchanged by this report follow-up. Default execution remains file-only and read-only; approved
draft creation uses the separate drafts command and explicit confirmation.

See [report implementation notes](docs/report-followup.md) for scope, assumptions and validation.

### Pagination completeness

Every list page must provide `data` as a list of records and `total` as a nonnegative integer.
The total must remain consistent throughout the fetch. Missing/malformed totals, zero-with-data,
duplicate IDs, repeated pages, excess rows or early empty pages raise `PaginationError` (an `McpError`)
rather than returning a partial result. A short page is not a completion signal when more rows are
advertised. Fetching is capped at 1,000 pages; `Client.list_all(..., max_pages=N)` can set a smaller
positive budget. A failed source prevents the CLI from publishing a new report pair; an existing pair
is left untouched. Concurrent source changes can therefore require a rerun, not a silent partial report.

### Shared validation and file publication

- Source dates must be a complete `YYYY-MM-DD` or ISO timestamp (`T`/space, hours/minutes,
  optional seconds/fraction, optional `Z` or `+/-HH:MM`). The recorded calendar day is retained;
  there is no implicit zone conversion. Trailing junk and impossible dates are rejected.
- Orders need a valid nonfuture date to enter age-based exceptions. Invoices with missing/invalid
  due dates are retained in the separate no-usable-due-date list and never get overdue reminders.
  Incoming payments with usable balances but missing/invalid dates stay visible with unknown age;
  valid future payment dates retain a negative age and #35's explicit `future` bucket, with a warning.
- Amounts use one finite Decimal parser. Numeric strings render correctly, cent rounding is
  half-even, and zero/negative balances do not become overdue/unallocated exceptions. Missing or
  malformed informational amounts remain `null`/`unknown`, not zero. Rows whose required balance
  is unusable are excluded from balance-based exceptions and explicitly diagnosed.
- Each section has `data_issues` and `coverage` (`complete`, `partial`, `blocked`). `status=ok`
  means a source was read, not that every row passed validation. Valid exceptions survive bad neighbours.
  Warnings reach JSON, Markdown and the internal digest; missing-due-date warnings also reach Accounts.
- Existing numeric JSON money fields stay numeric when a finite cent value is representable safely;
  rejected values are `null` plus diagnostics. No `NaN`/Infinity JSON is emitted.
- Output instance labels allow 1–64 ASCII letters/digits/underscores/hyphens, starting with a letter/digit.
  An omitted label uses `report`; explicitly blank labels, separators and absolute/traversal paths fail
  before platform reads. Direct writer callers are validated too.
- Both UTF-8 files are staged before replacing final files. Handled replacement failures restore the
  old pair (or remove a newly published first file), and temporary artifacts are cleaned up. This is
  not a cross-file atomicity guarantee for machine crashes or concurrent readers.

### Section 3 integration from PR #35

Deepak's payment feature is now integrated into this draft: age/status/customer summaries are
per currency; reconciled-but-unallocated payments are flagged; applied history is read from
PaymentReceived when available. The report reads tool availability once to choose source coverage.

`order_age_bucket` and `ORDER_AGE_BUCKETS` stay separate from payment `age_bucket` / `AGE_BUCKETS`.
Order buckets are 0–7, 8–14, 15–30, 31–60, >60; payment buckets are future, 0–30, 31–60, 61–90, 90+, unknown.
Existing payment IDs, amounts, currency provenance and statuses remain; #35 adds `summary`, `note`,
`receipt_history`, row bucket/docstatus/notes and receipt hints. These fields are covered by integration tests.

Receipt hints compare customer/amount only: they never allocate money or prove a particular invoice is paid.
Posted events are not double-counted as applied events; v1 receipt consideration/number fields are preserved.
Malformed financial receipt data is excluded with diagnostics and partial history coverage. If that prevents
verifying any history, the additional `unknown` hint renders as “history incomplete” and its applied total
is null, rather than claiming “no history” or zero. Validated paid counts are labelled accordingly.

This draft now depends on **#13 → #17 → #35** before its own final replay/rebase and review.
