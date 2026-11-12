# Section 3 P2 review fixes

The 12 November review of #35 reproduced a cross-currency receipt hint and a task-7 verifier that accepted incorrect currencies and group labels. This follow-up is on Sunil's #29 branch, which already contains #35; it does not change Deepak's source branch.

## Receipt contract

- `same_amount` now requires the same customer, a known equal currency, and an amount within the existing tolerance. It remains a human check, never settlement proof.
- The report resolves receipt currency using its existing precedence: explicit `currency_code`/`currency`, customer `Party.currency_id`, then company `Company.default_currency` (including the existing single-company fallback). These are the report's contextual currency assumptions, not a newly verified PaymentReceived schema field. If none is available, currency remains unknown.
- `receipts_applied_total` is retained but now scoped to `receipts_currency`, the payment's resolved currency; it is null for an unknown payment currency. It is no longer a sum across currencies.
- `receipts_applied_by_currency` exposes `{currency, applied_total}` entries. Unknown-currency history is retained with a null total, since unknown currencies cannot safely be added together.
- Paid-receipt count and last receipt date remain customer-wide history facts. Currency uncertainty does not erase history or manufacture a same-amount match.

## Independent task-7 verifier

Expected payment currencies are recounted from raw Party/Company records, rather than report rows. Payment currently has no currency field. The verifier independently derives date buckets, statuses and customer group keys, then compares exact keys, counts and Decimal totals. Duplicate/missing groups and duplicate report rows fail verification.

The ordinary offline regression tests exercise mixed/unknown currencies, live receipt field names, contextual fallback, consistent row-and-summary corruption, wrong classification labels, and duplicate/missing groups. These are software regression tests, not graded task scenarios authored for the course.
