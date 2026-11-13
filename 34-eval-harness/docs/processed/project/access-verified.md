# Access verification log — seat 34 login

## 2026-11-11 — Keystone
After the 11 Nov platform release, seat-34 token re-login:

| Entity | Read | Fields seen |
|---|---|---|
| Invoice.list | OK, count > 0 | id, number, party_id, sales_order_id, direction |
| PaymentReceived.list | OK, count > 0 | id, number, customer_id, payment_number, date, amount, bank_charges |

BUG-31-001 read gap: closed on Keystone.
Suryodaya: pending next session.
