"""Draft quality and model-client rules, and the course agent contract.

Drafts: the 120-word limit, the one-line summary, the "needs your decision" mark. Model client: a model list tried
in order, the extra request body, and the unreachable short-circuit.
"""
import json
import socket
import urllib.error
from datetime import date
from zoneinfo import ZoneInfo

import pytest

from ea_agent.briefing import build_briefing
from ea_agent.drafts import (MAX_REPLY_WORDS, SUMMARY_MAX, SYSTEM_PROMPT, check_draft, needs_decision, reply_words,
                             triage)
from ea_agent.llm import UNREACHABLE_MESSAGE, LlmError, make_llm
from fakes import FakeClient, FakeLLM, FakeOpener

ME = {"id": "u1", "email": "me@example.test", "name": "Nora Example", "company_id": "c1", "employee_id": "e1",
      "party_id": "p1"}


def message(**kw):
    base = {"id": "m1", "message_id": "<m1@mail.test>", "thread_id": "th1", "mailbox_id": "mb1",
            "from_email": "alice@example.test", "from_name": "Alice", "subject": "Budget review",
            "received_at": "2026-11-04T08:00:00+00:00", "snippet": "", "body_text": "Can you review the budget?"}
    base.update(kw)
    return base


def answer(needs, draft=None, **extra):
    return json.dumps({"needs_reply": needs, "reason": "r", "draft": draft, **extra})


def words(n):
    return " ".join(["word"] * n)


# --------------------------------------------------------------------------- the prompt

def test_prompt_asks_for_language_length_summary_and_decision():
    text = " ".join(SYSTEM_PROMPT.format(name="Nora").split())
    assert "in the same language as the email" in text
    assert "under 120 words including the greeting and the signature" in text
    assert '"summary": "one sentence in English' in text
    assert '"needs_decision": true if the email asks Nora to agree to a date, an amount, a payment or attendance' in text
    assert "draft must be null when needs_reply is false" in text


def test_result_has_summary_and_needs_decision_keys():
    out = triage(message(), ME, FakeLLM([answer(False)]))
    assert {"summary", "needs_decision"} <= set(out)


# --------------------------------------------------------------------------- length

def test_reply_words_counts_whitespace_separated_words():
    assert reply_words("Hi Ana,\n\nThanks.\n\nNora") == 4
    assert reply_words(None) == 0


def test_draft_at_the_limit_is_clean():
    out = triage(message(), ME, FakeLLM([answer(True, words(MAX_REPLY_WORDS))]))
    assert out["draft"] and "draft_needs_review" not in out["flags"]
    assert out["review_reason"] is None


def test_draft_over_the_limit_needs_review():
    out = triage(message(), ME, FakeLLM([answer(True, words(MAX_REPLY_WORDS + 1))]))
    assert "draft_needs_review" in out["flags"]
    assert out["review_reason"] == f"draft longer than {MAX_REPLY_WORDS} words"
    assert out["draft"]  # still shown in the briefing, so the user can write their own


def test_length_joins_other_reasons():
    out = triage(message(), ME, FakeLLM([answer(True, "See https://x.example " + words(MAX_REPLY_WORDS))]))
    assert out["review_reason"] == f"draft contains a link; draft longer than {MAX_REPLY_WORDS} words"


def test_check_draft_does_not_limit_length():
    # check_draft also checks the user's own edits; the word limit is for model drafts only
    assert check_draft(words(500), message(), []) == []


def test_long_draft_is_not_saved():
    day, tz = date(2026, 11, 4), ZoneInfo("America/New_York")
    row = dict(message(), folder="inbox", is_read=False, is_draft=False, is_answered=False, to=[ME["email"]], cc=[],
               in_reply_to=None, body_html=None, labels=[], importance="normal")
    fc = FakeClient(ME, {"Mailbox": [{"id": "mb1", "email": ME["email"], "created_by": "u1", "owner_id": "u1"}],
                         "EmailAccount": [], "EmailMessage": [row], "Calendar": [], "CalendarEvent": [], "Task": [],
                         "Project": []}, today=day)
    b = build_briefing(fc, ME, day, tz, llm=FakeLLM([answer(True, words(MAX_REPLY_WORDS + 5))]), save_drafts=True)
    item = b["mail"]["items"][0]
    assert "draft_needs_review" in item["flags"]
    assert fc.calls_to("EmailMessage.create") == []


