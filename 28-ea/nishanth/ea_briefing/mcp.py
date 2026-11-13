"""MCP (JSON-RPC over HTTP POST) client for AgentSwitch, restricted to an allow-list of tools."""
import http.client
import json
import re
import time
import urllib.error
import urllib.request

READ_TOOLS = frozenset({
    "EmailAccount.list", "Mailbox.list", "EmailMessage.list", "EmailMessage.get", "Calendar.list",
    "CalendarEvent.list", "Task.list", "Project.get", "Project.list",
})
WRITE_TOOLS = frozenset({"EmailMessage.create"})

KINDS = frozenset({"not_found", "forbidden", "invalid", "http", "network", "tool_error", "refused", "auth"})
RETRY_STATUSES = {502, 503, 504}
READ_RETRIES = 2

# JSON-RPC codes seen when the error envelope carries no `data.code`.
_RPC_KINDS = {-32700: "invalid", -32600: "invalid", -32602: "invalid", -32601: "not_found"}


class McpError(Exception):
    """Accepts `McpError(message)`, `McpError(kind, message)`, or keywords `kind=`, `message=`, `code=`."""

    def __init__(self, *args, kind: str | None = None, message: str | None = None, code: int | None = None):
        for a in args:
            if isinstance(a, int) and not isinstance(a, bool) and code is None:
                code = a
            elif isinstance(a, str) and kind is None and a in KINDS:
                kind = a
            elif message is None:
                message = str(a)
        self.kind = kind or "tool_error"
        self.message = message or self.kind
        self.code = code
        super().__init__(f"{self.kind}: {self.message}")


class ToolNotAllowed(McpError):
    def __init__(self, message: str = "tool not allowed", **kw):
        kw["kind"] = "refused"
        super().__init__(message=message, **kw)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # A followed redirect would replay the Authorization header to whatever host the Location names.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def urllib_opener(url: str, data: bytes | None, headers: dict, method: str, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b""


NETWORK_ERRORS = (OSError, http.client.HTTPException)

