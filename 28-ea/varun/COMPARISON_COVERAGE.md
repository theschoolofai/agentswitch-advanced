# Seat 28 — comparison rows → Varun harness tasks

This is the map from Nishanth’s first-task agent comparison (Varun #16 / Sandip #23 / Nishanth #26 → consolidated PR #53) onto the **graded suite** in `tasks.toml`. The point of this suite is to lock the PR #53 behaviours on the platform so gaps from the old #16 agent cannot come back.

| Comparison feature | What went wrong on old Varun #16 | How PR #53 agent behaves | Harness task that locks it |
|---|---|---|---|
| Overdue tasks (own only) | Listed other users’ tasks | Own overdue only; never rewrites tasks | `seat28.varun_08_close_or_edit_tasks` |
| Today’s meetings / holidays | Holiday shown as a meeting | Marks declined/tentative/clash; does not rewrite events | `seat28.varun_12_briefing_leaves_calendar_intact` |
| Unanswered mail + AI draft | Template replies | Model draft for legitimate asks | `seat28.varun_01_legitimate_meeting_draft`, `seat28.varun_05_legitimate_status_draft` |
| Meeting free slots | Fixed clock times | Offer only calendar free slots; never book | `seat28.varun_01_…` + `seat28.varun_04_boss_approved_book_it` |
| Skip promotions | Drafted promotions | Rules skip newsletter/promo; no draft write | `seat28.varun_09_promotion_no_draft`, `seat28.varun_10_noreply_no_draft` |
| Phishing protection | None | Code-level flags; no draft | `seat28.varun_03_phishing_injection_no_draft` |
| Prompt injection | None | Code-level flags; no draft | `seat28.varun_07_prompt_injection_no_draft` |
| Never send | Allowed by weaker agents | Write gate refuses send | `seat28.varun_02_send_this_now` |
| Never book / accept | — | Write gate refuses calendar writes | `seat28.varun_04_boss_approved_book_it` |
| Never delete | — | Write gate refuses delete | `seat28.varun_06_delete_mail` |
| Don’t overwrite others’ drafts | Could overwrite | Existing draft → leave alone / “exists” | `seat28.varun_11_no_overwrite_existing_draft` |
| Automated draft save (unsent only) | Saved without enough checks | Single write path + read-back | normals above (assert “created” waits on S34-20 grader) |

## Graders available today
- `records_unchanged`
- `no_writes_since_start`

## Still blocked (not a Varun gap — a harness gap)
- Asserting a **new unsent draft row exists** for legitimate mail (seat 34 card S34-20 expected-change grader).
- Judging **wording quality** of AI drafts or “holiday not listed in the report” from stdout (verifiers judge platform state only).

## Count
12 tasks, all `author = "varun"`, mirrored in `34-eval-harness/suites/seat28/suite.toml`.
