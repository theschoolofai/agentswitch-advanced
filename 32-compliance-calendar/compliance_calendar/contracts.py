"""Due items derived from contract end dates.

The rule is one line and the whole seat rests on it:

    due date = end date - notice period

The end date is not the due date. A contract ending 31 January with 60 days'
notice must be acted on by 2 December; by 31 January the renewal has already
happened automatically or the chance to renegotiate is gone. A calendar that
lists end dates is a calendar that warns everybody too late.

Two notice periods, not one
---------------------------
Each contract carries a renewal notice period AND a termination notice
period. On 121 of the 124 contracts surveyed they are different numbers,
measured on 3 Nov 2026 and again on 9 Nov after the platform release.

They are different actions with different deadlines, so a contract produces
up to two rows, each naming its action. Collapsing them to one row means
choosing which deadline to hide from the owner.
"""
from datetime import date, timedelta

from .model import DueItem, UNASSIGNED

# The two notice fields, and the action each one gates.
NOTICE_RULES = (
    ("renewal_notice_days",
     "Decide on renewal and give notice",
     "renewal notice"),
    ("termination_notice_days",
     "Give notice if the contract is to end",
     "termination notice"),
)

# Statuses that carry a live obligation. A draft has nothing to give notice
# on and an expired contract is finished.
#
# Set by the course team on 9 Nov 2026 for the 15 November delivery: active
# AND expiring_soon in the main table. expiring_soon matters because the
# platform's own is_expiring_soon flag requires status active, so every
# expiring_soon contract fails it and the platform never flags them - which
# is exactly why they must not be missed here too.
LIVE_STATUSES = ("active", "expiring_soon")

# Reported in their own section, labelled, never mixed into the table above.
# A contract awaiting approval is not yet in force, so its notice deadlines
# are provisional rather than binding - but they are close enough to matter
# if approval lands.
PENDING_STATUSES = ("pending_approval",)


def _as_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_days(value):
    """Notice periods arrive as '30.0'. int('30.0') raises; this does not."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def contract_items(rows, system, today, window_days=90, statuses=LIVE_STATUSES):
    """Every notice deadline falling in [today, today + window_days].

    Also returns deadlines that have already passed on a contract that has
    not yet ended - see `overdue_items`. Those are not padding: the notice
    window has closed while the contract is still running, which is the
    single worst state this calendar can find, and dropping them because
    they fall outside "the next 90 days" would hide exactly the rows that
    need escalating.
    """
    horizon = today + timedelta(days=window_days)
    due, overdue, skipped = [], [], []

    for row in rows:
        status = str(row.get("status") or "")
        if statuses is not None and status not in statuses:
            continue

        end = _as_date(row.get("end_date"))
        if end is None:
            skipped.append((row.get("number"), "no end date"))
            continue

        owner = row.get("_owner_id_display") or UNASSIGNED
        ref = row.get("number") or row.get("id") or "?"
        title = (row.get("title") or "").strip()

        for field_name, action, label in NOTICE_RULES:
            days = _as_days(row.get(field_name))
            if days is None:
                skipped.append((ref, "no %s" % label))
                continue

            deadline = end - timedelta(days=days)
            item = DueItem(
                due_date=deadline,
                system=system,
                source="contract",
                reference=ref,
                action="%s - %s" % (action, title) if title else action,
                owner=owner,
                basis="end date %s minus %d days %s" % (end.isoformat(), days, label),
                notes=("contract status: %s" % status,),
            )

            if deadline < today:
                # The window has closed. Only worth raising while the
                # contract is still running - once it has ended there is
                # nothing left to act on.
                if end >= today:
                    overdue.append(item)
            elif deadline <= horizon:
                due.append(item)

    due.sort(key=lambda i: (i.due_date, i.reference))
    overdue.sort(key=lambda i: (i.due_date, i.reference))
    return due, overdue, skipped
