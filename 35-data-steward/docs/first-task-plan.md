# First task plan: duplicate-party and duplicate-item report

Due 15 Nov 2026. Written 3 Nov; last updated 10 Nov with the instructor's answers, the Eval Harness seat's agent
contract, the steps left for 15 Nov and a version 1 plan.

## What we deliver

A read-only command that scans parties and items on one system and writes a report: one JSON file (the record of
truth) and a Markdown page made from it, both under `local/`, which is git-ignored because the report holds real
party data. Each proposal pairs two records, gives a confidence with the evidence behind it, suggests which record
survives, and lists what differs. Nothing on the platform changes and no record is created.

It runs on either system, one per run; both have been read. The report says which system it covers.

**Handed over on 15 Nov:** the merged pull request (code, tests, this plan), a summary with counts only in the pull
request description (rows read, proposals per band, exclusions per reason, no record data), the full report sent to
the seat lead directly, not through the repository, and the pair list in whatever form the grader reads (step 9).

## What the Keystone read showed

- Both tables are small, far under the 5000-row limit, and were read whole.
- Addresses and roles come back inside each party row, so they can be used without fetching records one by one.
  Item variants are always empty there.
- Every reference filter narrows both the rows and the reported total, so a reference count is a small read.
- There are almost no natural duplicates. The duplicates that exist are another team's test records, created again
  on each of their test runs, with nothing in common but a name and, mostly, a role. A shared bracketed test tag at the start
  of their names also makes different test records look alike.

The Suryodaya read (3 Nov) showed the same: both tables small and read whole, every reference filter narrowing rows
and total, no shared email, phone or code, and nothing proposed. A few same-name parties with different emails sit
in review. Its items do carry SKUs and variants, which Keystone's do not. (That was at rules version 2; version 3
adds a few Suryodaya pairs to review: see "Known gaps".)

So live data cannot tune or check the matcher. Made-up data does that instead: a tuning set and a separately written held-back set (steps 4, 4b and 7).

## Decisions

| Question | Decision | Why |
|---|---|---|
| Where proposals live | Local JSON plus Markdown. No platform records for 15 Nov. From version 1: one approval request per proposal, assigned to a named person, alongside the report. | The instructor (10 Nov) plans to grade the first task with no writes, and recommends the approval request as the proposal record, since the platform has no proposal entity. Our login has no tool that creates one directly, so how to create it is asked; until answered nothing is written. Creating a shared record needs the person's approval, and the publish step gets its own reviewed write path. |
| What a proposal is | Every listed pair, in the propose or the review band, gets a proposal in the report (survivor, differences). "Proposed merge" means the propose band only. | Which of the two become approval requests, and which the 15 Nov grader counts, is asked (see "Checks"). |
| How matches are found | Rules only: normalize, group by shared keys, score. No model. | The same data always gives the same result, it costs no tokens, it works offline, and a verifier can recompute it. The instructor (10 Nov) allows a model, not requires one, to understand requests and explain proposals, as long as the scoring rules stay fixed so confidences repeat. We plan to use one for the version 1 `--prompt` entry point only; it never touches matching or scores. |
| What confidence means | A score from 0 to 1 with the signals that produced it, and one band. **Propose:** 0.9 or more, with no conflict and no cap. **Review:** 0.6 to below 0.9, or 0.9 or more with a conflict or a cap (a conflict between strong values, a role difference, or party names that are only near). **Dropped:** below 0.6, whatever the conflicts; counted in the report, not listed. The band is the confidence; a capped pair keeps its full score (a pair can score 1.0 and be in review), so the score alone overstates a held pair. | It is a rule score, not a probability, and the report says so. The held-back set of made-up data gives how many in each band were right (step 7). Those figures come from made-up data that holds many duplicates, so the report says they do not predict how often a live proposal is right. Whether the grader reads the band or the number is asked. |
| Pairs or groups | Pairs. A record in two proposals is flagged so both are reviewed together. | A matches B and B matches C does not mean A matches C. |
| Pair identity | Party or item, plus the two record ids, sorted. The report is sorted by band, then pair id, so two runs with the same rows, date, labels and test tags write the same file. The id names no system, so the one labels file assumes the two systems never share a record id (not yet checked). | Review labels must still apply after the weights are tuned. |
| Survivor | Suggested, never decided: more references, then older, then more fields filled, then the first id in text order ("10" before "9"). If either side's reference count is unknown, the reference step is skipped and the report says so. | A person makes the call. The rule is printed so they can overrule it. |
| How a person acts | They mark each pair accepted or rejected in a labels file in `local/` that the command reads but never writes. Labels are shown beside each pair and never change its score, band or survivor. Accepting records intent only. Any change to a record is made by a person, through the platform, with approval. | There is no merge tool, and the agent never changes a record. |
| Write guard | Done (step 1). `McpClient.call` loads the tool list once and allows a tool only when it is on that list and marked both read-only and non-destructive. Every other tool is refused before anything is sent. Retries follow the same decision instead of the tool's name. | The login can see update tools for parties and items, and they are not marked destructive. Making the client refuse them is safer than relying on care. |

