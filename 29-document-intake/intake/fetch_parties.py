"""Save the Party records that the vendor check compares against.

Run from 29-document-intake:  python -m intake.fetch_parties suryodaya keystone

It makes read-only calls and prints counts only. It never sees a document, so no
document text can reach a query. From Party it keeps ids, names, the supplier role
and any GSTIN the platform shows us. From Bill it keeps a count per vendor id and
nothing else. Output goes to the git-ignored local/ folder, because it holds names.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from .mcp_client import IntakeClientError, McpClient, load_settings

PAGE_SIZE = 1000
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")


class IncompleteRead(IntakeClientError):
    """The platform returned fewer records than it reported. A partial list could mislead the check."""


def read_all(client: McpClient, tool: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    while True:
        reply = client.call_tool(tool, {"limit": PAGE_SIZE, "offset": len(rows)})
        page = next((reply[key] for key in ("items", "data") if isinstance(reply.get(key), list)), None)
        total = reply.get("total")
        if page is None or not isinstance(total, int):
            raise IncompleteRead(f"{tool}: the reply has no record list or total.")
        rows.extend(page)
        if len(rows) >= total:
            return rows
        if not page:
            raise IncompleteRead(f"{tool}: read {len(rows)} of {total}.")


def _is_supplier(party: Mapping[str, Any]) -> bool:
    return any(isinstance(role, dict) and role.get("role") == "supplier" and role.get("active")
               for role in party.get("roles") or [])


def _visible_tax_ids(party: Mapping[str, Any]) -> list[str]:
    """Keep a GSTIN only where the platform shows one."""
    if "gst_no" in (party.get("_redacted_fields") or []):
        return []
    value = party.get("gst_no")
    return [value] if isinstance(value, str) and GSTIN.match(value) else []


def build_records(system: str, parties: list[dict[str, Any]], bills: list[dict[str, Any]],
                  now: Optional[datetime] = None) -> dict[str, Any]:
    bill_counts = collections.Counter(bill.get("vendor_id") for bill in bills)
    return {
        "system": system,
        "fetched_at": (now or datetime.now(timezone.utc)).isoformat(),
        "parties": [
            {
                "id": party["id"],
                "names": [name for name in (party.get("name"), party.get("company_name")) if name],
                "is_supplier": _is_supplier(party),
                "bill_count": bill_counts[party["id"]],
                "tax_ids": _visible_tax_ids(party),
            }
            for party in parties
        ],
    }


def fetch(system: str, out_dir: Path) -> None:
    client = McpClient(load_settings(system))
    parties, bills = read_all(client, "Party.list"), read_all(client, "Bill.list")
    records = build_records(system, parties, bills)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"parties_{system}.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    rows = records["parties"]
    print(f"{system}: saved {len(rows)} parties, from {len(bills)} bills")
    print(f"  active supplier role: {sum(row['is_supplier'] for row in rows)}")
    print(f"  on a bill without that role: {sum(bool(row['bill_count']) and not row['is_supplier'] for row in rows)}")
    print(f"  GSTIN visible to this login: {sum(bool(row['tax_ids']) for row in rows)}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("systems", nargs="+")
    parser.add_argument("--out-dir", type=Path, default=Path("local"))
    args = parser.parse_args(argv)
    failed = False
    for system in args.systems:
        try:
            fetch(system, args.out_dir)
        except IntakeClientError as error:
            print(f"{system}: {type(error).__name__}: {error}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
