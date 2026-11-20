# 0005 Verifiers never read the agent's answer

- **Status:** Accepted, 7 Nov 2026. Amended by [0011](0011-recount-checks-the-answer-against-the-platform.md) for recount tasks (19 Nov)
- **Context:** An agent can claim success and be wrong, or report ids that do not exist. Judging the words rewards confident answers.
- **Decision:** A verifier never reads the agent's reply, report file, logs or claims. It snapshots the relevant records before the trial, reads the platform after it, and decides from the difference. Records the agent created are found through the platform (audit trail, or `created_by` plus the start time), never through what the agent says it created.
- **Consequences:** Seats whose output is only a local file must write their results to the platform before their tasks can be graded.
