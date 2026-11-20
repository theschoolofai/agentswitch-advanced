"""Provider-neutral model access, returned as a plain `(system, user) -> str` callable.

Two wire formats: `openai` (POST {url}/chat/completions) and `chat` (POST {url}/chat with the system prompt in its own
field, as the course gateway "glc" expects). `auto` tries `openai` and switches to `chat` for the rest of the run
when the server answers 404 or 405 there (unless `/chat` answers 404 or 405 too: then the model name is unknown).

Settings follow the course agent contract (34-eval-harness/docs/processed/evaluation/agent-contract.md):
- `models`: OPENAI_MODEL may name several models, tried in order. The next one is tried only when the current one
  fails on the model side (an HTTP error other than 401/403), never past the run's deadline, and a model that failed
  is not tried again in this run. Absent: just `model`.
- `extra_body`: a JSON object sent with every request (OPENAI_EXTRA_BODY, provider quirks). Our own fields win.
After a connection failure that outlasts the retries (not a timeout), the endpoint counts as unreachable and the rest
of the run makes no model request.
"""
import json
import socket
import threading
import time
import urllib.error
from urllib.parse import urlsplit

from .mcp import NETWORK_ERRORS, urllib_opener

RETRY_STATUSES = {429, 500, 502, 503, 504}
BACKOFF = (1, 2, 4)  # seconds before retry 1, 2 and 3
REQUEST_TIMEOUT = 30
MAX_TOKENS = 700
TIME_LIMIT_MESSAGE = "time limit reached"
UNAVAILABLE_503 = "model unavailable (HTTP 503 — check the model name and the gateway)"
UNREACHABLE_MESSAGE = "model endpoint unreachable earlier in this run; not tried again"
APIS = ("openai", "chat", "auto")
# A key problem is the same for every model, so these never move on to the next model.
_KEY_STATUSES = (401, 403)


