# Risks, blockers and open questions

> Everything that could stop us, with an owner and a status. We review it every Sunday. A blocker is written here only after it has been checked live. Exact requests and replies stay in the local platform notes (`docs/processed/platform/access.md`, see [../platform/README.md](../platform/README.md)), not here, because the repository is public.

## Log
Types: **R** risk, **A** assumption, **I** issue (happening now), **D** dependency.

| # | Type | What | Owner | Status | Checked |
|---|---|---|---|---|---|
| 1 | I | Our login cannot read the sales, accounting and item data that seats 31 and 35 use. So our checks cannot verify those seats' results yet. | seat lead | Open: ask instructor (Q3) | 7 Nov, both systems |
| 2 | D | Seats 31 and 35 keep their results in **local files**, not on the platform, so our checks have nothing to read. We need to agree where results land (for example drafts or approval requests). | seat lead | Open: talk to both seats | 7 Nov, from their pull requests |
| 3 | D | Seat 31 cannot yet create its reminder drafts (their own open bug). | seat 31 | Open (theirs) | From their pull request |
| 4 | R | The harness file must be at a repository root, but this repository is shared by 8 seats. | seat lead | Open: Q1 | n/a |
| 5 | R | We do not know which login a course run gives us, or how our harness should start another seat's agent. | seat lead | Open: Q2 | n/a |
| 6 | R | Official runs are limited (one run every 3 days, plus token caps), so a failed run costs 3 days. | seat lead | Mitigate: local dry run before every official run | 7 Nov |
| 7 | R | Shared live data changes under us, so expected answers go stale. | suite owners | Mitigate: checks compute from snapshots taken at run time; any fixed answer carries an "as of" date | n/a |
| 8 | R | Tests written by AI tools score zero. | everyone | Mitigate: agents only draft in `ideas.md`; people write the tasks; each task file names its author | n/a |
| 9 | A | Course runs happen on a throwaway copy, so any writes by the agent under test are discarded. | seat lead | Assumed from `TASK_FORMAT.md`; confirm in the first official run | n/a |
| 10 | R | The platform is still being developed, so behaviour can change with each release. | seat lead | Mitigate: run `scripts/platform_sync.py` after every release notice, and review the change report | n/a |

## Open questions for the instructor
Post these in the seat group. For Q3, paste the exact requests and replies from the local `access.md` (system, login, request, reply), as the course asks. Never include a password or a token.

1. **Harness file location.** `agentswitch-harness.toml` must be at a repository root, but this repository has one root for 8 seats. Can our harness registration point at a subfolder (`34-eval-harness/`) or a branch of our fork? Until we hear back, the file stays in our seat folder.
2. **Login and starting the agent.** Which token does a course run give: seat 34's (as your 6 Nov note says) or the seat under test's (as `TASK_FORMAT.md` says)? And how should our harness start seat 31's and seat 35's agents?
3. **Read access for our checks.** On both systems our login is refused when it reads sales orders, invoices, payments and items. Our checks need these to verify seats 31 and 35. Can our read access be widened?
4. **Knowledge base.** Our login now has the knowledge base. What is it meant for in our seat: as the written standard of correct behaviour, or as a place to publish score reports?
5. **Nightly run.** Where may the nightly regression run (our own machine, or a CI job in our fork), and against what: live data read-only, or a copy?
6. **Test data.** Can a run on the throwaway copy create test records (for example two planted duplicate parties), so tasks have known answers?

## Closed
- (none yet)
