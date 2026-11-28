# Current Status

**The single place to see where Seat 29 stands.** Update it after every run: change "Right now" and any tables that moved, and add one line to the run log.

**Last updated:** 28 Nov 2026, IST

## Right now

| | |
|---|---|
| **Phase** | Version 1, **due Mon 30 Nov 2026, in 2 days**. No Seat 29 commit since 18 Nov |
| **Overall** | PR #11 and PR #50 are both merged into `main`, so the client, reader, vendor check, harness-copy write path and harness checks are all there. **The 12-task suite is not built**: Seats 31 and 35 have a suite in `34-eval-harness/suites/`, Seat 29 has none. No live draft decision was posted, so no draft Bills exist on the live systems |
| **Merged** | [PR #11](https://github.com/theschoolofai/agentswitch-advanced/pull/11), merged 18 Nov: client and read guard, reader, vendor check, and the write path for harness copies. Approved by Rohan on 17 Nov after one sentence was removed from this file |
| **Merged** | [PR #50](https://github.com/theschoolofai/agentswitch-advanced/pull/50), merged 19 Nov after Rohan's approval: harness checks only, with the `extract` error-message logging and the harness file test skip |
| **Closed** | [PR #44](https://github.com/theschoolofai/agentswitch-advanced/pull/44), closed by Sudip on 18 Nov in favour of #50 |
| **Branches** | `main` now holds all of `29-document-intake/`. `seat29/document-reader` and `seat29/platform-client` are both at `4c0db14`, already in `main`. The harness link points at `seat29/harness-setup-check`, now at `e6c192a`: `main` + #50 + the root harness file and `requirements.txt`. Its `harness/` folder is identical to #50's. New work should branch from current `main` |
| **Accuracy** | **Fair test on samples 15 to 20: 12 of 13 fields at 6/6, `total_stated` at 3/6, flags 5/6.** Rules frozen at commit `b4fe528` |
| **Known cause** | All 3 misses were credit notes labelled `CREDIT TOTAL`, which the frozen rules could not read. They left the total empty and went to a person |
| **Version 2** | Commit `61b1f48` reads that label. All 20: 13 of 13 fields at 20/20, flags 19/20. **Not a fair test**, because the fix came after seeing the result |
| **Version 3** | Adds date clues: the document, then the vendor's country, then our company, then currency. Not scored against the key. Compared with version 2, only one document changed: sample 20 lost its date flag, and its date stayed the same |
| **Versions 4 and 5** | Later reader changes, not scored against the key. All 20 sample results for the scored fields match version 3 |
| **New test set** | Priye's 207 outside PDFs, on this machine outside git (Apache 2.0 and MIT). Split fixed before tuning in `benchmarks/outside_set_split.json`: 54 tuning, 153 held out. **Reader version 6** (`9d97643`) was tuned on the 54 only, then frozen and run once on the 153. Fields filled on the held-out files, before and after: invoice number 0 to 152, invoice date 0 to 152, due date 0 to 150, tax rate 0 to 95, total 104 to 151, currency 104 to 152. **Correctness is not scored yet**: Sudip runs the scorer. The 20 course samples give exactly the same results |
| **Harness** | Last run 17 Nov, `ce6f312`, 14 of 26: the copy lists the samples but returns 404 for their files. Harness branch now at `1b28e27` with reader version 6. Next run to be submitted by Sudip from the web page |
| **Platform access** | Tokens renewed on 28 Nov, due again about 5 Dec. Login check passed on both systems, and the guard still refuses `Bill.submit` unsent. A harness run may be submitted now (one every 3 days) |
| **Mailboxes** | Read on 18 Nov: 1 mailbox, 3 threads and 3 messages on each system. No message has an attachment, so there is no bill PDF to test intake with yet |
| **First task** | Due 15 Nov. Reader and scores done, no live draft Bills, under the accepted fallback. Priye held the hand-in. **The hand-in is not recorded here: confirm it was made** |
| **Report** | "Seat 29 First Task Accuracy Report" is shared and linked in the 7 Nov message |
| **Bugs** | 16 reported by Sudip. Course team's status on the first 15: 10 open, 2 fixed and live (BUG-29-006 and 011, description text only, confirmed by us on 7 Nov), 2 by design, 1 no change. BUG-29-016 answered in chat on 10 Nov: use `gst_no` on Bills. Mailbox failure fixed by the course team on 12 Nov, not yet rechecked by us |
| **Team** | Priye has accepted the fork invitation and opened PR #50 from our fork. Rohan said he looks at Priye's write access to the course repo after Priye confirms the GitHub account in the seat chat |
| **Next action** | Today: post the seat status in the chat (it includes the mailbox read and the harness result) and close PR #44. Then run the reader on Priye's new test set |

## What is pending

Open work by deadline. Done work is in the run log below. Some items are tracked separately by the team.

### Due now: seat review, 18 Nov

| # | Item | Owner | Waiting on |
|---|---|---|---|
| 1 | Post the seat status in the seat chat, as Rohan asked on 18 Nov | Sudip | Nothing |
| 2 | ~~Close PR #44, which is replaced by #50~~ Done 18 Nov | Sudip | |
| 3 | ~~Get PR #50 reviewed and merged~~ Merged 19 Nov | Rohan | |
| 4 | Post in the seat chat the platform finding Rohan asked for on 13 Nov, so the course team can log it | Sudip | Nothing. The details are kept outside this repo |
| 5 | ~~Renew the API tokens on both systems~~ Done 18 Nov | Sudip | |
| 6 | Tell Rohan the mailbox read result: 1 mailbox, 3 threads, 3 messages, no attachments on each system (read 18 Nov). Ask for a thread with a bill PDF | Sudip | Nothing. In the status message |
| 7 | Report the 17 Nov harness result to Rohan: on the copy, the sample records exist but their files return 404, and `extract` fails on all 20. Ask him to store the files there or say they won't be | Sudip | Nothing |
| 8 | Confirm the 15 Nov first-task hand-in was made | Priye | Nothing |

### First task, from 15 Nov: still open

| # | Item | Owner | Waiting on |
|---|---|---|---|
| 1 | Get an answer on how the 12 sample vendors get Party records on the live systems | Sudip | Rohan. No decision posted by 12 Nov, so nothing is created live |
| 2 | Get an answer on running `extract` and `accept` on the 20 samples on the live systems. On the harness copy: allowed, 10 Nov | Sudip | Rohan. No decision posted by 12 Nov |
| 3 | Create draft Bills on the live systems. Nothing is created there until Rohan writes | Claude | Items 1 and 2 |
| 4 | Run the scorer on `local/predictions_v5_all.json`. Versions 3 to 5 have not been scored | Sudip | Nothing |
| 5 | Run the latest reader on Priye's new test set, once, then Sudip scores it | Claude, then Sudip | Priye: share where the set is |
| 6 | Get an answer on whether the sample files should exist on the harness copy | Sudip | Rohan, checking since 10 Nov |

### Dated and ongoing

| When | Item | Owner |
|---|---|---|
| Sun 8 Nov, then weekly | Post the Sunday update | Sudip |
| Every 7 days | Renew the API tokens on both systems. Overdue since about 25 Nov | Sudip |
| When announced | Recheck the tool list after Release 16 | Claude |
| After the next release | Recheck the 4 bugs still marked for that release (BUG-29-006 and 011 are done). To close the list by 31 Dec, each of the 15 needs a final status | Sudip |

### Due 30 Nov: version 1

| # | Item | Owner | Waiting on |
|---|---|---|---|
| 1 | Collect documents from Drive, email and forms. Mailboxes exist since 12 Nov, one per login on each system, with 3 plain sample threads and no bill PDF. Ask Rohan for a thread with a bill PDF for the intake test | Claude | Rohan: how an uploaded file reaches bill intake (after 15 Nov), and a thread with a bill PDF |
| 2 | Connect to the platform's review queue | Claude | Permission for live data |
| 3 | Build the reviewed write path for drafts | Claude, reviewed by Sudip and Priye | Permission for live data |
| 4 | Handle scans and photos. The harness's model named both test colours correctly on 10 Nov, so a model can read scans in the harness | Claude | Nothing |
| 5 | Read our company, its GSTINs, currency and country from the platform, not from fixed values | Claude | Nothing |
| 6 | Build the 12-task suite and harness file (status below). The harness file stays on its separate fork branch, confirmed 10 Nov. The harness checks are in PR #50 | Claude | Nothing |
| 7 | Write the seat skill record on the platform: procedures, knowledge, examples | Sudip, with Priye | Nothing |
| 8 | Vendor tax check: compare an Indian bill's GSTIN with `gst_no` on the vendor's existing Bills. For a US vendor, compare the vendor name only, and send every US bill to a person marked "tax id not checked" (Rohan, 11 Nov). Seat 29 does not get `tax_id` on Party in version 1 | Claude | Nothing |
| 9 | Keep `seat29/harness-setup-check` up to date with `main`, so the harness runs the reviewed code. Done 18 Nov at `e6c192a`: `main` + #50 + the root harness file and `requirements.txt`. Redo after #50 merges or `main` moves | Sudip | |

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
| 15 Nov 2026 | Classify and extract 20 PDFs, report accuracy per field | Reader and scores done under the accepted fallback, no live drafts. Hand-in to be confirmed |
| 18 Nov 2026 | Seat review | **Today**: status post due in the seat chat |
| 30 Nov 2026 | Version 1 and 12-task suite | In progress: client and reader merged (#11), harness checks in review (#50) |
| 20 Dec 2026 | Integration run of all 8 seats | Not started |
| 31 Dec 2026 | Final: suite passes on both systems, demo, README, closed bug list | Not started |

## What exists

| Part | Status | Where |
|---|---|---|
| Platform client, read-only write guard | Built, merged in PR #11 | `intake/mcp_client.py` |
| Live login check | Built, merged in PR #11 | `intake/probe.py` |
| Document reader | Built, versions 1 to 5 merged in PR #11 | `intake/reader.py` |
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
| Harness setup check | In review as PR #50 (only `harness/`). Runs come from fork branch `seat29/harness-setup-check`. First run passed 10 of 10 on 7 Nov, the second 14 of 26 on 10 Nov. Later runs not recorded yet | `harness/` |
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

On 18 Nov: Suryodaya has 382 Bills, 120 accounting documents and 120 in the intake queue. Keystone has 104 Bills, 20 accounting documents and 20 in the queue. Other rows above are from 6 Nov.

API tokens last 7 days. Renewed on 18 Nov.

Mailboxes, read on 18 Nov: 1 mailbox, 3 threads and 3 messages on each system, no attachments.

Harness runs on record: 3. 7 Nov passed, 10 Nov and 17 Nov failed at 14 of 26.

## Blockers

| Blocker | Needs | Owner | Since |
|---|---|---|---|
| The harness copy lists the 20 samples but their files return 404, so `extract`, the reader comparison and `accept` cannot run there | The course team stores the files on the copy, or says they won't be | Rohan | 10 Nov |
| Permission to run `extract` and `accept` on the 20 samples on the live systems. Allowed on the harness copy since 10 Nov | Rohan's decision. None posted by 12 Nov, so the fallback applies | Asked 5 Nov and 7 Nov | 5 Nov |
| Sample vendors have no Party records, and `accept` needs a vendor id, so no sample can become a draft on the live systems | Rohan's decision. None posted by 12 Nov | Asked 7 Nov | 6 Nov |

## Open questions

| Question | Asked? | Answer |
|---|---|---|
| Where are the 20 sample PDFs? | Yes | **Answered 6 Nov:** zip supplied, and now stored on the platform |
| Why do seeded files return `file_unavailable`? | Yes | **Answered 6 Nov:** they have records but no stored files |
| Test one upload and report the result | Asked by Rohan | **Done.** Reply drafted. Confirm it was sent |
| How does an uploaded file reach bill intake? | Yes, 7 Nov | Waits until after 15 Nov (Rohan, 10 Nov) |
| May we run `extract` and `accept` on the 20 samples? | Yes, again on 7 Nov | **Harness copy: yes**, `extract`, one `accept` and one labelled test Party, `Bill.submit` blocked (10 Nov). Live systems: decision by 12 Nov |
| Why does `Bill.submit` preview as allowed? | Yes | **Answered 6 Nov:** it comes from the role our login holds. A role decision is still open with the course team |
| May the harness file live on a separate fork branch? | Yes, again on 7 Nov | **Answered 10 Nov: yes,** also for the 30 Nov suite |
| Which Python and operating system does the harness use? | Yes, 7 Nov | **Answered 7 Nov by our own run:** Python 3.11.16 on Linux |
| Does the harness's model read images? | Yes, 7 Nov | **Yes.** On 10 Nov it named a red and a blue test image correctly on both systems |
| Who makes the login role decision, and by when? | Yes, 7 Nov | Waits until after 15 Nov |
| What should sales invoices and credit notes become? | Yes, 7 Nov | Waits until after 15 Nov |
| Does 20 Dec run on a copy or live data, and how do seats connect? | Yes, 7 Nov | Waits until after 15 Nov |
| How do the 12 sample vendors get Party records? | Yes, 7 Nov | Live systems: decision by 12 Nov. Harness copy: one labelled test Party allowed |
| How do we check a vendor's GSTIN? (BUG-29-016) | Yes, 10 Nov | **Answered 10 Nov:** use `gst_no` on the vendor's Bills. A narrow check tool is listed for a later release |
| How do we check a US vendor's tax id? | Yes, 10 Nov | **Answered 11 Nov:** compare the vendor name, and send every US bill to a person marked "tax id not checked". No `tax_id` on Party in version 1 |
| Are the sample files meant to be on the harness copy? | Yes, 10 Nov | Rohan is checking. No answer in the chat yet |
| Can Seat 29 have a mailbox? | Yes, 10 Nov | **Done 12 Nov:** one mailbox per login on each system, 3 plain sample threads, no bill PDF. Rohan asked us to read them again and report. Ask for a thread with a bill PDF |
| Live draft Bills and Party records for the samples? | Yes, 7 Nov | No decision posted by 12 Nov. The 15 Nov fallback was accepted in advance: no draft Bills created live |

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
| 28 Nov | Harness branch updated to `1b28e27` with reader version 6, pushed | 32 harness tests, 321 unit tests, course samples 20/20 against `expected_samples.py` |
| 28 Nov | **Reader version 6, one run on the 153 held-out outside files**, rules frozen at `9d97643` | 153 read, 0 failed. Filled: invoice number 152, invoice date 152, due date 150, total 151, tax rate 95. Not scored yet |
| 28 Nov | Reader version 6 built on the 54 tuning files only. Split committed first as `eaff5f9` | 321 unit tests passed (12 new). Course samples 20/20 unchanged. Two defence tests caught two first attempts and both were fixed |
| 28 Nov | Tokens renewed on both systems. Login probe | Login ok on both, `Bill.submit` refused unsent. Bills 401 and 104. Harness: can submit now |
| 28 Nov | Baseline: reader from `main` on Priye's 207 PDFs, without the key | 207 read, 0 failed. Type `unknown` on all 207, because none is addressed to Suryodaya or Keystone, so all go to a person. 1 file flagged for active content. Not scored yet: Sudip runs the scorer |
| 28 Nov | Code revalidated from a clean checkout of `main` (`94585cf`), fresh install of `requirements.txt`, Python 3.14 on Windows. Same on the harness branch `e6c192a` | `main`: 309 of 309 unit tests, 31 harness tests passed and 1 skipped (no root harness file on `main`, as designed). Harness branch: 309 and 32 of 32. Reader on the 20 local samples: files 20/20 and results 20/20 match `harness/expected_samples.py`, 0 errors |
| 28 Nov | Read-only recheck and repo check | Both tokens rejected, so nothing on the platform could be read. PR #50 merged 19 Nov. `harness/` and `29-document-intake/` on the harness branch match `main` exactly. No Seat 29 suite on `main` yet |
| 18 Nov, 21:45 | PR #50 branch: the `extract` logging commit added, plus a fix found while testing it. The harness file test failed wherever the root harness file is absent, including on `main`, so it now skips there. Same fix on the harness branch. #44 closed by Sudip. Pushed as `fdc9764` (#50) and `e6c192a` (harness branch) | #50: 31 passed, 1 skipped. Harness branch: 32 of 32. `harness/` identical on both |
| 18 Nov, 21:15 | Harness branch `seat29/harness-setup-check` brought up to `main` + PR #50, and the `extract` check now keeps the platform's first error message. Pushed as `b4e839c` | 309 unit tests and 32 harness tests passed on Windows. On Linux (WSL, Python 3.12) the 32 harness tests passed. 5 unit tests failed there only because the test setup lent pypdf through `PYTHONPATH`, which the PDF worker drops by design. The intake code is unchanged since `ce6f312`, which passed 309 of 309 in the harness |
| 18 Nov, 20:30 | Tokens renewed on both systems. Login probe and read-only checks | Login ok on both, `Bill.submit` refused unsent. Mailbox: 1, threads 3, messages 3, attachments 0, on each system. Bills 382 and 104. 3 harness runs on record. No record changed |
| 18 Nov, 20:00 | Read-only recheck of both systems | Both API tokens rejected, so the mailbox, intake queue and harness run list could not be read. No record changed |
| 18 Nov, 19:50 | Local branches brought up to date. `seat29/document-reader` fast-forwarded to `4c0db14` and pushed to our fork | `29-document-intake/` matches `main` exactly. #50 differs from `main` only in `harness/` |
| 18 Nov, 17:10 | Priye opened PR #50 with only `harness/`, from fork branch `seat29/harness-checks`, to replace #44. Sudip approved it | Waits for Rohan. #44 still open, to be closed by Sudip |
| 18 Nov, 08:26 | **PR #11 merged into `main`** by the course team | Client, reader, vendor check and harness-copy write path are on `main` |
| 17 Nov, 17:58 | Rohan approved PR #11, and requested changes on #44: empty description, root harness file, size | #44 is replaced by #50 |
| 17 Nov, 09:24 | One sentence removed from this file, as Rohan asked on 13 Nov, commit `4c0db14` | PR #11 updated |
| 17 Nov, 09:32 | **Third harness run, commit `ce6f312`, 1,230 tokens** | 14 of 26, 7 of 13 on each system. Same passes as 10 Nov. All 20 sample downloads on the copy gave HTTP 404, and `extract` gave a tool error on all 20, so the reader, vendor, comparison and `accept` checks had nothing to run on. Bill counts unchanged |
| 12 to 16 Nov | Course team: mailboxes created on 12 Nov, PR #11 changes requested on 13 Nov, seat review set for 18 Nov. Sudip away 11, 15 and 16 Nov | The planned 13 Nov harness run and the 15 Nov hand-in are not recorded here |
| 11 Nov | Rohan answered the US vendor question | Compare the name only. Every US bill goes to a person, marked "tax id not checked" |
| 10 Nov, 15:20 | Harness fix pushed to `seat29/harness-setup-check` as `b81fca0`, and the docs brought up to date | 31 harness tests and 309 unit tests passed before the push |
| 10 Nov, 15:00 | Rohan's reply to the follow-up recorded | Harness copy writes allowed, separate harness branch fine, GSTIN check uses `gst_no` on Bills, mailbox accepted as a failure, PR #11 in his queue. Live drafts and Party records decided by 12 Nov. A follow-up on US tax ids was asked |
| 10 Nov, 12:00 | Harness fix, local only: the HTTP status is logged, a refused token is tried once without it, `extract` runs on every listed sample even if downloads fail, and `accept` uses the platform's values only when our reader had no files | 31 harness tests passed. Read-only dry run on live Suryodaya: same as before, 20 of 20 downloaded and matched. Not pushed |
| 10 Nov, 11:02 | **Second harness run, commit `f462dea`, 1,349 tokens** | 14 of 26, 7 of 13 on each system. Passed: setup, image reading (both colours right), 309 unit tests, 14 of 14 risky tools refused, Bill counts unchanged. Failed: all 20 sample downloads gave an HTTP error with no status kept, so the reader, vendor, `extract`, comparison and `accept` checks had nothing to run on. |
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
