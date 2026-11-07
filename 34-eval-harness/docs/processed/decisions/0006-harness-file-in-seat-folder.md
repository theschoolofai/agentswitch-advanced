# 0006 Harness file stays in the seat folder for now

- **Status:** Accepted, 7 Nov 2026. Review once the instructor answers Q1.
- **Context:** The course runner expects `agentswitch-harness.toml` at the root of a repository. This repository is shared by 8 seats, and we must not edit its root.
- **Decision:** Keep `agentswitch-harness.toml` in `34-eval-harness/`. Ask the instructor (risks, Q1) whether the course's harness registration can point at a subfolder or a branch of our fork.
- **Consequences:** No official run is possible until Q1 is answered, or until we agree another way, for example a separate repository holding only the harness.
