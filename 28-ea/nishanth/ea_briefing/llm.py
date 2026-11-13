"""Provider-neutral model access, returned as a plain `(system, user) -> str` callable.

Two wire formats: `openai` (POST {url}/chat/completions) and `chat` (POST {url}/chat with the system prompt in its own
field, as the course gateway "glc" expects). `auto` tries `openai` and switches to `chat` for the rest of the run
when the server answers 404 or 405.
"""
import json
import threading
import time
from urllib.parse import urlsplit

from .mcp import NETWORK_ERRORS, urllib_opener

RETRY_STATUSES = {429, 500, 502, 503, 504}
BACKOFF = (1, 2, 4)  # seconds before retry 1, 2 and 3
REQUEST_TIMEOUT = 30
MAX_TOKENS = 700
TIME_LIMIT_MESSAGE = "time limit reached"
UNAVAILABLE_503 = "model unavailable (HTTP 503 — check the model name and the gateway)"
APIS = ("openai", "chat", "auto")


class LlmError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class _WrongApi(Exception):
    """404/405 from the openai path: the server speaks a different protocol (glc answers 404 there)."""

    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


def _wants_temperature(model: str | None) -> bool:
    # Newer reasoning models reject a temperature parameter; older chat models accept 0.
    name = (model or "").rsplit("/", 1)[-1].lower()
    return name.startswith(("gpt-4", "gpt-3"))


def _host(url: str) -> str:
    # describe() is printed; drop any user:password@ part so nothing secret can leak through it
    try:
        return urlsplit(url).hostname or "?"
    except ValueError:
        return "?"


class Llm:
    def __init__(self, settings: dict, deadline: float | None = None, opener=None, sleep=time.sleep,
                 clock=time.monotonic, parallel: int = 1):
        api = str(settings.get("api") or "auto").lower()
        if api not in APIS:
            raise ValueError(f"unknown model API {api!r}; expected one of {', '.join(APIS)}")
        self.base_url = str(settings["base_url"]).rstrip("/")
        self.key = settings.get("key") or None
        self.model = settings.get("model") or None
        self.mode = api
        # The openai protocol needs a model name; without one `auto` can only mean the gateway's own /chat.
        self.api = "chat" if api == "chat" or (api == "auto" and not self.model) else "openai"
        self.deadline = deadline
        self.opener = opener or urllib_opener
        self.sleep = sleep
        self.clock = clock
        self._lock = threading.Lock()  # calls run in parallel; the protocol switch must happen once, cleanly
        # One object serves every system, so this bounds requests in flight for the whole run (retries included).
        self._slots = threading.BoundedSemaphore(max(1, int(parallel or 1)))
        # In `auto` mode the first openai request is a probe; until it answers, other calls wait instead of each
        # collecting its own 404.
        self._decided = self.mode != "auto" or self.api == "chat"
        self._probe = threading.Lock()

    def describe(self) -> str:
        return f"{self.api} API at {_host(self.base_url)}, model {self.model or '(server default)'}"

    def __call__(self, system: str, user: str) -> str:
        if not self._decided:
            with self._probe:
                if not self._decided:
                    return self._call(system, user)
        return self._call(system, user)

    def _call(self, system: str, user: str) -> str:
        with self._lock:
            api = self.api
        if api == "openai":
            try:
                out = self._request("openai", system, user)
                self._decided = True
                return out
            except _WrongApi as e:
                if self.mode != "auto":
                    raise LlmError("http", f"model request failed: HTTP {e.status}") from None
                with self._lock:
                    self.api = "chat"  # remembered: later calls in this run go straight to /chat
                    self._decided = True
        return self._request("chat", system, user)

    def _left(self) -> float | None:
        return None if self.deadline is None else self.deadline - self.clock()

    def _body(self, api: str, system: str, user: str) -> tuple[str, bytes]:
        if api == "openai":
            body = {"model": self.model, "max_tokens": MAX_TOKENS,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            url = self.base_url + "/chat/completions"
        else:
            # glc silently drops a role "system" message, so the prompt must travel in `system`.
            body = {"system": system, "messages": [{"role": "user", "content": user}], "max_tokens": MAX_TOKENS}
            if self.model:
                body["model"] = self.model
            url = self.base_url + "/chat"
        if _wants_temperature(self.model):
            body["temperature"] = 0
        return url, json.dumps(body).encode()

    def _request(self, api: str, system: str, user: str) -> str:
        with self._slots:
            return self._request_locked(api, system, user)

    def _request_locked(self, api: str, system: str, user: str) -> str:
        url, data = self._body(api, system, user)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        problem, last_status = "no attempt made", None
        for attempt in range(len(BACKOFF) + 1):
            if attempt:
                wait = BACKOFF[attempt - 1]
                left = self._left()
                if left is not None and left <= wait:
                    problem += " (no time left to retry)"
                    break
                self.sleep(wait)
            left = self._left()
            if left is not None and left <= 0:
                if attempt == 0:
                    raise LlmError("time_limit", TIME_LIMIT_MESSAGE)
                problem += " (no time left to retry)"
                break
            timeout = REQUEST_TIMEOUT if left is None else min(REQUEST_TIMEOUT, left)
            try:
                status, raw = self.opener(url, data, headers, "POST", timeout)
            except NETWORK_ERRORS as e:
                problem, last_status = f"network error ({type(e).__name__})", None
                continue
            if status in RETRY_STATUSES:
                problem, last_status = f"HTTP {status}", status
                continue
            if 300 <= status < 400:
                # Redirects are not followed: the API key must only ever go to the configured host.
                raise LlmError("http", f"model request was redirected (HTTP {status}); not followed")
            if status in (404, 405) and api == "openai":
                raise _WrongApi(status)
            if status != 200:
                raise LlmError("http", f"model request failed: HTTP {status}")
            return self._parse(api, raw)
        if last_status == 503:
            # glc answers 503 for an unknown model name as well as when it is busy
            raise LlmError("http", UNAVAILABLE_503 + (" (no time left to retry)" if "no time" in problem else ""))
        raise LlmError("network" if problem.startswith("network") else "http",
                       f"model request failed: {problem}")

    @staticmethod
    def _parse(api: str, raw: bytes) -> str:
        try:
            payload = json.loads(raw)
            content = payload["choices"][0]["message"]["content"] if api == "openai" else payload["text"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LlmError("invalid", "model response was not in the expected shape") from None
        if not isinstance(content, str):
            raise LlmError("invalid", "model response had no text content")
        return content


def make_llm(settings: dict, deadline: float | None = None, opener=None, sleep=time.sleep, clock=time.monotonic,
             parallel: int = 1):
    """`parallel`: most requests in flight at once, across every caller of this object."""
    return Llm(settings, deadline=deadline, opener=opener, sleep=sleep, clock=clock, parallel=parallel)
