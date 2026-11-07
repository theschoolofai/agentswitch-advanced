# Platform bugs

> How seat 34 finds, checks and files bugs in the AgentSwitch platform. The platform is still being developed, so bugs are expected, and finding real ones is valuable. **A person always verifies and files a bug.** Coding agents may only draft.

## Where things live
| Path | What | In git? |
|---|---|---|
| `README.md` (this page) | The workflow and the bug index | Yes |
| [TEMPLATE.md](TEMPLATE.md) | The form every report uses | Yes |
| `reports/BUG-34-NNN.md` | The full reports, with steps and replies | **No.** They hold platform data, and the course allows a bug file in the seat folder only if it contains none |

## The workflow
| Status | Who | What happens |
|---|---|---|
| **draft** | anyone, including a coding agent | Copy [TEMPLATE.md](TEMPLATE.md) to `reports/BUG-34-NNN.md` and fill it in |
| **verified** | a person | Re-run every step yourself, on the system named, and confirm the same result. Fill in "Verified by". If it does not repeat, set it to **closed**, with a note |
| **filed** | a person | Report it with the bug icon in the app, on the screen where it happened, or with the platform's bug-report form. Note the date and the platform's report id. Add a row to the index below |
| **fixed** / **won't fix** | a person | When the course team answers, record their answer, then re-check after the next release |
| **closed** | a person | A final status, with a one-line reason |

## Rules
- **Check that it is a bug first.** These are by design, not bugs:
  - being refused when reading another app's data (the seat boundary);
  - another team changing shared data;
  - a tool missing from our list that another seat has.

  If the intended behaviour is unclear, say so in the report ("Product decision?") and let the course team decide.
- **Check that it is new.** Look at the course's known-issues list, and at this index.
- **One report per bug.** Write steps another person can repeat exactly.
- **Numbers.** Reports are numbered `BUG-34-NNN`. Claim the next number in your pull request title, and never reuse one.
- **No secrets or customer data.** No passwords, tokens or customer records anywhere. Shorten ids to 8 characters.
- **Filing limit.** The platform accepts at most 20 bug reports an hour per login.
- **Coding agents never file.** They never call the platform's bug-report tool or endpoint.

## Index (committed; titles only, no platform data)
| ID | Title | System | Severity | Status | Filed on | Platform id |
|---|---|---|---|---|---|---|
| BUG-34-001 | Some list replies do not match their own declared shape | Suryodaya | Medium | draft | | |
| BUG-34-002 | Some knowledge-base endpoints that only read are labelled as writes | both | Low | draft | | |
