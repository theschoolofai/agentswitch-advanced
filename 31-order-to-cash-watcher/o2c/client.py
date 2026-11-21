"""Read-only MCP client for AgentSwitch.

Only tools on the read allowlist can be called. Anything else raises
WriteBlocked before a request is sent, so the report can never change a record.
"""
import hashlib
import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from .values import display_text, reject_json_constant

READ_SUFFIXES = (".list", ".get")
READ_TOOLS = {"tools.list", "tools.search", "tools.describe", "endpoint.make.thread"}
# The platform's maximum (19 Nov: limit 1000 accepted, 1001 refused). Bigger pages mean fewer
# multi-page reads, which are the only reads that can see the data change half-way (D5).
PAGE_SIZE = 1000
# A broken endpoint must not keep the report fetching indefinitely.
MAX_PAGES = 1000
# Bug hunt D1 (19 Nov): a read is retried after a transient failure, with backoff. Writes are
# never retried (a retried draft create could save the same draft twice).
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS = (1, 2, 4)        # seconds before the 2nd, 3rd and 4th try
RETRY_AFTER_MAX = 30            # cap on a server's Retry-After
RETRY_BUDGET = 90               # stop retrying once a request has taken this long in total


class WriteBlocked(Exception):
    pass


class McpError(Exception):
    pass


class PaginationError(McpError):
    """A list response cannot establish complete, consistent coverage."""



class UnstablePaginationError(PaginationError):
    """A changing source may succeed after a bounded full restart."""


class PlatformUnavailable(McpError):
    """The platform could not be reached or kept failing after the bounded retries."""


def is_read_tool(name):
    return name in READ_TOOLS or name.endswith(READ_SUFFIXES)


