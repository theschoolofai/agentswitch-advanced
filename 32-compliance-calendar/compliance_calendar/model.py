"""What one row of the compliance calendar is.

Every field exists because a reader of the table needs it to act. `owner` and
`basis` in particular: a due date nobody owns is not actionable, and a due
date whose derivation is not stated cannot be checked by the person who has
to sign off on it.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

UNASSIGNED = "UNASSIGNED - needs a named owner"

# Printed against every figure that no chartered accountant has confirmed.
# The course team's instruction is explicit: every rate and every statutory
# date is provisional until a CA signs it off. The marker is part of the
# value, not a footnote, so it cannot be lost when a row is copied out of
# the table.
TO_VERIFY = "to be verified"


@dataclass(frozen=True)
class DueItem:
    due_date: date
    system: str                 # suryodaya | keystone
    source: str                 # "contract" | "statutory"
    reference: str              # contract number, or the rule's name
    action: str                 # what the owner must actually do
    owner: str
    basis: str                  # how due_date was derived, in words
    amount: Optional[str] = None
    needs_verification: bool = False
    notes: tuple = field(default_factory=tuple)

    def overdue_against(self, today):
        return self.due_date < today

    def days_from(self, today):
        return (self.due_date - today).days
