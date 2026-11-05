"""Check the login and the write guard on a live system.

Run from 29-document-intake:  python -m intake.probe suryodaya keystone

It makes read-only calls and prints counts only, never record contents. It also
asks the guard to refuse Bill.submit, which is never sent to the platform.
"""
from __future__ import annotations

import sys

from .mcp_client import GuardRefused, IntakeClientError, McpClient, load_settings

BILL_INTAKE_QUEUE = "endpoint.accounting.bill_intake.queue"
PLACEHOLDER_ID = "00000000-0000-0000-0000-000000000000"


def probe(client: McpClient) -> None:
    bills = client.call_tool("Bill.list", {"limit": 1})
    documents = client.call_tool("AcctDocument.list", {"limit": 1})
    queue = client.call_tool(BILL_INTAKE_QUEUE, {"state": "all", "limit": 1})
    print(f"{client.system}: login ok")
    print(f"  bills: {bills['total']}")
    print(f"  accounting documents: {documents['total']}")
    print(f"  intake queue: {queue['result']['window']['total']}")
    try:
        client.call_tool("Bill.submit", {"id": PLACEHOLDER_ID})
    except GuardRefused as refusal:
        print(f"  guard: refused, nothing sent ({refusal})")
    else:
        raise SystemExit(f"{client.system}: the guard let Bill.submit through.")


def main(systems: list[str]) -> int:
    if not systems:
        print(__doc__)
        return 2
    failed = False
    for system in systems:
        try:
            probe(McpClient(load_settings(system)))
        except IntakeClientError as error:
            print(f"{system}: {type(error).__name__}: {error}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