## Signals

An empty value never counts as a match, and neither does a placeholder such as "N/A" or a dummy phone number shared
by many records. A conflict between two filled strong values caps the pair at review.

Two limits are part of the frozen rules. A strong value (email, phone, code) held by more than 5 records is treated
as shared, not as an identity. A grouping key held by more than 50 records is too common to group on, so those
records are not compared through it (51 records with one identical name and nothing else shared give no pair); the
report counts the keys skipped. On the saved reads, comparing every pair found nothing grouping missed (see "Known
gaps"), but that is not a guarantee for larger tables.

- **Parties.** Strong: the same customer code, the same email, the same phone (at least 10 digits). Weaker: the same
  name after normalizing (case, spacing, punctuation, legal endings such as Pvt Ltd or Corporation), the same website,
  the same address city and postcode.
- **Near names.** Two normalized names with a similarity of 0.9 or more (Python's `SequenceMatcher` ratio; about a
  letter or two apart) count as much as the same name for parties (for items, a little less: see Items), so a
  duplicate that differs only by a typo reaches review, once
  the two records meet in grouping (a shared word of three letters or more, or a shared key: a typo in a one-word name
  with nothing else shared is never compared). A party pair whose names are only near is held at review, because two
  people a letter apart can share a household email or phone, unless the two share a customer code, which belongs to
  one customer.
- **Items.** Strong: the same SKU or code. Weaker: the same name after normalizing, the same category and unit of
  measure (not weight unit). Since rules version 3 (6 Nov, after the first held-back run): item names are split
  wherever a digit meets a letter, so a size or model is the same however it is spaced ("25mm" and "25 mm", "MX200"
  and "MX 200"); the same item name alone reaches review, even with
  different codes, because a re-entered item usually gets a new code; a near item name reaches review with a
  shared unit, because about half the live items have no category; and one name that is the other with words
  added, such as a brand in front, counts as a near name when the shorter has three different words or more and no
  added word holds a digit. The digit check applies only to that last rule: names a letter apart are still near by
  similarity, so size variants ("M6" and "M8") and a long name with a short number added go to review, where a person
  rejects them. Because words are sorted, a split can also make different sizes look the same ("2.5mm" and "5.2mm",
  "AB12" and "12AB"); those reach review too. No item reaches propose without a shared code.
- **Test tags.** Only the test-run tags found in the read, listed in `local/`, are removed from the start of a name
  before names are compared, so a shared tag adds nothing to the score. Any other bracketed prefix is part of the
  name and is kept. Tags never exclude a pair or keep it out of grouping, and the report keeps the original names. A
  pair where either name carried a test tag keeps its score and band but is shown under its own heading, and is left
  out of the band totals in the pull request summary. The report says where the tag came from (on Keystone, another
  team's test runs) only as far as the read showed it. The tags file is git-ignored and never hard-coded, so under
  the harness runner there is none: tagged pairs then show as ordinary pairs and their names keep the tag. Whether
  that is acceptable for grading is asked.
- **Tax numbers (not used).** GST number, PAN and tax id are empty on every party on both systems (3 Nov reads), so
  none is a signal. Adding one later is a rules change and needs a new held-back set.
- **Known gaps (checked on the saved reads, 5 Nov at rules version 2 and 6 Nov at version 3).** Comparing every
  pair instead of only grouped ones finds no extra pair on either system, so grouping loses nothing on live data
  today. What the rules do not catch:
  - spelling variants further apart than a letter or two, such as Lakshmi and Laxmi (0.67 as one word, 0.86 in
    "Lakshmi Traders" and "Laxmi Traders"), which fall below the 0.9 cut;
  - item abbreviations ("SS" for stainless steel) and initials in party names ("R. K." for two first names);
  - a brand-prefixed item name whose shorter form has fewer than three words, or whose added words hold a number
    and are long enough to keep the names under 0.9 alike;
  - a party name with a bracketed prefix that is not a confirmed test tag, such as "[OLD]", kept by design;
  - a one-word name against the same name with a copy number ("Acme" and "Acme (2)"): the copy number is kept as a
    word, so the names are not near and the pair is dropped. Longer names with a copy number reach review at 0.6;
  - a name whose accented letters were garbled by a wrong character encoding (second held-back run);
  - city and postcode are compared on each party's first address only.
  Rules version 3 brings to review one Suryodaya item pair that a person should judge (names 0.89 alike, one with a
  brand prefix, different codes, created minutes apart) and three other near-name pairs there, all for a person to
  check; it adds nothing on Keystone (saved 3 Nov reads, 6 Nov). The details are in `local/`.

## Never proposed

A pair caught by one of these never becomes a proposal. It is listed in its own section of the report, with the
reason, when it scored 0.6 or more; below that it is only counted as dropped.

- Either party is flagged as an allowed duplicate.
- Either party's privacy state is anything other than the ordinary one, or missing. These parties are counted and
  left out before grouping, so no detail of theirs reaches a pair. The ordinary state's name is in the code; the
  others are noted in `local/`.
- Both records carry a company id and the ids differ. A missing company proves nothing either way.
- Different party types, such as an individual and an organisation.
- Items of different kinds or different units of measure. When an item lists variants, also variants of one item.

Parties whose active roles differ (for example a customer and a supplier, or an employee and a customer) stay in
**review** at most. A person decides whether one party should hold both roles. A party with no active role has no role
evidence; that alone is not a role difference.

## Reference counts

For proposed pairs only, count the records that point at each side: orders, payments, ledger entries, leads,
deals and relationships for parties (every link to the party, from either side), and stock movements for items. A
count that could not be read is **unknown**, never zero. Each count is the number of filtered rows, read page by
page until an empty page; the reported total is not used, since a system may report the whole table's total or cap a
page below the limit asked for. A row that does not carry the filter value means the filter was ignored, and the
count is unknown, as it is for a row seen twice, more than 5000 rows, an error or a dropped connection. An unknown
count makes the survivor rule skip the reference step and say so. Either way, matching goes ahead.

## Build order (about 27.5 hours)

| # | Step | Hours | Status or needs |
|---|---|---|---|
| 1 | Write guard, with offline tests: an update refused, a delete refused, a list allowed, an unknown tool refused | 2 | done |
| 2 | Ask the Eval Harness seat what they will check, and whether their copies of the systems hold seeded duplicates. Get the person's approval for the Keystone reads. | 0.5 | done: approval given 3 Nov; answered 10 Nov by the instructor (see "Checks") |
| 3 | Keystone read: counts, both tables into `local/`, filter checks, child rows, what duplicates look like | 2 | done |
| 4 | `data_steward/dedupe.py`: normalize, group, score, exclusions, with tests on hand-made pairs. A made-up tuning set of parties and items with known duplicates and known non-duplicates. It covers typos, case and spacing, legal endings, phone formats, the same email under two names, records sharing a name prefix that are different, ordinary names that start with a bracketed prefix, different records sharing a city and postcode, items with near names and different codes, role differences, and repeated test records. Run from grouping to report, so a duplicate the grouping never finds shows up as a miss. Every value is invented, test tags included (tests pass their own tag list); nothing is copied from a live record. | 8 | done |
| 4b | The other person on the seat writes the held-back set (see "Held-back set" below) the same way, with no entity shared with the tuning set, commits it, and does not tune. The person tuning does not open it until step 7. | (in 4) | done: two sets |
| 5 | Proposals: survivor suggestion, field differences, reference counts | 4 | done |
| 6 | JSON and Markdown report and the `python -m data_steward.dedupe` command. Under the harness runner the instance comes from the runner. The report states rows read, whether any table was cut off, and that an incomplete scan does not mean there are no duplicates. | 3 | done; run on both systems 3 Nov |
| 7 | Tune the weights and the 0.6 and 0.9 cuts on the tuning set, then freeze the whole matcher (code and settings, by commit) before opening the held-back set. Run once on the held-back set and report how many examples each band had, wrong proposals and known misses, as a check on made-up data only. Any later change that can affect which pairs are found, their scores, bands or exclusions voids that check and needs a new held-back set from the other person. Run on Keystone; one person and the seat lead review every pair it reports. | 2 | rules version 2 frozen 3 Nov and checked once 6 Nov; rules version 3 frozen at `457799b` 6 Nov and checked once 9 Nov on a new set (see "Held-back runs") |
| 8 | README and AGENTS.md updates, pull request, review | 2 | pull request open, review requested |
| 9 | Grader output, by 12 Nov. The command accepts `--prompt` and ignores its value (no model), so a harness run does not fail on an unknown argument, and runs the same scan. It writes the pair list in the form the grader reads: pair id, the two record ids, score and band, no names or other record data. Until the format is known, build a plain JSON list and adapt it to the answer. Output only: rules version 3 is untouched. | 2 | waits on the grader's format |
| 10 | One rehearsal harness run by 12 Nov, only if the grader is the harness and only with the person's approval, so the first run is not the graded one (one run per seat every 3 days). | 0.5 | step 9 |
| | Buffer | 1.5 | |

**Not for 15 Nov:** a model in the loop, platform records, merges, missing-field
and orphan checks, and the 12-task suite (30 Nov).

## Version 1 (30 Nov)

Every task in the suite passes only on platform state after the run, so version 1 needs a proposal record on the
platform. The matcher stays at rules version 3.

| # | Step | Hours | Needs |
|---|---|---|---|
| V1 | Decide the proposal record by 17 Nov: an approval request if the instructor says how our login creates one; otherwise ask whether one escalation per proposal (see "Escalations") is acceptable, and build that only on a yes. Also settle which pairs qualify: the propose band only, or review pairs too. | 0.5 | instructor's answer |
| V2 | Publish path: one record per qualifying pair, naming both records, the band, the score and the suggested survivor, assigned to a named person. Its own reviewed write path; the write guard stays as it is for every other tool. Offline tests: a record per pair, nothing sent when no assignee exists or the person has not approved, no update or delete ever called. Nothing live without the person's approval. | 6 | V1 |
| V3 | `--prompt` entry point with a model: it reads the request and picks the action (duplicate report, missing fields, orphans, publish); the fixed rules do the matching and scoring. Under the runner, it uses the runner's `AGENTSWITCH_*` and `OPENAI_*` values. | 4 | step 9 |
| V4 | Missing-field check: required fields from the schema endpoint (answer 3), saved to `local/`. A field the platform fills another way (full name filled while first and last are empty on individuals) is reported as that platform gap once, not as each party's own gap. | 4 | schema read approved |
| V5 | Orphan check: for each link field from parties and items, a row whose target does not exist. A target table that could not be read whole makes the result unknown, never an orphan. The cause is the known missing link check; not filed again. | 4 | |
| V6 | The 12-task suite in the harness format, on both systems, each task checking platform state. Written by hand until question 6 is answered. | 6 | V2 to V5 |
| | Buffer | 2 | |

Question 7 (tracing damage to the job that caused it) stays out of version 1 until answered.

## Held-back set (step 4b)

The one honest check of the matcher: data the tuner never saw, run once against the frozen rules. Two sets so far,
both by Dheeraj and kept in `tests/data/`: `dedupe_heldback.json` checked rules version 2, and
`dedupe_heldback_v3.json` checked rules version 3 (frozen at `457799b`). Both have now been seen by the person
tuning, so any rules change that can affect pairs, scores, bands or exclusions needs a third set, with no entity
shared with the tuning set or the first two.

**Who:** the other person on the seat (Dheeraj), not the person tuning (Pravin).

**A third set, only if the rules change:** a new file such as `tests/data/dedupe_heldback_v4.json` (never
overwrite an earlier set), in the layout of `tests/data/dedupe_heldback_v3.json`, with every value invented and no
name, email, phone or code shared with the tuning set or the earlier sets. Every party has `privacy_state` set to
the ordinary state (a missing one is withheld). Label pairs both ways (`duplicates` and `distinct`), cover the cases
in step 4 and the exclusions under "Never proposed", and include cases you think the rules get wrong. Write it from
the plan, not the code; do not run the matcher on it or change it after seeing a result.

**How it is run (step 7):** once, at the frozen commit, with `dedupe.find_duplicates` and `dedupe.evaluate` on each
table. The result is recorded with the commit: how many pairs each band held and how many were right, wrong
proposals, known misses, and exclusions. These are figures from made-up data and do not predict how often a live
proposal is right. Any later change that can affect pairs, scores, bands or exclusions voids the check and needs a
new held-back set.

### Held-back runs

#### First run (rules version 2, 6 Nov)

Run once at `ef06658` on Dheeraj's set (commit `538cca6` on his fork; 84 parties, 63 items). Made-up data with many
duplicates, so these figures do not predict how often a live proposal is right.

| | Known duplicates | Propose (right / wrong) | Review (right / wrong) | Missed | Excluded duplicates |
|---|---|---|---|---|---|
| Parties | 31 | 5 / 0 | 22 / 10 | 4 | 0 |
| Items | 26 | 3 / 0 | 6 / 5 | 17 | 0 |

The 17 item misses: 12 pairs with the same name and a shared unit but different codes (0.55, dropped; 10 of them
repeated test-run records), and 5 whose names differ by spacing, an abbreviation or a brand word (0.15). Rules
version 3 answers the first group and the spacing and brand cases; abbreviations remain a gap. The 4 party misses
are in "Known gaps". Wrong review pairs were mostly two names sharing one email. The tuning set gained 9 items for
version 3 (written by the person tuning, not copied from the held-back set); on it version 3 proposes 2 right and
no wrong, and reviews 5 right and 1 wrong (a name with one word added, the cost of the containment rule).

#### Second run (rules version 3, 9 Nov)

Run once at `457799b` on Dheeraj's second set (commit `0084782` on his fork; 98 parties, 72 items; no name, email,
phone or code shared with the tuning set or the first set). The commits after `457799b` and before the run changed
only this plan.

| | Known duplicates | Propose (right / wrong) | Review (right / wrong) | Missed | Excluded duplicates |
|---|---|---|---|---|---|
| Parties | 36 | 8 / 0 | 23 / 10 | 5 | 0 |
| Items | 28 | 3 / 0 | 22 / 13 | 3 | 0 |

- **Missed.** Items, 3: abbreviations and units written differently ("Three-Quarter Inch" and "3/4 in", "Galv" and
  "Galvanised", "1kg" and "1000 g"). Parties, 5: a one-word typo name never compared, "Lab" and "Laboratory" with a
  7-digit phone, an "[OLD]" prefix, initials ("S. P." and two first names), and a name whose accented letters were
  garbled by a wrong character encoding. All but the last are in "Known gaps"; that one is added here as a gap.
- **Wrong in review.** Items: 9 of 13 are sizes or ratings of one product (150mm and 200mm, 5L and 2.5L, 230V and
  110V), the accepted cost of rules version 3; 3 are numbered test fixtures ("Fixture Item 3" and "4"); 1 is two
  different products sharing a code. Parties: mostly two names sharing one email, as in the first run.
- **How far this goes.** This set covers the same kinds of cases as the first, often case for case, and rules
  version 3 was written after seeing the first set's misses. So these figures are likely kinder than a set of new
  kinds of cases would be. No wrong proposal in either run (11 of 11 proposals right on the second set), but that
  rests on few proposals. Made-up data: they do not predict how often a live proposal is right.

## Checks that could change this plan

- **Seeded duplicates.** Answered 10 Nov by the instructor: the data has a few natural look-alike parties and no
  planted answers, so we keep building our own fixtures (the tuning and held-back sets). A harness run writes to a
  copy and discards it.
- **The Eval Harness seat's agent contract.** Read 10 Nov in their pull request (#21,
  `34-eval-harness/docs/processed/evaluation/agent-contract.md`, not yet merged). Their harness runs one command per
  request with `--prompt "<request>"` added, passes the runner's `AGENTSWITCH_*` and `OPENAI_*` values, and judges
  only the platform state after the run; a local report file cannot be graded. A non-zero exit is an
  infrastructure failure, and an optional last line `AGENT_RESULT {...}` is scored for honesty, never for pass or
  fail. What it means here: our code already uses the runner's token and never logs in under the runner, but the
  command rejects `--prompt` today (it accepts only `--instance`), which would end a harness run with a non-zero
  exit. Step 9 makes it accept and ignore the value for 15 Nov; the model behind it is version 1 (V3).
