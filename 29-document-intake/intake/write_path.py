"""The only route to a write, and for now it works on a harness copy only.

The read-only client refuses every write. This adds a short named list of writes,
each with the name of whoever approved it, and only when the run is on a
throwaway copy: AGENTSWITCH_RUN_ID must be set, and the base URL must not be either
live system. On live data it refuses everything until the course team allows
writes there. It never allows a posting tool, whatever the platform labels it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

from .mcp_client import DEFAULT_BASE_URLS, GuardRefused, McpClient, Settings

BILL_INTAKE = "endpoint.accounting.bill_intake."
EXTRACT, ACCEPT = BILL_INTAKE + "extract", BILL_INTAKE + "accept"
CREATE_PARTY = "Party.create"
ALLOWED_WRITES = frozenset({EXTRACT, ACCEPT, CREATE_PARTY})
# Anything this path creates on a copy carries this label, so it is easy to find.
TEST_LABEL = "[seat29-harness]"
LIVE_HOSTS = frozenset(urlparse(url).hostname for url in DEFAULT_BASE_URLS.values())


class WriteRefused(GuardRefused):
    """The write path refused the call. Nothing was sent."""


@dataclass(frozen=True)
class WriteRecord:
    tool: str
    approved_by: str


def copy_problem(settings: Settings, env: Optional[Mapping[str, str]] = None) -> Optional[str]:
    """Return why writes are not allowed here, or None on a harness copy."""
    env = os.environ if env is None else env
    if not env.get("AGENTSWITCH_RUN_ID"):
        return "not a harness run (no AGENTSWITCH_RUN_ID)"
    if env.get("AGENTSWITCH_BASE_URL") != settings.base_url:
        return "the client was not set up from the harness settings"
    host = urlparse(settings.base_url).hostname
    if not host or host in LIVE_HOSTS:
        return "the base URL is a live system"
    return None


class ApprovedWrites:
    def __init__(self, client: McpClient, settings: Settings, env: Optional[Mapping[str, str]] = None):
        problem = copy_problem(settings, env)
        if problem:
            raise WriteRefused(f"Writes are not allowed: {problem}.")
        self._client = client
        self.records: list[WriteRecord] = []

    def call(self, name: str, arguments: Mapping[str, Any], approved_by: str) -> Any:
        if name not in ALLOWED_WRITES:
            raise WriteRefused(f"{name}: not on the write path's list.")
        if not approved_by.strip():
            raise WriteRefused(f"{name}: a write needs whoever approved it.")
        if name == CREATE_PARTY and not str(arguments.get("name", "")).startswith(TEST_LABEL):
            raise WriteRefused(f"{name}: a Party made here must be labelled {TEST_LABEL}.")
        risk_class = self._client._risk_class(name)
        if risk_class != "WRITE":
            raise WriteRefused(f"{name}: risk class {risk_class or 'unknown'} is not allowed.")
        self.records.append(WriteRecord(name, approved_by))
        return self._client._send_tool_call(name, arguments)
