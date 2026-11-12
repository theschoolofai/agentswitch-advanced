# Deepak review follow-ups — 12 November

Addresses the five follow-ups in [the second review of PR #29](https://github.com/theschoolofai/agentswitch-advanced/pull/29#pullrequestreview-5873375608).

| Comment | Change | Regression coverage |
|---|---|---|
| Receipt quarantine affects unrelated customers | Track quarantined customer IDs; retain unrelated customers' verified absence. A receipt without a customer keeps the conservative all-customer fallback. Affected rows expose partial history and null scalar/per-currency totals even when valid history exists. | Unrelated customer, affected customer, missing customer, incomplete totals, and valid allocations with a malformed date. |
| Concurrent pagination changes abort immediately | Order reads by `id asc`; restart the entire read up to twice on changing totals, repeated pages, or duplicate IDs. Each attempt discards prior rows and restarts at offset zero. Permanent instability and malformed protocols still fail without partial publication. | Successful total-change/duplicate restart, bounded permanent instability, and immediate malformed-response failure; existing full-report tests retained. |
| Order date warning duplicated | Show unusable dates once in the dedicated section. Keep structured JSON diagnostics intact and other validation issues visible. | Markdown lists the bad order once; JSON still contains its diagnostic. |
| Python 3.10 fractional timestamp parsing | Pad validated fractional seconds to six digits before `fromisoformat`, preserving the source calendar day. | All six supported fraction lengths pass a parser double enforcing the older width restriction. Actual validation runtime is Python 3.14, not Python 3.10. |
| README approval gate | Use `python3 -m` for Ubuntu commands in README and supporting instructions. | Reviewed command examples; no new runtime test for a documentation edit. |

Validation: **215 offline tests passed**, including 11 new follow-up tests and the 12 earlier P2 regression tests. Network calls were disabled and platform credentials excluded for the recorded suite. No live platform compatibility claim is made for the new sort parameters; they follow the list-tool contract described in Deepak's review.

The prerequisite merge/rebase gate remains: #13 → #17 → #35 → #29. These fixes do not merge prerequisites or turn #29 into an approved aggregate PR. After prerequisite merges, update the branch and rerun validation before marking ready.