# --------------------------------------------------------------------------- summary

def test_summary_is_kept_on_one_line():
    out = triage(message(), ME, FakeLLM([answer(False, summary="  Alice wants\nthe budget\treviewed.\x07 ")]))
    assert out["summary"] == "Alice wants the budget reviewed."


def test_summary_is_capped():
    out = triage(message(), ME, FakeLLM([answer(False, summary=words(200))]))
    assert len(out["summary"]) <= SUMMARY_MAX and out["summary"].endswith("…")


@pytest.mark.parametrize("value", [None, "", "   ", 42, ["a"], {"a": 1}])
def test_odd_summary_is_none_and_costs_nothing(value):
    out = triage(message(), ME, FakeLLM([answer(True, "Hi Alice, I will look at it. Nora", summary=value)]))
    assert out["summary"] is None
    assert out["needs_reply"] is True and out["draft"]


def test_missing_summary_is_none():
    out = triage(message(), ME, FakeLLM([answer(False)]))
    assert out["summary"] is None


def test_no_summary_without_a_model_or_on_failure():
    assert triage(message(), ME, None)["summary"] is None
    assert triage(message(), ME, FakeLLM([LlmError("http", "boom")]))["summary"] is None


# --------------------------------------------------------------------------- needs your decision

@pytest.mark.parametrize("subject,body", [
    ("Meeting next week", "Hello"),
    ("Hello", "Please confirm the delivery"),
    ("Invoice 42", "Attached."),
    ("Hello", "Can you attend on Friday?"),
    ("Hello", "What dates suit you?"),
    ("Hello", "The deadline is close."),
    ("Payment", "x"),
    ("Hello", "Is there a good time?"),
])
def test_keyword_rule_marks(subject, body):
    assert needs_decision(message(subject=subject, body_text=body)) is True


@pytest.mark.parametrize("body", ["Please send an update.", "Sometimes it rains.", "Thanks for the report."])
def test_keyword_rule_matches_word_starts_only(body):
    assert needs_decision(message(subject="Hello", body_text=body)) is False


def test_keyword_rule_uses_snippet_when_body_empty():
    assert needs_decision(message(subject="Hi", body_text="", snippet="Can you confirm?")) is True


def test_keyword_rule_sees_through_invisible_characters():
    assert needs_decision(message(subject="Hi", body_text="Please con​firm")) is True


def test_mark_without_a_model_and_on_model_failure():
    msg = message(subject="Meeting", body_text="Thursday?")
    assert triage(msg, ME, None)["needs_decision"] is True
    assert triage(msg, ME, FakeLLM([LlmError("http", "boom")]))["needs_decision"] is True


def test_model_can_add_the_mark():
    msg = message(subject="Hello", body_text="Can you sign off the budget?")
    assert triage(msg, ME, FakeLLM([answer(False, needs_decision=True)]))["needs_decision"] is True


def test_model_cannot_remove_the_mark():
    msg = message(subject="Meeting", body_text="Thursday?")
    assert triage(msg, ME, FakeLLM([answer(False, needs_decision=False)]))["needs_decision"] is True


@pytest.mark.parametrize("value", ["true", 1, "yes", None])
def test_only_a_real_true_from_the_model_counts(value):
    msg = message(subject="Hello", body_text="Thanks for the report.")
    assert triage(msg, ME, FakeLLM([answer(False, needs_decision=value)]))["needs_decision"] is False


def test_mark_never_blocks_a_draft():
    msg = message(subject="Meeting", body_text="Can we talk?")
    out = triage(msg, ME, FakeLLM([answer(True, "Hi Alice, I will check and come back to you. Nora",
                                          needs_decision=True)]))
    assert out["needs_decision"] is True
    assert "draft_needs_review" not in out["flags"]


# --------------------------------------------------------------------------- model client

KEY = "sk-test-SECRET-key-123"
BASE = "https://llm.example/v1"


def ok(content="hello"):
    return 200, {"choices": [{"message": {"role": "assistant", "content": content}}]}


def chat_ok(text="from chat"):
    return 200, {"text": text}


