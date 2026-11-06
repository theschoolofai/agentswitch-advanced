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


def main():
    ap = argparse.ArgumentParser(prog="o2c", description="Daily order-to-cash exception report (read-only)")
    ap.add_argument("--days", type=int, default=int(os.environ.get("O2C_DAYS", 7)), help="N: days before an order counts as not invoiced")
    ap.add_argument("--date", type=date.fromisoformat, help="report date (default: today in IST)")
    ap.add_argument("--instance", default=os.environ.get("AGENTSWITCH_INSTANCE"), help="label for the report, e.g. suryodaya")
    ap.add_argument("--out", type=Path, help="folder to write <instance>-<date>.md and .json; prints Markdown if omitted")
    args = ap.parse_args()

    rep = report.build(Client(), report_date=args.date, days=args.days, instance=args.instance)
    md = report.to_markdown(rep)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        stem = f"{args.instance or 'report'}-{rep['report_date']}"
        (args.out / f"{stem}.json").write_text(json.dumps(rep, indent=2))
        (args.out / f"{stem}.md").write_text(md)
        counts = ", ".join(f"{k}={len(v['rows'])}" if v["status"] == "ok" else f"{k}={v['status']}" for k, v in rep["sections"].items())
        print(f"wrote {args.out / stem}.md ({counts})")
    else:
        print(md)


if __name__ == "__main__":
    main()
