from ea_briefing.collect import collect_mail
from fakes import FakeClient

ME = {"id": "u1", "email": "me@example.test", "name": "Me", "company_id": "c1", "employee_id": "e1",
      "party_id": "p1"}
KEEP = {"id", "message_id", "thread_id", "mailbox_id", "from_email", "from_name", "subject", "received_at",
        "snippet", "body_text"}
ACCOUNT = {"id": "acc1", "email": "me@example.test", "created_by": "u1"}
MAILBOX = {"id": "mb1", "email": "me@example.test", "created_by": "u1", "owner_id": "u1"}


def msg(id, received="2026-11-04T08:00:00+00:00", **kw):
    base = {"id": id, "mailbox_id": "mb1", "thread_id": f"th-{id}", "message_id": f"<{id}@mail.test>",
            "in_reply_to": None, "from_email": "alice@example.test", "from_name": "Alice", "to": ["me@example.test"],
            "cc": [], "subject": f"Subject {id}", "body_text": f"Body {id}", "body_html": None, "snippet": "snip",
            "folder": "inbox", "is_read": False, "is_draft": False, "is_answered": False, "received_at": received,
            "importance": "normal", "labels": []}
    base.update(kw)
    return base


def test_no_mailbox_status_and_no_message_list():
    fc = FakeClient(ME, {"EmailAccount": [], "Mailbox": [], "EmailMessage": [msg("m1")]})
    s = collect_mail(fc, ME)
    assert s["status"] == "no_mailbox"
    assert s["items"] == []
    assert s["notes"]
    assert fc.calls_to("EmailMessage.list") == []
    assert fc.refused == []


def test_filters_and_drops():
    messages = [
        msg("keep"),
        msg("answered", is_answered=True),
        msg("draft", is_draft=True),
        msg("self", from_email="me@example.test"),
        msg("read", is_read=True),
        msg("sent", folder="sent"),
        msg("spam", folder="spam"),
    ]
    fc = FakeClient(ME, {"EmailAccount": [ACCOUNT], "Mailbox": [MAILBOX], "EmailMessage": messages})
    s = collect_mail(fc, ME)
    assert s["status"] == "ok"
    # read but unanswered mail still needs a reply: opening it in the web app marks it read
    assert sorted(i["id"] for i in s["items"]) == ["keep", "read"]
    keep = next(i for i in s["items"] if i["id"] == "keep")
    assert KEEP <= set(keep)
    assert keep["body_text"] == "Body keep"
    calls = fc.calls_to("EmailMessage.list")
    assert calls
    assert all(a["folder"] == "inbox" for a in calls)
    assert all("is_read" not in a for a in calls)


def test_drops_survive_server_ignoring_flags():
    messages = [msg("keep"), msg("answered", is_answered=True), msg("draft", is_draft=True),
                msg("self", from_email="me@example.test")]
    fc = FakeClient(ME, {"EmailAccount": [ACCOUNT], "Mailbox": [MAILBOX], "EmailMessage": messages})
    fc.ignored_filters = {"is_answered", "is_draft", "from_email"}
    s = collect_mail(fc, ME)
    assert [i["id"] for i in s["items"]] == ["keep"]


def test_body_html_fallback_stripped():
    messages = [msg("h", body_text="", body_html="<html><body><p>Hello <b>there</b>,</p><div>see you</div></body></html>")]
    fc = FakeClient(ME, {"EmailAccount": [ACCOUNT], "Mailbox": [MAILBOX], "EmailMessage": messages})
    s = collect_mail(fc, ME)
    body = s["items"][0]["body_text"]
    assert "Hello" in body and "there" in body and "see you" in body
    assert "<" not in body and ">" not in body


def test_body_html_fallback_when_body_text_none():
    messages = [msg("h", body_text=None, body_html="<p>Only <i>html</i></p>")]
    fc = FakeClient(ME, {"EmailAccount": [ACCOUNT], "Mailbox": [MAILBOX], "EmailMessage": messages})
    body = collect_mail(fc, ME)["items"][0]["body_text"]
    assert "Only" in body and "html" in body and "<" not in body


def test_newest_first():
    messages = [msg("old", received="2026-11-01T08:00:00+00:00"), msg("new", received="2026-11-04T09:00:00+00:00"),
                msg("mid", received="2026-11-03T08:00:00+00:00")]
    fc = FakeClient(ME, {"EmailAccount": [ACCOUNT], "Mailbox": [MAILBOX], "EmailMessage": messages})
    assert [i["id"] for i in collect_mail(fc, ME)["items"]] == ["new", "mid", "old"]


def test_cap_respected_and_truncated():
    messages = [msg(f"m{i:02d}", received=f"2026-11-0{1 + i % 4}T{i % 24:02d}:00:00+00:00") for i in range(30)]
    fc = FakeClient(ME, {"EmailAccount": [ACCOUNT], "Mailbox": [MAILBOX], "EmailMessage": messages})
    s = collect_mail(fc, ME, cap=5)
    assert len(s["items"]) == 5
    assert s["truncated"] is True
    fetched = sum(a["limit"] for a in fc.calls_to("EmailMessage.list"))
    assert fetched <= 5


def test_default_cap_25():
    messages = [msg(f"m{i:02d}") for i in range(40)]
    fc = FakeClient(ME, {"EmailAccount": [ACCOUNT], "Mailbox": [MAILBOX], "EmailMessage": messages})
    s = collect_mail(fc, ME)
    assert len(s["items"]) == 25
    assert s["truncated"] is True


def test_message_list_failure_is_error():
    fc = FakeClient(ME, {"EmailAccount": [ACCOUNT], "Mailbox": [MAILBOX], "EmailMessage": [msg("m1")]})
    fc.fail("EmailMessage.list", kind="forbidden", message="mailbox locked")
    s = collect_mail(fc, ME)
    assert s["status"] == "error"
    assert s["error"]


def test_account_list_failure_is_error_not_no_mailbox():
    fc = FakeClient(ME, {"EmailAccount": [ACCOUNT], "Mailbox": [MAILBOX], "EmailMessage": [msg("m1")]})
    fc.fail("EmailAccount.list", kind="network", message="unreachable")
    s = collect_mail(fc, ME)
    assert s["status"] == "error"
