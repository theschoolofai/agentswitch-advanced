"""The write boundary: one write method, a single-use approval, an argument allowlist, the call budget, the draft
cap, the re-check of the original before saving and the read-back after it, and the review step's use of them."""
import json
import urllib.error

import pytest

from ea_agent import briefing, drafts, mcp
from ea_agent.mcp import CREATE_ARGS, Approval, McpClient, McpError, ToolNotAllowed
from ea_agent.review import Reviewer
from fakes import FakeClient, FakeOpener, rpc_ok

BASE = "https://example.invalid"
ME = {"id": "u1", "email": "me@example.test", "name": "Nora", "company_id": "c1"}
DRAFT = {"folder": "drafts", "is_draft": True, "to": "a@x.test", "subject": "Re: hi", "body_text": "Hi"}


def client(opener, **kw):
    c = McpClient(BASE, "tok", timeout=5, opener=opener)
    c.sleep = lambda *_a, **_k: None
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def original(**kw):
    base = {"id": "m1", "message_id": "<m1@mail.test>", "thread_id": "th1", "mailbox_id": "mb1",
            "from_email": "alice@example.test", "from_name": "Alice", "subject": "Budget", "body_text": "Can you?",
            "folder": "inbox", "is_draft": False, "is_answered": False}
    base.update(kw)
    return base


def world(*rows):
    return FakeClient(ME, {"EmailMessage": [dict(r) for r in rows]})


def save(fc, orig, cache=None, text="Thanks, will do."):
    return drafts.save_draft(fc, ME, orig, text, mailbox_ids=["mb1"], cache={} if cache is None else cache)


class Platform:
    """An opener that answers like the platform: list, get and create on one EmailMessage table."""

    def __init__(self, rows, fail_get_ids=(), created_row=None):
        self.rows = [dict(r) for r in rows]
        self.fail_get_ids = set(fail_get_ids)
        self.created_row = created_row
        self.sent = []

    def __call__(self, url, data, headers, method, timeout):
        status, body = self._answer(data)
        return status, json.dumps(body).encode()

    def _answer(self, data):
        body = json.loads(data)
        name, args = body["params"]["name"], body["params"]["arguments"]
        self.sent.append((name, args))
        if name == "EmailMessage.list":
            rows = [r for r in self.rows if r.get("folder") == args.get("folder")]
            return rpc_ok({"data": rows, "total": len(rows)})
        if name == "EmailMessage.get":
            if args["id"] in self.fail_get_ids:
                raise urllib.error.URLError("reset")
            for r in self.rows:
                if r["id"] == args["id"]:
                    return rpc_ok(r)
            return 200, {"jsonrpc": "2.0", "id": 1, "error": {"code": -32004, "message": "not found",
                                                               "data": {"code": "not_found"}}}
        if name == "EmailMessage.create":
            row = dict(self.created_row) if self.created_row is not None else {**args, "id": f"d{len(self.rows)}"}
            if row.get("id"):
                self.rows.append(row)
            return rpc_ok(row)
        raise AssertionError(f"unexpected tool {name}")

    def names(self):
        return [n for n, _ in self.sent]


# --------------------------------------------------------------------------- the one write method

def test_call_refuses_every_write_even_a_valid_draft():
    opener = FakeOpener(fn=lambda rec: rpc_ok({"id": "x"}))
    with pytest.raises(ToolNotAllowed):
        client(opener).call("EmailMessage.create", DRAFT)
    assert opener.calls == []


@pytest.mark.parametrize("tool", ["EmailMessage.send", "EmailMessage.update", "EmailMessage.delete",
                                  "CalendarEvent.create", "Task.update", "endpoint.email.messages.send"])
def test_call_refuses_other_writes(tool):
    opener = FakeOpener(fn=lambda rec: rpc_ok({}))
    with pytest.raises(ToolNotAllowed):
        client(opener).call(tool, {})
    assert opener.calls == []


@pytest.mark.parametrize("approval", [None, True, object(), "approved"])
def test_create_draft_needs_an_approval_object(approval):
    opener = FakeOpener(fn=lambda rec: rpc_ok({"id": "x"}))
    with pytest.raises(ToolNotAllowed):
        client(opener).create_draft(DRAFT, approval)
    assert opener.calls == []


def test_approval_is_single_use_even_when_the_write_fails():
    opener = FakeOpener(fn=lambda rec: urllib.error.URLError("reset"))
    c, approval = client(opener), Approval()
    with pytest.raises(McpError):
        c.create_draft(DRAFT, approval)
    assert approval.used is True
    with pytest.raises(ToolNotAllowed):
        c.create_draft(DRAFT, approval)
    assert len(opener.calls) == 1


