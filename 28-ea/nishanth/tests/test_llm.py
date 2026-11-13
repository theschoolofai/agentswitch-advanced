import json
import urllib.error

import pytest

from ea_briefing.llm import LlmError, make_llm
from fakes import FakeOpener

KEY = "sk-test-SECRET-key-123"
BASE = "https://llm.example/v1"


def ok(content="hello"):
    return 200, {"choices": [{"message": {"role": "assistant", "content": content}}]}


def make(model, opener, sleeps=None, api="openai", **kw):
    rec = sleeps if sleeps is not None else []
    return make_llm({"base_url": BASE, "api": api, "key": KEY, "model": model}, opener=opener,
                    sleep=lambda s: rec.append(s), **kw)


def test_request_shape_and_result():
    opener = FakeOpener([ok("the answer")])
    llm = make("gpt-4.1-mini", opener)
    assert llm("SYS", "USR") == "the answer"
    assert len(opener.calls) == 1
    assert opener.calls[0]["url"] == BASE + "/chat/completions"
    assert str(opener.calls[0].get("method", "POST")).upper() == "POST"
    body = opener.json_bodies()[0]
    assert body["model"] == "gpt-4.1-mini"
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USR"}]
    assert body["max_tokens"] == 700
    assert opener.header(0, "Authorization") == "Bearer " + KEY


@pytest.mark.parametrize("model", ["gpt-4.1-mini", "gpt-4o", "gpt-4", "gpt-3.5-turbo", "openai/gpt-4.1",
                                   "openai/gpt-3.5-turbo"])
def test_temperature_zero_for_old_families(model):
    opener = FakeOpener([ok()])
    make(model, opener)("s", "u")
    body = opener.json_bodies()[0]
    assert body.get("temperature") == 0
    assert "temperature" in body


@pytest.mark.parametrize("model", ["gpt-5", "gpt-5-mini", "o4-mini", "o3", "openai/gpt-5", "llama-3-70b",
                                   "openai/o4-mini", "my-gpt-4-clone"])
def test_no_temperature_for_other_models(model):
    opener = FakeOpener([ok()])
    make(model, opener)("s", "u")
    assert "temperature" not in opener.json_bodies()[0]


def test_retries_on_429_and_503_then_succeeds():
    sleeps = []
    opener = FakeOpener([(429, b"slow down"), (503, b"busy"), ok("finally")])
    assert make("gpt-4.1-mini", opener, sleeps)("s", "u") == "finally"
    assert len(opener.calls) == 3
    assert sleeps == [1, 2]


@pytest.mark.parametrize("status", [500, 502, 504])
def test_retries_other_transient_statuses(status):
    opener = FakeOpener([(status, b"x"), ok("y")])
    assert make("gpt-4.1-mini", opener)("s", "u") == "y"
    assert len(opener.calls) == 2


def test_gives_up_after_four_attempts_without_leaking_key():
    # D3: backoff 1s, 2s, 4s, so four attempts in all (was three before v1)
    sleeps = []
    opener = FakeOpener(fn=lambda rec: (503, json.dumps({"error": f"bad key {KEY}"}).encode()))
    with pytest.raises(LlmError) as exc:
        make("gpt-4.1-mini", opener, sleeps)("s", "u")
    assert len(opener.calls) == 4
    assert sleeps == [1, 2, 4]
    assert KEY not in str(exc.value) + repr(exc.value)


def test_401_not_retried_and_key_hidden():
    opener = FakeOpener(fn=lambda rec: (401, json.dumps({"error": {"message": f"Incorrect API key {KEY}"}}).encode()))
    with pytest.raises(LlmError) as exc:
        make("gpt-4.1-mini", opener)("s", "u")
    assert len(opener.calls) == 1
    assert KEY not in str(exc.value) + repr(exc.value)


def test_network_error_becomes_llm_error():
    opener = FakeOpener(fn=lambda rec: urllib.error.URLError(f"cannot reach {BASE}"))
    with pytest.raises(LlmError) as exc:
        make("gpt-4.1-mini", opener)("s", "u")
    assert KEY not in str(exc.value)


