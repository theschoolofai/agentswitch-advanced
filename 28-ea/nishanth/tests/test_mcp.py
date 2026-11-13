import json
import urllib.error

import pytest

from ea_briefing import mcp
from ea_briefing.mcp import McpClient, McpError, ToolNotAllowed, list_capped
from fakes import FakeClient, FakeOpener, rpc_error, rpc_ok, rpc_text

BASE = "https://example.invalid"
PASSWORD = "hunter2-Very-Secret-pw"
TOKEN = "tok-abc-123-secret"


def make_client(opener):
    client = McpClient(BASE, TOKEN, timeout=5, opener=opener)
    client.sleep = lambda *_a, **_k: None
    return client


def list_payload(rows, total=None):
    return {"data": rows, "total": len(rows) if total is None else total, "limit": 100, "offset": 0}


# --------------------------------------------------------------------------- allow-list

def test_allow_lists_match_spec():
    assert mcp.READ_TOOLS == frozenset({"EmailAccount.list", "Mailbox.list", "EmailMessage.list", "EmailMessage.get",
                                        "Calendar.list", "CalendarEvent.list", "Task.list", "Project.get", "Project.list"})
    assert mcp.WRITE_TOOLS == frozenset({"EmailMessage.create"})


def test_tool_not_allowed_is_mcp_error_with_kind_refused():
    assert issubclass(ToolNotAllowed, McpError)
    opener = FakeOpener()
    with pytest.raises(ToolNotAllowed) as exc:
        make_client(opener).call("EmailMessage.send_email", {"id": "m1"})
    assert exc.value.kind == "refused"


@pytest.mark.parametrize("name", [
    "EmailMessage.send_email", "EmailMessage.reply", "EmailMessage.record_sent", "EmailMessage.save_draft",
    "endpoint.email.messages.send", "EmailMessage.update", "EmailMessage.delete", "CalendarEvent.create",
    "CalendarEvent.update", "CalendarEvent.accept", "Task.update", "Task.create", "Project.delete",
    "emailmessage.list", "EmailMessage.list ", "", "tools/call", "EmailAccount.create",
])
def test_unknown_or_send_capable_tools_refused_without_io(name):
    opener = FakeOpener(fn=lambda rec: rpc_ok({}))
    client = make_client(opener)
    with pytest.raises(ToolNotAllowed):
        client.call(name, {"folder": "drafts", "is_draft": True})
    assert opener.calls == []


@pytest.mark.parametrize("arguments", [
    None,
    {},
    {"folder": "inbox", "is_draft": True},
    {"folder": "sent", "is_draft": True},
    {"folder": "outbox", "is_draft": True},
    {"folder": "drafts"},
    {"folder": "drafts", "is_draft": False},
    {"folder": "drafts", "is_draft": "true"},
    {"folder": "drafts", "is_draft": 1},
    {"folder": "Drafts", "is_draft": True},
])
def test_email_create_refused_unless_draft(arguments):
    opener = FakeOpener(fn=lambda rec: rpc_ok({"id": "x"}))
    with pytest.raises(ToolNotAllowed):
        make_client(opener).call("EmailMessage.create", arguments)
    assert opener.calls == []


def test_email_create_draft_allowed_and_sent_as_tools_call():
    opener = FakeOpener([rpc_ok({"id": "d1"})])
    args = {"folder": "drafts", "is_draft": True, "to": ["a@x.test"], "subject": "Re: hi"}
    out = make_client(opener).call("EmailMessage.create", args)
    assert out == {"id": "d1"}
    assert len(opener.calls) == 1
    body = opener.json_bodies()[0]
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "tools/call"
    assert body["params"] == {"name": "EmailMessage.create", "arguments": args}


# --------------------------------------------------------------------------- request shape

def test_request_shape_and_headers():
    opener = FakeOpener([rpc_ok(list_payload([{"id": 1}]))])
    out = make_client(opener).call("Task.list", {"limit": 0})
    assert out["data"] == [{"id": 1}]
    call = opener.calls[0]
    assert call["url"] == BASE + "/api/mcp"
    assert str(call.get("method", "POST")).upper() == "POST"
    assert opener.header(0, "Authorization") == "Bearer " + TOKEN
    assert "application/json" in opener.header(0, "Content-Type")
    accept = opener.header(0, "Accept")
    assert "application/json" in accept and "text/event-stream" in accept
    assert opener.json_bodies()[0]["params"] == {"name": "Task.list", "arguments": {"limit": 0}}