@pytest.mark.parametrize("extra", [{"status": "sent"}, {"sent_at": "2026-11-19T10:00:00Z"}, {"labels": ["x"]},
                                   {"is_read": True}, {"server_folder": "outbox"}, {"cc": "boss@x.test"}])
def test_create_draft_refuses_arguments_outside_the_allowlist(extra):
    opener = FakeOpener(fn=lambda rec: rpc_ok({"id": "x"}))
    with pytest.raises(ToolNotAllowed):
        client(opener).create_draft({**DRAFT, **extra}, Approval())
    assert opener.calls == []


def test_create_args_are_exactly_what_save_draft_sends():
    fc = world(original())
    assert save(fc, original())["status"] == "created"
    sent = fc.calls_to("EmailMessage.create")[0]
    assert set(sent) == CREATE_ARGS


def test_transport_guard_refuses_create_without_a_spending_approval():
    opener = FakeOpener(fn=lambda rec: rpc_ok({"id": "x"}))
    c = client(opener)
    with pytest.raises(ToolNotAllowed):
        c._post("EmailMessage.create", dict(DRAFT))
    with pytest.raises(ToolNotAllowed):
        c._post("Task.update", {})
    assert opener.calls == []


def test_fake_client_refuses_writes_through_call_like_the_real_one():
    fc = world()
    with pytest.raises(AssertionError):
        fc.call("EmailMessage.create", DRAFT)
    assert fc.refused == ["EmailMessage.create"]


# --------------------------------------------------------------------------- budget and draft cap

def test_call_budget_stops_further_requests():
    opener = FakeOpener(fn=lambda rec: rpc_ok({"ok": 1}))
    c = client(opener, max_calls=3)
    for _ in range(3):
        c.call("Calendar.list", {})
    with pytest.raises(McpError) as exc:
        c.call("Calendar.list", {})
    assert exc.value.kind == "budget"
    assert len(opener.calls) == 3


def test_call_budget_counts_retries_and_me():
    opener = FakeOpener([(200, {"id": "u1"}), (502, b"busy"), (502, b"busy")])
    c = client(opener, max_calls=3)
    c.me()
    with pytest.raises(McpError) as exc:
        c.call("Calendar.list", {})
    assert exc.value.kind == "budget"
    assert len(opener.calls) == 3


def test_default_budget_and_cap_values():
    assert mcp.MAX_CALLS_PER_RUN == 400
    assert mcp.MAX_DRAFTS_PER_RUN == 25
    c = McpClient(BASE, "tok")
    assert (c.max_calls, c.max_drafts, c.http_calls, c.drafts_created) == (400, 25, 0, 0)


def test_draft_cap_refuses_before_the_network():
    opener = FakeOpener(fn=lambda rec: rpc_ok({"id": "x"}))
    c = client(opener, max_drafts=2)
    c.create_draft(DRAFT, Approval())
    c.create_draft(DRAFT, Approval())
    with pytest.raises(ToolNotAllowed) as exc:
        c.create_draft(DRAFT, Approval())
    assert "draft limit" in str(exc.value)
    assert len(opener.calls) == 2


def test_draft_cap_is_a_skip_and_costs_no_platform_call():
    platform = Platform([original(), original(id="m2", message_id="<m2@mail.test>")])
    c = client(platform, max_drafts=1)
    cache = {}
    first = drafts.save_draft(c, ME, original(), "Thanks.", mailbox_ids=["mb1"], cache=cache)
    second = drafts.save_draft(c, ME, original(id="m2", message_id="<m2@mail.test>"), "Thanks.",
                               mailbox_ids=["mb1"], cache=cache)
    assert first["status"] == "created"
    assert second["status"] == "skipped" and "draft limit" in second["error"]
    assert platform.names().count("EmailMessage.create") == 1
    # the first draft's re-check and read-back only: the capped one makes no re-check call
    assert platform.names().count("EmailMessage.get") == 2


# --------------------------------------------------------------------------- re-check before, read-back after

@pytest.mark.parametrize("answered", [True, "true", "1", 1, "yes"])
def test_answered_meanwhile_is_not_saved(answered):
    fc = world(original(is_answered=answered))
    out = save(fc, original())
    assert out["status"] == "skipped" and "already answered" in out["error"]
    assert fc.calls_to("EmailMessage.create") == []


def test_original_gone_is_not_saved():
    fc = world()
    out = save(fc, original())
    assert out["status"] == "skipped" and "no longer exists" in out["error"]
    assert fc.calls_to("EmailMessage.create") == []


def test_recheck_failure_is_not_saved():
    fc = world(original())
    fc.fail("EmailMessage.get", kind="network", message="down")
    out = save(fc, original())
    assert out["status"] == "error" and "re-check" in out["error"]
    assert fc.calls_to("EmailMessage.create") == []


