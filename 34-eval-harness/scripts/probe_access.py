"""Read-only probe: what can the seat 34 login actually reach on each AgentSwitch system?

Why: docs and chat disagree about our access (knowledge base, invoices, parties, an empty tool list).
We check live instead of trusting what is written.

What it does, per system (both systems run at the same time):
  1. Logs in once. A refused login stops that system at once (no retry: ten wrong tries lock the account).
  2. Reads a few REST pages: who we are, the locale, entity schemas, the agent tools.
  3. Opens one MCP session, lists our tools, and makes 1-row reads of the entities other seats use.
  4. Moves the last snapshot to data/platform/<system>/previous/ (so scripts/platform_sync.py can
     compare), then writes the raw answers to data/platform/<system>/ (git-ignored) and a short
     data/platform/access-summary.md. Row values are never saved, only counts and field names.

Safety: every MCP call passes `assert_read_only` first, so the probe cannot change a record.

Run:  uv run python scripts/platform_sync.py     (runs this probe, then reports changes; needs .env)
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Literal

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import Tool
from pydantic import BaseModel, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

SEAT_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = SEAT_DIR / "data" / "platform"

INSTANCES = ("suryodaya", "keystone")  # web addresses come from .env (AS_<SYSTEM>_URL)
VERSION_PAGES = ("/openapi.json", "/api/version")
CALL_TIMEOUT_S = 90
REST_PAGES = {
    "me": "/api/auth/me",
    "locale": "/api/accounting/locale",
    "display_locale": "/api/accounting/display-locale",
    "schemas": "/api/schemas",
    "agent_tools": "/api/agent/tools",
}
# Entities seats 31 and 35 read, plus agent records and the bug list.
ENTITIES = [
    "SalesOrder",
    "Invoice",
    "PaymentReceived",
    "Party",
    "Item",
    "Company",
    "AgentSeat",
    "AgentJob",
    "AgentJobStep",
    "AgentTask",
    "AgentSkill",
    "AgentToolPolicy",
    "BugReport",
    "Note",
]
OTHER_READS: dict[str, dict[str, Any]] = {
    "TeamHarness.get_mine": {},
    "HarnessRun.list_mine": {},
    "events.catalog": {},
    "tools.search": {"query": "knowledge"},
}
KB_WORDS = ("knowledge", "kb", "vault", "note", "article", "wiki")
READ_SUFFIXES = (".list", ".get", ".get_mine", ".list_mine")
META_READS = {"tools.search", "tools.describe", "events.catalog"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=SEAT_DIR / ".env", env_prefix="AS_", extra="ignore")
    email: str
    suryodaya_password: SecretStr
    keystone_password: SecretStr
    suryodaya_url: str
    keystone_url: str

    def url(self, instance: str) -> str:
        base: str = getattr(self, f"{instance}_url")
        return base.rstrip("/")

    def password(self, instance: str) -> str:
        secret: SecretStr = getattr(self, f"{instance}_password")
        return secret.get_secret_value()


class LoginFailed(Exception):
    """The platform refused our login. We never retry, to avoid the lockout."""


class RefusedWrite(Exception):
    """A tool that is not a read was about to be called."""


class Check(BaseModel):
    """The result of one read: reachable or not, how many rows, which fields. Never row values."""

    door: Literal["rest", "mcp"]
    name: str
    listed: bool | None = None  # MCP only: is the tool in our tools/list?
    ok: bool
    http_status: int | None = None
    error_code: str | None = None
    message: str | None = None
    total: int | None = None
    fields: list[str] = []


def assert_read_only(name: str, tool: Tool | None) -> None:
    """Refuse anything that is not clearly a read, before it is sent."""
    if tool is not None:
        meta = (tool.meta or {}).get("agentswitch", {})
        hinted = tool.annotations is not None and tool.annotations.read_only_hint is True
        if hinted or meta.get("risk") == "READ":
            return
        raise RefusedWrite(f"{name} is listed but not marked read-only; not calling it")
    if name in META_READS or name.endswith(READ_SUFFIXES):
        return  # not in our list: the server will refuse it, which is the fact we want to record
    raise RefusedWrite(f"{name} is not a read by name; not calling it")


def shape_of(payload: Any) -> tuple[int | None, list[str]]:
    """Count rows and list field names of the first row, without keeping any values."""
    if isinstance(payload, dict):
        rows = payload.get("data")
        if rows is None and isinstance(payload.get("result"), dict):
            rows = payload["result"].get("rows")
        if isinstance(rows, list):
            total = payload.get("total", len(rows))
            first = rows[0] if rows and isinstance(rows[0], dict) else {}
            return (total if isinstance(total, int) else len(rows)), sorted(first)
        return None, sorted(payload)
    if isinstance(payload, list):
        first = payload[0] if payload and isinstance(payload[0], dict) else {}
        return len(payload), sorted(first)
    return None, []


async def login(http: httpx2.AsyncClient, base: str, settings: Settings, instance: str) -> str:
    reply = await http.post(
        f"{base}/api/auth/login", json={"email": settings.email, "password": settings.password(instance)}
    )
    if reply.status_code != 200:
        raise LoginFailed(f"{instance}: login refused with HTTP {reply.status_code}: {reply.text[:200]}")
    token = reply.json().get("token")
    if not isinstance(token, str) or not token:
        raise LoginFailed(f"{instance}: login reply had no token")
    return token


async def read_rest(http: httpx2.AsyncClient, base: str, name: str, path: str, raw_dir: Path) -> Check:
    reply = await http.get(f"{base}{path}")
    try:
        payload: Any = reply.json()
    except ValueError:
        payload = reply.text[:500]
    ok = reply.status_code == 200
    if ok and name in REST_PAGES:  # keep whole pages (schemas, tools, me) locally for reference
        (raw_dir / f"rest-{name}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    total, fields = shape_of(payload) if ok else (None, [])
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return Check(
        door="rest",
        name=path,
        ok=ok,
        http_status=reply.status_code,
        message=None if ok else str(detail or payload)[:200],
        total=total,
        fields=fields,
    )


async def call_tool(client: Client, name: str, args: dict[str, Any], tools: dict[str, Tool]) -> Check:
    tool = tools.get(name)
    assert_read_only(name, tool)
    try:
        async with asyncio.timeout(CALL_TIMEOUT_S):
            result = await client.call_tool(name, args)
    except MCPError as e:  # JSON-RPC error: arrives inside an HTTP 200
        code = e.data.get("code") if isinstance(e.data, dict) else None
        return Check(
            door="mcp",
            name=name,
            listed=tool is not None,
            ok=False,
            error_code=str(code or e.code),
            message=e.message[:200],
        )
    except TimeoutError:
        return Check(door="mcp", name=name, listed=tool is not None, ok=False, error_code="timeout")
    payload: Any = result.structured_content
    if payload is None:
        text = "".join(getattr(c, "text", "") for c in result.content)
        try:
            payload = json.loads(text)
        except ValueError:
            payload = text
    if result.is_error:
        return Check(
            door="mcp",
            name=name,
            listed=tool is not None,
            ok=False,
            error_code="tool_error",
            message=str(payload)[:200],
        )
    total, fields = shape_of(payload)
    return Check(door="mcp", name=name, listed=tool is not None, ok=True, total=total, fields=fields)


def tolerate_schema_mismatches(client: Client, mismatches: dict[str, str]) -> None:
    """The SDK refuses a reply that breaks the tool's own output schema (seen as BUG-031 in Oct).
    We record the mismatch instead, so one bad schema does not hide whether the tool is reachable."""
    session = client.session
    strict = session.validate_tool_result

    async def tolerant(name: str, result: Any) -> None:
        try:
            await strict(name, result)
        except RuntimeError as e:
            mismatches.setdefault(name, str(e).splitlines()[0][:200])

    session.validate_tool_result = tolerant  # type: ignore[method-assign]


def tool_record(tool: Tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "risk": (tool.meta or {}).get("agentswitch", {}).get("risk"),
        "read_only": tool.annotations.read_only_hint if tool.annotations else None,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
    }


async def probe_mcp(base: str, token: str, raw_dir: Path) -> tuple[list[Check], dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}"}
    checks: list[Check] = []
    mismatches: dict[str, str] = {}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(60, read=120)) as http,
        Client(streamable_http_client(f"{base}/api/mcp", http_client=http), mode="legacy") as client,
    ):
        tolerate_schema_mismatches(client, mismatches)
        listed: list[Tool] = []
        cursor: str | None = None
        while True:
            page = await client.list_tools(cursor=cursor)
            listed.extend(page.tools)
            cursor = page.next_cursor
            if not cursor:
                break
        tools = {t.name: t for t in listed}
        (raw_dir / "mcp-tools.json").write_text(json.dumps([tool_record(t) for t in listed], indent=1))

        reads = {f"{e}.list": {"limit": 1} for e in ENTITIES} | OTHER_READS
        kb_tools = [n for n in tools if any(w in n.lower() for w in KB_WORDS) and n.endswith(".list")]
        reads |= {n: {"limit": 1} for n in kb_tools}
        for name, args in reads.items():  # one at a time: the platform answers calls in sequence
            checks.append(await call_tool(client, name, args, tools))
    facts = {
        "tool_count": len(tools),
        "kb_tools": kb_tools,
        "schema_mismatches": mismatches,
        "risk_counts": _risk_counts(listed),
    }
    return checks, facts


def _risk_counts(tools: list[Tool]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in tools:
        risk = str((t.meta or {}).get("agentswitch", {}).get("risk"))
        counts[risk] = counts.get(risk, 0) + 1
    return counts


def rotate_snapshot(raw_dir: Path) -> None:
    """Move the files of the last run into previous/, replacing the older copy, so a diff can compare."""
    files = [f for f in raw_dir.iterdir() if f.is_file()] if raw_dir.exists() else []
    if not files:
        return
    previous = raw_dir / "previous"
    if previous.exists():
        shutil.rmtree(previous)
    previous.mkdir()
    for f in files:
        f.rename(previous / f.name)


async def read_version(http: httpx2.AsyncClient, base: str) -> dict[str, Any]:
    """The platform version, if a read-only page reports one. "unknown" is a normal answer."""
    for path in VERSION_PAGES:
        try:
            reply = await http.get(f"{base}{path}")
            payload = reply.json() if reply.status_code == 200 else None
        except (httpx2.HTTPError, ValueError):
            continue
        if isinstance(payload, dict):
            info = payload["info"] if isinstance(payload.get("info"), dict) else payload
            version = info.get("version")
            if version:
                return {"source": path, "version": str(version)}
    return {"source": None, "version": "unknown"}


async def probe_instance(instance: str, settings: Settings) -> dict[str, Any]:
    base = settings.url(instance)
    raw_dir = OUT_DIR / instance
    async with httpx2.AsyncClient(timeout=httpx2.Timeout(60, read=120)) as anon:
        token = await login(anon, base, settings, instance)
    rotate_snapshot(raw_dir)  # only after a good login, so a failed run keeps the last snapshot in place
    raw_dir.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}, timeout=httpx2.Timeout(60, read=120)
    ) as http:
        (raw_dir / "version.json").write_text(json.dumps(await read_version(http, base)))
        for name, path in REST_PAGES.items():
            checks.append(await read_rest(http, base, name, path, raw_dir))
        for entity in ("SalesOrder", "Invoice", "PaymentReceived", "Party", "Item", "Note"):
            checks.append(await read_rest(http, base, f"list-{entity}", f"/api/{entity}?limit=1", raw_dir))
    mcp_checks, facts = await probe_mcp(base, token, raw_dir)
    checks += mcp_checks
    me = _read_json(raw_dir / "rest-me.json")
    facts |= {"roles": me.get("roles"), "allowed_apps": me.get("allowed_apps")}
    result = {"instance": instance, "facts": facts, "checks": [c.model_dump() for c in checks]}
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if token in text or settings.password(instance) in text:
        raise RuntimeError("a secret reached the probe output; nothing was written")
    (raw_dir / "probe.json").write_text(text)
    return result


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else {}


def summary_markdown(results: list[dict[str, Any]]) -> str:
    lines = ["# Seat 34 access summary (generated by scripts/probe_access.py)", ""]
    for r in results:
        f = r["facts"]
        lines += [
            f"## {r['instance']}",
            "",
            f"- allowed_apps: {f.get('allowed_apps')}",
            f"- roles: {f.get('roles')}",
            f"- MCP tools listed: {f.get('tool_count')} (by risk: {f.get('risk_counts')})",
            f"- knowledge-base-like tools: {f.get('kb_tools') or 'none'}",
            f"- output-schema mismatches: {list(f.get('schema_mismatches', {})) or 'none'}",
            "",
            "| Door | Read | Listed | Reachable | Rows | Error |",
            "|---|---|---|---|---|---|",
        ]
        for c in r["checks"]:
            err = c["error_code"] or (f"HTTP {c['http_status']}" if not c["ok"] else "")
            msg = f" {c['message']}" if c["message"] else ""
            lines.append(
                f"| {c['door']} | `{c['name']}` | {c['listed'] if c['listed'] is not None else '-'} "
                f"| {'yes' if c['ok'] else 'no'} | {c['total'] if c['total'] is not None else '-'} "
                f"| {err}{msg[:80]} |"
            )
        lines.append("")
    return "\n".join(lines)


def load_settings() -> Settings | None:
    """Read .env. On a problem, name the missing variables only: never echo values (they hold passwords)."""
    try:
        return Settings()  # values come from .env
    except ValidationError as e:
        names = sorted({"AS_" + "_".join(str(part) for part in err["loc"]).upper() for err in e.errors()})
        print(f"Missing or invalid in .env: {', '.join(names)} (see .env.example)", file=sys.stderr)
        return None


async def probe_all(settings: Settings) -> tuple[list[dict[str, Any]], list[BaseException]]:
    """Probe both systems at once. Returns the systems that were read and the failures."""
    outcomes = await asyncio.gather(*(probe_instance(i, settings) for i in INSTANCES), return_exceptions=True)
    results = [o for o in outcomes if isinstance(o, dict)]
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    for failure in failures:
        print(f"FAILED: {type(failure).__name__}: {failure}", file=sys.stderr)
    if results:
        (OUT_DIR / "access-summary.md").write_text(summary_markdown(results))
    for r in results:
        reachable = sum(c["ok"] for c in r["checks"])
        print(
            f"{r['instance']}: {reachable}/{len(r['checks'])} reads reachable, "
            f"{r['facts']['tool_count']} MCP tools listed"
        )
    return results, failures


async def main() -> int:
    settings = load_settings()
    if settings is None:
        return 2
    _, failures = await probe_all(settings)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
