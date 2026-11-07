"""In-memory stand-ins for the platform and the model, used by every offline test."""

import copy
import json
import re
from datetime import date, datetime, timedelta, timezone

READ_TOOLS = frozenset({"EmailAccount.list", "Mailbox.list", "EmailMessage.list", "EmailMessage.get",
                        "Calendar.list", "CalendarEvent.list", "Task.list", "Project.get", "Project.list"})
WRITE_TOOLS = frozenset({"EmailMessage.create"})
ALLOWED = READ_TOOLS | WRITE_TOOLS

# Arguments that steer paging/presentation rather than filter rows.
NON_FILTER_KEYS = {"limit", "offset", "sort", "order", "order_by", "sort_by", "sort_order", "fields"}
OPERATORS = ("lte:", "gte:", "lt:", "gt:", "eq:", "ne:", "between:")


class FakeRefused(AssertionError):
    """Raised by the fake when code under test calls a tool the spec does not allow."""


def make_mcp_error(kind: str, message: str, code: int | None = None):
    from ea_briefing.mcp import McpError
    err = McpError.__new__(McpError)
    Exception.__init__(err, message)
    err.code = code
    err.kind = kind
    err.message = message
    return err


_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?\s*(Z|[+-]\d{2}:?\d{2})?)?$")


