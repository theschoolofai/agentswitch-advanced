# AGENTS.md: seat 34 (Eval Harness)

These are the working rules for every person and every coding agent (Claude Code, Codex, Cursor, Copilot and others) in this folder. They are team rules. Personal preferences go in your own tool's local memory, not here.

Seat 34 builds the eval harness: hand-written test suites for the other seats' AI agents on the AgentSwitch platform. A test passes only when the platform's data shows the work was done. Background: [docs/processed/README.md](docs/processed/README.md).

## 1. Start of every session
1. Read [docs/processed/project/status.md](docs/processed/project/status.md) (the top entry) and [docs/processed/project/board.md](docs/processed/project/board.md).
2. Pick **one** card, or the one you were given. Do not start a second.
3. Work on your own branch, in your own folder (a git worktree if another session is active). Never share a folder or branch with another session.
4. Run `uv sync` once, if `.venv` is missing.

## 2. Boundaries
- **Edit only inside `34-eval-harness/`.** Never edit another seat's folder, or files at the repository root (`README.md`, `BUG_REPORT_FORMAT.md`, `.github/`).
- **Live platform data is read-only.** Any write needs approval first, recorded in the card. The seat lead approves a teammate's write, and a teammate approves the seat lead's. Whoever runs a write never approves it. Never delete, and never touch records we did not create. See the safety levels in [ways-of-working.md](docs/processed/ways-of-working.md).
- **Never commit:**
  - passwords, tokens, keys or `.env`;
  - platform source code, schemas or tool lists (they go in the git-ignored `data/platform/`);
  - customer records, run records or `results.json`;
  - anything from `docs/raw/`.
- **Never retry a refused login in a loop.** Ten wrong passwords lock the account for the whole team.
- **Platform specifics stay local.** Tool names, error codes, record counts, field lists, access details and exact replies go only in the local platform notes (`docs/processed/platform/`, git-ignored except its README) or in `data/platform/`. Committed pages describe them in plain, generic words. Shorten any id to 8 characters.
- **Be respectful.** Refer to people by role and by first name where a name is needed. No surnames, logins or contact details in committed files.

## 3. Verify, don't trust
- **Check before you rely on it.** Facts about access, blockers or platform behaviour must be checked live (`uv run python scripts/platform_sync.py`) before you rely on them. Docs, chat and old notes can be wrong. On 7 Nov, three of them were.
- **Write down the date.** When you record a fact, note the date you checked it and how.
- **Verifiers judge only the platform.** A verifier never reads or trusts the agent's answer: not its reply, report file, logs or claimed ids. It snapshots the records before the trial, reads the platform after it, and decides from what changed. Records the agent created are found through the platform's own fields (audit trail, `created_by` plus start time). See [principles.md](docs/processed/evaluation/principles.md).
- **Unevaluated is never a pass.** A trial that could not run fairly (timeout, bad login, blocked tool, budget) is an infrastructure failure, never a pass, and never silently dropped.

## 4. Tests are written by people
The course gives zero marks to tests written by AI tools. So:
- **Agents may only suggest.** Coding agents may write task *ideas* only, in [docs/processed/evaluation/ideas.md](docs/processed/evaluation/ideas.md).
- **People write the tasks.** A person writes every real golden task, expected result and verifier check by hand. Each task file names its author.
- **Agents may build everything else:** the harness machinery (platform client, driver, run records, scorer, history, scheduling), tests of that machinery, docs, and reviews.
- **Never change a test to make it pass.** No agent edits, weakens or deletes a golden task or verifier to make a run pass.

## 5. Coding practice
- **YAGNI and KISS.** Build only what a card needs, in the simplest form that works. No speculative options or abstraction layers.
- **DRY.** Keep business rules in one place. Copy-paste once is fine; the third copy becomes a function.
- **SOLID, where it helps.** Each module has one job, and parts depend on small interfaces (for example, verifiers depend on a read-only client, not on HTTP details). Do not add patterns that do not pay for themselves.
- **Clean code.**
  - Clear names.
  - Small functions that do one thing.
  - Type hints everywhere (`mypy --strict` must pass).
  - A short docstring saying *why*, when it is not obvious.
- **Use maintained libraries rather than writing your own:**
  - `mcp` (the official SDK) for MCP;
  - `httpx2` for REST;
  - `pydantic` and `pydantic-settings` for data and settings;
  - the `openai` SDK for model calls (added to `pyproject.toml` with the first card that needs it);
  - `asyncio` where calls can run side by side.

  Keep concurrency low, because the platform answers about one call per second.
- **Errors.**
  - Handle errors explicitly, with messages that say what failed and what to do.
  - No bare `except`, no silent `pass`.
  - A platform refusal can arrive inside a successful HTTP reply, so always check the reply body.
  - Every platform call has a time limit.
