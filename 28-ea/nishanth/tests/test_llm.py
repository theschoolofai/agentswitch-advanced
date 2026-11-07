import json
import urllib.error

import pytest

from ea_briefing.llm import LlmError, make_llm
from fakes import FakeOpener

KEY = "sk-test-SECRET-key-123"
BASE = "https://llm.example/v1"


def ok(content="hello"):
    return 200, {"choices": [{"message": {"role": "assistant", "content": content}}]}


def make(model, opener, sleeps=None):
    rec = sleeps if sleeps is not None else []
    return make_llm(BASE, KEY, model, timeout=5, opener=opener, sleep=lambda s: rec.append(s))


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
    assert len(sleeps) == 2


@pytest.mark.parametrize("status", [500, 502, 504])
def test_retries_other_transient_statuses(status):
    opener = FakeOpener([(status, b"x"), ok("y")])
    assert make("gpt-4.1-mini", opener)("s", "u") == "y"
    assert len(opener.calls) == 2


def test_gives_up_after_three_attempts_without_leaking_key():
    opener = FakeOpener(fn=lambda rec: (503, json.dumps({"error": f"bad key {KEY}"}).encode()))
    with pytest.raises(LlmError) as exc:
        make("gpt-4.1-mini", opener)("s", "u")
    assert len(opener.calls) == 3
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
    opener = FakeOpener([(200, body)] * 3)
    with pytest.raises(LlmError):
        make("gpt-4.1-mini", opener)("s", "u")
