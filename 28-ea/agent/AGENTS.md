# Working on the EA agent

This guide is for developers and coding agents who change this code. Read it first. The README is for people who
run the agent.

## Rules that must not break

These come from the course rules in the top-level README and the agent contract in `34-eval-harness`. Every one of
them has tests, and a change that weakens one needs the team's agreement first.

1. **Never send, book, delete or change records.**
   - The only write is an unsent draft, through `McpClient.create_draft` with a fresh `mcp.Approval`.
   - `Approval()` is minted in one place only, `drafts.save_draft`.
   - Don't add tools to `mcp.WRITE_TOOLS` or `mcp.CREATE_ARGS`.
2. **Read tools are an allow-list (`mcp.READ_TOOLS`).** Before adding one, check that it only reads, and say why it
   is needed in the PR.
3. **Untrusted text stays data.**
   - Mail, and anything the model returns, goes to the model fenced (`drafts.fence`).
   - It is shown escaped (`briefing.plain`, `_clean`).
   - Code checks it before anything is saved (`injection_flags`, `draft_risk_flags`, `check_draft`).
   - Never let the model choose a tool or an argument.
4. **No secret in any output.** stdout, stderr, the briefing file and the JSON file are all redacted
   (`redact.py`, the final writes in `runner.py`). A new output path must go through the same redaction.
5. **Stay inside the limits.** Usage is monitored, and each platform call takes about 2 s.
   - The limits are `MAX_CALLS_PER_RUN`, `MAX_DRAFTS_PER_RUN`, the caps in `collect.py` and `slots.py`, and the
     model time limit.
   - Never page a list without a cap; use `mcp.list_capped`.
   - Say in the PR how many platform calls your change adds.
6. **Failure is never shown as "nothing".** A failed section says it could not load, mail the model did not reach
   says "not assessed", and a partial run exits 2. In harness mode it exits 0 and prints a `warning:` line.
7. **A harness run against a live system saves nothing** (`config.resolve`, `read_only`).

## Layout

| File | Job |
|---|---|
| `ea_agent/__main__.py` | Command-line flags |
| `ea_agent/config.py` | Settings from flags, the environment and the env file; harness mode |
| `ea_agent/auth.py` | Login, ready tokens, the 7-day token cache |
| `ea_agent/runner.py` | One run: systems in parallel, model calls, output files, exit code, `AGENT_RESULT` |
| `ea_agent/mcp.py` | Platform client: allow-list, write gate, call and draft limits, `list_capped` |
| `ea_agent/collect.py` | Reads mail, meetings and tasks, filtered to the user; time zone |
| `ea_agent/rules.py` | Mail that needs no reply, decided by fixed rules before the model |
| `ea_agent/drafts.py` | Model triage and prompt; draft checks; `save_draft` (re-check, create, read back) |
| `ea_agent/llm.py` | Model client: OpenAI-style or the gateway's `/chat`, retries, model list, deadline |
| `ea_agent/slots.py`, `ea_agent/rrule.py` | Free time slots; recurring events |
| `ea_agent/briefing.py` | Builds and renders one system's briefing; the status line |
| `ea_agent/review.py` | The `--review` prompt and editor |
| `ea_agent/redact.py` | Secret redaction |

One run works like this:

1. `runner.run` resolves settings with `config.resolve`.
2. For each system, `auth.connect` gives a client and the user.
3. `briefing.build_briefing` reads the sections with `collect.*`, sets aside rule-matched mail with `rules`, triages
   the rest with `drafts.triage`, and saves with `drafts.save_draft`.
4. `briefing.render_run` produces the Markdown.
5. `runner` writes the files and returns the exit code.

## Tests

```sh
python -m pytest tests -q            # from this folder; Python 3.10 and newer
```

- **Offline only.** Tests use `tests/fakes.py` (`FakeClient`, `FakeLLM`) and never touch the network.
  `tests/conftest.py` clears `AGENTSWITCH_*`, `OPENAI_*` and `EA_*` from the environment for every test.
- **Fakes must follow the write gate.** A fake platform must refuse writes in `call` and provide `create_draft`.
  Save tests must hold the original message, because saving reads it again.
- **Pin the clock.** Pass `now` and `--today` in every test. Two tests once broke because a draft said "Thursday"
  and the real date moved on.
- **Run both interpreters.** The suite must pass on Python 3.10 and on the newest Python before a PR.

## Making a change

1. Make a branch in your fork, and keep each PR to one topic.
2. Write the test first, and make sure it fails on the old code.
3. When you change a function, a settings key or a result key, search for every caller and update them all.
   Result keys like `needs_decision`, `summary` and `draft_saved` are read by `briefing.py` and the JSON output.
4. Update the README if a flag, setting or behaviour changes.
5. Live checks run only on our own `[team28a seed]` data. Don't touch data you didn't create.
6. Commit messages and PRs carry no tool attribution. The seat lead merges after one review, and nobody merges their
   own PR.
