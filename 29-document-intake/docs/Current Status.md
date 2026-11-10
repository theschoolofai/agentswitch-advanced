# Current Status

**The single place to see where Seat 29 stands.** Update it after every run: change "Right now" and any tables that moved, and add one line to the run log.

**Last updated:** 10 Nov 2026, 12:00 IST

## Right now

| | |
|---|---|
| **Phase** | First task, due 15 Nov 2026 |
| **Overall** | The reader is on track. Draft Bills, due 15 Nov, are blocked until the items under Blockers are answered |
| **Active branch** | `seat29/document-reader`. On 10 Nov it was also pushed to `seat29/platform-client`, so PR #11 now holds the client, every reader version, the vendor check and the write path: 19 commits, 25 files. The harness checks are on `seat29/harness-setup-check`, which is never merged. Some notes stay private until after 20 Dec |
| **In review** | [PR #11](https://github.com/theschoolofai/agentswitch-advanced/pull/11): client and write guard, reader, vendor check, and the write path for harness copies. The PR title and description still describe only the client |
| **Accuracy** | **Fair test on samples 15 to 20: 12 of 13 fields at 6/6, `total_stated` at 3/6, flags 5/6.** Rules frozen at commit `b4fe528` |
| **Known cause** | All 3 misses were credit notes labelled `CREDIT TOTAL`, which the frozen rules could not read. They left the total empty and went to a person |
| **Version 2** | Commit `61b1f48` reads that label. All 20: 13 of 13 fields at 20/20, flags 19/20. **Not a fair test**, because the fix came after seeing the result |
| **Version 3** | Adds date clues: the document, then the vendor's country, then our company, then currency. Pushed 10 Nov, not scored against the key. Compared with version 2, only one document changed: sample 20 lost its date flag, and its date stayed the same |
| **Versions 4 and 5** | Later reader changes, pushed 10 Nov, not scored against the key. All 20 sample results for the scored fields match version 3 |
| **Harness** | Second run, 10 Nov 11:02, commit `f462dea`: **14 of 26** (7 of 13 on each system). Setup, image reading, all 309 unit tests and the 14 risky-tool refusals passed on both. The sample files gave an HTTP error on both copies, and the checks after that had nothing to run on. A fix is ready locally, not pushed |
| **First task** | Reader and scores are done. Still missing: draft Bills on the platform, which need Rohan's permission |
| **Report** | "Seat 29 First Task Accuracy Report" is shared and linked in the 7 Nov message |
| **Bugs** | 16 reported by Sudip. Course team's status on the first 15: 10 open, 2 fixed and live (BUG-29-006 and 011, description text only, confirmed by us on 7 Nov), 2 by design, 1 no change. BUG-29-016 was filed on 7 Nov, no reply yet |
| **Team** | Priye is back and gave a GitHub ID on 7 Nov. The course team still needs to give Priye write access to merge |
| **Next action** | Sudip decides whether to push the harness fix. The next submit opens 13 Nov, about 11:02. Requests to the course team are still unanswered, and a follow-up is drafted |

## What is pending

Open work by deadline. Done work is in the run log below. Some items are tracked separately by the team.

### Due 15 Nov: first task

| # | Item | Owner | Waiting on |
|---|---|---|---|
| 2 | Confirm the reply about the upload test was sent | Sudip | Nothing |
| 3 | Get an answer on how the 12 sample vendors get Party records | Sudip | Rohan, asked 7 Nov, answer wanted by 10 Nov |
| 4 | Get an answer on running `extract` and `accept` on the 20 samples | Sudip | Rohan, asked 5 Nov and 7 Nov, answer wanted by 10 Nov |
| 5 | Create draft Bills on the platform. This is the only part of the first task not built | Claude | Items 3 and 4 |
| 6 | Run the scorer on `local/predictions_v5_all.json`. Versions 3 to 5 have not been scored | Sudip | Nothing |
| 7 | Ask Priye for a new held-back set with vendor bills, then test the latest version fairly | Sudip | Priye |
| 8 | Push the later reader versions, when Sudip decides | Sudip | Nothing |
| 9 | Get PR #11 reviewed and merged. Priye gave a GitHub ID on 7 Nov | Sudip, with Priye | Rohan: write access, asked 7 Nov, answer wanted by 10 Nov |

### Dated and ongoing

| When | Item | Owner |
|---|---|---|
| Sun 8 Nov, then weekly | Post the Sunday update | Sudip |
| About 12 Nov | Renew the API tokens on both systems, which last 7 days | Sudip |
| When announced | Recheck the tool list after Release 16 | Claude |
| After the next release | Recheck the 4 bugs still marked for that release (BUG-29-006 and 011 are done). To close the list by 31 Dec, each of the 15 needs a final status | Sudip |

### Due 30 Nov: version 1

| # | Item | Owner | Waiting on |
|---|---|---|---|
| 1 | Collect documents from Drive, email and forms | Claude | Rohan: how an uploaded file reaches bill intake |
| 2 | Connect to the platform's review queue | Claude | Permission for live data |
| 3 | Build the reviewed write path for drafts | Claude, reviewed by Sudip and Priye | Permission for live data |
| 4 | Handle scans and photos. The harness's model named both test colours correctly on 10 Nov, so a model can read scans in the harness | Claude | Nothing |
| 5 | Read our company, its GSTINs, currency and country from the platform, not from fixed values | Claude | Nothing |
| 6 | Build the 12-task suite and harness file (status below) | Claude | Rohan: may the harness file live on a separate fork branch? |
| 7 | Write the seat skill record on the platform: procedures, knowledge, examples | Sudip, with Priye | Nothing |

**12-task suite.** No task has a suite test yet, and none has run in the harness.

### Due 20 Dec: integration run

| # | Item | Owner | Waiting on |
|---|---|---|---|
| 1 | Find out what happens at the run and how seats connect | Sudip | Rohan |
| 2 | Finish the items the team tracks separately | Claude and Sudip | Rohan, for some items |

### Due 31 Dec: final

| # | Item | Owner |
|---|---|---|
| 1 | Suite passes on both Suryodaya and Keystone | Claude and Sudip |
| 2 | Record the demo | Sudip, with Priye |
| 3 | Final README and a closed bug list | Sudip, with Priye |
| 4 | After the 20 Dec run, publish the team's remaining notes | Sudip |
| 5 | Decide what a credit note becomes on the platform | Rohan |

## Milestones

| Date | Milestone | Status |
|---|---|---|
| 15 Nov 2026 | Classify and extract 20 PDFs, report accuracy per field | **In progress** |
| 30 Nov 2026 | Version 1 and 12-task suite | Not started |
| 20 Dec 2026 | Integration run of all 8 seats | Not started |
| 31 Dec 2026 | Final: suite passes on both systems, demo, README, closed bug list | Not started |

## What exists

| Part | Status | Where |
|---|---|---|
| Platform client, read-only write guard | Built, in PR #11 | `intake/mcp_client.py` |
| Live login check | Built, in PR #11 | `intake/probe.py` |
| Document reader | Built. Version 2 is pushed, later versions are not | `intake/reader.py` |
| Local extract command | Built, pushed | `intake/extract.py` |
| Later reader changes | Built, pushed | `intake/` |
| Write path, harness copies only | Built, pushed. Allows `extract`, `accept` and a labelled `Party.create`, and refuses everything outside a harness copy | `intake/write_path.py` |
| Accuracy scorer | Built, pushed to our fork, scores flags | `intake/score.py` |
| Docs | The guide and this status are committed. Other team notes are kept separately until after the 20 Dec run | `docs/` |
| Accuracy report for Rohan | Shared, linked in the 7 Nov message | Claude Docs |
| Collect from Drive, email and forms | **Not built** | |
| Create drafts on the platform | **Not built**, needs approval | |
| Review queue connection | **Not built** | |
| Handling for scans and photos | **Not built** | |
| Harness setup check | Pushed to our fork, branch `seat29/harness-setup-check`. First run passed 10 of 10 on 7 Nov | `harness/` on that branch |
| 12-task suite and harness file | **Not built** | |
| Seat skill record: procedures, knowledge, examples | **Not written** | On the platform |
| Demo recording | **Not made** | |

## Latest results

**Unit tests:** 300 of 300 passed on Python 3.12 on Windows and Python 3.11 on Linux (7 Nov). The harness uses Python 3.11.16 on Linux.

**Version 2 on all 20 samples (commit `61b1f48`, not a fair test):** all 13 fields at 20/20, flags 19/20. The one flag difference is the extra `ambiguous_date_order`, which we keep on purpose. Proposed actions: 11 draft bills, 1 duplicate rejected, 5 rejected as not a bill, 3 credit notes for review.

**Reader on samples 01 to 14:**

| Measure | Result |
|---|---|
| Documents read | 14 of 14 |
| Types found | 12 vendor bills, 2 sales invoices |
| Flags raised | 1 discount line, 1 duplicate, 1 foreign currency, 1 no due date, 1 tax exempt, 1 total mismatch |
| Key fields produced | 14 of 14 |
| Check method | Exact match against the answer key. The scorer printed totals only |

**Accuracy per field (exact match, rules frozen at commit `b4fe528`):**

| Field | Samples 01–14 (tuning set) | Samples 15–20 (fair test, one run) | All 20 |
|---|---|---|---|
| `counterparty_gstin` | 14/14 | 6/6 | 20/20 |
| `counterparty_name` | 14/14 | 6/6 | 20/20 |
| `currency` | 14/14 | 6/6 | 20/20 |
| `doc_type` | 14/14 | 6/6 | 20/20 |
| `due_date` | 14/14 | 6/6 | 20/20 |
| `invoice_date` | 14/14 | 6/6 | 20/20 |
| `invoice_number` | 14/14 | 6/6 | 20/20 |
| `lines` | 14/14 | 6/6 | 20/20 |
| `subtotal` | 14/14 | 6/6 | 20/20 |
| `tax_rate_percent` | 14/14 | 6/6 | 20/20 |
| `tax_total` | 14/14 | 6/6 | 20/20 |
| `tax_type` | 14/14 | 6/6 | 20/20 |
| **`total_stated`** | 14/14 | **3/6** | **17/20** |
| `flags`, exact set per document | 14/14 | 5/6 | 19/20 |

**Flags found across all 20:** duplicate 1 of 1, foreign currency 1 of 1, discount line 1 of 1, no due date 2 of 2, tax exempt 1 of 1, total mismatch 1 of 1. One extra flag was raised that is not in the key: `ambiguous_date_order`.

**How to read this:**

- The fair test is the honest number, but it is only 6 documents, all sales invoices and credit notes. No vendor bills were in it.
- The tuning scores come from documents the rules were built on, so they do not predict accuracy on new documents.
- `total_stated` missed on all 3 credit notes, which label their total `CREDIT TOTAL`. The total was left empty, confidence went to 0, and they went to a person. No value was invented.
- The extra flag came from one document whose two dates can each be read day-first or month-first. Our reader flags that for a person. The key does not list it, so that document's flag set does not match exactly.
- A different held-back set may be used at review.

## Platform facts

| Fact | Suryodaya | Keystone |
|---|---|---|
| Accounting documents | 120 | 20 |
| Intake samples stored | 20, since 10:18 UTC on 6 Nov | 20, since 10:18 UTC on 6 Nov |
| Sample files match our copies by size | 20 of 20 | 20 of 20 |
| Samples extracted so far | 0 | 0 |
| Our records on the platform | 1 Drive file, labelled `[seat29-upload-test]` | None |
| Bills | 358 as of 6 Nov | 104 as of 6 Nov |
| Parties | 233 | 147 |
| Sample vendor bills matching a Party | 0 of 12 | 0 of 12 |
| Harness link set | Yes, 7 Nov, branch `seat29/harness-setup-check`. The run covers both systems | No link of its own |

Release 16 was not announced as live at the last update, but the samples are already stored. Recheck the tool list when the release is announced.

API tokens were issued on 5 Nov and last 7 days, so they need renewing around 12 Nov.

## Blockers

| Blocker | Needs | Owner | Since |
|---|---|---|---|
| Permission to run `extract` and `accept` on the 20 samples | Rohan's answer | Asked 5 Nov and 7 Nov | 5 Nov |
| Priye cannot merge PRs yet. GitHub ID given on 7 Nov | Rohan to give write access | Asked 7 Nov | 5 Nov |
| Sample vendors have no Party records, and `accept` needs a vendor id, so no sample can become a draft | Rohan's answer | Asked 7 Nov | 6 Nov |

## Open questions

| Question | Asked? | Answer |
|---|---|---|
| Where are the 20 sample PDFs? | Yes | **Answered 6 Nov:** zip supplied, and now stored on the platform |
| Why do seeded files return `file_unavailable`? | Yes | **Answered 6 Nov:** they have records but no stored files |
| Test one upload and report the result | Asked by Rohan | **Done.** Reply drafted. Confirm it was sent |
| How does an uploaded file reach bill intake? | Yes, 7 Nov | Waiting |
| May we run `extract` and `accept` on the 20 samples? | Yes, again on 7 Nov | Waiting |
| Why does `Bill.submit` preview as allowed? | Yes | **Answered 6 Nov:** it comes from the role our login holds. A role decision is still open with the course team |
| May the harness file live on a separate fork branch? | Yes, again on 7 Nov | **It works:** our 7 Nov run used one. Rohan has not confirmed it is the intended route |
| Which Python and operating system does the harness use? | Yes, 7 Nov | **Answered 7 Nov by our own run:** Python 3.11.16 on Linux |
| Does the harness's model read images? | Yes, 7 Nov | **Yes.** On 10 Nov it named a red and a blue test image correctly on both systems |
| Who makes the login role decision, and by when? | Yes, 7 Nov | Waiting |
| What should sales invoices and credit notes become? | Yes, 7 Nov | Waiting |
| Does 20 Dec run on a copy or live data, and how do seats connect? | Yes, 7 Nov | Waiting |
| How do the 12 sample vendors get Party records? | Yes, 7 Nov | Waiting |

## How to score

Run these from `29-document-intake`. They print field names and totals only, never answers.

```
.venv\Scripts\python.exe -m intake.score --describe --key "PATH\TO\KEY.zip"
.venv\Scripts\python.exe -m intake.score --labels --key "PATH\TO\KEY.zip"
.venv\Scripts\python.exe -m intake.score local\predictions_v5_all.json --key "PATH\TO\KEY.zip"
```

## Run log

Newest first. Keep each entry to one line, with counts only.

| When (IST) | Run | Result |
|---|---|---|
| 10 Nov, 12:00 | Harness fix, local only: the HTTP status is logged, a refused token is tried once without it, `extract` runs on every listed sample even if downloads fail, and `accept` uses the platform's values only when our reader had no files | 31 harness tests passed. Read-only dry run on live Suryodaya: same as before, 20 of 20 downloaded and matched. Not pushed |
| 10 Nov, 11:02 | **Second harness run, commit `f462dea`, 1,349 tokens** | 14 of 26, 7 of 13 on each system. Passed: setup, image reading (both colours right), 309 unit tests, 14 of 14 risky tools refused, Bill counts unchanged. Failed: all 20 sample downloads gave an HTTP error with no status kept, so the reader, vendor, `extract`, comparison and `accept` checks had nothing to run on. The live system serves the same files even without a token |
| 10 Nov, 10:40 | Branches pushed to our fork: `seat29/document-reader` and `seat29/harness-setup-check`, after Sudip decided to publish the code | A scan of every new commit found no secrets, samples or answer key. Private notes were not included |
| 10 Nov, ~10:35 | Harness checks built: a write path for harness copies only, and 8 new intake checks. Read-only dry runs on live Suryodaya and Keystone | 309 unit tests and 27 harness tests passed. Every read-only check passed on both systems. The write checks refused on live data, as designed |
| 10 Nov, 10:20 | Read-only check for any change since the 7 Nov requests, both systems | Nothing changed: 0 of 11 sample vendors have a Party, all 20 samples not extracted, all 16 reports still `new`, PR #11 has no review |
| 7 Nov, 11:24 | Status updated and pushed to our fork. No new run | Later reader versions stay unpushed |
| 7 Nov, 11:23 | Reader now sends a valid photo to a person, not pushed. Pictures are not read yet | 300 of 300 tests passed on Windows and Linux. All 20 sample results unchanged |
| 7 Nov, 11:10 | Docs brought up to date and committed. No new run | This status and the guide are pushed to our fork. Later reader versions stay unpushed |
| 7 Nov, 11:08 | Stricter image check pushed to the harness branch, commit `5b8c4b3`. It passes only if the model names two colours correctly, and it records the short answers | 16 of 16 tests passed from a clean export on Python 3.11. Not run in the harness yet. Next submit from 10 Nov, 11:00 |
| 7 Nov, 11:04 | Unit tests on Python 3.11 on Windows, and on Python 3.11 on Linux (Ubuntu in WSL) | 256 of 256 passed on both. All 20 sample results unchanged |
| 7 Nov, 11:02 | **First harness run, setup check, commit `6182dc7`** | 10 of 10 on both systems, 585 tokens, about 90 seconds. Python 3.11.16 on Linux x86_64 with 4 CPUs. `Bill.submit` refused and Bill counts unchanged. The model accepted an image but did not answer the colour correctly, so image reading is not settled |
| 7 Nov, 11:01 | Sudip set the harness link and submitted the setup check, commit `6182dc7`, at 11:00 | Accepted from the separate branch. Queued on both systems. Next submit no earlier than 10 Nov, 11:00 |
| 7 Nov, 10:56 | Harness setup check pushed to our fork, branch `seat29/harness-setup-check`, commit `6182dc7`. No PR, because the harness file must not merge to `main` | 12 of 12 tests passed from a clean export. Link not set and no run submitted yet |
| 7 Nov, 10:49 | Harness setup check built on a separate local branch. Its tests ran, then a read-only local run on both systems | 12 of 12 tests passed. Login, read and the Bill.submit refusal worked on both systems, and no record changed. The model check needs a real harness run. Not pushed |
| 7 Nov, 09:34 | Sudip confirmed the report is shared and the answer key is moved. No new run | Sudip runs the scorer from now on |
| 7 Nov, 09:32 | Sudip sent the course team our status and requests, by message. No new run | Answers asked for by 10 Nov. If none arrive, we deliver the reader, scores and proposed drafts on 15 Nov, and say no draft Bills were created |
| 7 Nov, 09:03 | Harness link and run limits read, read-only | No link set, no run submitted. Nothing to run yet |
| 7 Nov, 08:58 | Message for Rohan written, and the new bug report confirmed, read-only | 16 reports on the platform. Message not sent yet. No record changed by us |
| 7 Nov, 08:52 | Read-only recheck of one drafted bug report, both systems | It still repeats. No record changed |
| 7 Nov, 08:47 | Read-only recheck of the course team's fixes, both systems. 256 of 256 tests passed | BUG-29-006 and 011 descriptions are live. Queue results unchanged at 72 and 20. All 15 reports intact |
| 6 Nov, 20:29 | Course team's status on the 15 bugs recorded. Bug list read, no record changed | 10 open, 2 fixed in the next release, 2 by design, 1 no change. None reproduced yet |
| 6 Nov, 20:20 | Status and blockers added to the accuracy report. No new run | Report not sent yet. Nothing pushed |
| 6 Nov, 20:15 | Docs updated. No new run | Nothing pushed |
| 6 Nov, 19:52 | Reader version 5 finished, and pending work written up | 256 of 256 tests passed, also from a clean export of the commit. Not pushed |
| 6 Nov, 19:15 | Reader version 5 built. Party and Bill lists read on both systems, no record changed. Samples compared with version 4 without the key | All tests passed. Scored fields unchanged. 0 of 12 sample vendor bills match a Party |
| 6 Nov, 17:50 | Reader version 4 built. Samples compared with version 3 without the key | 220 of 220 tests passed. All 20 sample results identical |
| 6 Nov, 17:16 | Version 3 date clues built and compared with version 2, without the key | 100 of 100 tests passed. Only sample 20 changed: date flag gone, date unchanged |
| 6 Nov, 16:56 | Branch `seat29/document-reader` pushed to our fork | Scan of all commits found no secrets, samples or answer key. No PR opened |
| 6 Nov, 16:44 | Sudip reported 15 bugs on the platform | All show Received, none triaged yet |
| 6 Nov, ~16:40 | Docs updated with the solution details. No new run | The guide now covers fields, rules, flags, confidence, testing and lessons |
| 6 Nov, ~16:38 | Accuracy report drafted for Rohan | Fair-test numbers first, with the limits and the scorer disclosure |
| 6 Nov, 16:35 | Version 2 on all 20 samples, commit `61b1f48`, not a fair test | All 13 fields at 20/20, flags 19/20. 86 of 86 tests passed |
| 6 Nov, 16:32 | **Fair test on samples 15 to 20, one run, rules at `b4fe528`** | 12 of 13 fields at 6/6, `total_stated` 3/6, flags 5/6. All 20: `total_stated` 17/20, flags 19/20, other fields 20/20 |
| 6 Nov, 16:30 | Flag scoring added, samples 01 to 14 rescored | All 13 fields at 14/14, flags 14/14. 84 of 84 tests passed |
| 6 Nov, 16:25 | First score on samples 01 to 14, at Sudip's request | 13 of 13 scored fields at 14/14. Tuning set, flags not scored |
| 6 Nov, 16:23 | Reader aligned with the key, samples 01 to 14 re-run | 82 of 82 tests passed, 14 of 14 key fields produced. Not scored yet |
| 6 Nov, 16:22 | Scorer `--labels` on the answer key, at Sudip's request | Label lists only, nothing per document. 1 flag label withheld by the safeguard |
| 6 Nov, 16:19 | Scorer `--describe` on the answer key | 20 documents, 14 fields. Names and types only, no answers printed, key not extracted |
| 6 Nov, 16:13 | Intake queue state check, both systems | `review_required` returned 72 and 20 documents that were never extracted. Became BUG-29-006 |
| 6 Nov, 16:11 | Read-only bug checks, both systems | 15 findings written up. No record changed |
| 6 Nov, ~15:55 | Reader on samples 01 to 14 | 14 read, 12 bills and 2 sales invoices, all known traps in that range flagged |
| 6 Nov, ~15:50 | Unit tests | First run: 9 failed and found the "Rs." bug. After the fix: 71 of 71 passed |
| 6 Nov, 15:35 | One upload to Suryodaya, requested by Rohan | Stored correctly in Drive, did not reach the intake queue |
| 5 Nov | Live login check, both systems | Logins fine, `Bill.submit` refused by the guard without being sent |
| 5 Nov | Unit tests for the client | 27 of 27 passed on Python 3.14 |
| 5 Nov | First read-only look at both systems | Found built-in bill intake, no sample PDFs at that time |
