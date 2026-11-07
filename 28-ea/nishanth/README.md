# EA daily briefing (seat 28, v0)

A daily briefing for the logged-in user:

1. **Mail that needs an answer**: unanswered inbox mail from the last 14 days, each with a draft reply.
2. **Today's meetings**: the user's own events, recurring ones included.
3. **Overdue tasks**: the user's open tasks due before today.

It reads and drafts. It never sends, books, deletes or changes anything.

## How it works

1. Log in, then find the user and their time zone (from their own calendar).
2. Fetch meetings, overdue tasks and mail. Each is filtered to the user, because the login can see other people's
   data.
3. For each email, one model call decides whether a reply is needed and writes a draft. The model sees nothing else
   and calls no tools.
4. Code checks every result: suspicious mail is flagged, risky drafts are blocked, bad model output becomes
   "not assessed".
5. Print the briefing. With `--save-drafts`, save the clean drafts to the Drafts folder.

## Run

Python 3.10+, standard library only.

```sh
python -m ea_briefing --instance keystone                 # print the briefing
python -m ea_briefing --instance keystone --save-drafts   # also save drafts
python -m ea_briefing --instance keystone --today 2026-11-06 --no-llm --json out.json
```

| Flag | Meaning |
|---|---|
| `--instance keystone\|suryodaya` | Which system |
| `--today`, `--tz` | Briefing date and time zone (default: today, in the user's zone) |
| `--save-drafts` | Save drafts (off by default) |
| `--no-llm` | Skip the model; mail is listed as "not assessed" |
| `--json PATH` | Also write the briefing as JSON |
| `--env-file PATH` | Credentials file (default `./.env`) |

Settings: `EA_EMAIL`, `EA_PASSWORD_KEYSTONE`, `EA_PASSWORD_SURYODAYA`, and `OPENAI_API_KEY`, `OPENAI_BASE_URL`,
`OPENAI_MODEL` for the model. On the course harness, `AGENTSWITCH_TOKEN` and `AGENTSWITCH_BASE_URL` are used
instead of a login. Keep the credentials file outside the repo.

Exit code: `0` all good, `2` the briefing printed but something failed (a section, the model, or a draft save),
`1` it could not start.

Tests: `python -m pytest tests` (offline, no network).

## Safety

- **Allow-list.** Only 9 read tools and `EmailMessage.create` can be called, and the create only as a draft. Any
  send tool is refused before anything goes over the network.
- **Suspicious mail.** Prompt injection, phishing and payment requests are flagged by code, not just by the model.
  They are always shown with a warning and never get a saved draft.
- **Risky drafts are not saved**: links, money amounts, promises to pay, passwords or codes.
- **No invented facts.** The model may not make up times, prices or answers, or accept anything for the user. It
  leaves a `[placeholder]` instead.
- **No duplicates.** A second run finds the existing draft and does not create another.
- **Failure is never shown as zero.** A section that failed says "Could not load", never "nothing today".

## Known limits

- Sample mailboxes exist on Keystone only. On Suryodaya the mail section says "No mailbox is linked".
- The web app lists threads. Mail without a thread, and its draft, is invisible there, though the briefing reads it.
- Recurring events are expanded only from the user's own calendars, and only for daily, weekly and monthly rules.
  Other patterns are shown as "not checked".
- Drafts for questions the email can't answer are mostly placeholders. Using the calendar to suggest times is v1
  work.
