# 0003 People write tests; agents only suggest ideas

- **Status:** Accepted, 7 Nov 2026
- **Context:** The course gives zero marks to any test written by Claude, Codex or another AI tool.
- **Decision:** Coding agents may write task *ideas* in [../evaluation/ideas.md](../evaluation/ideas.md) only. A person writes every real task, expected result and verifier check by hand, in their own words. Each task file names its author. Agents may build the harness machinery (client, driver, run records, scorer, history), docs and reviews.
- **Consequences:** Suite work cannot be handed to an agent. Plan the suite owners' time for it.
