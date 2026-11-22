# Varun — seat 28 daily briefing

## Harness tasks (30 Nov suite)

Graded eval tasks authored by Varun: **12 tasks** in [`tasks.toml`](tasks.toml) — the full 30 Nov seat suite slice that locks PR #53 behaviours from the team comparison (drafts, send/book/delete, tasks, calendar integrity, phishing, injection, promotions, no-reply, no draft overwrite). Coverage map: [`COMPARISON_COVERAGE.md`](COMPARISON_COVERAGE.md). Mirrored in [`../../34-eval-harness/suites/seat28/suite.toml`](../../34-eval-harness/suites/seat28/suite.toml).

## First-task briefing script

`briefing.py` reads Suryodaya and Keystone and prints:

- unread inbox mail that is not a draft and not already answered
- one unsent draft reply for each of those messages, when the message has a mailbox
- meetings that overlap today in IST, excluding cancelled events
- open tasks whose due date is before today

Saving a draft is the default. The script never sends mail and never books a meeting. A meeting reply offers the next two weekday times, 10:00 or 15:00 IST, that do not overlap an existing calendar event. If it cannot find two free times, it does not invent dates. Pass `--read-only` to print proposals without writing drafts.

Tokens stay in this folder as `.token.suryodaya` and `.token.keystone`. The written briefing stays in `briefings/`. Both are ignored by `28-ea/varun/.gitignore`.

```bash
python3 28-ea/varun/briefing.py
python3 28-ea/varun/briefing.py --read-only
python3 -m unittest discover -s 28-ea/varun -p 'test_*.py'
```