@pytest.mark.parametrize("body", [b"not json", {"choices": []}, {"nothing": True}])
def test_malformed_response_is_llm_error(body):
    opener = FakeOpener([(200, body)] * 4)
    with pytest.raises(LlmError):
        make("gpt-4.1-mini", opener)("s", "u")


# --------------------------------------------------------------------------- v1: chat API, auto mode, deadline

def chat_ok(text="from chat"):
    return 200, {"text": text, "model": "whatever"}


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t


def glc_like(rec):
    # The course gateway: no /chat/completions, a /chat endpoint with its own shape.
    if rec["url"].endswith("/chat/completions"):
        return 404, b'{"detail": "Not Found"}'
    if rec["url"].endswith("/chat"):
        return chat_ok("gateway says hi")
    raise AssertionError(rec["url"])


def test_chat_api_shape_system_prompt_in_system_field():
    opener = FakeOpener([chat_ok("hello")])
    llm = make_llm({"base_url": BASE, "api": "chat", "key": None, "model": None}, opener=opener)
    assert llm("SYS", "USR") == "hello"
    assert opener.calls[0]["url"] == BASE + "/chat"
    body = opener.json_bodies()[0]
    assert body["system"] == "SYS"
    assert body["messages"] == [{"role": "user", "content": "USR"}]
    assert "model" not in body
    assert opener.header(0, "Authorization") is None
    assert llm.api == "chat"


def test_auto_switches_to_chat_on_404_and_remembers():
    opener = FakeOpener(fn=glc_like)
    llm = make("some-model", opener, api="auto")
    assert llm.api == "openai"
    assert llm("SYS", "USR") == "gateway says hi"
    assert [c["url"] for c in opener.calls] == [BASE + "/chat/completions", BASE + "/chat"]
    body = opener.json_bodies()[1]
    assert body["system"] == "SYS"
    assert all(m["role"] != "system" for m in body["messages"])
    assert body["model"] == "some-model"
    assert llm.api == "chat"
    assert llm("S2", "U2") == "gateway says hi"
    assert [c["url"] for c in opener.calls[2:]] == [BASE + "/chat"]


def test_auto_switches_on_405():
    opener = FakeOpener([(405, b""), chat_ok("ok")])
    assert make("m", opener, api="auto")("s", "u") == "ok"


def test_auto_without_model_goes_straight_to_chat():
    opener = FakeOpener([chat_ok("ok")])
    llm = make_llm({"base_url": BASE, "api": "auto", "key": None, "model": None}, opener=opener)
    assert llm("s", "u") == "ok"
    assert [c["url"] for c in opener.calls] == [BASE + "/chat"]


def test_openai_mode_does_not_switch_on_404():
    opener = FakeOpener([(404, b"")])
    with pytest.raises(LlmError) as exc:
        make("m", opener, api="openai")("s", "u")
    assert "404" in exc.value.message
    assert len(opener.calls) == 1


def test_persistent_503_message_names_model_and_gateway():
    sleeps = []
    opener = FakeOpener(fn=lambda rec: (503, b"busy"))
    with pytest.raises(LlmError) as exc:
        make_llm({"base_url": BASE, "api": "chat", "model": "no-such-model"}, opener=opener,
                 sleep=sleeps.append)("s", "u")
    assert exc.value.message == "model unavailable (HTTP 503 — check the model name and the gateway)"
    assert len(opener.calls) == 4 and sleeps == [1, 2, 4]


def test_deadline_passed_means_no_request():
    clock = Clock(100.0)
    opener = FakeOpener([ok()])
    llm = make("gpt-4.1-mini", opener, deadline=50.0, clock=clock)
    with pytest.raises(LlmError) as exc:
        llm("s", "u")
    assert exc.value.kind == "time_limit"
    assert opener.calls == []


