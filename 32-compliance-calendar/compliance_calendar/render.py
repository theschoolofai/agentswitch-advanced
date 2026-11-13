"""The table, as Markdown.

Two rules shape this file.

Every figure states where it came from. A due date with no basis cannot be
checked by the person who has to act on it, and an unverified statutory date
that does not say so is a trap.

Nothing is silently empty. A section with no rows says why it has none -
"TDS does not apply to a US company" and "no contracts fall due" are
different answers, and a blank cell cannot tell them apart.
"""
from datetime import timedelta

from .model import TO_VERIFY

HEAD = "| Due | In | What must be done | Owner | System | Basis |"
RULE = "|---|---|---|---|---|---|"


def _cell(text):
    return str(text).replace("|", "\|").replace("\n", " ")


def _row(item, today):
    days = item.days_from(today)
    when = "%+d days" % days if days else "today"
    mark = " **(%s)**" % TO_VERIFY if item.needs_verification else ""
    return "| %s | %s | %s%s | %s | %s | %s |" % (
        item.due_date.isoformat(), when, _cell(item.action), mark,
        _cell(item.owner), item.system, _cell(item.basis))


def render(today, window_days, sections, statuses, skipped=(),
           include_pending=True):
    out = []
    out.append("# Compliance calendar - next %d days" % window_days)
    out.append("")
    horizon = today + timedelta(days=window_days)
    out.append("Generated %s. Covers %s to %s inclusive."
               % (today.isoformat(), today.isoformat(), horizon.isoformat()))
    out.append("")
    out.append("**Every statutory rate and date below is marked \"%s\". "
               "None has been confirmed by a chartered accountant. Do not "
               "act on a statutory date in this table without that "
               "confirmation.**" % TO_VERIFY)
    out.append("")
    out.append("Contract rows are computed as `due date = end date - notice "
               "period`, not from the end date itself.")
    out.append("")
    out.append("**Assumptions stated:** contracts with status %s are in the "
               "main tables. A contract carries two notice periods, for "
               "renewal and for termination; both are reported as separate "
               "rows naming the action, because a termination deadline is "
               "its own date and is not implied by the renewal one."
               % (", ".join("`%s`" % s for s in statuses) if statuses else "any"))
    out.append("")
    if include_pending:
        out.append("Contracts awaiting approval are **not yet in force**, so "
                   "their deadlines are provisional. They appear in their own "
                   "section, never mixed into the tables above.")
    else:
        out.append("Contracts awaiting approval are **excluded** from this "
                   "run. Re-run without `--no-pending` to list them "
                   "separately.")
    out.append("")

    for title, items, empty_reason in sections:
        out.append("## %s" % title)
        out.append("")
        if not items:
            out.append("_%s_" % (empty_reason or "Nothing falls due in this window."))
            out.append("")
            continue
        out.append(HEAD)
        out.append(RULE)
        for item in items:
            out.append(_row(item, today))
        out.append("")

    if skipped:
        out.append("## Left out, and why")
        out.append("")
        for ref, why in skipped:
            out.append("- `%s` - %s" % (ref, why))
        out.append("")

    return "\n".join(out)
