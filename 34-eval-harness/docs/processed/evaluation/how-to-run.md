# How to run the eval harness (runbook)

> Set-up, everyday commands, how to add a task, and what to do when something goes wrong. Checked on 7 Nov 2026.

## 1. One-time set-up
1. **Install:** `uv sync` (this installs Python 3.11 and the packages from `uv.lock`).
2. **Create `.env`.** Copy `.env.example` to `.env` (it is git-ignored) and fill it in. Never commit it, and never share it:

| Variable | What to put | Used by |
|---|---|---|
| `AS_EMAIL` | your own seat 34 login (each person uses their own) | local runs only |
| `AS_SURYODAYA_PASSWORD`, `AS_KEYSTONE_PASSWORD` | your passwords, one per system | local runs only, to get a token |
| `AS_SURYODAYA_URL`, `AS_KEYSTONE_URL` | the two system web addresses | local runs only |
| `TOKEN_CACHE_DIR` | where cached tokens live; default `.cache/tokens` (git-ignored) | local runs only |
| `OPENAI_BASE_URL` | your model provider's OpenAI-compatible address (W&B: `https://api.inference.wandb.ai/v1`) | the agent |
| `OPENAI_API_KEY` | your provider's key | the agent |
| `OPENAI_MODEL` | one model, or a comma-separated list to try in order | the agent |
| `OPENAI_PROJECT_ID` | optional (W&B: `<team>/<project>`) | the agent |
| `OPENAI_EXTRA_BODY` | optional JSON object on **one line**, for example `{"chat_template_kwargs":{"enable_thinking":false}}`. It must be valid JSON: double quotes, lowercase `false`, every brace closed | the agent |
| `AGENTSWITCH_*` | **leave empty.** The course runner (on the platform) and `run_local.py` (on your PC) set these | the eval harness and the agent |

## 2. Run locally
```bash
uv run python scripts/run_local.py --instance keystone -- --suite suites/example
uv run python scripts/run_local.py --instance both     -- --suite suites/example --out runs/results.json
```
What happens:
1. **A token.** `run_local.py` gets a token for each system from the cache, or logs in once.
2. **The same start as the platform.** It sets the same variables the course runner sets, then starts `python -m eval_harness`.
3. **Where results go.** They land in `runs/results-<system>.json` (or `runs/<run_id>/results.json`), with one trial record per task in `runs/<run_id>/`.

Local runs use **live shared data**, so only read-only tasks are allowed locally.

**The token cache** (`scripts/local_auth.py`):
- **Reuse.** A cached token is reused while the platform still accepts it, for about 7 days.
- **Renewal.** When it no longer works, the script logs in **once** and saves the new token, readable only by you.
- **No retries.** A refused login stops the run, because ten wrong passwords lock the account for the whole team.
- **Starting over.** To force a fresh login, delete `.cache/tokens/<system>.json`.

## 3. What an official run does (on the course platform)
- **The runner file.** The course runner reads `agentswitch-harness.toml`:
  - install: `pip install uv && uv sync --frozen --no-dev`, while it still has internet;
  - run: `uv run --frozen --no-sync python -m eval_harness --suite suites/example --out results.json`, with no internet.
- **What it provides.** It sets `AGENTSWITCH_*` and `OPENAI_*` itself and uses a throwaway copy of one system. It allows one run every 3 days.
- **Before submitting,** do a local run first, every time.
- **Where the file goes (instructor, 13 Nov).** Each seat puts its own `agentswitch-harness.toml` at the root of the fork it submits; `main` has none. The runner reads only that root file, so its commands start with `cd 34-eval-harness &&`.
- **Several suites in one run.** The runner reads one `results.json`, and `eval_harness` runs one suite per call. `python -m eval_harness.run_all --suite suites/seat35 --suite suites/seat31 --out ../results.json` runs the suites in that order, each in its own process, and joins their rows into one file. A suite that leaves no results (for example it fails to load) becomes one infrastructure row, and the other suites still run.

## 4. Re-score without re-running
```bash
uv run python -m eval_harness.rescore runs/<run_id> --suite suites/example --out runs/<run_id>/rescored.json
```
This makes no model calls and no platform calls. Use it after changing a grader or the scorer. If a task's version changed, it prints a note.

## 5. Read a trial record
`runs/<run_id>/<system>__<task>__t0.json` holds:
- `manifest`: everything that can change a score (git commit, task version, graders, agent command, model);
- `targets`, `before`, `after`: the snapshots;
- `writes_since_start`;
- `agent`: exit code, seconds, the tail of its output, and its `AGENT_RESULT` line;
- `infrastructure`: why the trial could not run fairly, if it couldn't.

Reading records is how people check that a failure was fair. Keep failed and odd runs; never delete them.

## 6. When something goes wrong
| You see | It means | Do this |
|---|---|---|
| `stopped: … login refused` | wrong email or password in `.env` | fix `.env`. **Do not retry in a loop** |
| `infrastructure: login check failed: … 401` | the token no longer works | locally, run again (a fresh token is fetched); on the platform, tell the course team |
| `infrastructure: agent exited with code 4: settings problem: …` | an agent setting is missing or malformed (for example `OPENAI_EXTRA_BODY` is not valid JSON) | fix the named variable |
| `infrastructure: agent exited with code 3: model problem: every model failed …` | none of the models in `OPENAI_MODEL` answered | check the key, the model names and your provider's status |
| `infrastructure: agent timed out …` | the agent exceeded `task_minutes` | look at the output tail in the trial record |
| `python-dotenv could not parse statement starting at line N` | line N of `.env` is not `NAME=value` | fix that line (comments start with `#`) |
| `outcome=unevaluated` | a grader could not check (for example a record could not be read) | read the grader reason in `evidence`. It is never a pass |

## 7. Add a task or a suite (people only)
The course gives zero marks to tests written by AI tools, so **a person writes every graded task, by hand**.
1. Create `suites/<seat>/suite.toml` (copy the layout of `suites/example/suite.toml`), with `graded = true` and `agent = "<the seat's command>"` (see [agent-contract.md](agent-contract.md)).
2. For each task, fill in:
   - `id` (lower case; it becomes `<system>:<id>` in results);
   - `title`;
   - `kind` (normal, refusal, integrity or missing_resource);
   - `exercises` (what a failure would reveal);
   - `version` (raise it whenever you change the task);
   - `author` (your first name);
   - `targets`;
   - `prompt` (`{target_ids}` is replaced at run time);
   - `graders`;
   - `fails_if` (how this task could fail: try it).
3. Run it locally on both systems, and read the trial records.
4. If you ever relabel a task, add a line to `corrections`. Never change a label silently.

## 8. Add a grader (machinery; agents may help)
1. Add a function `(record, params) -> GraderResult` to `eval_harness/graders.py`, register it in `GRADERS`, and document when it fails.
2. Graders must read **only the trial record**. If a grader needs new data, the trial must capture it first (`eval_harness/trial.py`), so that rescoring still works without the platform.
3. Add a test in `tests/` with a hand-made record that makes it pass, and one that makes it fail.

## 9. Checks before a pull request
```bash
uv run ruff format --check && uv run ruff check && uv run mypy && uv run lint-imports && uv run pytest
```
