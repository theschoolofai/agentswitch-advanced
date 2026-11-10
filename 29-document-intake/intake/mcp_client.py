"""Read-only MCP client for the AgentSwitch systems.

A write guard runs before anything is sent. A call goes through only if the
platform says the tool's risk class is READ. Everything else is refused,
including posting tools such as Bill.submit and any tool whose risk class is
missing or cannot be looked up. Writes will get their own reviewed path later.

The client never logs in, so it cannot use up password attempts, and it never
retries a rejected token. Stdlib only.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

DEFAULT_BASE_URLS = {
    "suryodaya": "https://agentswitch.theschoolofai.in",
    "keystone": "https://class.agentswitch.theschoolofai.in",
}
SEAT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# The lookup the guard itself depends on. It is read-only.
_DESCRIBE_TOOL = "tools.describe"

# Refused by name whatever label the platform gives them. The risk class check below
# still applies to the rest.
_NEVER_CALL = re.compile(
    r"\.(?:submit|open|close|post|send\w*|reply|approve\w*|accept|reject|extract|mark_\w+|record_\w+|apply_to_\w+|"
    r"delete\w*|void\w*|cancel\w*)(?:\.|$)",
    re.I,
)

# Takes the request body; returns (HTTP status, response text).
Transport = Callable[[bytes], "tuple[int, str]"]


class IntakeClientError(Exception):
    """Base class for errors from this client."""


class ConfigError(IntakeClientError):
    """The system or its token is not configured."""


class GuardRefused(IntakeClientError):
    """The write guard refused the call. Nothing was sent."""


class AuthError(IntakeClientError):
    """The platform rejected the token. Log in again; this is not retried."""


class TransportError(IntakeClientError):
    """The platform could not be reached or sent an unreadable reply."""


class ToolError(IntakeClientError):
    """The platform answered with an error."""

    def __init__(self, tool: str, code: str, message: str):
        super().__init__(f"{tool}: {code}: {message}")
        self.tool = tool
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Settings:
    system: str
    base_url: str
    token: str = field(repr=False)


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and not key.startswith("#"):
            values[key.strip()] = value.strip()
    return values


def load_settings(
    system: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    env_file: Path = SEAT_ENV_FILE,
) -> Settings:
    """Find the token for a harness run or a local run.

    A harness run sets AGENTSWITCH_TOKEN and AGENTSWITCH_BASE_URL (see
    34-eval-harness/TASK_FORMAT.md). A local run names a system and reads
    AGENTSWITCH_<SYSTEM>_TOKEN from the environment or the git-ignored .env.
    """
    env = os.environ if env is None else env
    token, base_url = env.get("AGENTSWITCH_TOKEN"), env.get("AGENTSWITCH_BASE_URL")
    if token and base_url:
        return Settings(system or env.get("AGENTSWITCH_INSTANCE", ""), base_url, token)

    if system not in DEFAULT_BASE_URLS:
        raise ConfigError(f"Unknown system {system!r}. Use one of {sorted(DEFAULT_BASE_URLS)}.")
    name = f"AGENTSWITCH_{system.upper()}_TOKEN"
    token = env.get(name) or _read_env_file(env_file).get(name)
    if not token:
        raise ConfigError(f"{name} is not set. Log in and put the token in the environment or .env.")
    return Settings(system, DEFAULT_BASE_URLS[system], token)


def _http_transport(settings: Settings, timeout_seconds: int = 90) -> Transport:
    url = settings.base_url.rstrip("/") + "/api/mcp"
    headers = {
        "Authorization": "Bearer " + settings.token,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "seat29-intake",
    }

    def send(body: bytes) -> "tuple[int, str]":
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            try:
                with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                    return response.status, response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as error:
                return error.code, error.read().decode("utf-8", "replace")
        # A connection can fail while connecting or drop partway through a reply.
        except (OSError, http.client.HTTPException) as error:
            raise TransportError(f"Could not reach the platform: {error!r}") from None

    return send


def _last_event_data(text: str) -> str:
    """Return the data of the last event. One event's data may span several lines."""
    events, lines = [], []
    for line in [*text.splitlines(), ""]:
        if line.startswith("data:"):
            lines.append(line[5:].removeprefix(" "))
        elif not line and lines:
            events.append("\n".join(lines))
            lines = []
    return events[-1] if events else ""


def _decode(text: str) -> Any:
    """Parse a JSON reply or an event-stream reply."""
    stripped = text.lstrip()
    if stripped.startswith(("data:", "event:")):
        stripped = _last_event_data(stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        raise TransportError("The platform sent a reply that is not JSON.") from None


class McpClient:
    def __init__(self, settings: Settings, transport: Optional[Transport] = None):
        self.system = settings.system
        self._transport = transport or _http_transport(settings)
        self._next_id = 0
        self._risk_classes: dict[str, Optional[str]] = {}

    def call_tool(self, name: str, arguments: Optional[Mapping[str, Any]] = None) -> Any:
        """Call a tool if the guard allows it. Raises GuardRefused otherwise."""
        self._check_guard(name)
        return self._send_tool_call(name, arguments or {})

    def _check_guard(self, name: str) -> None:
        if name == _DESCRIBE_TOOL:
            return
        if _NEVER_CALL.search(name):
            raise GuardRefused(f"{name}: this kind of action is never allowed from this client.")
        risk_class = self._risk_class(name)
        if risk_class != "READ":
            raise GuardRefused(f"{name}: risk class {risk_class or 'unknown'} is not allowed.")

    def _risk_class(self, name: str) -> Optional[str]:
        if name not in self._risk_classes:
            try:
                reply = self._send_tool_call(_DESCRIBE_TOOL, {"names": [name]})
            except ToolError:
                raise GuardRefused(f"{name}: could not look up its risk class.") from None
            results = reply.get("results", []) if isinstance(reply, dict) else []
            found = next((row for row in results if row.get("name") == name), {})
            risk_class = found.get("risk_class")
            self._risk_classes[name] = risk_class.upper() if isinstance(risk_class, str) else None
        return self._risk_classes[name]

    def _send_tool_call(self, name: str, arguments: Mapping[str, Any]) -> Any:
        self._next_id += 1
        body = json.dumps({
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": dict(arguments)},
        }).encode()
        status, text = self._transport(body)
        if status == 401:
            raise AuthError(f"{self.system}: the token was rejected. Log in again.")
        return self._unwrap(name, status, _decode(text))

    @staticmethod
    def _unwrap(tool: str, status: int, reply: Any) -> Any:
        if not isinstance(reply, dict):
            raise TransportError(f"{tool}: unexpected reply shape (HTTP {status}).")
        error = reply.get("error")
        if error is not None:
            details = error if isinstance(error, dict) else {"message": str(error)}
            data = details.get("data") if isinstance(details.get("data"), dict) else {}
            code = data.get("code") or details.get("code") or f"http_{status}"
            raise ToolError(tool, str(code), str(details.get("message", "")))
        result = reply.get("result")
        if not isinstance(result, dict) or "content" not in result:
            if status >= 400:
                raise ToolError(tool, f"http_{status}", str(reply.get("detail", "")))
            return result
        text = "\n".join(
            part.get("text", "") for part in result["content"] if part.get("type") == "text"
        )
        if result.get("isError"):
            raise ToolError(tool, "tool_error", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
