# EA daily briefing (seat 28, v1)

A daily briefing for the logged-in user, for Keystone and Suryodaya in one run:

1. **Mail that needs an answer**: unanswered inbox mail from the last 14 days, each with a draft reply saved to
   Drafts. Mail that needs no reply is listed with the reason.
2. **Today's meetings**: the user's own events, recurring ones included, with declined, tentative, unanswered and
   clashing meetings marked.
3. **Overdue tasks**: the user's open tasks due before today.

It reads and drafts. It never sends, books, deletes or changes anything else.

## How it works

1. For each system: use the saved login if it still works, otherwise log in once. Find the user and their time zone.
2. Fetch meetings, overdue tasks and mail. Each is filtered to the user, because the login can see other people's
   data.
3. Code rules set aside mail that needs no reply (no-reply senders, newsletters, automated notifications). These are
   not sent to the model.
4. For the rest, one model call each decides whether a reply is needed and writes a draft. The model sees the email
   and up to 3 free 30-minute slots from the user's calendar (next 5 working days, 09:00–17:00), nothing else, and
   calls no tools.
5. Code checks every result: suspicious mail is flagged; risky drafts, and drafts with times or days not taken from
   your calendar or the email, are flagged and not saved; bad model output becomes "not assessed".
6. Save the clean drafts, print the briefing and write it to `briefings/briefing-YYYY-MM-DD.md`.

Systems run in parallel, and up to 3 model calls run at once: each platform call takes about 2 seconds.

## Run

Python 3.10+, standard library only.

```sh
python -m ea_briefing                               # every system with a saved login or a password
python -m ea_briefing --system keystone             # one system; asks for the password in a terminal
python -m ea_briefing --no-save                     # preview drafts, save nothing
python -m ea_briefing --review                      # approve, edit or skip each draft before it is saved
python -m ea_briefing --today 2026-11-06 --no-llm --json out.json
```

| Flag | Meaning |
|---|---|
| `--system NAME` | `keystone` or `suryodaya`; repeatable (`--instance` still works). Default: all with credentials |
| `--today` | Briefing date (default: today in each system's zone) |
| `--tz ZONE`, `--tz SYSTEM=ZONE` | Time zone for all systems, or for one (repeatable) |
| `--no-save` | Preview: drafts are shown, not saved (saving is the default; `--save-drafts` is accepted) |
| `--review` | After all mail is triaged, ask per draft: `[s]ave / [e]dit then save / [k] skip / [q] quit`. Needs a terminal. Edits use `$EDITOR`, or type the draft and end with a line holding only `.` |
| `--unread-only` | Only unread mail (default: unanswered mail, read or not, since opening a mail marks it read) |
| `--time-limit SECONDS` | Limit for all model calls, from start (default 60; review time does not count). Mail not reached says so |
| `--model-parallel N` | Model calls at once (default 3; 1 = one after another) |
| `--mail-cap N` | Most messages read per system (default 25) |
| `--out DIR`, `--no-file` | Where the Markdown file goes (default `./briefings`), or no file |
| `--json PATH` | Also write the combined run as JSON (`{"date", "systems": [...], ...}`) |
| `--no-llm` | Skip the model; mail is listed as "not assessed" |
| `--logout` | Delete saved logins and exit |
| `--env-file PATH` | Settings file (default `./.env`) |

Login: `EA_EMAIL` and `EA_PASSWORD_KEYSTONE` / `EA_PASSWORD_SURYODAYA`, or type the password when asked (never
echoed or stored). After a login the token is saved in `~/.config/ea-briefing/tokens.json` (owner-only; tokens last
7 days), so a daily run needs no password; `EA_TOKEN_CACHE` moves that file. On the course harness, `AGENTSWITCH_TOKEN` and `AGENTSWITCH_BASE_URL`
are used instead and nothing is saved (`--logout` does nothing there). Other settings: `EA_TZ` and `EA_TODAY` (as
`--tz` and `--today`), `EA_INSTANCE` (as `--system`), `EA_ENV_FILE` (as `--env-file`). Keep the settings file
outside the repo.

Time zone, first match wins: `--tz`, the zone of the user's own calendar, the system's default (Keystone
`America/New_York`, Suryodaya `Asia/Kolkata`). Each block says which zone it used and why.

Exit code: `0` all good, `2` the briefing printed but something failed (a login, a section, the model, a draft save,
the time limit, writing the Markdown or JSON file), `1` nothing could run (bad flags or settings, no system set up,
every login failed).

Tests: `python -m pytest tests` (offline, no network).

## Model settings

There is no default model. Without settings, mail is listed as "not assessed: no model configured".

| Setting | Meaning |
|---|---|
| `EA_LLM_URL` | Base URL of the model server |
| `EA_LLM_API` | `openai` (`POST /chat/completions`), `chat` (`POST /chat`, as glc), or `auto` (default: try `openai`, switch to `chat` on 404/405) |
| `EA_LLM_MODEL` | Model name; needed for `openai`, optional for `chat` |
| `EA_LLM_KEY` | API key, if the server needs one |

If `EA_LLM_URL` is not set, `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `OPENAI_MODEL` are used with `auto`.

```sh
# an OpenAI-compatible server
EA_LLM_URL=https://api.openai.com/v1 EA_LLM_API=openai EA_LLM_MODEL=gpt-4.1-mini EA_LLM_KEY=... python -m ea_briefing

# the course gateway glc (no key; the gateway picks the model unless EA_LLM_MODEL is set)
EA_LLM_URL=<glc base URL> EA_LLM_API=chat python -m ea_briefing
```

Busy servers (429, 5xx) are retried after 1, 2 and 4 seconds while time allows. A 503 that does not go away is
reported as "model unavailable": on glc that usually means an unknown model name.

## Safety

- **Allow-list.** Only 9 read tools and `EmailMessage.create` can be called, and the create only as a draft. Any
  send tool is refused before anything goes over the network.
- **Suspicious mail.** Prompt injection, phishing and payment requests are flagged by code, not just by the model.
  They are always shown with a warning, never set aside by a rule, and never get a saved draft.
- **Risky drafts are not saved**: links, money amounts, promises to pay, passwords or codes, and times or days not
  taken from your calendar or the email. A draft edited in `--review` goes through the same checks.
- **No invented facts.** The model may only offer the listed free times, and may not make up prices or answers or
  accept anything for the user. It leaves a `[placeholder]` instead.
- **No duplicates.** A second run finds the existing draft and does not create another.
- **Failure is never shown as zero.** A section that failed says "Could not load", a system that could not log in
  says so, and mail the model did not reach says "not assessed".
- **Secrets.** Passwords are never stored; tokens, passwords and keys are never printed. One login attempt per
  system per run, because ten wrong passwords lock the account.

## Known limits

- Sample mailboxes exist on Keystone only. On Suryodaya the mail section says "No mailbox is linked".
- The web app lists threads. Mail without a thread, and its draft, is invisible there, though the briefing reads it.
- Recurring events are expanded only from the user's own calendars. Rules with BYSETPOS, BYWEEKNO, BYYEARDAY or
  hourly parts are shown as "not checked".
- Newsletter and automated-mail rules rely on fields the current sample mail does not set, so the model still makes
  most "no reply needed" calls.
- Free times come from the user's own calendars only; other people's availability is not known.
- Free times are not offered if a calendar read hits its row cap (missing events could look free).
- The time check is a backstop, not a guarantee: unusual phrasings may slip through. Drafts are never sent, and you
  see every one.
- The agent cannot edit drafts: when a draft already exists, a newer suggestion is shown but not saved.
- Two mails with no message ids, from the same sender with the same subject, share one draft.