# Filter values are parsed by the server (commas mean OR, "lt:" etc. are operators), so only plain server-issued
# ids may ever be used as one. Anything from mail content is matched locally instead.
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def safe_id(value) -> str | int | None:
    """The value if it is a uuid-like server id (or an int), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _ID.match(value) and value.lower() != "today":
        return value
    return None


def _decode(body: bytes):
    text = body.decode("utf-8", "replace").strip()
    # We advertise text/event-stream (the server wants both in Accept), so a reply may come back as SSE frames.
    if text.startswith(("event:", "data:", "id:")):
        frames = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
        text = frames[-1] if frames else ""
    return json.loads(text)


def _status_kind(status: int) -> str:
    # 3xx lands here too: redirects are never followed, so the bearer token cannot leave the configured host.
    return {401: "auth", 403: "forbidden", 404: "not_found"}.get(status, "http")


class McpClient:
    def __init__(self, base_url: str, token: str, timeout: float = 60, opener=None):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self.opener = opener or urllib_opener
        self.sleep = time.sleep
        self.instance = None
        self._me = None
        self._id = 0

    def __repr__(self) -> str:
        return f"McpClient({self.base_url!r})"

    @classmethod
    def login(cls, base_url: str, email: str, password: str, timeout: float = 60, opener=None) -> "McpClient":
        # Ten wrong passwords lock the account, so this is one attempt and nothing retries it.
        opener = opener or urllib_opener
        url = base_url.rstrip("/") + "/api/auth/login"
        data = json.dumps({"email": email, "password": password}).encode()
        try:
            status, body = opener(url, data, {"Content-Type": "application/json", "Accept": "application/json"},
                                  "POST", timeout)
        except NETWORK_ERRORS as e:
            raise McpError(kind="network", message=f"login request failed ({type(e).__name__}); not retried") from None
        token = None
        if status == 200:
            try:
                payload = _decode(body)
                token = payload.get("token") if isinstance(payload, dict) else None
            except ValueError:
                pass
        if not token:
            raise McpError(kind="auth" if status in (400, 401, 403) else "http", code=status,
                           message=f"login failed: HTTP {status}; not retried (repeated failures lock the account)")
        return cls(base_url, token, timeout=timeout, opener=opener)

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {self._token}"}

    def me(self) -> dict:
        if self._me is None:
            try:
                status, body = self.opener(self.base_url + "/api/auth/me", None, self._headers(), "GET", self.timeout)
            except NETWORK_ERRORS as e:
                raise McpError(kind="network", message=f"/api/auth/me failed ({type(e).__name__})") from None
            if status == 401:
                raise McpError(kind="auth", code=401, message="token rejected (HTTP 401); log in again")
            if status != 200:
                raise McpError(kind=_status_kind(status), code=status, message=f"/api/auth/me: HTTP {status}")
            try:
                me = _decode(body)
            except ValueError:
                raise McpError(kind="http", code=status, message="/api/auth/me: non-JSON body") from None
            if not isinstance(me, dict):
                raise McpError(kind="http", code=status, message="/api/auth/me: unexpected body")
            self._me = me
        return self._me

    def call(self, name: str, arguments: dict | None = None) -> dict:
        if name not in READ_TOOLS and name not in WRITE_TOOLS:
            raise ToolNotAllowed(f"tool {name!r} is not on the allow-list")
        arguments = dict(arguments or {})
        is_write = name in WRITE_TOOLS
        if name == "EmailMessage.create" and not (arguments.get("folder") == "drafts"
                                                  and arguments.get("is_draft") is True):
            raise ToolNotAllowed("EmailMessage.create is allowed only with folder 'drafts' and is_draft true")
        self._id += 1
        data = json.dumps({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}}).encode()
        attempts = 1 if is_write else 1 + READ_RETRIES
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                status, body = self.opener(self.base_url + "/api/mcp", data, self._headers(), "POST", self.timeout)
            except NETWORK_ERRORS as e:
                if not last:
                    self.sleep(0.5 * (attempt + 1))
                    continue
                hint = "; a write is never retried and may or may not have been applied" if is_write else ""
                raise McpError(kind="network", message=f"{name}: {type(e).__name__}{hint}") from None
            if status in RETRY_STATUSES and not last:
                self.sleep(0.5 * (attempt + 1))
                continue
            return self._parse(name, status, body, paged="limit" in arguments)
        raise McpError(kind="network", message=f"{name}: no attempts made")  # unreachable

    def _parse(self, name: str, status: int, body: bytes, paged: bool = False) -> dict:
        if status == 401:
            raise McpError(kind="auth", code=401, message=f"{name}: token rejected (HTTP 401); log in again")
        if status != 200:
            raise McpError(kind=_status_kind(status), code=status, message=f"{name}: HTTP {status}")
        try:
            envelope = _decode(body)
        except ValueError:
            raise McpError(kind="http", code=status, message=f"{name}: non-JSON response body") from None
        if not isinstance(envelope, dict):
            raise McpError(kind="http", code=status, message=f"{name}: unexpected response body")
        # The platform reports tool and permission errors as HTTP 200 with a JSON-RPC error envelope.
        err = envelope.get("error")
        if err:
            err = err if isinstance(err, dict) else {"message": str(err)}
            code = err.get("code") if isinstance(err.get("code"), int) else None
            data = err.get("data") if isinstance(err.get("data"), dict) else {}
            kind = data.get("code") or _RPC_KINDS.get(code, "tool_error")
            raise McpError(kind=str(kind), code=code, message=f"{name}: {err.get('message') or 'error'}")
        result = envelope.get("result")
        if not isinstance(result, dict):
            raise McpError(kind="http", code=status, message=f"{name}: response has no result")
        content = result.get("content")
        if content is None:
            content = []
        if not isinstance(content, list) or not all(isinstance(c, dict) for c in content):
            raise McpError(kind="http", code=status, message=f"{name}: malformed result content")
        texts = [c.get("text") for c in content if c.get("type", "text") == "text"]
        if any(not isinstance(t, str) for t in texts):
            raise McpError(kind="http", code=status, message=f"{name}: result content text is not a string")
        text = "".join(t for t in texts if t)
        if result.get("isError"):
            raise McpError(kind="tool_error", message=f"{name}: {text[:300] or 'tool reported an error'}")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            return self._check_shape(name, structured, paged)
        if structured is not None and not text:
            raise McpError(kind="http", code=status, message=f"{name}: structuredContent is not an object")
        if not text:
            payload = {}
        else:
            try:
                payload = json.loads(text)
            except ValueError:
                payload = {"text": text}
            if not isinstance(payload, dict):
                payload = {"data": payload}
        return self._check_shape(name, payload, paged)

    @staticmethod
    def _check_shape(name: str, payload: dict, paged: bool) -> dict:
        # A paged list reply without a numeric total cannot be told apart from "nothing there", so it is an error.
        if name.endswith(".list"):
            if paged:
                _total(name, payload)
            if payload.get("data") is not None and not isinstance(payload["data"], list):
                raise McpError(kind="http", message=f"{name}: list data is not a list")
        return payload


def _total(tool: str, payload) -> int:
    total = payload.get("total") if isinstance(payload, dict) else None
    if isinstance(total, bool) or not isinstance(total, (int, float, str)):
        raise McpError(kind="http", message=f"{tool}: list result has no usable total")
    try:
        number = int(total)
    except (TypeError, ValueError):
        raise McpError(kind="http", message=f"{tool}: list total {str(total)[:40]!r} is not a number") from None
    if number < 0 or (isinstance(total, float) and total != number):
        raise McpError(kind="http", message=f"{tool}: list total {total!r} is not a count")
    return number


def list_capped(client, tool: str, filters: dict, cap: int = 200, page: int = 100) -> dict:
    """Up to `cap` rows. The first page also carries the total, so there is no separate count call: each platform call
    costs about 2 s, and most lists fit in one page. Rows already received are never thrown away because the
    server's numbers disagree with them."""
    filters = dict(filters or {})
    if cap <= 0 or page <= 0:
        total = _total(tool, client.call(tool, {**filters, "limit": 0}))
        return {"rows": [], "total": total, "truncated": total > max(cap, 0)}
    rows: list = []
    ids: set = set()
    offset, reported, more = 0, None, False
    while len(rows) < cap and (reported is None or len(rows) < reported):
        limit = min(page, cap - len(rows))
        payload = client.call(tool, {**filters, "limit": limit, "offset": offset})
        if reported is None:
            # A reply without a usable total cannot be told apart from "nothing there", so it is an error.
            reported = _total(tool, payload)
        batch = payload.get("data") if isinstance(payload, dict) else None
        if batch is None and reported == 0:
            batch = []
        if not isinstance(batch, list) or not all(isinstance(r, dict) for r in batch):
            raise McpError(kind="http", message=f"{tool}: list data is not a list of objects")
        if not batch:
            break
        full = len(batch) >= limit
        batch = batch[:limit]
        fresh = [r for r in batch if r.get("id") is None or r.get("id") not in ids]
        rows.extend(fresh)
        ids.update(r["id"] for r in fresh if r.get("id") is not None)
        if len(fresh) < len(batch):
            # Rows seen before: the server ignored the offset. Paging further would only repeat them.
            more = True
            break
        offset += len(batch)
        if len(rows) > reported:
            # The total was too low; keep what arrived, and a full page means there may be more.
            more = more or full
            break
    total = max(reported or 0, len(rows))
    return {"rows": rows[:cap], "total": total, "truncated": total > cap or more}
