# Report follow-up: validation, order ages and safe output

This draft combines Sunil's report/runner follow-up with Deepak's #35 as an explicit dependency.
It preserves the shared parsing/output fixes requested in review. The agent entry point, model
integration and graded-task prompts remain separate.

## Dependency and scope

The branch initially started from #17 at `0b1540b`. It now incorporates the latest #17
`da9299c84b049f9cffaf6bcfb4bcc0e90c29fb92` and upstream main `40d2900` without rewriting
published history. Thus it includes the attribution fix, partially-paid labels and three-table digest.
The refreshed source inventory includes open/closed PRs through #35. #35 head `0c4744b` is now
integrated, following Deepak's refreshed Seat 31 handoff. #13/#17/#35 remain open; this draft
still has inherited changes relative to upstream main. That merge-readiness blocker is not resolved
by integrating their code. No aggregate-PR approval is assumed.

Merge order is #13 → #17 → #35, followed by the #29 follow-up. After those dependencies merge,
replay only this follow-up onto updated main and rerun verification.
The initial report commit is `1a8becc`; pagination is `a3dbc5f`; explanatory comments are `2f70611`.
The later review-fix commit and current evidence are identified in the PR description.

## Order-report contract

- Preserve submitted/unbilled-or-partly-invoiced eligibility and strict order age > N.
- Record order-date provenance, unverified deliverability and exception-only age buckets.
- Keep oldest first; equal ages group by resolved currency, then descending value, then number/ID.
- Never compare raw values across currencies or invent a deliverable date from delivery status.
- Use `order_age_bucket` / `ORDER_AGE_BUCKETS` separately from the integrated #35 payment helpers.
- Round normalized monetary fields to cents before rendering/sorting; sub-cent differences are
  not invisible value tie-breakers. JSON keys and numeric monetary field types remain compatible.

## Review findings addressed in code

1. Shared strict date parsing rejects malformed suffixes and invalid timestamps. Source calendar
   dates are retained without implicit time-zone conversion.
2. Shared Decimal parsing/formatting accepts numeric strings and rejects nonfinite/invalid amounts.
   Half-even cent rounding is explicit. Unknown information is null/unknown, not zero.
3. Orders without valid nonfuture dates are diagnosed/excluded from age checks. Missing/invalid
   invoice due dates remain separately visible. A payment with usable funds but no usable date
   remains a financial exception with unknown age.
4. Section data_issues/coverage identify partial validation while valid records survive.
   Candidate matching and digest formatting also use safe amount parsing.
5. Pagination requires stable integer totals and complete pages; contradictions/duplicates/limits
   raise PaginationError instead of silently returning partial data.
6. Instance labels and report dates are validated before file creation, including direct writer
   calls; both report and draft CLIs validate labels before constructing a client.
7. JSON/Markdown are staged before publication. Handled replace failures roll back the old pair;
   temporary files are cleaned. Two files are not power-failure/concurrent-reader atomic.
8. The internal digest retains missing-due-date and validation warnings, including warning-only input.
   Those rows are not included in overdue totals or customer overdue reminders.

The dependency/aggregate scope thread remains external to these code fixes. Review threads are not
automatically resolved; passing tests do not substitute for the reviewer's final assessment.

## Context used

- Seat 31 Admin answers on 6/10/11 November: direct invoice balances/dates, missing-date warnings,
  internal reporting first, draft-only approval, explicit N and recommended deliverability-age buckets.
- Deepak's division of ownership and #13/#17 comments; latest #17 fixes integrated.
- #35 is integrated with its original commits/attribution. Currency-separated summaries and receipt
  fields are retained, not reimplemented independently. Integration tests verify summary dimensions,
  tool availability, legacy shape, posted/applied handling, future payment buckets and read-only output.
  Shared validation additionally diagnoses bad receipt amounts/dates/children; incomplete history
  never becomes an asserted absence or a zero applied total.
- Open #21 replaces closed #12; state-only graders cannot validate local report content, and
  the identity/cwd contract remains later agent work.
- #24/#25's instructor-scored pairs-file exception is not assumed to cover Seat 31.
- Merged EA/Red Team work and current #26/#34 inform scope, safety and approval boundaries without
  importing another seat's default write behaviour.

The complete PR inventory was checked for state; relevant code/docs/reviews were examined.
This is not a claim that every historical PR received a new full code review.

## Verification

Run `python3 -m unittest discover -s tests -t . -v` in the seat folder. Tests are ordinary synthetic
unit/CLI checks, not human-authored graded course tasks. They cover inherited behaviour, order
threshold/bucket/currency sorting, pagination, strict values, mixed valid/malformed paginated data,
output paths, Unicode/escaping, staged-write failures and replacement rollback.

Private logs and sanitized synthetic outputs are linked from the PR. No model/live business writes
were performed. The stronger guarantees of live schema verification, all Python versions and
complete agent/harness operation are not claimed.
