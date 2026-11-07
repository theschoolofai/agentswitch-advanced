@AGENTS.md

## Claude Code notes
- Start Claude Code from inside `34-eval-harness/`, so this file and `AGENTS.md` load.
- Personal preferences belong in `CLAUDE.local.md` (git-ignored) or your own memory, never in this file.
- For parallel sessions, use `claude -w <name>` or a git worktree per session. A fresh worktree needs `.env` copied in, then `uv sync`.
