# Platform notes (kept on your own computer)

> The pages about the AgentSwitch platform are **not committed**, because this repository is public. Platform specifics (tool names, error codes, record counts, access details, field lists, exact replies) could help someone misuse the platform. The course rules also forbid committing schemas.

## What is kept locally, in this folder
| Page | What it holds |
|---|---|
| `agentswitch.md` | What the platform is: the two companies, the apps, the seats and their goal keys |
| `access.md` | What our login can and cannot reach, checked live. It includes the exact requests and replies for instructor questions |
| `api-notes.md` | How to log in and call the platform, and the traps that have caught teams before |
| `other-seats.md` | What the other advanced seats build, with seats 31 and 35 in more detail |

`.gitignore` keeps every file in this folder out of git, except this README.

## How to get them
- **Regenerate the data.** Run `uv run python scripts/platform_sync.py` (read-only; needs `.env`, see `AGENTS.md`). It writes the raw platform data and a change report to `data/platform/`, which is also git-ignored.
- **Get the written notes.** These pages are written by hand, so the sync script does not rebuild them. Ask the seat lead for a copy privately. Never post them in a public group, an issue or a pull request.
- **Keep them current.** When you check something live, update the local page and its "checked on" date. If the finding affects the plan, add a **plain, generic** line to the committed [risks.md](../project/risks.md) or [status.md](../project/status.md), for example "sales data is not readable yet", with no tool names or counts.