class LlmError(Exception):
    def __init__(self, kind: str, message: str, status: int | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status  # the final HTTP status, when the failure was one


class _WrongApi(Exception):
    """404/405 from the openai path: the server speaks a different protocol (glc answers 404 there)."""

    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


def _wants_temperature(model: str | None) -> bool:
    # Newer reasoning models reject a temperature parameter; older chat models accept 0.
    name = (model or "").rsplit("/", 1)[-1].lower()
    return name.startswith(("gpt-4", "gpt-3"))


def _is_timeout(exc: BaseException) -> bool:
    # socket.timeout is TimeoutError from 3.10; urllib wraps a connect timeout in URLError(reason=timeout)
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else None
    return isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(reason, (TimeoutError, socket.timeout))


def _models(settings: dict) -> list[str]:
    """`models` when it is a non-empty list of names (duplicates dropped, order kept), else `model`, else none."""
    listed = settings.get("models")
    if isinstance(listed, (list, tuple)):
        names = [m.strip() for m in listed if isinstance(m, str) and m.strip()]
        if names:
            return list(dict.fromkeys(names))
    model = settings.get("model")
    return [model.strip()] if isinstance(model, str) and model.strip() else []


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
        self.key = str(settings.get("key") or "").strip() or None  # a stray newline would break the header
        self.models = _models(settings)
        self.model = self.models[0] if self.models else None  # the first choice; `current_model` is the one in use
        extra = settings.get("extra_body")
        if extra is not None and not isinstance(extra, dict):
            raise ValueError("extra_body must be a JSON object")
        self.extra_body = dict(extra or {})
        self._index = 0  # into `models`; only moves forward
        self._unreachable = False
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

    @property
    def current_model(self) -> str | None:
        with self._lock:
            return self.models[self._index] if self.models else None

    def describe(self) -> str:
        then = f" (then {', '.join(self.models[1:])})" if len(self.models) > 1 else ""
        return f"{self.api} API at {_host(self.base_url)}, model {self.model or '(server default)'}{then}"

    def __call__(self, system: str, user: str) -> str:
        if not self._decided:
            with self._probe:
                if not self._decided:
                    return self._call(system, user)
        return self._call(system, user)

    def _call(self, system: str, user: str) -> str:
        while True:
            with self._lock:
                index = self._index
            model = self.models[index] if self.models else None
            try:
                return self._call_model(model, system, user)
            except LlmError as e:
                if not self._model_problem(e):
                    raise
                with self._lock:
                    if self._index == index:
                        if index + 1 >= len(self.models):
                            raise LlmError(e.kind, f"{e.message} (every model failed: {', '.join(self.models)})",
                                           e.status) from None
                        self._index = index + 1
                # Next model (another call may have moved on already). The deadline still bounds every request.

    def _model_problem(self, e: LlmError) -> bool:
        """True when trying the next model can help: a final HTTP error that is not about the key."""
        return len(self.models) > 1 and e.kind == "http" and e.status is not None and e.status not in _KEY_STATUSES

    def _call_model(self, model: str | None, system: str, user: str) -> str:
        with self._lock:
            api = self.api
        if api == "openai":
            try:
                out = self._request("openai", model, system, user)
                self._decided = True
                return out
            except _WrongApi as e:
                if self.mode != "auto":
                    raise LlmError("http", f"model request failed: HTTP {e.status}", e.status) from None
                wrong = e.status
            try:
                out = self._request("chat", model, system, user)
            except LlmError as chat_err:
                if chat_err.status in (404, 405):
                    # Neither path knows it: the server speaks openai and the model name is unknown there.
                    self._decided = True
                    raise LlmError("http", f"model request failed: HTTP {wrong}", wrong) from None
                self._use_chat()
                raise
            self._use_chat()
            return out
        return self._request("chat", model, system, user)

    def _use_chat(self) -> None:
        with self._lock:
            self.api = "chat"  # remembered: later calls in this run go straight to /chat
            self._decided = True

    def _left(self) -> float | None:
        return None if self.deadline is None else self.deadline - self.clock()

    def _body(self, api: str, model: str | None, system: str, user: str) -> tuple[str, bytes]:
        if api == "openai":
            body = {"model": model, "max_tokens": MAX_TOKENS,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            url = self.base_url + "/chat/completions"
        else:
            # glc silently drops a role "system" message, so the prompt must travel in `system`.
            body = {"system": system, "messages": [{"role": "user", "content": user}], "max_tokens": MAX_TOKENS}
            if model:
                body["model"] = model
            url = self.base_url + "/chat"
        if _wants_temperature(model):
            body["temperature"] = 0
        return url, json.dumps({**self.extra_body, **body}).encode()

    def _request(self, api: str, model: str | None, system: str, user: str) -> str:
        if self._unreachable:
            raise LlmError("network", UNREACHABLE_MESSAGE)
        with self._slots:
            if self._unreachable:  # set by a request that finished while this one waited for a slot
                raise LlmError("network", UNREACHABLE_MESSAGE)
            return self._request_locked(api, model, system, user)

    def _request_locked(self, api: str, model: str | None, system: str, user: str) -> str:
        url, data = self._body(api, model, system, user)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        problem, last_status, timed_out = "no attempt made", None, False
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
            except ValueError:
                # http.client rejects a header with a control character and quotes the header, key included, in
                # its message: report the setting, never the message.
                raise LlmError("settings", "the model key or URL holds an invalid character") from None
            except NETWORK_ERRORS as e:
                problem, last_status, timed_out = f"network error ({type(e).__name__})", None, _is_timeout(e)
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
                raise LlmError("http", f"model request failed: HTTP {status}", status)
            return self._parse(api, raw)
        if last_status == 503:
            # glc answers 503 for an unknown model name as well as when it is busy
            raise LlmError("http", UNAVAILABLE_503 + (" (no time left to retry)" if "no time" in problem else ""), 503)
        if problem.startswith("network"):
            if not timed_out:
                self._unreachable = True  # a slow answer is not a dead endpoint; a refused connection is
            raise LlmError("network", f"model request failed: {problem}")
        raise LlmError("http", f"model request failed: {problem}", last_status)

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
