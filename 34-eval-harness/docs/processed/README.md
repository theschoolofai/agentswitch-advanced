# Seat 34 wiki

> This wiki is where seat 34 keeps what it knows. Start here.

**AgentSwitch** is the course's business software (accounting, sales, stock, email and more). It runs two pretend manufacturing companies, one in India (Suryodaya) and one in the US (Keystone), and each course team builds one AI agent inside it, called a **seat**.

Seat 34 is the **Eval Harness** seat. We build the tests that check whether the other seats' AI agents really do their job. A test passes only when the platform's data shows the work was done. The agent saying "done" is not enough.

## If you are new (a person or a coding agent)
1. Read [project/status.md](project/status.md) to see what happened last and what is next.
2. Read [project/board.md](project/board.md) to see who is doing what.
3. Read `../../AGENTS.md` for the working rules.

## Pages

| Area | Page | What it tells you |
|---|---|---|
| Words | [glossary.md](glossary.md) | Every special word we use, in plain English |
| Platform | [platform/README.md](platform/README.md) | Why the platform notes are kept on your own computer, and how to get or regenerate them |
| Bugs | [../bugs/README.md](../bugs/README.md) | How we find, check and file platform bugs, and the bug index |
| Evaluation | [evaluation/principles.md](evaluation/principles.md) | How to judge an agent fairly |
| Evaluation | [evaluation/harness-design.md](evaluation/harness-design.md) | What we are building, part by part |
| Evaluation | [evaluation/ideas.md](evaluation/ideas.md) | Rough ideas for test tasks (people rewrite them by hand) |
| Project | [project/plan.md](project/plan.md) | Goal, milestones, definition of done |
| Project | [project/board.md](project/board.md) | Task board |
| Project | [project/risks.md](project/risks.md) | Risks, blockers, open questions for the instructor |
| Project | [project/status.md](project/status.md) | Handoff log, newest first |
| Project | [project/team.md](project/team.md) | Who does what, the weekly rhythm |
| Decisions | [decisions/](decisions/) | Short records of lasting decisions and why we made them |
| Team | [ways-of-working.md](ways-of-working.md) | Branches, pull requests, parallel agents, keeping secrets out |

## How these docs are kept
- **Folders.**
  - `docs/raw/` holds pasted chats, course notes and fetched web pages. It stays on your own computer and is never committed, because it may contain passwords.
  - `docs/processed/` (this wiki) is the cleaned, checked version, and it is committed.
- **Language.** Plain English. A special word is explained the first time it appears, and listed in the glossary.
- **Size.** Keep pages short. Write down only what someone will need. If a fact goes out of date, fix it or delete it.
- **Checking.** A fact about access or a blocker is only written here after it has been checked live, with the date it was checked.
- **Public repository.** Platform specifics (tool names, record counts, access details, exact replies) never go in committed pages. They live in the local platform notes; see [platform/README.md](platform/README.md).