def llm_with(opener, api="openai", sleeps=None, **settings):
    rec = sleeps if sleeps is not None else []
    return make_llm({"base_url": BASE, "api": api, "key": KEY, **settings}, opener=opener,
                    sleep=lambda s: rec.append(s))


def models_sent(opener):
    return [b.get("model") for b in opener.json_bodies()]


def test_model_list_falls_back_on_unknown_model_and_remembers():
    opener = FakeOpener([(404, b"no such model"), ok("from b"), ok("again b")])
    llm = llm_with(opener, model="a", models=["a", "b"])
    assert llm("s", "u") == "from b"
    assert llm("s", "u") == "again b"
    assert models_sent(opener) == ["a", "b", "b"]
    assert llm.current_model == "b" and llm.model == "a"


def test_model_list_falls_back_after_busy_retries():
    sleeps = []
    opener = FakeOpener([(503, b"busy")] * 4 + [ok("b answers")])
    llm = llm_with(opener, sleeps=sleeps, model="a", models=["a", "b"])
    assert llm("s", "u") == "b answers"
    assert models_sent(opener) == ["a"] * 4 + ["b"]
    assert sleeps == [1, 2, 4]


@pytest.mark.parametrize("status", [401, 403])
def test_key_problem_never_moves_to_the_next_model(status):
    opener = FakeOpener([(status, b"bad key")])
    llm = llm_with(opener, model="a", models=["a", "b"])
    with pytest.raises(LlmError):
        llm("s", "u")
    assert models_sent(opener) == ["a"]


def test_network_problem_never_moves_to_the_next_model():
    opener = FakeOpener(fn=lambda rec: urllib.error.URLError(ConnectionRefusedError("refused")))
    llm = llm_with(opener, model="a", models=["a", "b"])
    with pytest.raises(LlmError) as e:
        llm("s", "u")
    assert e.value.kind == "network"
    assert set(models_sent(opener)) == {"a"}


def test_every_model_failed_is_said_once():
    opener = FakeOpener([(404, b"x"), (404, b"y")])
    llm = llm_with(opener, model="a", models=["a", "b"])
    with pytest.raises(LlmError) as e:
        llm("s", "u")
    assert "every model failed: a, b" in e.value.message
    assert e.value.status == 404 and KEY not in e.value.message


def test_single_model_error_is_unchanged():
    opener = FakeOpener([(404, b"x")])
    with pytest.raises(LlmError) as e:
        llm_with(opener, model="a")("s", "u")
    assert e.value.message == "model request failed: HTTP 404"
    assert e.value.status == 404


def test_next_model_is_not_tried_past_the_deadline():
    now = {"t": 0.0}

    def opener_fn(rec):
        now["t"] = 10.0  # the first request took the run past its deadline
        return 404, b"x"

    opener = FakeOpener(fn=opener_fn)
    llm = make_llm({"base_url": BASE, "api": "openai", "model": "a", "models": ["a", "b"]}, opener=opener,
                   deadline=5.0, clock=lambda: now["t"], sleep=lambda s: None)
    with pytest.raises(LlmError) as e:
        llm("s", "u")
    assert e.value.kind == "time_limit"
    assert models_sent(opener) == ["a"]


def test_models_absent_means_model():
    opener = FakeOpener([ok()])
    llm = llm_with(opener, model="only")
    llm("s", "u")
    assert llm.models == ["only"] and models_sent(opener) == ["only"]


def test_models_list_is_cleaned():
    llm = make_llm({"base_url": BASE, "api": "openai", "model": "a", "models": [" a ", "", "b", "a", 3]})
    assert llm.models == ["a", "b"]


def test_describe_names_the_fallbacks_without_secrets():
    llm = make_llm({"base_url": "https://user:pw@llm.example/v1", "api": "openai", "key": KEY, "model": "a",
                    "models": ["a", "b", "c"]})
    text = llm.describe()
    assert "model a (then b, c)" in text
    assert KEY not in text and "pw" not in text


