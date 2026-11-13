#!/usr/bin/env python3
"""Build the 90-day compliance calendar.

    python build.py                     # both systems, 90 days, active only
    python build.py --days 120
    python build.py --status active --status pending_approval
    python build.py --out calendar.md

Read-only. This script never writes to the platform.

The output contains live contract data, so it is written to a file you
choose and is NOT committed to this repository - see the repository rules
on platform data. The code that produces it is the deliverable; the table
itself goes to the seat lead and the course team directly.
"""
import argparse
import sys
from datetime import date

from compliance_calendar.client import Client, Unreachable
from compliance_calendar.contracts import (contract_items, LIVE_STATUSES,
                                           PENDING_STATUSES)
from compliance_calendar.model import UNASSIGNED
from compliance_calendar.render import render
from compliance_calendar.statutory import statutory_items

SYSTEMS = ("suryodaya", "keystone")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--status", action="append", default=None,
                    help="contract status to include; repeatable. "
                         "Default: %s" % ", ".join(LIVE_STATUSES))
    ap.add_argument("--system", action="append", default=None, choices=SYSTEMS)
    ap.add_argument("--today", default=None, help="YYYY-MM-DD, for testing")
    ap.add_argument("--tds-owner", default=UNASSIGNED,
                    help="who owns the statutory TDS deadlines")
    ap.add_argument("--no-pending", action="store_true",
                    help="omit the separate 'not yet in force' section for "
                         "contracts awaiting approval")
    ap.add_argument("--out", default=None, help="write here instead of stdout")
    args = ap.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else date.today()
    statuses = tuple(args.status) if args.status else LIVE_STATUSES
    systems = tuple(args.system) if args.system else SYSTEMS

    sections, all_skipped = [], []
    for system in systems:
        try:
            rows = Client(system).list("Contract")
        except Unreachable as exc:
            sections.append(("%s - contracts" % system.title(), [],
                             "NOT READ: %s. This is a failure of this run, "
                             "not a statement that nothing is due." % exc))
            continue

        due, overdue, skipped = contract_items(rows, system, today,
                                               args.days, statuses)
        all_skipped.extend(skipped)

        if overdue:
            sections.append((
                "%s - notice window ALREADY MISSED (%d)" % (system.title(), len(overdue)),
                overdue,
                None))
        sections.append(("%s - contracts (%d)" % (system.title(), len(due)),
                         due, None))

        # Contracts awaiting approval are not yet in force, so their
        # deadlines are provisional. They go in their own labelled section
        # and are never mixed into the table above, because an owner acting
        # on a deadline needs to know whether it binds.
        if not args.no_pending:
            pending, pending_overdue, _ = contract_items(
                rows, system, today, args.days, PENDING_STATUSES)
            sections.append((
                "%s - NOT YET IN FORCE, awaiting approval (%d)"
                % (system.title(), len(pending) + len(pending_overdue)),
                pending + pending_overdue,
                "No contracts awaiting approval fall due in this window."))

        tds, not_applicable = statutory_items(system, today, args.days,
                                              args.tds_owner)
        sections.append(("%s - statutory TDS (%d)" % (system.title(), len(tds)),
                         tds, not_applicable))

    text = render(today, args.days, sections, statuses, all_skipped,
                  include_pending=not args.no_pending)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("written: %s" % args.out, file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