def test_call_with_no_arguments_sends_empty_object():
    opener = FakeOpener([rpc_ok(list_payload([]))])
    make_client(opener).call("Calendar.list")
    assert opener.json_bodies()[0]["params"]["arguments"] == {}


def test_text_content_fallback_is_joined_and_parsed():
    opener = FakeOpener([rpc_text('{"data": [{"id": 7}], ', '"total": 1}')])
    out = make_client(opener).call("Task.list", {})
    assert out == {"data": [{"id": 7}], "total": 1}


def test_structured_content_preferred_over_text():
    body = {"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": {"a": 1},
                                                   "content": [{"type": "text", "text": '{"a": 2}'}]}}
    opener = FakeOpener([(200, body)])
    assert make_client(opener).call("Task.list", {}) == {"a": 1}


# --------------------------------------------------------------------------- error envelopes

def test_http_200_error_envelope_uses_data_code_as_kind():
    opener = FakeOpener([rpc_error(-32000, "Task not found", "not_found")])
    with pytest.raises(McpError) as exc:
        make_client(opener).call("Project.get", {"id": "p1"})
    assert exc.value.kind == "not_found"
    assert exc.value.code == -32000
    assert "not found" in exc.value.message.lower()
    assert not isinstance(exc.value, ToolNotAllowed)


@pytest.mark.parametrize("data_code", ["forbidden", "invalid"])
def test_http_200_error_envelope_other_kinds(data_code):
    opener = FakeOpener([rpc_error(-32000, "nope", data_code)])
    with pytest.raises(McpError) as exc:
        make_client(opener).call("Task.list", {})
    assert exc.value.kind == data_code


def test_http_200_error_without_data_still_raises_with_code():
    opener = FakeOpener([rpc_error(-32602, "Invalid params")])
    with pytest.raises(McpError) as exc:
        make_client(opener).call("Task.list", {})
    assert exc.value.code == -32602
    assert isinstance(exc.value.kind, str) and exc.value.kind
    assert exc.value.kind != "refused"


