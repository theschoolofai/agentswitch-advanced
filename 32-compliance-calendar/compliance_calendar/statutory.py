"""Statutory TDS due dates.

Nothing in this file has been confirmed by a chartered accountant. Every
item it produces is marked `needs_verification=True` and prints the
"to be verified" marker, as the course team instructed. The marker is not
decoration: these are deadlines with penalties attached, and a wrong one
published without a warning is worse than no calendar at all.

These are RULES, not platform data. They are written here rather than read
from the platform because the platform does not hold them - the tax-section
master holds rates and thresholds, not deposit or return dates.

Keystone
--------
Keystone is a US company. TDS is Indian and does not apply to it. That is a
real answer and the table says so in words; it must never appear as a blank
cell, because a blank reads as "nobody checked".
"""
from datetime import date, timedelta

from .model import DueItem, UNASSIGNED, TO_VERIFY

INDIAN_SYSTEMS = ("suryodaya",)

# Quarter end -> return due date. To be verified.
RETURN_DUE = {
    (6, 30): (7, 31),
    (9, 30): (10, 31),
    (12, 31): (1, 31),
    (3, 31): (5, 31),
}


def _deposit_due(year, month):
    """TDS deducted in a month is deposited by the 7th of the next month,
    except March, which is deposited by 30 April. To be verified."""
    if month == 3:
        return date(year, 4, 30)
    nxt = date(year + (month == 12), (month % 12) + 1, 7)
    return nxt


def _months_in(today, horizon):
    y, m = today.year, today.month
    while date(y, m, 1) <= horizon:
        yield y, m
        y, m = y + (m == 12), (m % 12) + 1


def statutory_items(system, today, window_days=90, owner=UNASSIGNED):
    """TDS deposit and return deadlines falling in the window.

    Returns (items, not_applicable_reason). Exactly one of the two is
    meaningful: a system outside India yields no items and a reason naming
    why, so the caller can print the reason instead of an empty section.
    """
    if system not in INDIAN_SYSTEMS:
        return [], ("TDS is an Indian deduction and does not apply to %s, "
                    "which is a US company. No TDS rows are due. This is a "
                    "checked answer, not a gap in the data." % system)

    horizon = today + timedelta(days=window_days)
    items = []

    # Monthly deposits, one per month whose deposit date lands in the window.
    for year, month in _months_in(today - timedelta(days=62), horizon):
        due = _deposit_due(year, month)
        if not (today <= due <= horizon):
            continue
        items.append(DueItem(
            due_date=due,
            system=system,
            source="statutory",
            reference="TDS deposit",
            action="Deposit TDS deducted in %s %d" % (date(year, month, 1).strftime("%B"), year),
            owner=owner,
            basis="deducted in %s %d; rule says the 7th of the following month "
                  "(March: 30 April) - %s" % (date(year, month, 1).strftime("%B"), year, TO_VERIFY),
            needs_verification=True,
            notes=("rate and date %s" % TO_VERIFY,),
        ))

    # Quarterly returns.
    for (qm, qd), (rm, rd) in RETURN_DUE.items():
        for year in (today.year, today.year + 1):
            q_end = date(year, qm, qd)
            r_year = year + 1 if rm < qm else year
            due = date(r_year, rm, rd)
            if today <= due <= horizon:
                items.append(DueItem(
                    due_date=due,
                    system=system,
                    source="statutory",
                    reference="TDS return",
                    action="File the quarterly TDS return for the quarter ending %s"
                           % q_end.isoformat(),
                    owner=owner,
                    basis="quarter ended %s; return due %s - %s"
                          % (q_end.isoformat(), due.isoformat(), TO_VERIFY),
                    needs_verification=True,
                    notes=("date %s" % TO_VERIFY,),
                ))

    seen, unique = set(), []
    for i in sorted(items, key=lambda x: (x.due_date, x.reference)):
        key = (i.due_date, i.reference, i.action)
        if key not in seen:
            seen.add(key)
            unique.append(i)
    return unique, None
