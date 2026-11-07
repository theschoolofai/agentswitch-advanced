# Varun — seat 28 daily briefing

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