- **Security.**
  - Validate inputs at the edges.
  - Scrub tokens, passwords and keys from logs and records.
  - The platform client refuses non-read tools unless the card explicitly allows a write.
- **Tests.**
  - Add or update tests with every change. Unit tests make no live calls: use a small fake or stub in the test, until the shared fake platform (card S34-13) exists.
  - Live checks are separate, and opt-in.
- **Performance.** No premature optimisation. Measure first. Prefer fewer, larger reads.
- **Platform bugs.** Code that works around a platform bug is tagged `WORKAROUND(BUG-…)`, so it can be removed once the bug is fixed.

## 6. Commands
```bash
uv sync                      # install (Python 3.11, from uv.lock; the course runner uses --frozen)
uv run ruff format           # format (in CI or review: ruff format --check)
uv run ruff check            # lint
uv run mypy                  # type check (folders are listed in pyproject.toml [tool.mypy] files)
uv run pytest                # tests (no live calls; once a tests/ folder exists)
uv run python scripts/platform_sync.py  # live, read-only: re-read the platform and report what changed; needs .env
```
`ruff format --check`, `ruff check`, `mypy` and `pytest` must all pass before you ask for review. The platform helper scripts (`scripts/probe_access.py`, `scripts/platform_sync.py`, `scripts/platform_diff.py`) have no tests, by the seat lead's choice; check them by running them. When you add a new code folder, add it to `[tool.mypy] files` in `pyproject.toml`.

`.env` needs these names (see `.env.example`): `AS_EMAIL`, `AS_SURYODAYA_PASSWORD`, `AS_KEYSTONE_PASSWORD`, `AS_SURYODAYA_URL`, `AS_KEYSTONE_URL`. Each person creates their own `.env`; never share or commit it.

Run the sync after every platform release notice. Review `data/platform/changes-<date>.md`: new gaps become instructor questions or bug drafts, and changed access updates the local platform notes.

## 7. Planning practice
- **Cards.** Every piece of work is a card on [board.md](docs/processed/project/board.md) (`S34-NN | title | owner | milestone`).
  - Each card has a user story: "As a … I want … so that …".
  - Each card has acceptance criteria in Given/When/Then form, written before the code.
- **Done.** A card is done only when it meets the **definition of done** in [plan.md](docs/processed/project/plan.md).
- **Limits.**
  - At most one card in Doing per person.
  - Dates are fixed and scope can shrink. Cut nice-to-haves first, and never quietly drop agreed scope; write it down.
- **Decisions.** A lasting decision gets a short record in [docs/processed/decisions/](docs/processed/decisions/). Never delete one; replace it with a new one.
- **Risks.** New risks, blockers and questions go in [risks.md](docs/processed/project/risks.md), with an owner.

## 8. Git and pull requests
- Work on a fork, on a branch named `seat34/<topic>`.
- Use small pull requests (about 300 lines or fewer), one card each, titled `S34-NN: …`.
- Commit messages follow `type(seat34): summary`, where the type is `feat`, `fix`, `docs`, `test` or `chore`.
- One review from a teammate; the seat lead merges. Nobody merges their own pull request.
- Put the card number in the pull request title. A new card or bug gets the next free number (`S34-NN`, `BUG-34-NNN`), claimed in that pull request's title. Never reuse a number.

## 9. Bugs
The platform is still being developed, so expect bugs. The workflow is in [docs/bugs/README.md](docs/bugs/README.md).
- **Agents may draft only.** An agent may draft a report from [TEMPLATE.md](docs/bugs/TEMPLATE.md) in `docs/bugs/reports/` (git-ignored), with status **draft**.
- **People verify and file.** Only a person re-runs the steps, marks a bug **verified**, files it with the platform, and marks it **filed**.
- **Agents never file.** Agents never call the platform's bug-report tool or endpoint.
- **Before drafting,** check it is not by design (a seat-boundary refusal) and not already known.

## 10. Docs
- **Folders.**
  - `docs/raw/` holds pasted and fetched material. It is **local only** (git-ignored).
  - `docs/processed/` is the wiki: organised, checked, and committed. Its `platform/` pages are the exception and stay local.
  - `docs/bugs/` holds the bug workflow, template and index. Full reports in `docs/bugs/reports/` are local.
  - `data/` holds platform data. The live dumps in `data/platform/` are git-ignored; see [data/README.md](data/README.md).
- **Language.** Plain English that anyone can follow. Explain a special word the first time it appears, and add it to [glossary.md](docs/processed/glossary.md).
- **Size.** Keep pages short. Add only what someone will need. Update or delete facts that go stale, rather than piling up new pages.

## 11. End of every session
1. Leave the code runnable, with checks passing. Or say clearly in the handoff what is broken.
2. Add an entry at the top of [status.md](docs/processed/project/status.md): what changed, what's next, blockers.
3. Move your card on [board.md](docs/processed/project/board.md).
4. List the files you changed, and the commands a person should run to commit them.
