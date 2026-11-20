# EA agent (seat 28)

The seat 28 agent. One run gives the logged-in user a daily briefing for Keystone and Suryodaya:

1. **Mail that needs an answer.** Unanswered inbox mail from the last 14 days. Each email gets a one-line summary
   and, where a reply is needed, a draft saved to Drafts. Mail that needs no reply is listed with the reason.
2. **Today's meetings.** Recurring ones are included. Declined, tentative, unanswered and clashing meetings are
   marked.
3. **Overdue tasks.** Sorted by priority.

It reads, and it saves drafts. It never sends, books, deletes, or changes anything else.

Developers and coding agents: read [AGENTS.md](AGENTS.md) before changing code.

## Run

Python 3.10+, standard library only. Run these from this folder.

```sh
python -m ea_agent                        # every system with a saved login, a token or a password
python -m ea_agent --system keystone      # one system; asks for the password in a terminal
python -m ea_agent --no-save              # preview drafts, save nothing
python -m ea_agent --review               # save, edit or skip each draft yourself
python -m pytest tests                    # offline tests, no network
```

| Flag | Meaning |
|---|---|
| `--system NAME` | `keystone` or `suryodaya`; repeatable. Default: every system that is set up |
| `--no-save` / `--review` | Preview only, or approve each draft (`[s]ave / [e]dit / [k] skip / [q] quit`; needs a terminal) |
| `--today`, `--tz ZONE` or `--tz SYSTEM=ZONE` | Briefing date and time zone (default: today, in the zone of your calendar, else the system's own) |
| `--unread-only` | Only unread mail (default: unanswered mail, read or not) |
| `--mail-cap N` | Most emails read per system (default 25) |
| `--time-limit S`, `--model-parallel N` | Time limit for all model calls (default 60 s), and how many calls run at once (default 3) |
| `--out DIR`, `--no-file`, `--json PATH` | Where the Markdown file goes (default `./briefings`), no file, or a JSON copy as well |
| `--no-llm` | No model: mail is listed as "not assessed" |
| `--env-file PATH`, `--logout` | Settings file (default `./.env`); delete saved logins and exit |
| `--prompt TEXT` | Added by the course eval runner; accepted and not used |

Exit code: `0` all good. `2` the briefing printed but part of it failed. `1` nothing could run, for example bad
settings or every login failed.

## Settings

| Variable | Meaning |
|---|---|
| `EA_EMAIL`, `EA_PASSWORD_KEYSTONE`, `EA_PASSWORD_SURYODAYA` | Login. Without a password you are asked in a terminal. A login is saved owner-only in `~/.config/ea-agent/tokens.json` for 7 days (`EA_TOKEN_CACHE` moves it) |
| `AGENTSWITCH_KEYSTONE_TOKEN`, `AGENTSWITCH_SURYODAYA_TOKEN` | A ready token for one system, used instead of a login |
| `EA_LLM_URL`, `EA_LLM_API`, `EA_LLM_MODEL`, `EA_LLM_KEY`, `EA_LLM_EXTRA_BODY` | Model server. `EA_LLM_API` is `openai` (`/chat/completions`), `chat` (the course gateway's `/chat`) or `auto` (the default: tries `openai` first) |
| `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_API_KEY`, `OPENAI_EXTRA_BODY` | Used when `EA_LLM_URL` is not set. `OPENAI_MODEL` may be a comma-separated list, tried in order |
| `EA_TZ`, `EA_TODAY`, `EA_INSTANCE`, `EA_ENV_FILE` | The same as `--tz`, `--today`, `--system` and `--env-file` |

There is no default model. Keep the settings file outside the repository.

```sh
# the course gateway
EA_LLM_URL=http://127.0.0.1:8107/v1 EA_LLM_API=chat python -m ea_agent
# any OpenAI-compatible server
EA_LLM_URL=https://api.example/v1 EA_LLM_API=openai EA_LLM_MODEL=<model> EA_LLM_KEY=<key> python -m ea_agent
```

## Course eval harness

When `AGENTSWITCH_TOKEN` or `AGENTSWITCH_INSTANCE` is set, the agent follows the course agent contract
(`34-eval-harness/docs/processed/evaluation/agent-contract.md`):

- **Required settings.** It needs `AGENTSWITCH_TOKEN`, `AGENTSWITCH_INSTANCE` and `AGENTSWITCH_BASE_URL` together,
  plus `OPENAI_BASE_URL`, `OPENAI_API_KEY` and `OPENAI_MODEL`, unless you pass `--no-llm`.
- **One system only.** It reads the one system it was given, uses only that token, and reads no settings file or
  saved login.
- **Read-only on live systems.** If `AGENTSWITCH_BASE_URL` is a live system rather than a harness copy, drafts are
  previewed and nothing is saved.
- **Exit codes.** A briefing that ran exits `0`; anything that failed is named on one `warning:` line. With
  `AGENTSWITCH_RUN_ID` set, the last line is `AGENT_RESULT {"claim": ..., "steps": ..., "model": ...}`.

## Safety

- **Allow-listed tools.** The agent can call 9 read tools, plus one write: an unsent draft. Every other tool is
  refused before anything is sent.
- **One write path.** A draft is saved only through `create_draft`, with a fresh single-use approval and only draft
  fields. Just before saving, the original email is read again: if it was answered meanwhile, nothing is saved.
  Afterwards the new draft is read back. A write is never retried, and an existing draft is never replaced.
- **Limits per system per run:** 400 platform calls, 25 drafts, 60 s of model time.
- **Prompt injection, phishing and payment requests.** Code flags these, not only the model. Flagged mail is
  shown with a warning and never gets a draft.
- **Drafts that are held back.** A draft is shown but not saved if it contains links, money, promises to pay,
  passwords or codes, or times or days not taken from your calendar or the email. A model draft is also held back
  if it is over 120 words. A draft you edit in `--review` goes through the same checks, except the word limit.
- **No invented facts.** The model may offer only the listed free times. Anything only you know goes in a
  `[placeholder]`, so fill those in before you send.
- **Secrets.** Tokens, passwords and keys are replaced with `***` on screen and in every file. Briefing files are
  owner-only.

## Known limits

- Only Keystone has sample mailboxes. On Suryodaya the mail section says no mailbox is linked.
- The "needs your decision" mark is a keyword rule, so it is a hint, not a judgement.
- The time check on drafts is a backstop. In a sample it missed about 8% of invented times and wrongly flagged
  about 10% of good drafts.
- Recurring events are expanded only from your own calendars. Rare rule parts (BYSETPOS, BYWEEKNO, BYYEARDAY,
  hourly rules) show as "not checked".
- Platform calls take about 2 s each, so a run takes 25–55 s.
