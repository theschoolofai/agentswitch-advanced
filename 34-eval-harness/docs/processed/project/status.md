# Status and handoff log

> Newest entry first. Every work session (person or agent) ends by adding an entry here. A new session reads the top entry first, so it can carry on without old chat history.

Entry format: date · who · what changed · what's next · blockers. Keep entries free of platform detail (tool names, counts, record data). Those belong in the local platform notes.

---

## 2026-11-07 · seat lead (with Claude Code)
**What changed**
- **Seat foundations:**
  - `.gitignore` keeps raw notes, platform data, local platform notes, full bug reports, run output, `.env` and personal files out of git;
  - a uv project (`pyproject.toml`, `uv.lock`: Python 3.11, mcp, httpx2, pydantic, ruff, mypy, pytest);
  - `AGENTS.md` and `CLAUDE.md`.
- **Platform scripts:**
  - `scripts/probe_access.py`: a read-only live access check;
  - `scripts/platform_sync.py`: re-reads the platform after a release and reports what changed.
- **Docs:**
  - this wiki, the plan, the board, risks and decision records;
  - the bug workflow and template in [../../bugs/](../../bugs/README.md).
- **Live findings that corrected earlier beliefs** (details in the local platform notes):
  - our tool list is not empty;
  - the knowledge base is reachable;
  - sales, accounting and item data are not readable by our login.

**What's next**
1. Seat lead: create `.env.example` and add the two address lines to `.env` (see `AGENTS.md`). Then commit on branch `seat34/foundations` in the fork, and open the pull request.
2. Seat lead: post instructor questions Q1–Q6 from [risks.md](risks.md), and talk with seats 31 and 35 about where their results land (risk 2).
3. Seat lead: verify the seed bug drafts and file the real ones (S34-17).
4. Seat lead: share this plan with Ranjani and Abhinav, and meet to agree who looks after what. Every owner in the docs is a proposal until then.
5. Then the M1 cards, S34-04 to S34-09, on the [board](board.md).

**Blockers**
- Risk 1: some data our checks need is not readable.
- Risk 2: seat results are not on the platform.
- Q1: where the harness file may live. No official run can be submitted until it is answered.