- **What the course harness checks.** Read 7 Nov: `../34-eval-harness/TASK_FORMAT.md`, written by the Eval Harness
  seat, says a task passes only when a check on the resulting data confirms it, never because of the agent's wording.
  A report in `local/` is not platform data, so no task can pass on it alone; version 1 needs the publish path (V2).
  The instructor's plan for 15 Nov (10 Nov, to be confirmed in the seat channel before then): a harness task is
  judged on the correct duplicate pairs found against a labelled set, with a confidence for each pair and no
  writes. With no writes, the pairs must reach the grader some other way than platform state. Asked, to settle
  before step 9:
  - Which output does the grader read: a printed list in a set format, a results file, or another form?
  - Do review pairs count as found pairs, and are wrong pairs penalised? On the second held-back run, the propose
    band alone found 8 of 36 party duplicates, and party review pairs were right 23 times in 33 and item review pairs 22 in 35.
  - Is the confidence the band or the score? A held pair can score 1.0 and still be in review.
  - Who labels the set, on which system, and do repeated test-run records count as duplicates? Under the runner
    there is no test-tags file, so tagged pairs show as ordinary pairs.
  If the grader reads platform state after all, that conflicts with "no writes" and goes back to the instructor.
- **Questions for the instructor.** Drafted 7 Nov; record the answers here and change the plan to match. Answers to
  1 to 5 came 10 Nov; where the brief is silent the instructor marked the answer "recommended". 6 and 7 are still
  open.
  - Answer 1: one approval request per merge proposal, assigned to a named person (recommended). The platform has
    no proposal entity; the approval request is its human-in-the-loop item. Whether our login may create one was
    not checked by the course team. A read-only probe on 10 Nov found no tool that creates one directly on either
    system. Some agent records refer to one, so the platform may create it itself when an agent action needs
    approval (field names in `local/tools-<instance>.json`). Asked how seat 35 should create one; until answered,
    no write is made. Escalations (below) are a candidate fallback, not yet agreed (V1).
  - Answer 2: a few natural look-alike parties and no planted answers; build our own fixtures.
  - Answer 3: use the fields the schemas declare as required (recommended). This matches "Where required fields
    come from" below.
  - Answer 4: a report plus the approval request is enough; a UI is optional.
  - Answer 5: a model may understand requests and explain proposals; keep the scoring rules fixed so confidences
    repeat.
  - Also answered (to the seat lead): the platform does not lower-case party names when they come in, and no
    change is planned. Compare on a normalised key and leave stored values unchanged. `norm_name` already does this
    (lower case, trimmed, punctuation and legal endings such as Pvt Ltd dropped, plus accents and word order).
  Still open:
  6. The capstone brief for teams 01 to 27 says a test written by Claude or Codex scores zero. Does that apply to
     the Advanced seats' 12-task suite? If it does, the suite's tasks and checks are written by hand by this seat.
     (Session 20 states the rule for the core seats; until answered, assume it applies here too.)
  7. Session 20 described seat 35 as watching shared data for damage and naming its source through the audit trail,
     using only invariants that already exist. The 2 Nov brief describes duplicates, missing fields and orphans. Is
     tracing a problem to the job that caused it part of version 1, of the final, or no longer in scope?
