"""Minimal MCP (JSON-RPC over HTTP POST) client for AgentSwitch.

A JSON-RPC error still arrives as HTTP 200, so every call inspects the envelope.
"""
import http.client
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request

from . import config

PROTOCOL_VERSION = "2025-11-25"
TOKEN_DIR = config.ROOT / ".tokens"

CONNECT_RETRIES = 3
CONNECT_BACKOFF_SECONDS = 2.0
GATEWAY_ERRORS = {502, 503, 504}

# A table read with no filter still has to end. Hitting this is a bug in the caller's filters, not a big table.
LIST_ALL_MAX_ROWS = 5000


class McpError(Exception):
    def __init__(self, code, message, data=None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data or {}

    @property
    def kind(self) -> str:
        if isinstance(self.data, dict) and self.data.get("code"):
            return self.data["code"]
        if "permission" in self.message.lower() or "cannot perform" in self.message.lower():
            return "permission_denied"
        if self.code == -32601 or "unknown tool" in self.message.lower():
            return "unknown_tool"
        return "error"


class AuthExpired(Exception):
    pass


class RowPage(list):
    """Rows, plus whether they are all of them. A plain list to every caller."""
    total: int | None = None
    truncated: bool = False


def _decode(raw: bytes, content_type: str):
    """JSON body, or the last `data:` event of an SSE body: the MCP endpoint may answer either way, since we
    accept both as the streamable-HTTP transport requires."""
    if content_type.startswith("text/event-stream"):
        # One event's data may span several `data:` lines; a blank line ends the event.
        events, lines = [], []
        for line in [*raw.decode().splitlines(), ""]:
            if line.startswith("data:"):
                lines.append(line[5:].removeprefix(" "))
            elif not line and lines:
                events.append("\n".join(lines))
                lines = []
        return json.loads(events[-1]) if events else None
    return json.loads(raw or b"null")


def _http(url, body=None, token=None, method=None, timeout=120, retries=CONNECT_RETRIES, read_only=None):
    """read_only: retry gateway errors too. Defaults to True for bodiless requests (GET). A gateway error on a
    write may come after the server applied it, so writes are never retried on 502/503/504."""
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    if read_only is None:
        read_only = data is None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, _decode(resp.read(), resp.headers.get("Content-Type", ""))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise AuthExpired(url) from e
            if read_only and e.code in GATEWAY_ERRORS and attempt < retries:
                time.sleep(CONNECT_BACKOFF_SECONDS * (attempt + 1))
                continue
            try:
                payload = json.loads(e.read() or b"null")
            except ValueError:
                payload = None
            return e.code, payload
        except urllib.error.URLError:
            # Raised only while connecting or sending, before any response exists, so a retry cannot repeat a
            # write the server processed. A timeout waiting for the response is a TimeoutError and is not retried.
            if attempt == retries:
                raise
            time.sleep(CONNECT_BACKOFF_SECONDS * (attempt + 1))
        except (http.client.IncompleteRead, ConnectionResetError):
            # The connection dropped mid-response after the server finished the request: only a read may repeat.
            if not read_only or attempt == retries:
                raise
            time.sleep(CONNECT_BACKOFF_SECONDS * (attempt + 1))


class Session:
    """Login for one instance. Tokens are cached under .tokens/ (git-ignored), one file per instance.

    Under the harness runner the runner's base URL and seat token are used as given: no password, no login, no
    token file, and only the one instance that run serves.
    """

    def __init__(self, instance: str):
        if instance not in config.INSTANCES:
            raise ValueError(f"unknown instance {instance!r}")
        self.instance = instance
        self._lock = threading.Lock()
        self.platform = config.platform()
        if self.platform:
            if instance != self.platform["instance"]:
                raise ValueError(f"this run serves {self.platform['instance']} only, not {instance}")
            self.base, self.token, self._token_file = self.platform["base"], self.platform["token"], None
            return
        self.base = config.INSTANCES[instance]
        self._token_file = TOKEN_DIR / f"seat35-{instance}.token"
        self.token = self._token_file.read_text().strip() if self._token_file.exists() else None
        if not self.token:
            self.login()

    def login(self):
        if self.platform:
            # The runner's token is all a platform run has: there is no password to fall back on.
            raise RuntimeError(f"{self.base} rejected the harness runner's token (401)")
        email, password = config.credentials(self.instance)
        # Ten wrong passwords in 15 minutes lock the account, so a failed login is never retried here.
        try:
            status, payload = _http(f"{self.base}/api/auth/login", {"email": email, "password": password}, retries=0)
        except AuthExpired:
            # On the login endpoint a 401 means wrong credentials, not an expired token: re-logging in would only
            # spend another of the ten tries.
            # The login name stays out of the message: failure output gets pasted into chats and bug reports.
            raise RuntimeError(
                f"login failed on {self.instance}: HTTP 401 (check SEAT35_EMAIL and the password)") from None
        if status != 200 or not payload or "token" not in payload:
            raise RuntimeError(f"login failed on {self.instance}: HTTP {status}")
        self.token = payload["token"]
        TOKEN_DIR.mkdir(exist_ok=True)
        # A new private file replacing the old one: rewriting in place would keep an existing file's looser mode,
        # and would follow a symlink left in its place.
        fd, tmp = tempfile.mkstemp(dir=TOKEN_DIR, prefix=".token.")  # created 0600
        try:
            with os.fdopen(fd, "w") as f:
                f.write(self.token)
            os.replace(tmp, self._token_file)
        except BaseException:
            os.unlink(tmp)
            raise
        return payload

    def with_reauth(self, fn):
        # Taken before the call: a token refreshed by another call while this one was in flight is not stale.
        stale = self.token
        try:
            return fn()
        except AuthExpired:
            with self._lock:
                # Concurrent calls share one session: whoever gets here first logs in again, the rest reuse it.
                if self.token == stale:
                    self.login()
            return fn()


class McpClient:
    def __init__(self, session: Session):
        self.session = session
        self._id = 0
        self._lock = threading.Lock()
        self._tools = None
        self.session.with_reauth(self._initialize)

    def _is_read_only(self, method, params) -> bool:
        if method in ("initialize", "tools/list"):
            return True
        return method == "tools/call" and self.allows(params["name"])

    def _rpc(self, method, params=None):
        with self._lock:
            self._id += 1
            request_id = self._id
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        status, payload = _http(f"{self.session.base}/api/mcp", body, self.session.token,
                                read_only=self._is_read_only(method, params))
        if status != 200 or payload is None:
            raise McpError(status, f"HTTP {status}", payload)
        if "error" in payload:
            err = payload["error"]
            raise McpError(err.get("code"), err.get("message", ""), err.get("data"))
        return payload.get("result")

    def _initialize(self):
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "seat35-data-steward", "version": "0.1"},
        })

    def tools(self) -> dict[str, dict]:
        if self._tools is None:
            result = self.session.with_reauth(lambda: self._rpc("tools/list"))
            self._tools = {t["name"]: t for t in result.get("tools", [])}
        return self._tools

    def tool_names(self) -> set[str]:
        return set(self.tools())

    def has_tool(self, name: str) -> bool:
        return name in self.tool_names()

    def allows(self, name: str) -> bool:
        """Only tools the platform itself marks read-only and non-destructive. The seat's login can see update
        tools for parties and items, and those are not marked destructive, so read-only is the test that counts.
        A tool missing from the list, or missing either mark, is refused."""
        hints = (self.tools().get(name) or {}).get("annotations") or {}
        return hints.get("readOnlyHint") is True and hints.get("destructiveHint") is False

    def call(self, name: str, arguments: dict | None = None):
        if not self.allows(name):
            raise McpError("refused", f"{name} is not a read-only tool; this agent never changes a record",
                           {"code": "refused"})
        result = self.session.with_reauth(
            lambda: self._rpc("tools/call", {"name": name, "arguments": arguments or {}}))
        if not isinstance(result, dict):
            raise McpError("bad_reply", f"{name} returned no result", result)
        blocks = result.get("content")
        if result.get("structuredContent") is not None:
            content = result["structuredContent"]
        elif not (isinstance(blocks, list) and all(isinstance(b, dict) for b in blocks)):
            content = result  # some tools return the record itself as the result
        else:
            text = "".join(c.get("text", "") for c in blocks)
            try:
                content = json.loads(text)
            except ValueError:
                content = {"text": text}
        if result.get("isError"):
            raise McpError("tool_error", json.dumps(content)[:500], content)
        return content

    def list_all(self, entity: str, page: int = 200, max_rows: int = LIST_ALL_MAX_ROWS, **filters) -> RowPage:
        """Every matching row, up to a ceiling that is never crossed silently: `RowPage.truncated` says it was hit,
        because a partial table that reads as a whole one would hide duplicates in the rows left behind."""
        rows, offset, total, seen = RowPage(), 0, None, set()
        while True:
            res = self.call(f"{entity}.list", {"limit": page, "offset": offset, **filters})
            if isinstance(res, dict) and not isinstance(res.get("data"), list):
                # call() turns a non-JSON reply into {"text": ...}; reading that as an empty table would hide rows.
                raise McpError("bad_reply", f"{entity}.list returned no rows list", res)
            batch = res["data"] if isinstance(res, dict) else res
            if isinstance(res, dict) and res.get("total") is not None:
                total = res["total"]
            ids = {str(r.get("id")) for r in batch if isinstance(r, dict)}
            if ids and ids <= seen:
                # The same rows again: the server ignored the offset, and paging on would only repeat them.
                raise McpError("bad_reply", f"{entity}.list repeated a page (offset ignored)", None)
            seen |= ids
            rows.extend(batch[:max(0, max_rows - len(rows))])
            offset += len(batch)
            # A short page is not the end: a server may cap a page below the requested limit. Only an empty page,
            # or reaching the reported total, is.
            exhausted = not batch or (total is not None and offset >= total)
            if exhausted and offset <= len(rows):
                rows.total = total if total is not None else len(rows)
                rows.truncated = rows.total > len(rows)
                return rows
            if len(rows) >= max_rows:
                # Rows were left behind, or may be: without a total the table's size is unknown.
                rows.total = total
                rows.truncated = True
                return rows
