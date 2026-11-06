"""Read-only MCP client for AgentSwitch.

Only tools on the read allowlist can be called. Anything else raises
WriteBlocked before a request is sent, so the report can never change a record.
"""
import json
import os
import urllib.request

READ_SUFFIXES = (".list", ".get")
READ_TOOLS = {"tools.list", "tools.search", "tools.describe", "endpoint.make.thread"}
PAGE_SIZE = 500


class WriteBlocked(Exception):
    pass


class McpError(Exception):
    pass


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

    def call(self, name, args=None):
        if not is_read_tool(name):
            raise WriteBlocked(f"{name} is not a read tool; the report is read-only")
        result = self._rpc("tools/call", {"name": name, "arguments": args or {}})
        if result.get("isError"):
            raise McpError(result["content"][0]["text"])
        return result.get("structuredContent") or json.loads(result["content"][0]["text"])

    def list_all(self, entity, filters=None):
        """Page through Entity.list and return every row."""
        rows, offset = [], 0
        while True:
            page = self.call(f"{entity}.list", {**(filters or {}), "limit": PAGE_SIZE, "offset": offset})
            data = page.get("data", [])
            rows.extend(data)
            offset += len(data)
            if not data or offset >= page.get("total", 0):
                return rows
