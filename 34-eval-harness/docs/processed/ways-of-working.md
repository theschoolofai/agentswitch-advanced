# Ways of working

> How people and coding agents (Claude Code, Codex, Cursor and others) share this repository safely, often at the same time.

## The repository is shared by 8 seats
- **Stay in our folder.** We change files **only inside `34-eval-harness/`**. Never edit another seat's folder, and never edit the files at the repository root (`README.md`, `BUG_REPORT_FORMAT.md`, `.github/`).
- **Reading is fine.** We may read other seats' code to understand their agents. We may run it, but we never copy it into our folder.
- **The repository is public.** Anything committed can be read by anyone.

## First-time setup: fork and remotes
You may create branches in your local copy; branches are local. You cannot push them to the course repository, because students have read access only and the course rules say "work in your own fork". So push to your fork, and open pull requests from it.
```bash
gh repo fork theschoolofai/agentswitch-advanced --clone=false   # once; or use an existing fork
git remote rename origin upstream                                # the course repository
git remote add origin https://github.com/<your-fork-owner>/agentswitch-advanced.git
git remote -v                                                    # origin = your fork, upstream = course repo
```
If you have more than one GitHub account, pick the right one first (`gh auth switch --user <account>`, then `gh auth setup-git`). Set your name and email for this repository only (`git config user.name …`, without `--global`).

**Keeping your fork current:** `git fetch upstream && git switch main && git merge --ff-only upstream/main && git push origin main`.

## Branches and pull requests
1. **Work in your fork.** Work on a branch named `seat34/<topic>`, for example `seat34/platform-client`. Push it to `origin` (your fork), then open the pull request against the course repository: `gh pr create --repo theschoolofai/agentswitch-advanced --base main --head <your-fork-owner>:seat34/<topic>`.
2. **Keep it small.** One card per pull request, ideally about 300 changed lines or fewer. Keep tidy-ups in a separate pull request.
3. **Commit messages.** Use `type(seat34): what changed`, where the type is `feat`, `fix`, `docs`, `test` or `chore`. Example: `feat(seat34): add read-only platform client`.
4. **Pull request title.** Start it with the card number, for example `S34-04: platform client`. Claim a card or bug number there, so two people never take the same one, and never reuse a number.
5. **Pull request template.** Fill in the template from `.github/`: what changed, the seat, and the tests you ran. Tick the "no credentials, no platform code, no data files" box.
6. **Review.** One review by a teammate, then the seat lead merges. Nobody merges their own pull request.

## Parallel coding agents
- **Separate folders.** Give each agent session its **own branch in its own folder** (a git worktree, for example `git worktree add ../as-seat34-client seat34/platform-client`). Two agents never share one folder or one branch.
- **Split by card.** Divide work by card, not by file, so sessions do not edit the same lines.
- **Fresh worktrees.** A fresh worktree has no `.env` and no installed packages. Copy `.env` in by hand, then run `uv sync`.
- **Start inside the seat folder.** Start the agent **inside `34-eval-harness/`**, so it reads our `AGENTS.md` (and Claude also reads `CLAUDE.md`).
- **Leave a handoff.** Every session ends by updating [project/status.md](project/status.md) and [project/board.md](project/board.md). The next session, or another tool, can then carry on without the chat history.
- **Second-opinion review.** Before a person reviews a pull request, it helps to have a fresh agent session (one that did not write the code) review the diff against the card's acceptance criteria.

## Team rules vs personal preferences
- **Team rules.** These live in `AGENTS.md` and are committed. They apply to everyone and every agent.
- **Personal preferences.** These stay out of the repository. Examples are "don't run git for me" or a preferred tone. Put them in your own tool's local memory or a git-ignored `CLAUDE.local.md`.

## Keeping secrets and platform data out of git
- **Secrets.** Passwords go only in `.env`, which is git-ignored. If a secret is ever committed, tell the course team at once so it can be changed. Deleting the commit is not enough.
- **Platform files.** Raw platform dumps (schemas, tool lists, records) go only in `data/platform/` (git-ignored). Regenerate them with `scripts/platform_sync.py`.
- **Platform notes.** Hand-written platform notes go in `docs/processed/platform/`, which is git-ignored except its README. Committed pages mention the platform only in plain, generic words.
- **Run output.** Run records and `results.json` are git-ignored, because they may contain customer data.
- **In docs and pull requests:**
  - describe the *shape* of data (field names, counts), never paste records;
  - shorten ids to 8 characters (`1a2b3c4d…`);
  - use placeholders such as `<suryodaya-company-id>`.

## Live data safety
| Level | Covers | Rule |
|---|---|---|
| 1 | Reads, logging in | Allowed |
| 2 | A write to a record we created | Only with approval, recorded in the card. The seat lead approves a teammate's write, and a teammate approves the seat lead's. Label the record `[seat34-test]`. |
| 3 | A write to anyone else's record, a delete, anything that reaches a customer | Never on live data. Only on the course's throwaway copy. |

Ten wrong passwords lock the login for the whole team. Never retry a refused login in a loop.

## Platform releases
The platform is still being developed. When the instructor announces a release:
1. Run `uv run python scripts/platform_sync.py`.
2. Read `data/platform/changes-<date>.md`.
3. Act on it:
   - new gaps or odd behaviour become instructor questions or bug drafts;
   - changed access updates the local platform notes;
   - anything that affects the plan gets a generic line in [project/risks.md](project/risks.md).

## Bugs
The workflow and template are in [../bugs/README.md](../bugs/README.md). In short:
- anyone (including an agent) may **draft** a report;
- a person **verifies** it by re-running the steps, then **files** it;
- bugs are numbered `BUG-34-NNN`, claimed in the pull request title.