def parse_dt(text: str) -> datetime | None:
    """Lenient ISO parser (Z, +0530, 1-6 fraction digits, space separator, date-only); naive means UTC."""
    m = _DT_RE.match(text.strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss, frac, off = m.groups()
    micro = int((frac or "0").ljust(6, "0"))
    tz = timezone.utc
    if off and off != "Z":
        sign = -1 if off[0] == "-" else 1
        digits = off[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
    try:
        return datetime(int(y), int(mo), int(d), int(hh or 0), int(mi or 0), int(ss or 0), micro, tzinfo=tz)
    except ValueError:
        return None


def _parse_temporal(value, today: date):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    if value.strip() == "today":
        return datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    return parse_dt(value)


def _matches(field_value, expected, today: date) -> bool:
    if isinstance(expected, str):
        for op in OPERATORS:
            if expected.startswith(op):
                operand = expected[len(op):]
                left = _parse_temporal(field_value, today)
                if left is None:
                    return False
                if op == "between:":
                    lo_s, _, hi_s = operand.partition(",")
                    lo, hi = _parse_temporal(lo_s, today), _parse_temporal(hi_s, today)
                    return lo is not None and hi is not None and lo <= left <= hi
                right = _parse_temporal(operand, today)
                if right is None:
                    return False
                return {"lt:": left < right, "lte:": left <= right, "gt:": left > right, "gte:": left >= right,
                        "eq:": left == right, "ne:": left != right}[op]
        if "," in expected:
            return field_value is not None and str(field_value) in [p.strip() for p in expected.split(",")]
        if isinstance(field_value, bool) or field_value is None:
            return str(field_value).lower() == expected.lower() if field_value is not None else False
        return str(field_value) == expected
    if expected is None:
        return field_value is None
    if isinstance(expected, bool) or isinstance(field_value, bool):
        return field_value is expected or field_value == expected and type(field_value) is type(expected)
    return field_value == expected


class FakeClient:
    def __init__(self, me: dict, tables: dict | None = None, today: date | None = None):
        self._me = dict(me)
        self.tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}
        self.today = today or date(2026, 11, 4)
        self.calls = []          # list of (name, arguments-copy)
        self.refused = []        # tool names the fake refused
        self.failures = {}       # tool name -> McpError to raise
        self.ignored_filters = set()   # fields the "server" silently ignores
        self.total_override = {}       # tool name -> total to report (a lying server)
        self.me_calls = 0
        self._next_id = 1

    # -- configuration helpers -------------------------------------------------
    def fail(self, name: str, kind: str = "forbidden", message: str = "simulated failure", code: int | None = None):
        self.failures[name] = make_mcp_error(kind, message, code)

    def add(self, entity: str, *rows: dict):
        self.tables.setdefault(entity, []).extend(dict(r) for r in rows)

    # -- inspection helpers ----------------------------------------------------
    def calls_to(self, name: str) -> list:
        return [args for n, args in self.calls if n == name]

    def names(self) -> list:
        return [n for n, _ in self.calls]

    # -- client interface ------------------------------------------------------
    def me(self) -> dict:
        self.me_calls += 1
        return dict(self._me)

    def call(self, name: str, arguments: dict | None = None) -> dict:
        args = copy.deepcopy(arguments) if arguments else {}
        self.calls.append((name, args))
        if name not in ALLOWED:
            self.refused.append(name)
            raise FakeRefused(f"tool not on the allow-list: {name}")
        if name == "EmailMessage.create" and not (args.get("folder") == "drafts" and args.get("is_draft") is True):
            self.refused.append(name)
            raise FakeRefused("EmailMessage.create outside drafts")
        if name in self.failures:
            raise self.failures[name]
        entity, _, verb = name.partition(".")
        if entity not in self.tables:
            # A real server answers an unregistered tool with -32601; never invent an empty table.
            raise make_mcp_error("not_found", f"{name}: Tool not found", -32601)
        if verb == "list":
            return self._list(name, entity, args)
        if verb == "get":
            return self._get(entity, args)
        if verb == "create":
            return self._create(entity, args)
        raise FakeRefused(f"unsupported verb {name}")

    def _list(self, name: str, entity: str, args: dict) -> dict:
        rows = self.tables.get(entity, [])
        for key, expected in args.items():
            if key in NON_FILTER_KEYS or key in self.ignored_filters:
                continue
            rows = [r for r in rows if _matches(r.get(key), expected, self.today)]
        total = self.total_override.get(name, len(rows))
        limit = args.get("limit", 1000)
        offset = args.get("offset", 0) or 0
        limit = max(0, min(int(limit), 1000))
        page = [] if limit == 0 else rows[int(offset):int(offset) + limit]
        return {"data": copy.deepcopy(page), "total": total, "limit": limit, "offset": offset}

    def _get(self, entity: str, args: dict) -> dict:
        wanted = args.get("id")
        if wanted is None and len(args) == 1:
            wanted = next(iter(args.values()))
        for r in self.tables.get(entity, []):
            if r.get("id") == wanted:
                return copy.deepcopy(r)
        raise make_mcp_error("not_found", f"{entity} {wanted} not found", -32004)

    def _create(self, entity: str, args: dict) -> dict:
        row = copy.deepcopy(args)
        row.setdefault("id", f"created-{self._next_id}")
        self._next_id += 1
        self.tables.setdefault(entity, []).append(row)
        return copy.deepcopy(row)


class FakeLLM:
    """Scripted model: a list of replies (str or Exception) consumed in order, or a function(system, user)."""

    def __init__(self, replies=None, fn=None):
        self.replies = list(replies or [])
        self.fn = fn
        self.calls = []   # list of (system, user)

    @property
    def systems(self) -> list:
        return [s for s, _ in self.calls]

    @property
    def users(self) -> list:
        return [u for _, u in self.calls]

    def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.fn is not None:
            out = self.fn(system, user)
        elif self.replies:
            out = self.replies.pop(0)
        else:
            raise AssertionError("FakeLLM ran out of scripted replies")
        if isinstance(out, BaseException):
            raise out
        if isinstance(out, dict):
            return json.dumps(out)
        return out


class FakeOpener:
    """Injectable HTTP opener: (url, data, headers, method, timeout) -> (status, body_bytes)."""

    def __init__(self, responses=None, fn=None):
        self.responses = list(responses or [])
        self.fn = fn
        self.calls = []   # dicts with url, data, headers, method, timeout

    def __call__(self, *args, **kwargs):
        names = ["url", "data", "headers", "method", "timeout"]
        rec = dict(zip(names, args))
        for k, v in kwargs.items():
            key = {"data_bytes": "data", "body": "data", "payload": "data"}.get(k, k)
            rec[key] = v
        self.calls.append(rec)
        if self.fn is not None:
            out = self.fn(rec)
        elif self.responses:
            out = self.responses.pop(0)
        else:
            raise AssertionError("FakeOpener ran out of scripted responses")
        if isinstance(out, BaseException):
            raise out
        status, body = out
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        return status, body

    def json_bodies(self) -> list:
        out = []
        for c in self.calls:
            data = c.get("data")
            out.append(json.loads(data) if data else None)
        return out

    def header(self, index: int, name: str):
        headers = self.calls[index].get("headers") or {}
        for k, v in dict(headers).items():
            if k.lower() == name.lower():
                return v
        return None


def rpc_ok(payload: dict) -> tuple:
    return 200, {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": payload}}


def rpc_text(*chunks: str) -> tuple:
    return 200, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": c} for c in chunks]}}


def rpc_error(code: int, message: str, data_code: str | None = None) -> tuple:
    err = {"code": code, "message": message}
    if data_code:
        err["data"] = {"code": data_code}
    return 200, {"jsonrpc": "2.0", "id": 1, "error": err}
