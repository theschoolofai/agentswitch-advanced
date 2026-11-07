"""OpenAI-compatible chat completions, returned as a plain `(system, user) -> str` callable."""
import json
import time

from .mcp import NETWORK_ERRORS, urllib_opener

RETRY_STATUSES = {429, 500, 502, 503, 504}
ATTEMPTS = 3


class LlmError(Exception):
    def __init__(self, message: str, kind: str = "http"):
        super().__init__(message)
        self.kind = kind
        self.message = message


def _wants_temperature(model: str) -> bool:
    # Newer reasoning models reject a temperature parameter; older chat models accept 0.
    name = (model or "").rsplit("/", 1)[-1].lower()
    return name.startswith(("gpt-4", "gpt-3"))


def make_llm(base_url: str, api_key: str, model: str, timeout: float = 60, opener=None, sleep=time.sleep):
    opener = opener or urllib_opener
    url = base_url.rstrip("/") + "/chat/completions"

    def complete(system: str, user: str) -> str:
        body = {"model": model, "max_tokens": 700,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if _wants_temperature(model):
            body["temperature"] = 0
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        problem = "no attempt made"
        for attempt in range(ATTEMPTS):
            if attempt:
                sleep(2 ** (attempt - 1))
            try:
                status, raw = opener(url, data, headers, "POST", timeout)
            except NETWORK_ERRORS as e:
                problem = f"network error ({type(e).__name__})"
                continue
            if status in RETRY_STATUSES:
                problem = f"HTTP {status}"
                continue
            if 300 <= status < 400:
                # Redirects are not followed: the API key must only ever go to the configured host.
                raise LlmError(f"model request was redirected (HTTP {status}); not followed")
            if status != 200:
                raise LlmError(f"model request failed: HTTP {status}")
            try:
                content = json.loads(raw)["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise LlmError("model response was not in the expected shape", kind="invalid") from None
            if not isinstance(content, str):
                raise LlmError("model response had no text content", kind="invalid")
            return content
        raise LlmError(f"model request failed after {ATTEMPTS} attempts: {problem}",
                       kind="network" if problem.startswith("network") else "http")

    return complete
