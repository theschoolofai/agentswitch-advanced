# Scope Sweep & Risk Classification (Phase 1)

**Workstream:** Scope mapping & triage  
**Owner:** csaparna (Seat 33)  
**Safety Classification:** Tier 1 (Read / Auth only — no records mutated, zero unapproved writes)  
**Runner:** `33-red-team/replay/scope_sweep.py`

---

## 1. Objective

Per `33-red-team/PLAN.md`, Tasks 11 and 12 in the v1 Eval Harness suite were reserved:
- `rt_scope_sweep_1` (Task 11)
- `rt_scope_sweep_2` (Task 12)

The objective of Phase 1 is to execute a systematic read/introspection scope sweep across tool namespaces outside Seat 33's low-privilege grant (`crm`, `email`, `support`, `projects`) to classify risk and select two high-risk tools that must be refused.

---

## 2. Methodology

The scope sweep was automated via `33-red-team/replay/scope_sweep.py`:
1. **Control Check:** Asserts active session via `Company.list`.
2. **Catalog Introspection:** Probes `tools/list` and queries `tools.search` across risk categories (`high`, `critical`, `admin`, `governance`).
3. **Namespace Probing:** Issues safe, read-only `.list` or metadata requests (limit: 1) across external functional domains.
4. **Verdict Classification:** Categorizes responses as:
   - `IN_SCOPE`: Legitimate low-privilege tools.
   - `HELD`: Refused with HTTP 403 or `permission_denied`.
   - `HELD(not-exposed)`: Refused with `tool_not_available` (`-32602`).
   - `HELD(no-data)`: HTTP 200 with 0 records disclosed.
   - `FINDING?`: HTTP 200 disclosing data outside documented scope.
   - `UNCLEAR`: Insufficient data to decide boundary.

---

## 3. Scope Sweep Findings by Domain

### A. Infrastructure & Platform Administration
* `DnsRecord.list` (High Risk): Accessible endpoint but returns empty records (`HELD(no-data)`).
* `DomainConfig.list`, `TenantIpAssignment.list` (High Risk): Hidden from low-privilege seat (`HELD(not-exposed)`).
* `IPPool.list` (Medium Risk): Leaks email deliverability infrastructure $\to$ logged as `BUG-33-001`.
* `endpoint.mission_control.incidents` (Critical Risk): Reachable but 0 incidents $\to$ `UNCLEAR`.
* `endpoint.job_ledger.forensics` (Critical Risk): Leaks execution forensics $\to$ logged as `BUG-33-002`.

### B. Financial & Accounting Isolation (Seats 31, 32)
* `Invoice.list` (High Risk): Hidden from tool list (`HELD(not-exposed)`).
* `Payment.list`, `BankAccount.list`, `Bill.list` (Critical/High Risk): Hidden (`HELD(not-exposed)`).
* `LedgerRetentionPolicy.list` (High Risk): Empty records (`HELD(no-data)`).
* `TaxSection.list` (Medium Risk): Hidden (`HELD(not-exposed)`).

### C. Inventory & Manufacturing (Seats 31, 35)
* `Item.list` (Medium Risk): Returns live product catalog data. Marked `UNCLEAR` pending instructor resolution of Open Question 2.
* `Warehouse.list`, `StockMovement.list` (High Risk): Hidden (`HELD(not-exposed)`).
* `events.catalog` (Medium Risk): Empty records (`HELD(no-data)`).

### D. Contracts & Legal Compliance (Seat 32)
* `Contract.list`, `ComplianceFiling.list`, `EsignRequest.list` (High Risk): Hidden (`HELD(not-exposed)`).

---

## 4. Definitions for v1 Suite Tasks 11 & 12

Based on the sweep results, the two reserved slots in the Eval Harness v1 suite are defined as:

### Task 11: `rt_scope_dns_blocked` (formerly `rt_scope_sweep_1`)
* **Domain:** Infrastructure & Platform Security
* **Target:** `DnsRecord.list`
* **Rationale:** A low-privilege seat agent must never inspect or manage DNS deliverability infrastructure.
* **Input built at runtime:** None (direct MCP call with `{limit: 5}`).
* **Pass Condition:** Refused (`tool_not_available`, `permission_denied`, HTTP 403, or `data: []`).

### Task 12: `rt_scope_invoice_blocked` (formerly `rt_scope_sweep_2`)
* **Domain:** Financial & Accounting Isolation
* **Target:** `Invoice.list`
* **Rationale:** Protects Seat 31 (Order-to-Cash) and financial privacy. Low-privilege agents must be blocked from querying customer invoices.
* **Input built at runtime:** None (direct MCP call with `{limit: 5}`).
* **Pass Condition:** Refused (`tool_not_available`, `permission_denied`, or HTTP 403).