- **Where required fields come from.** Read 7 Nov in the capstone brief: the platform's schema endpoint lists every
  entity's fields, types and which are required. The missing-fields check reads that list for parties and items
  instead of choosing fields by hand. What the endpoint returns is platform-derived and goes in `local/`, never in
  the repository.
- **Escalations as the proposal record.** A candidate fallback, used only if the instructor agrees (V1): the
  instructor recommends approval requests (answer 1).
  Seen 7 Nov in another seat's public repo (`mkthoma/files_agent`, the Files
  seat): its agent hands each case to a named person by raising an agent escalation, and its harness checks those
  escalations. The tool list this seat's probe saved on 6 Nov holds the same raise, assignee and escalation read
  tools on both systems (names in `local/tools-<instance>.json`). One escalation per merge proposal, naming both
  records, the confidence and the suggested survivor, would give the harness a record to check while the merge
  itself stays with a person. Two cautions from that repo, both from October and to be checked again: a raise needs
  a person from the assignee list, and when that list is empty nothing is sent (the course staff called recording
  that the expected behaviour); and each raise opens its own agent session. Raising is a write, so it gets its own
  reviewed path and the person's approval before any live run. That repo has no license and commits platform data:
  read it for ideas, never copy its code or data.
- **The Directory seat's dedupe.** Read 7 Nov (`varunsood189/A27-directory-agent`, no license, commits run files
  from live data: read for ideas only). It drops a trailing copy number such as "(2)" before comparing names. What
  it means here:
  - Copy numbers. In the saved Suryodaya read (6 Nov), 8 parties end in a copy number, each beside a record of the
    same plain name; our report finds all 8 in review at 0.6. A one-word name with a copy number would be missed
    (see "Known gaps"). Stripping copy numbers is a candidate for rules version 4, which needs a new held-back set.
  - Never link two parties with a relationship as a proposal record: it adds rows to shared customer data and puts
    nothing in front of a person.
  - Its bug list (late September, recheck before relying on it) bears on the missing-fields and orphan checks. On
    Suryodaya, first and last name are empty on individuals while the full name is filled, so a missing-fields
    check must not report that as each party's own gap. On Keystone, filtering parties by customer type returns
    none although some hold the customer role. Also on Keystone, sending the relationship list's default filter
    hides every relationship. These are filed already; do not file them again.
- **Session 20 (the capstone platform lesson).** Read 7 Nov. What bears on this seat:
  - The audit trail. The seat was first defined as attributing damage to the job that caused it, naming no source
    the log does not support (question 7). The 6 Nov tool lists hold read-only agent job and job ledger tools on
    both systems that could do this.
  - Orphans have a known cause: the platform does not check that a link field points at an existing record, and
    accepts the row. The orphan check can name that as the cause; it is a known defect, so it is not filed again.
  - Both jurisdictions are graded, and the lesson says an agent should read its company's locale (a read-only tool
    every seat has) rather than assume GST. Not built: rules version 3 uses one fixed list of legal endings and the
    last ten phone digits, and reads no locale. Making them follow the locale is a rules change (new held-back set);
    decide in version 1 only if a graded task needs it.
  - Agent records mostly have no per-team owner, so any escalation this seat raises carries a seat 35 prefix and
    the seat only ever reads or acts on its own.
