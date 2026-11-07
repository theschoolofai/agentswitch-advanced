# How to judge an agent fairly

> The rules our harness follows. They come from course session 18, the course brief, Anthropic's guide to agent evals, and lessons from earlier course harnesses.

## 1. Judge the platform, never the agent's answer
An agent can say "done" and be wrong. Our verifier never reads the agent's reply, report file, logs or claims. Instead it does three things:
1. It takes a **snapshot** of the records that matter **before** the trial.
2. It reads the platform again **after** the trial.
3. It decides from **what changed**, or from what should not have changed.

Records the agent created are found from the platform itself: the audit trail, or `created_by` combined with the trial's start time. They are never found from ids the agent reports. If a task's result never lands on the platform, nothing can be checked and the verdict is **unevaluated**.

## 2. Three verdicts, and "unevaluated" is never a pass
| Verdict | Meaning |
|---|---|
| approve | We checked, and the work is right |
| revise | We checked, and the work is wrong |
| unevaluated | Nothing could be checked (missing access, a stub, the verifier crashed) |

A task with several checks takes its **worst** verdict, where revise is worse than unevaluated, which is worse than approve.

How a verdict becomes a row in the course's `results.json`:

| Verdict | `passed` | `score` | `evidence` starts with |
|---|---|---|---|
| approve | true | the verifier's score, from 0 to 1 | `outcome=approve; verifier=<name>` |
| revise | false | the verifier's partial score, from 0 to 1 | `outcome=revise; verifier=<name>; reason=…` |
| unevaluated | false | 0 | `outcome=unevaluated; reason=…` |
| infrastructure failure | false | 0 | `infrastructure: <what failed>` |

## 3. Keep "the agent failed" apart from "the test could not run"
If a trial times out, the login fails, the model budget runs out or a tool is blocked, the agent was never really tested. That trial is reported as a failure **marked "infrastructure"** in `evidence`. It is never dropped, never counted as a pass, and never blamed on the agent. A table full of zeros caused by a broken setup looks exactly like a table of honest failures, so the record must say which one it is.

## 4. Save the record before scoring
Every trial writes a **run record** to disk first: what was asked, the settings used, the snapshots, timings and errors. Scoring happens afterwards, from that file. If we improve a verifier, we **rescore the saved records** without running the agent again.

## 5. Write down everything that can change a score
Each run record holds:
- the git commit;
- the task version and the verifier version;
- the model name;
- the instance;
- time limits.

When two scores differ, compare these first. A score is a measurement of the whole setup, not just of the model.

## 6. Every claimed property needs a task that could expose its failure
A suite of easy tasks cannot show that an agent refuses bad requests. Label each task with what it tests:

| Type | Tests |
|---|---|
| normal | The agent does the job and the expected change appears |
| refusal | The agent declines something it must not do, and nothing changed |
| integrity | The agent does not cheat or touch things outside its job |
| missing resource | The data or access it needs is absent. Under this setup the honest result is "not evaluable", not "agent failed" |

A "0 bad writes" result means something only if the task gave the agent a real chance to make one.

## 7. One trial is an observation, not a result
Agents vary from run to run. For a claim that matters, run the same task several times and report the raw counts, for example "3 of 3". Do not report that as "100%".
- **pass^k** means every one of k tries passed. It is the right measure for business agents, which must be reliable.
- A task that passes on some nights and fails on others is **flaky**. It is kept out of the regression alarm until someone fixes it.

## 8. Tasks must be clear and solvable
Two people reading a task should reach the same pass/fail verdict. Before trusting a task:
- check that a correct solution exists;
- check that the verifier accepts it.

A 0% pass rate most often means the task or the verifier is broken. Read the run records before blaming the agent.

## 9. Make narrow, honest claims
Write results as "Under this setup (manifest), we observed…". Include the raw counts, the failures, the cost, and one thing the run does **not** show. Never write a leaderboard sentence.

## 10. Tests are written by people
The course gives zero marks to tests written by an AI tool. Coding agents may suggest task ideas (in [ideas.md](ideas.md) only). A person writes every real task, expected result and verifier check, and the task file names its author.

Sources (raw notes in `docs/raw/`):
- course session 18, "Evaluating Agents";
- course sessions 19–20, about the capstone platform;
- https://www.anthropic.com/research/demystifying-evals-for-ai-agents;
- the user's email-agent harness;
- seat 33's probe runner.