class Client:
    def __init__(self, base_url=None, token=None, timeout=60):
        for name, value in (("AGENTSWITCH_BASE_URL", base_url), ("AGENTSWITCH_TOKEN", token)):
            if not (value or os.environ.get(name)):
                raise McpError(f"{name} is not set")
        # Bug hunt E1 (20 Nov): a token with a stray carriage return (a .env saved with Windows line
        # endings) made urllib raise a traceback that printed the whole token. Settings are checked
        # here, and the error names the setting, never its value.
        self.base_url = (base_url or os.environ["AGENTSWITCH_BASE_URL"]).strip().rstrip("/")
        self.token = (token or os.environ["AGENTSWITCH_TOKEN"]).strip()
        if not self.token or any(ord(c) < 33 or ord(c) == 127 for c in self.token):
            raise McpError("AGENTSWITCH_TOKEN contains spaces or control characters "
                           "(check the .env file for Windows line endings)")
        parts = urllib.parse.urlsplit(self.base_url)
        if parts.scheme not in ("http", "https") or not parts.netloc or any(ord(c) < 33 for c in self.base_url):
            raise McpError("AGENTSWITCH_BASE_URL must be an http:// or https:// address")
        self.timeout = timeout
        self._id = 0
        self._sleep = time.sleep

    def _rpc(self, method, params):
        """One JSON-RPC request. Reads are retried after transient failures (D1); every failure
        surfaces as an McpError with a short reason, never the token or record data (D2, D3)."""
        self._id += 1
        request_id = self._id
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode()
        name = params.get("name") if isinstance(params, dict) else None
        what = f"{method} {name}" if name else method
        retry = method == "tools/list" or (method == "tools/call" and isinstance(name, str) and is_read_tool(name))
        delays = RETRY_DELAYS if retry else ()
        started = time.monotonic()
        self._try_timeout = None
        for attempt in range(len(delays) + 1):
            try:
                status, ctype, raw = self._post(body)
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise McpError(f"{what}: HTTP {e.code}, the token was rejected (check AGENTSWITCH_TOKEN)") from None
                reason = f"HTTP {e.code} {e.reason}"
                transient = e.code in RETRY_STATUS
                wait_hint = _retry_after(e.headers)
            except (urllib.error.URLError, http.client.HTTPException, ConnectionError, socket.timeout, TimeoutError) as e:
                reason = _transport_reason(e)
                transient, wait_hint = True, None
            if not transient:
                raise McpError(f"{what}: {reason}") from None
            wait = min(max(delays[attempt], wait_hint or 0), RETRY_AFTER_MAX) if attempt < len(delays) else 0
            # Review of #54: the budget holds for the whole request. The next try starts only if it can begin
            # inside the budget, and its timeout is cut to what is left, so a read stops by about 90 s.
            left = RETRY_BUDGET - (time.monotonic() - started) - wait
            if attempt == len(delays) or left < 1:
                tries = attempt + 1
                raise PlatformUnavailable(f"{what}: {reason}" + (f" after {tries} tries" if tries > 1 else "")) from None
            self._sleep(wait)
            self._try_timeout = min(self.timeout, left)
        msg = _response_message(raw, ctype, status, request_id, what)
        if "error" in msg:
            error = msg["error"]
            text = error.get("message") if isinstance(error, dict) else None
            raise McpError(f"{what}: {text or json.dumps(error)[:200]}")
        if not isinstance(msg.get("result"), dict):
            raise McpError(f"{what}: reply has no result")
        return msg["result"]

    def _post(self, body):
        req = urllib.request.Request(
            self.base_url + "/api/mcp",
            body,
            {
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=getattr(self, "_try_timeout", None) or self.timeout) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode("utf-8", "replace")

    def tool_names(self):
        return {t["name"] for t in self._rpc("tools/list", {}).get("tools", [])}

    def tool_schemas(self):
        """{tool name: set of input field names}, from tools/list (read only)."""
        return {t["name"]: set(((t.get("inputSchema") or {}).get("properties") or {}))
                for t in self._rpc("tools/list", {}).get("tools", [])}

    def call(self, name, args=None):
        if not is_read_tool(name):
            raise WriteBlocked(f"{name} is not a read tool; the report is read-only")
        return tool_result(self._rpc("tools/call", {"name": name, "arguments": args or {}}), name)

    def list_all(self, entity, filters=None, max_pages=MAX_PAGES):
        """Retry an unstable read twice from offset zero; never expose partial rows.

        Bug hunt D5 (19 Nov): if another login deletes one record behind our cursor and adds one
        ahead of it between two pages, the total stays the same and nothing repeats, so a
        multi-page read could return a full-length list that misses a record. A read that took
        more than one page is therefore read again, and the two lists of record ids must match;
        otherwise the read restarts (at most three attempts in all).
        """
        for attempt in range(3):
            try:
                rows, pages = self._read_pages(entity, filters, max_pages)
                if pages > 1:
                    again, _ = self._read_pages(entity, filters, max_pages)
                    if _identity(rows) != _identity(again):
                        raise UnstablePaginationError(
                            f"{entity}.list pagination incomplete: records changed during a multi-page read")
                return rows
            except UnstablePaginationError:
                if attempt == 2:
                    raise

    def _list_all_once(self, entity, filters=None, max_pages=MAX_PAGES):
        """One complete read (all pages), without the D5 re-read. Returns the rows."""
        return self._read_pages(entity, filters, max_pages)[0]

    def _read_pages(self, entity, filters=None, max_pages=MAX_PAGES):
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
        rows, offset, pages = [], 0, 0
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
            pages += 1
            # Equality, not a short page, is our completion condition. The valid
            # empty-table case (zero rows, total zero) also completes here.
            if offset == total:
                return rows, pages
        invalid("page limit reached before total was reached")


EXIT_PLATFORM = 3   # the platform could not be read; 2 is bad options (argparse)


def platform_failure(prog, error):
    """One line on stderr and exit 3, instead of a traceback (bug hunt D2). Seat 34's harness
    shows the last output line as the reason."""
    import sys
    # The server's message is outside text: no escape sequences reach the terminal (E2).
    print(f"{prog}: could not complete: {display_text(error)}", file=sys.stderr)
    raise SystemExit(EXIT_PLATFORM)


def _identity(rows):
    """What two reads of a list must agree on (D5): the record ids in order, or the rows
    themselves for records without an id."""
    return [json.dumps(r.get("id"), sort_keys=True) if r.get("id") is not None
            else hashlib.sha256(json.dumps(r, sort_keys=True, default=str).encode("utf-8")).hexdigest() for r in rows]


def _retry_after(headers):
    """Seconds from a Retry-After header, or None (HTTP dates are ignored)."""
    try:
        value = float((headers or {}).get("Retry-After"))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _transport_reason(e):
    reason = getattr(e, "reason", None) or e
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "no answer before the timeout"
    return f"could not connect ({type(reason).__name__}: {str(reason)[:80]})"


def _response_message(raw, ctype, status, request_id, what):
    """The JSON-RPC message answering `request_id`. An event stream may carry notifications
    before or after the response; they are skipped (bug hunt D3)."""
    # An event's data may span several "data:" lines, joined with newlines (SSE rules; bug hunt G3).
    payloads, current = [], []
    for line in raw.splitlines() + [""]:
        if line.startswith("data:"):
            current.append(line[6:] if line[5:6] == " " else line[5:])   # one space only (SSE rules)
        elif not line.strip() and current:
            payloads.append("\n".join(current))   # as sent; json.loads ignores surrounding whitespace
            current = []
    candidates = payloads if payloads else [raw]
    messages = []
    for text in candidates:
        try:
            messages.append(json.loads(text, parse_constant=reject_json_constant))
        except ValueError:
            continue
    if not messages:
        kind = (ctype or "unknown type").split(";")[0]
        raise McpError(f"{what}: the reply was not JSON (HTTP {status}, {kind})")
    for msg in messages:
        if isinstance(msg, dict) and msg.get("id") == request_id and ("result" in msg or "error" in msg):
            return msg
    raise McpError(f"{what}: no reply to this request in the response")


def tool_result(result, name="tool"):
    """The data of a tools/call result, or McpError with the server's message (D3)."""
    content = result.get("content") if isinstance(result.get("content"), list) else []
    text = next((c.get("text") for c in content if isinstance(c, dict) and isinstance(c.get("text"), str)), None)
    if result.get("isError"):
        raise McpError(f"{name}: {(text or 'the server reported an error with no message')[:300]}")
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    if text is None:
        raise McpError(f"{name}: the result has no data")
    try:
        return json.loads(text, parse_constant=reject_json_constant)
    except ValueError:
        raise McpError(f"{name}: the result is not JSON") from None
