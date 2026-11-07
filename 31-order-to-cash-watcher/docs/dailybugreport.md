# Seat 31 — Daily bug report

Bugs raised by seat 31, in the format in `BUG_REPORT_FORMAT.md`. Newest day last. No passwords, tokens or customer data: the repository is public. Exact requests and replies (tool names, arguments, error text, counts) are kept in the local, gitignored `private/platform-notes.md` and given to the instructor in the seat group.

| ID | Title | System | Severity | Status |
|---|---|---|---|---|
| BUG-31-001 | Invoice and applied-receipt read tools are not available to seat 31 | Both | Medium | Open |
| BUG-31-002 | Login `team31a` has no mailbox, so reminder drafts cannot be saved | Both | Medium | Open |

---

## 7 Nov 2026

### BUG-31-001: Invoice and applied-receipt read tools are not available to seat 31

| Field | Value |
|---|---|
| Seat and login | 31, `team31a` |
| System | Suryodaya and Keystone |
| Date and time (IST) | First seen 6 Nov, about 11:20 pm. Checked again 7 Nov at 00:11 and later on 7 Nov; same result each time |
| Severity | Medium: blocks a first-task section; no data was changed |
| Repeats | Every time, on both systems |
| Status | Open, raised in the seat group on 7 Nov |

**Steps**
1. Log in as `team31a`.
2. Call the invoice list tool.
3. Call the applied-receipt list tool the same way.
4. List our tools, and search the tools for "invoice".
5. Open the linked-records view of an order that has an invoice.

**Expected**
The 3 Nov access update gives seat 31 the accounting tools. The instructor's 7 Nov answer says to read due date and balance from invoices, and to use the applied-receipt records for receipts. So both list tools should return rows.

**Actual**
- Steps 2–3 reply that the tool is not available to our seat.
- Step 4: our tool list has no invoice or applied-receipt tools on either system, and the search finds only the linked-records tool.
- Step 5: the invoice comes back redacted. Some other linked record types are redacted too.

**Evidence**
Exact request and reply text is in `private/platform-notes.md` (local only) and can be sent to the instructor on request. Nothing is attached here, so no platform data is included.

**Impact**
The "invoices overdue" section of the 15 Nov report is blocked, and so is matching the unallocated Suryodaya payments to invoices. Suite tasks 5–6 (`overdue_invoices`, `overdue_ageing`) depend on it. The rule is already written (commit `94e14fd`) and switches on as soon as the invoice tool is in our tool list, so no code change is needed on our side.

**Ask**
Please give `team31a` read access to the invoice and applied-receipt list and get tools on both systems. If seat 31 isn't meant to have them, please tell us how to read invoice due dates and balances instead.

**Log**
- 6 Nov, ~11:20 pm IST: found during the first exploration. Invoice nodes redacted; no Invoice tool.
- 7 Nov, 00:11 IST: after the instructor's answer, tried both list tools directly and was told they are not available, on both systems.
- 7 Nov, later: tool list checked again, still none. Posted in the seat group for the admin.

### BUG-31-002: Login `team31a` has no mailbox, so reminder drafts cannot be saved

| Field | Value |
|---|---|
| Seat and login | 31, `team31a` |
| System | Suryodaya and Keystone |
| Date and time (IST) | 7 Nov 2026, evening |
| Severity | Medium: blocks saving reminder drafts (v1); no data was changed |
| Repeats | Every time, on both systems |
| Status | Open, to raise in the seat group |

**Steps**
1. Log in as `team31a`.
2. List the mailboxes our login can see.
3. Read the inputs of the create-message tool in our tool list.

**Expected**
The brief says the agent drafts reminders for a person to send, and the 3 Nov access update grants email tools. So we expected a mailbox for our login, where drafts can be saved.

**Actual**
- Step 2 returns no mailboxes on both systems.
- Step 3: creating a message requires a mailbox, so with no mailbox no draft can be saved.

We did not try to create a mailbox or a message.

**Impact**
Suite task 9 (`reminder_is_draft`) cannot pass, and the demo cannot show a saved draft. Meanwhile drafts are written to a local review file (`python -m o2c.drafts`), and saving them needs only `--create --mailbox-id <id>` once a mailbox exists.

**Ask**
Please give `team31a` a mailbox on both systems, or tell us which mailbox seat 31 should save drafts in. We only create drafts; we never send.
