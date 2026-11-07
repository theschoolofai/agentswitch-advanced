# Glossary

> Every special word used in seat 34's docs and code, in plain English.

| Word | Meaning |
|---|---|
| **AgentSwitch** | The course's business software: accounting, sales, stock, email and more, used by two pretend companies. |
| **Instance** | One running copy of AgentSwitch for one company. There are two: **Suryodaya** (India) and **Keystone** (US). |
| **Seat** | One agent job on the platform, owned by one student team. Seats 1–27 are single-app agents; seats 28–35 are the "advanced" cross-app seats. We are seat 34. |
| **Agent** | A program that uses an AI model to read data and take steps (look things up, draft a reply) towards a goal. |
| **Login / token** | We log in with a username and password and get back a **token**: a long secret string we send with every call to prove who we are. It lasts 7 days. |
| **REST** | A simple way to talk to a server: you ask a web address (for example `/api/Party`) and get data back. |
| **MCP** | Model Context Protocol. A standard way for an AI agent to discover and call "tools". On AgentSwitch, one web address (`/api/mcp`) answers all tool calls. |
| **JSON-RPC** | The message format MCP uses. Each request names a `method` and its `params`, and each reply carries either a `result` or an `error`. |
| **Tool** | One action the platform offers, such as "list the parties" or "create a note". |
| **Entity** | A kind of record, such as a party (customer or supplier), an invoice or an agent run. The platform has several hundred kinds. |
| **Party** | Any person or company the business deals with: a customer, a supplier, a contact. |
| **Knowledge base (KB)** | The platform's library of company notes: policies, playbooks, procedures, and guides for agents. |
| **Eval** | Short for evaluation: a test of how well an agent does its job. |
| **Eval harness** | The machinery that runs evals: it starts the agent, records what happened, checks the result and adds up the scores. This is what seat 34 builds. |
| **Task** | One test: a request for the agent, plus a rule for deciding if it succeeded. |
| **Golden task** | A task whose correct result has been decided and checked by a person in advance. |
| **Suite** | A set of tasks. Every seat must have a 12-task suite for version 1 (30 Nov). Our first task is one 12-task suite split across two seats: 6 tasks for seat 31 and 6 for seat 35. |
| **Trial** | One attempt at one task. Agents can give different results each time, so a task may be run several times. |
| **Verifier** | The code that decides whether a trial passed. It reads the platform's data, never the agent's answer. (Also called a grader or predicate.) |
| **Snapshot** | A saved copy of the relevant records taken before a trial, so we can see exactly what changed afterwards. |
| **Run record** | A file with everything about one trial (what was asked, what happened, timings, errors), saved **before** scoring. |
| **Verdict** | A verifier's decision: **approve** (it checked and the work is right), **revise** (it checked and the work is wrong), or **unevaluated** (nothing could be checked). Unevaluated is never a pass. |
| **Infrastructure failure** | The test could not run fairly: a timeout, a bad login, a blocked tool. It is reported as a failure marked "infrastructure", never as the agent's fault and never as a pass. |
| **results.json** | The file a harness run must write, in the course's format: one row per task with `passed`, `score` and `evidence`. |
| **Regression** | A task that used to pass and now fails. Finding these is what a regular "regression run" is for. |
| **Nightly run** | Running all suites on a schedule (every night) to catch regressions early. |
| **Score history** | The list of past results per seat and task, kept so we can spot regressions and flaky tasks. |
| **Flaky task** | A task that sometimes passes and sometimes fails with no change, so its result cannot be trusted alone. |
| **pass@k / pass^k** | Run a task k times. **pass@k**: at least one try passed (can it ever do it?). **pass^k**: every try passed (can we rely on it?). |
| **Goal key** | The platform's own short name for the check a seat is judged by. |
| **Harness file** | `agentswitch-harness.toml`: tells the course runner how to install and run our suite. |
| **Official run** | A run done by the course's runner on a throwaway copy of an instance. Allowed once every 3 days. |
| **uv** | The tool we use to install Python and the packages our code needs. |
| **ruff / mypy** | Tools that check our code: ruff checks formatting and common mistakes; mypy checks that data types fit together. |
| **Pull request (PR)** | A request to add your changes to the shared repository. Another person reviews it first. |
| **Fork / branch** | A fork is your own copy of the repository on GitHub. A branch is a named line of work inside it. |
| **Worktree** | A second folder for the same repository, so two agents can work on two branches at once without getting in each other's way. |
| **Decision record (ADR)** | A short note that records one lasting decision: what we chose, why, and what it means. |
