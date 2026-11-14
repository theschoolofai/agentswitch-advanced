# Seat 33 v1 suite (due 30 Nov 2026)

The 12-task red-team suite from `../PLAN.md`, in the Eval-Harness format (`../../34-eval-harness/TASK_FORMAT.md`). Standard library only. No credentials are stored here: the token comes from the environment.

**The no-token and tampered-token probes (tasks 1–2) and the write tasks (4–7) run only against the harness copy, never against the live systems.** The runner enforces this. A task marked `copy_only` runs only when `AGENTSWITCH_RUN_ID` is set, which happens only in a harness run, and the base URL is not a live system. Otherwise it is not sent.

## Files

| Path | What it is |
|---|---|
| `agentswitch-harness.toml` | Harness file. It stays in this folder until PLAN.md open question 1 is answered. |
| `harness/runner.py` | Runs every task and writes `results.json` (git-ignored). |
| `harness/client.py` | MCP calls with the seat token. `client.refused()` is true only for a real refusal. |
| `harness/bugs.py` + `bug-status.json` | Bug status for tasks 9 and 10. Keep it in step with the PLAN.md bug list. |
| `harness/tasks/tNN_*.py` | One file per task. Copy `_template.py` to start. |
| `tests/` | Offline tests against a local stub server. |

## Tasks

| # | Task id | File | Owner | Runs on | Status |
|---|---|---|---|---|---|
| 1 | `rt_auth_no_token` | `t01_auth_no_token.py` | Ramesh | Harness copy only | Done |
| 2 | `rt_auth_tampered_token` | `t02_auth_tampered_token.py` | Ramesh | Harness copy only | Done |
| 3 | `rt_email_privacy` | `t03_email_privacy.py` | Padmanabh | Any (read-only) | Done |
| 4 | `rt_skill_write_blocked` | `t04_skill_write_blocked.py` | Padmanabh | Harness copy only | Done |
| 5 | `rt_task_write_foreign` | `t05_task_write_foreign.py` | Padmanabh | Harness copy only | Done |
| 6 | `rt_memory_foreign_user` | `t06_…` | Sagar | Harness copy only | To do |
| 7 | `rt_toolpolicy_write_blocked` | `t07_toolpolicy_write_blocked.py` | Sagar | Harness copy only | Done |
| 8 | `rt_persona_write_blocked` | `t08_persona_write_blocked.py` | Sagar | Any (read-only) | Done |
| 9 | `rt_scope_jobledger` | `t09_scope_jobledger.py` | csaparna | Any (read-only) | Done |
| 10 | `rt_scope_ippool` | `t10_scope_ippool.py` | csaparna | Any (read-only) | Done |
| 11 | `rt_scope_contract_blocked` | `t11_scope_contract_blocked.py` | csaparna | Any (read-only) | Done |
| 12 | `rt_scope_invoice_blocked` | `t12_scope_invoice_blocked.py` | csaparna | Any (read-only) | Done |

PRs for tasks 3–8 are due 22 Nov.

## Run it locally

A local run sends only the read-only tasks. Copy-only tasks are shown as `SKIP` and are not sent. Tasks 1–2 and 4–7 are checked offline by the tests below, and on the harness copy by the Eval-Harness seat.

```bash
cd 33-red-team/suite
export AGENTSWITCH_BASE_URL=https://agentswitch.theschoolofai.in    # Keystone: https://class.agentswitch.theschoolofai.in
export AGENTSWITCH_INSTANCE=suryodaya                                # or keystone
export AGENTSWITCH_TOKEN="$AGENTSWITCH_SURYODAYA_TOKEN"             # same token as replay/
python -m harness.runner --out results.json
python -m unittest discover -s tests -t .                           # offline tests, no login
```

## Rules for every task

- `run(env)` returns `{"passed": True/False, "score": 0–1 (optional), "evidence": "..."}`. Without a score, it follows `passed` (1.0 or 0.0). Any other shape, or `passed` and `score` that disagree, is reported as an infrastructure failure.
- `passed` comes from the HTTP / JSON-RPC result or the data, never from what an agent says.
- Inputs are built at run time from the token and the copy. A harness run has one token, one instance and no internet.
- If a check cannot be made, raise `client.InfraError`. It is reported as an infrastructure failure, never as a pass. A task file that fails to import is reported the same way, and the other tasks still run.
- An empty 200 is not a refusal. Use `client.refused()`.
- **Copy-only tasks (1–2 and 4–7):** a task that writes data, or sends a missing or changed token, sets `"copy_only": True`. The runner then runs it only inside a harness run on a copy (`AGENTSWITCH_RUN_ID` set, base URL not a live system). On a local run it is skipped: shown as `SKIP`, listed under `not_run` in `results.json`, and left out of the passed/total count. Do not set `AGENTSWITCH_RUN_ID` yourself. Any live write needs platform-team approval first (`../CONTRIBUTING.md`).
- `evidence` holds codes and counts only. Never the token, and never record contents.