def test_request_timeout_is_capped_by_time_left():
    clock = Clock(0.0)
    opener = FakeOpener([ok(), ok()])
    llm = make("gpt-4.1-mini", opener, deadline=12.0, clock=clock)
    llm("s", "u")
    assert opener.calls[0]["timeout"] == 12.0
    llm2 = make("gpt-4.1-mini", opener, deadline=500.0, clock=clock)
    llm2("s", "u")
    assert opener.calls[1]["timeout"] == 30


def test_no_retry_that_would_cross_the_deadline():
    clock = Clock(0.0)
    sleeps = []

    def opener_fn(rec):
        clock.t += 1.5  # each attempt takes 1.5 s
        return 503, b""

    def sleep(s):
        sleeps.append(s)
        clock.t += s

    llm = make_llm({"base_url": BASE, "api": "openai", "model": "gpt-4.1-mini"}, deadline=5.0,
                   opener=FakeOpener(fn=opener_fn), sleep=sleep, clock=clock)
    with pytest.raises(LlmError) as exc:
        llm("s", "u")
    # t=1.5 after attempt 1; 1 s wait fits (3.5 left); attempt 2 ends at 4.0; a 2 s wait would cross 5.0
    assert sleeps == [1]
    assert clock.t == 4.0
    assert "no time left to retry" in exc.value.message


def test_describe_never_shows_key_or_userinfo():
    llm = make_llm({"base_url": "https://user:pw-secret@llm.example/v1", "api": "openai", "key": KEY,
                    "model": "gpt-4.1-mini"})
    text = llm.describe()
    assert "llm.example" in text and "gpt-4.1-mini" in text
    assert KEY not in text and "pw-secret" not in text


def test_chat_malformed_reply_is_invalid():
    opener = FakeOpener([(200, {"choices": []})])
    with pytest.raises(LlmError) as exc:
        make_llm({"base_url": BASE, "api": "chat"}, opener=opener)("s", "u")
    assert exc.value.kind == "invalid"


def test_auto_switch_is_safe_with_parallel_calls():
    from concurrent.futures import ThreadPoolExecutor
    opener = FakeOpener(fn=glc_like)
    llm = make("some-model", opener, api="auto")
    with ThreadPoolExecutor(max_workers=3) as pool:
        out = list(pool.map(lambda i: llm("s", f"u{i}"), range(6)))
    assert out == ["gateway says hi"] * 6
    assert llm.api == "chat"
    n = len(opener.calls)
    llm("s", "again")
    assert [c["url"] for c in opener.calls[n:]] == [BASE + "/chat"]
    assert sum(c["url"].endswith("/chat/completions") for c in opener.calls) == 1  # a single probe


def test_parallel_limit_bounds_requests_in_flight():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    state = {"now": 0, "max": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(2, timeout=5)

    def fn(rec):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        barrier.wait()
        with lock:
            state["now"] -= 1
        return chat_ok()

    llm = make_llm({"base_url": BASE, "api": "chat"}, opener=FakeOpener(fn=fn), parallel=2)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda i: llm("s", str(i)), range(6)))
    assert state["max"] == 2


def test_auto_probe_is_single_with_parallel_calls():
    from concurrent.futures import ThreadPoolExecutor
    opener = FakeOpener(fn=glc_like)
    llm = make("some-model", opener, api="auto", parallel=3)
    with ThreadPoolExecutor(max_workers=6) as pool:
        out = list(pool.map(lambda i: llm("s", str(i)), range(6)))
    assert out == ["gateway says hi"] * 6
    assert sum(c["url"].endswith("/chat/completions") for c in opener.calls) == 1
    assert len(opener.calls) == 7


def test_auto_probe_success_unblocks_openai():
    opener = FakeOpener([ok("one"), ok("two")])
    llm = make("gpt-4.1-mini", opener, api="auto")
    assert llm("s", "u") == "one" and llm._decided is True and llm.api == "openai"
    assert llm("s", "u") == "two"
