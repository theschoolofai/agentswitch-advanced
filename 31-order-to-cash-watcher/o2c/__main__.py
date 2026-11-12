"""Run the daily exception report.

    python -m o2c --days 7 --instance suryodaya --out reports/

Reads AGENTSWITCH_BASE_URL and AGENTSWITCH_TOKEN from the environment.
"""
import argparse
import json
import os
from datetime import date
from pathlib import Path

from . import report
from .client import Client
from .output import instance_label, report_stem, write_pair


def nonnegative_days(value):
    try:
        return report.validate_days(int(value))
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("days must be a nonnegative integer") from None


def write_report(rep, md, out, instance):
    """Write <instance>-<date>.json and .md as UTF-8, whatever the machine's default encoding.

    Returns the file stem. Customer names can be any script (e.g. 客户); a cp1252 default on
    Windows would otherwise fail on the Markdown after the JSON was already written.
    """
    stem = report_stem(instance, rep["report_date"])
    # Serialize before touching output files. NaN/Infinity must never appear in JSON.
    encoded = json.dumps(rep, indent=2, allow_nan=False)
    write_pair(out, stem, encoded, md)
    return stem


def main():
    ap = argparse.ArgumentParser(prog="o2c", description="Daily order-to-cash exception report (read-only)")
    ap.add_argument("--days", type=nonnegative_days, default=os.environ.get("O2C_DAYS", "7"), help="N: nonnegative days before an order counts as not invoiced")
    ap.add_argument("--date", type=date.fromisoformat, help="report date (default: today in IST)")
    ap.add_argument("--instance", default=os.environ.get("AGENTSWITCH_INSTANCE"), help="label for the report, e.g. suryodaya")
    ap.add_argument("--out", type=Path, help="folder to write <instance>-<date>.md and .json; prints Markdown if omitted")
    args = ap.parse_args()
    try:
        instance_label(args.instance)
    except ValueError as e:
        ap.error(str(e))

    rep = report.build(Client(), report_date=args.date, days=args.days, instance=args.instance)
    md = report.to_markdown(rep)
    if args.out:
        stem = write_report(rep, md, args.out, args.instance)
        counts = ", ".join(f"{k}={len(v['rows'])}" if v["status"] == "ok" else f"{k}={v['status']}" for k, v in rep["sections"].items())
        issues = rep["sections"]["orders_not_invoiced"].get("date_issues", [])
        if issues:
            counts += f", order_date_issues={len(issues)}"
        validation = sum(len(sec.get("data_issues", [])) for sec in rep["sections"].values())
        if validation:
            counts += f", validation_issues={validation} (partial coverage)"
        print(f"wrote {args.out / stem}.md ({counts})")
    else:
        print(md)


if __name__ == "__main__":
    main()