def test_original_without_usable_id_is_not_saved():
    fc = world(original())
    out = save(fc, original(id=None))
    assert out["status"] == "error"
    assert fc.calls_to("EmailMessage.create") == []
    assert fc.calls_to("EmailMessage.get") == []


def test_order_is_list_get_create_get():
    platform = Platform([original()])
    out = drafts.save_draft(client(platform), ME, original(), "Thanks.", mailbox_ids=["mb1"], cache={})
    assert out["status"] == "created" and out["id"]
    assert platform.names() == ["EmailMessage.list", "EmailMessage.get", "EmailMessage.create", "EmailMessage.get"]
    assert platform.sent[1][1] == {"id": "m1"}
    assert platform.sent[3][1] == {"id": out["id"]}


def test_failed_read_back_is_unconfirmed_and_never_retried():
    platform = Platform([original()], created_row={"id": "d9", "folder": "drafts", "is_draft": True})
    platform.fail_get_ids.add("d9")
    c, cache = client(platform), {}
    out = drafts.save_draft(c, ME, original(), "Thanks.", mailbox_ids=["mb1"], cache=cache)
    assert out == {"status": "error", "id": "d9", "error": drafts.UNCONFIRMED}
    assert platform.names().count("EmailMessage.create") == 1
    # the same run never makes a second copy of it
    again = drafts.save_draft(c, ME, original(), "Thanks.", mailbox_ids=["mb1"], cache=cache)
    assert again["status"] == "exists"
    assert platform.names().count("EmailMessage.create") == 1


def test_create_reply_without_id_is_unconfirmed():
    platform = Platform([original()], created_row={"ok": True})
    out = drafts.save_draft(client(platform), ME, original(), "Thanks.", mailbox_ids=["mb1"], cache={})
    assert out["status"] == "error" and out["error"] == drafts.UNCONFIRMED


@pytest.mark.parametrize("row", [{"id": "d9", "folder": "sent", "is_draft": False},
                                 {"id": "d9", "folder": "drafts", "is_draft": False},
                                 {"id": "d9", "folder": "outbox"}])
def test_read_back_that_is_not_a_draft_is_reported(row):
    platform = Platform([original()], created_row=row)
    out = drafts.save_draft(client(platform), ME, original(), "Thanks.", mailbox_ids=["mb1"], cache={})
    assert out["status"] == "error" and "not an unsent draft" in out["error"]
    assert platform.names().count("EmailMessage.create") == 1


def test_create_failure_is_not_retried():
    fc = world(original())
    fc.fail("EmailMessage.create", kind="network", message="reset")
    out = save(fc, original())
    assert out["status"] == "error"
    assert len(fc.calls_to("EmailMessage.create")) == 1


# --------------------------------------------------------------------------- review

def _ctx():
    return {"slots": None, "deadline": None, "mailbox_ids": ["mb1"], "cache": {}}


def _item(**kw):
    return {**original(**kw), "needs_reply": True, "draft": "Thanks, will do.", "flags": []}


def test_review_does_not_offer_mail_that_already_has_a_draft():
    existing = {"id": "d0", "folder": "drafts", "is_draft": True, "mailbox_id": "mb1",
                "in_reply_to": "<m1@mail.test>", "thread_id": "th1", "subject": "Re: Budget"}
    fc = world(original(), existing)
    asked = []
    out = briefing._save(fc, ME, _item(), _ctx(), review=lambda *a: asked.append(a) or ("save", "x"))
    assert out == {"status": "exists", "id": "d0", "error": None}
    assert asked == []
    assert fc.calls_to("EmailMessage.create") == []


def test_review_still_offers_mail_without_a_draft():
    fc = world(original())
    asked = []
    out = briefing._save(fc, ME, _item(), _ctx(), review=lambda *a: asked.append(a) or ("skip", "skipped in review"))
    assert len(asked) == 1
    assert out["status"] == "skipped"


def test_edited_text_is_kept_when_the_save_fails():
    fc = world(original())
    fc.fail("EmailMessage.create", kind="forbidden", message="no write")
    item = _item()
    out = briefing._save(fc, ME, item, _ctx(), review=lambda *a: ("save", "Thanks Alice, will do today."))
    assert out["status"] == "error"
    assert item["draft"] == "Thanks Alice, will do today."
    assert item["draft_edited"] is True


def test_end_of_input_in_review_saves_nothing_more():
    def eof(_prompt=""):
        raise EOFError
    r = Reviewer(input_fn=eof, print_fn=lambda *_a: None, editor_fn=lambda t: t, environ={})
    assert r(_item(), _item()) == ("quit", None)
    assert r(_item(), _item()) == ("quit", None)
