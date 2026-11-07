# 0002 A task passes only on a check of platform state

- **Status:** Accepted, 7 Nov 2026
- **Context:** The course format says `passed` is true only when a check on the resulting data confirms it. The course grades by reading the database.
- **Decision:** Every task's verdict comes from reading the platform. Verdicts are approve, revise or unevaluated, and unevaluated is never a pass. A task with several checks takes its worst verdict. A trial that could not run fairly is reported as an infrastructure failure.
- **Consequences:** A task whose result never lands on the platform cannot pass. We must agree with each seat where its results land (risk 2).
