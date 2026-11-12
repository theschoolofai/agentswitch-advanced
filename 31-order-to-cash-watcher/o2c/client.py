"""Read-only MCP client for AgentSwitch.

Only tools on the read allowlist can be called. Anything else raises
WriteBlocked before a request is sent, so the report can never change a record.
"""
import hashlib
import json
import os
import urllib.request

READ_SUFFIXES = (".list", ".get")
READ_TOOLS = {"tools.list", "tools.search", "tools.describe", "endpoint.make.thread"}
PAGE_SIZE = 500
# A broken endpoint must not keep the report fetching indefinitely.
MAX_PAGES = 1000


class WriteBlocked(Exception):
    pass


class McpError(Exception):
    pass


class PaginationError(McpError):
    """A list response cannot establish complete, consistent coverage."""



class UnstablePaginationError(PaginationError):
    """A changing source may succeed after a bounded full restart."""

def is_read_tool(name):
    return name in READ_TOOLS or name.endswith(READ_SUFFIXES)


class Client:
    def __init__(self, base_url=None, token=None, timeout=60):
        self.base_url = (base_url or os.environ["AGENTSWITCH_BASE_URL"]).rstrip("/")
        self.token = token or os.environ["AGENTSWITCH_TOKEN"]
        self.timeout = timeout
        self._id = 0

    def _rpc(self, method, params):
        self._id += 1
        body = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        req = urllib.request.Request(
            self.base_url + "/api/mcp",
            body.encode(),
            {
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode()
        # The server may answer as an SSE stream; keep the last data line.
        for line in raw.splitlines():
            if line.startswith("data:"):
                raw = line[5:]
        msg = json.loads(raw)
        if "error" in msg:
            raise McpError(json.dumps(msg["error"]))
        return msg["result"]

    def tool_names(self):
        return {t["name"] for t in self._rpc("tools/list", {}).get("tools", [])}

    def tool_schemas(self):
        """{tool name: set of input field names}, from tools/list (read only)."""
        return {t["name"]: set(((t.get("inputSchema") or {}).get("properties") or {}))
                for t in self._rpc("tools/list", {}).get("tools", [])}

    def call(self, name, args=None):
        if not is_read_tool(name):
            raise WriteBlocked(f"{name} is not a read tool; the report is read-only")
        result = self._rpc("tools/call", {"name": name, "arguments": args or {}})
        if result.get("isError"):
            raise McpError(result["content"][0]["text"])
        return result.get("structuredContent") or json.loads(result["content"][0]["text"])

    def list_all(self, entity, filters=None, max_pages=MAX_PAGES):
        """Retry an unstable read twice from offset zero; never expose partial rows."""
        for attempt in range(3):
            try:
                return self._list_all_once(entity, filters, max_pages)
            except UnstablePaginationError:
                if attempt == 2:
                    raise

    def _list_all_once(self, entity, filters=None, max_pages=MAX_PAGES):
        """Return rows only after all pages satisfy the advertised integer total.

        Every page must carry data and a consistent nonnegative total. Missing
        metadata, repeated records/pages and early exhaustion are errors, never
        a partial success. A short page alone does not establish completion.

        The accumulated rows stay private to this call until completion. If a
        later page fails, callers get an exception instead of a shorter list
        that could be mistaken for the full financial report. These checks
        detect observed inconsistencies; they do not create a database snapshot.
        """
        if isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages <= 0:
            raise ValueError("max_pages must be a positive integer")
        rows, offset = [], 0
        expected_total = None
        seen_ids, seen_pages = set(), set()

        def invalid(reason, unstable=False):
            # Report protocol facts only; never include customer rows or tokens.
            error = UnstablePaginationError if unstable else PaginationError
            raise error(f"{entity}.list pagination incomplete: {reason}")

        for _ in range(max_pages):
            # The client owns paging. Caller-supplied filters cannot skip the
            # first records or override the page size through offset/limit.
            page = self.call(f"{entity}.list", {**(filters or {}), "limit": PAGE_SIZE, "offset": offset,
                                                     "sort_by": "id", "sort_order": "asc"})
            if not isinstance(page, dict):
                invalid("response is not an object")
            data, total = page.get("data"), page.get("total")
            # An absent data field is a malformed response, not an empty table.
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                invalid("data must be a list of record objects")
            # bool is a subclass of int in Python; True is not a valid row count.
            # Missing totals are deliberately errors: we cannot prove coverage.
            if isinstance(total, bool) or not isinstance(total, int) or total < 0:
                invalid("total must be a nonnegative integer on every page")
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                # The source may have changed while we read it. Restart the whole read
                # rather than combine pages with different advertised counts.
                invalid("total changed during pagination", unstable=True)
            if offset + len(data) > total:
                invalid("returned row count exceeds total")
            if not data and offset < total:
                # End-of-data contradicts the advertised count. Returning here
                # would hide the missing records as a successful report.
                invalid("empty page before total was reached")
            if data:
                # Detect an endpoint ignoring offset, even on rows without IDs.
                # Canonical key ordering avoids differences in dictionary order;
                # retain only a digest rather than another copy of customer data.
                fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).digest()
                if fingerprint in seen_pages:
                    invalid("repeated page", unstable=True)
                seen_pages.add(fingerprint)
                for row in data:
                    if row.get("id") is not None:
                        # Pages can overlap without being identical. Such overlap
                        # can inflate totals and conceal a record we never read.
                        record_id = json.dumps(row["id"], sort_keys=True)
                        if record_id in seen_ids:
                            invalid("duplicate record id", unstable=True)
                        seen_ids.add(record_id)
            # Accept a page only after all its checks pass. Advance by the actual
            # row count because a server may return less than the requested limit.
            rows.extend(data)
            offset += len(data)
            # Equality, not a short page, is our completion condition. The valid
            # empty-table case (zero rows, total zero) also completes here.
            if offset == total:
                return rows
        invalid("page limit reached before total was reached")