def test_auto_mode_unknown_model_on_openai_server_falls_back():
    # an OpenAI-style server: 404 on /chat/completions for model a, and no /chat at all
    def server(rec):
        body = json.loads(rec["data"])
        if rec["url"].endswith("/chat/completions"):
            return ok("b works") if body["model"] == "b" else (404, b"model not found")
        return 404, b"no such path"

    opener = FakeOpener(fn=server)
    llm = llm_with(opener, api="auto", model="a", models=["a", "b"])
    assert llm("s", "u") == "b works"
    assert llm.api == "openai"
    assert [c["url"].rsplit("/", 1)[-1] for c in opener.calls] == ["completions", "chat", "completions"]


def test_auto_mode_still_switches_to_chat_for_glc():
    def glc(rec):
        if rec["url"].endswith("/chat/completions"):
            return 404, b"Not Found"
        return chat_ok("gateway")

    opener = FakeOpener(fn=glc)
    llm = llm_with(opener, api="auto", model="a", models=["a", "b"])
    assert llm("s", "u") == "gateway"
    assert llm("s", "u") == "gateway"
    assert llm.api == "chat" and llm.current_model == "a"
    assert [c["url"].rsplit("/", 1)[-1] for c in opener.calls] == ["completions", "chat", "chat"]


def test_auto_mode_chat_busy_keeps_the_switch():
    def glc(rec):
        if rec["url"].endswith("/chat/completions"):
            return 404, b"Not Found"
        return 503, b"busy"

    opener = FakeOpener(fn=glc)
    llm = llm_with(opener, api="auto", model="a")
    with pytest.raises(LlmError):
        llm("s", "u")
    assert llm.api == "chat"


def test_extra_body_goes_into_every_request_and_never_overrides_ours():
    extra = {"reasoning": {"effort": "low"}, "model": "evil", "messages": [], "system": "evil"}
    opener = FakeOpener([ok()])
    llm_with(opener, model="a", extra_body=extra)("sys", "usr")
    body = opener.json_bodies()[0]
    assert body["reasoning"] == {"effort": "low"}
    assert body["model"] == "a" and body["messages"][0]["content"] == "sys"
    opener = FakeOpener([chat_ok()])
    llm_with(opener, api="chat", model="a", extra_body=extra)("sys", "usr")
    body = opener.json_bodies()[0]
    assert body["reasoning"] == {"effort": "low"} and body["system"] == "sys" and body["model"] == "a"


def test_no_extra_body_sends_nothing_extra():
    opener = FakeOpener([ok()])
    llm_with(opener, model="a", extra_body=None)("s", "u")
    assert set(opener.json_bodies()[0]) == {"model", "max_tokens", "messages"}


@pytest.mark.parametrize("value", ["{}", ["a"], 3])
def test_extra_body_must_be_an_object(value):
    with pytest.raises(ValueError):
        make_llm({"base_url": BASE, "api": "openai", "model": "a", "extra_body": value})


# --------------------------------------------------------------------------- unreachable short-circuit

def test_refused_connection_stops_model_calls_for_the_run():
    opener = FakeOpener(fn=lambda rec: urllib.error.URLError(ConnectionRefusedError("refused")))
    llm = llm_with(opener, model="a")
    with pytest.raises(LlmError):
        llm("s", "u")
    sent = len(opener.calls)
    assert sent == 4  # the normal retries first
    with pytest.raises(LlmError) as e:
        llm("s", "u")
    assert e.value.kind == "network" and e.value.message == UNREACHABLE_MESSAGE
    assert len(opener.calls) == sent


@pytest.mark.parametrize("exc", [socket.timeout("timed out"), TimeoutError("slow"),
                                 urllib.error.URLError(socket.timeout("timed out"))])
def test_timeout_is_not_unreachable(exc):
    opener = FakeOpener(fn=lambda rec: exc)
    llm = llm_with(opener, model="a")
    with pytest.raises(LlmError):
        llm("s", "u")
    with pytest.raises(LlmError) as e:
        llm("s", "u")
    assert e.value.message != UNREACHABLE_MESSAGE
    assert len(opener.calls) == 8


def test_recovered_connection_is_not_unreachable():
    opener = FakeOpener([urllib.error.URLError(ConnectionRefusedError("blip")), ok("fine"), ok("still fine")])
    llm = llm_with(opener, model="a")
    assert llm("s", "u") == "fine"
    assert llm("s", "u") == "still fine"