def test_is_error_result_raises_tool_error():
    body = {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": "boom"}]}}
    opener = FakeOpener([(200, body)])
    with pytest.raises(McpError) as exc:
        make_client(opener).call("Task.list", {})
    assert exc.value.kind == "tool_error"


def test_non_json_body_raises_http_kind():
    opener = FakeOpener([(200, b"<html>proxy error</html>")])
    with pytest.raises(McpError) as exc:
        make_client(opener).call("Task.list", {})
    assert exc.value.kind == "http"


def test_401_is_auth_kind_and_no_relogin():
    opener = FakeOpener([(401, {"detail": "token expired"})] * 5)
    with pytest.raises(McpError) as exc:
        make_client(opener).call("Task.list", {})
    assert exc.value.kind == "auth"
    assert len(opener.calls) == 1
    assert TOKEN not in str(exc.value)
    assert all("/api/auth/login" not in c["url"] for c in opener.calls)


# --------------------------------------------------------------------------- retries

def test_reads_retried_on_503_then_succeed():
    opener = FakeOpener([(503, b"busy"), (502, b"bad upstream"), rpc_ok(list_payload([{"id": 1}]))])
    out = make_client(opener).call("Task.list", {})
    assert out["data"] == [{"id": 1}]
    assert len(opener.calls) == 3


def test_reads_retried_at_most_two_extra_times():
    opener = FakeOpener(fn=lambda rec: (503, b"busy"))
    with pytest.raises(McpError):
        make_client(opener).call("CalendarEvent.list", {})
    assert len(opener.calls) == 3


def test_reads_retried_on_network_error():
    opener = FakeOpener([urllib.error.URLError("connection reset"), (504, b"timeout"), rpc_ok({"ok": True})])
    assert make_client(opener).call("Calendar.list", {}) == {"ok": True}
    assert len(opener.calls) == 3


def test_network_error_exhausted_is_network_kind():
    opener = FakeOpener(fn=lambda rec: urllib.error.URLError("no route"))
    with pytest.raises(McpError) as exc:
        make_client(opener).call("Calendar.list", {})
    assert exc.value.kind == "network"
    assert len(opener.calls) == 3


@pytest.mark.parametrize("status", [502, 503, 504])
def test_writes_never_retried(status):
    opener = FakeOpener(fn=lambda rec: (status, b"busy"))
    with pytest.raises(McpError):
        make_client(opener).call("EmailMessage.create", {"folder": "drafts", "is_draft": True})
    assert len(opener.calls) == 1


def test_writes_not_retried_on_network_error():
    opener = FakeOpener(fn=lambda rec: urllib.error.URLError("reset"))
    with pytest.raises(McpError):
        make_client(opener).call("EmailMessage.create", {"folder": "drafts", "is_draft": True})
    assert len(opener.calls) == 1


# --------------------------------------------------------------------------- login / me

def test_login_success_uses_token():
    opener = FakeOpener([(200, {"token": "fresh-token"}), rpc_ok({"ok": 1})])
    client = McpClient.login(BASE, "me@x.test", PASSWORD, timeout=5, opener=opener)
    client.sleep = lambda *_a: None
    assert opener.calls[0]["url"] == BASE + "/api/auth/login"
    assert str(opener.calls[0].get("method", "POST")).upper() == "POST"
    assert opener.json_bodies()[0] == {"email": "me@x.test", "password": PASSWORD}
    client.call("Task.list", {})
    assert opener.header(1, "Authorization") == "Bearer fresh-token"


@pytest.mark.parametrize("response", [
    (401, {"detail": "Invalid credentials"}),
    (400, {"detail": f"bad password {PASSWORD}"}),
    (200, {"no_token": True}),
    (503, b"busy"),
    (500, f"<html>{PASSWORD}</html>".encode()),
])
def test_login_failure_one_attempt_and_password_hidden(response):
    opener = FakeOpener(fn=lambda rec: response)
    with pytest.raises(McpError) as exc:
        McpClient.login(BASE, "me@x.test", PASSWORD, timeout=5, opener=opener)
    assert len(opener.calls) == 1
    text = " ".join([str(exc.value), repr(exc.value), str(getattr(exc.value, "message", "")),
                     repr(exc.value.args)])
    assert PASSWORD not in text


def test_login_network_error_one_attempt_password_hidden():
    opener = FakeOpener(fn=lambda rec: urllib.error.URLError("unreachable"))
    with pytest.raises(McpError) as exc:
        McpClient.login(BASE, "me@x.test", PASSWORD, timeout=5, opener=opener)
    assert len(opener.calls) == 1
    assert PASSWORD not in str(exc.value) + repr(exc.value)


def test_me_is_get_and_cached():
    me = {"id": "u1", "email": "me@x.test", "name": "Me", "company_id": "c1", "employee_id": None, "party_id": None}
    opener = FakeOpener([(200, me)])
    client = make_client(opener)
    assert client.me() == me
    assert client.me() == me
    assert len(opener.calls) == 1
    assert opener.calls[0]["url"] == BASE + "/api/auth/me"
    assert str(opener.calls[0].get("method", "GET")).upper() == "GET"
    assert opener.calls[0].get("data") in (None, b"")


# --------------------------------------------------------------------------- list_capped

def rows(n, prefix="r"):
    return [{"id": f"{prefix}{i}", "created_by": "u1"} for i in range(n)]


def test_list_capped_first_page_carries_the_total():
    # No separate limit=0 count call any more: each platform call costs ~2 s
    fc = FakeClient({"id": "u1"}, {"Task": rows(5)})
    out = list_capped(fc, "Task.list", {"created_by": "u1"}, cap=200, page=100)
    assert len(fc.calls) == 1
    first = fc.calls[0]
    assert first[0] == "Task.list"
    assert first[1]["limit"] == 100 and first[1]["offset"] == 0
    assert first[1]["created_by"] == "u1"
    assert out["total"] == 5
    assert out["truncated"] is False
    assert [r["id"] for r in out["rows"]] == [f"r{i}" for i in range(5)]


def test_list_capped_first_page_limited_by_cap():
    fc = FakeClient({"id": "u1"}, {"Task": rows(50)})
    out = list_capped(fc, "Task.list", {}, cap=25, page=100)
    assert [a["limit"] for _, a in fc.calls] == [25]
    assert len(out["rows"]) == 25 and out["truncated"] is True and out["total"] == 50


def test_list_capped_zero_total_makes_one_call():
    fc = FakeClient({"id": "u1"}, {"Task": rows(3)})
    out = list_capped(fc, "Task.list", {"created_by": "nobody"})
    assert len(fc.calls) == 1
    assert out == {"rows": [], "total": 0, "truncated": False}


def test_list_capped_missing_total_is_an_error():
    class NoTotal(FakeClient):
        def call(self, name, arguments=None):
            out = super().call(name, arguments)
            out.pop("total")
            return out

    with pytest.raises(McpError):
        list_capped(NoTotal({"id": "u1"}, {"Task": rows(3)}), "Task.list", {})


def test_list_capped_pages_by_offset_and_caps():
    fc = FakeClient({"id": "u1"}, {"Task": rows(250)})
    out = list_capped(fc, "Task.list", {}, cap=200, page=100)
    assert len(out["rows"]) == 200
    assert out["total"] == 250
    assert out["truncated"] is True
    assert [r["id"] for r in out["rows"]] == [f"r{i}" for i in range(200)]
    assert [a.get("offset", 0) for _, a in fc.calls] == [0, 100]
    assert all(0 < a["limit"] <= 100 for _, a in fc.calls)
    assert len(fc.calls) == 2


def test_list_capped_never_requests_more_than_cap():
    fc = FakeClient({"id": "u1"}, {"Task": rows(500)})
    out = list_capped(fc, "Task.list", {}, cap=150, page=100)
    assert len(out["rows"]) == 150
    assert out["truncated"] is True
    requested = sum(a["limit"] for _, a in fc.calls)
    assert requested <= 150
    assert [r["id"] for r in out["rows"]] == [f"r{i}" for i in range(150)]


def test_list_capped_exact_cap_not_truncated():
    fc = FakeClient({"id": "u1"}, {"Task": rows(20)})
    out = list_capped(fc, "Task.list", {}, cap=20, page=7)
    assert len(out["rows"]) == 20
    assert out["truncated"] is False
    assert len({r["id"] for r in out["rows"]}) == 20
    assert [a.get("offset", 0) for _, a in fc.calls] == [0, 7, 14]


def test_list_capped_stops_on_empty_page_when_total_lies():
    fc = FakeClient({"id": "u1"}, {"Task": rows(30)})
    fc.total_override["Task.list"] = 1000
    out = list_capped(fc, "Task.list", {}, cap=200, page=10)
    assert len(out["rows"]) == 30
    # 3 full pages + one empty page, and no more
    assert len(fc.calls) == 4
    assert out["total"] == 1000


def test_list_capped_total_too_low_keeps_rows():
    fc = FakeClient({"id": "u1"}, {"Task": rows(250)})
    fc.total_override["Task.list"] = 10
    out = list_capped(fc, "Task.list", {}, cap=200, page=100)
    assert [r["id"] for r in out["rows"]] == [f"r{i}" for i in range(100)]  # nothing received is thrown away
    assert out["total"] == 100
    assert out["truncated"] is True  # a full page: more may exist
    assert len(fc.calls) == 1


def test_list_capped_total_too_low_short_page_is_complete():
    fc = FakeClient({"id": "u1"}, {"Task": rows(12)})
    fc.total_override["Task.list"] = 5
    out = list_capped(fc, "Task.list", {}, cap=200, page=100)
    assert len(out["rows"]) == 12 and out["total"] == 12 and out["truncated"] is False


def test_list_capped_server_ignoring_offset_stops_and_marks_truncated():
    fc = FakeClient({"id": "u1"}, {"Task": rows(250)})
    fc.ignored_filters = set()
    real = fc._list

    def no_offset(name, entity, args):
        return real(name, entity, {**args, "offset": 0})

    fc._list = no_offset
    out = list_capped(fc, "Task.list", {}, cap=250, page=100)
    assert [r["id"] for r in out["rows"]] == [f"r{i}" for i in range(100)]
    assert out["truncated"] is True
    assert len(fc.calls) == 2


def test_list_capped_rows_without_ids_are_not_deduplicated():
    fc = FakeClient({"id": "u1"}, {"Task": [{"title": "a"}, {"title": "a"}, {"title": "b"}]})
    out = list_capped(fc, "Task.list", {}, cap=10, page=2)
    assert len(out["rows"]) == 3 and out["truncated"] is False
