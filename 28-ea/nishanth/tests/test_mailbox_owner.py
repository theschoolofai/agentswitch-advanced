"""Mailbox ownership as the live platform reports it: each mailbox carries `user_id` and its own address."""

import json
from datetime import date

from ea_briefing.briefing import build_briefing
from ea_briefing.collect import collect_mail
from ea_briefing.drafts import save_draft
from fakes import FakeClient, FakeLLM

DAY = date(2026, 11, 4)
ME = {"id": "u1", "email": "me@login.test", "name": "Nora Example", "company_id": "c1", "employee_id": None,
      "party_id": None}
MINE = {"id": "mb1", "user_id": "u1", "email": "nora@company.test", "created_by": "admin"}
THEIRS = {"id": "mb2", "user_id": "u9", "email": "ceo@company.test", "created_by": "admin"}


def msg(id, mailbox="mb1", **kw):
    base = {"id": id, "mailbox_id": mailbox, "thread_id": f"th-{id}", "message_id": f"<{id}@mail.test>",
            "in_reply_to": None, "from_email": f"{id}@ext.test", "from_name": f"Sender {id}",
            "to": "nora@company.test", "cc": None, "subject": f"Subject {id}", "body_text": "please reply",
            "body_html": None, "snippet": "", "folder": "inbox", "is_read": False, "is_draft": False,
            "is_answered": False, "received_at": "2026-11-04T08:00:00+00:00"}
    base.update(kw)
    return base


def world(messages, mailboxes=(MINE,)):
    return FakeClient(ME, {"Mailbox": list(mailboxes), "EmailAccount": [], "EmailMessage": list(messages),
                           "Calendar": [], "CalendarEvent": [], "Task": [], "Project": []}, today=DAY)


def ids(section):
    return [i["id"] for i in section["items"]]


def test_mail_to_the_mailbox_address_is_kept():
    s = collect_mail(world([msg("a")]), ME)
    assert s["status"] == "ok" and ids(s) == ["a"]
    assert not any("not addressed" in n for n in s["notes"])


def test_owned_mailbox_keeps_mail_not_addressed_to_me():
    # bcc and mailing-list mail land in the mailbox without naming it; ownership is proven, so it counts
    s = collect_mail(world([msg("bcc", to="list@company.test")]), ME)
    assert ids(s) == ["bcc"]


def test_mailbox_of_another_user_is_skipped_even_if_listed():
    fc = world([msg("a"), msg("ceo", mailbox="mb2", to="ceo@company.test")], mailboxes=(MINE, THEIRS))
    s = collect_mail(fc, ME)
    assert ids(s) == ["a"]
    assert s["mailbox_ids"] == ["mb1"]
    assert any("belong to other users" in n for n in s["notes"])
    assert all("mb2" not in str(a.get("mailbox_id", "")) for a in fc.calls_to("EmailMessage.list"))


def test_only_other_users_mailboxes_is_an_error_not_zero():
    s = collect_mail(world([msg("ceo", mailbox="mb2")], mailboxes=(THEIRS,)), ME)
    assert s["status"] == "error" and "belongs to this user" in s["error"]


def test_mail_from_the_mailbox_address_is_not_listed():
    s = collect_mail(world([msg("self", from_email="Nora@Company.test")]), ME)
    assert ids(s) == []


def test_mailbox_email_attached_to_items():
    s = collect_mail(world([msg("a")]), ME)
    assert s["items"][0]["mailbox_email"] == "nora@company.test"


def test_draft_goes_out_from_the_mailbox_address():
    fc = world([msg("a")])
    original = collect_mail(fc, ME)["items"][0]
    res = save_draft(fc, ME, original, "Thanks, Thursday works.", mailbox_ids=["mb1"])
    assert res["status"] == "created"
    (args,) = fc.calls_to("EmailMessage.create")
    assert args["from_email"] == "nora@company.test"
    assert args["to"] == "a@ext.test" and args["folder"] == "drafts" and args["is_draft"] is True


def test_draft_falls_back_to_login_address_without_mailbox_email():
    fc = world([msg("a")], mailboxes=({"id": "mb1", "user_id": "u1"},))
    original = collect_mail(fc, ME)["items"][0]
    save_draft(fc, ME, original, "Thanks, Thursday works.", mailbox_ids=["mb1"])
    (args,) = fc.calls_to("EmailMessage.create")
    assert args["from_email"] == "me@login.test"


def test_end_to_end_briefing_lists_and_drafts_from_owned_mailbox():
    fc = world([msg("a"), msg("ceo", mailbox="mb2")], mailboxes=(MINE, THEIRS))
    llm = FakeLLM([json.dumps({"needs_reply": True, "reason": "asks to confirm", "draft": "Confirmed, thanks."})])
    b = build_briefing(fc, ME, DAY, __import__("zoneinfo").ZoneInfo("UTC"), llm=llm, save_drafts=True)
    assert [i["id"] for i in b["mail"]["items"]] == ["a"]
    assert b["mail"]["items"][0]["draft_saved"]["status"] == "created"
    assert all(a["mailbox_id"] == "mb1" for a in fc.calls_to("EmailMessage.create"))
    assert len(llm.calls) == 1


# --------------------------------------------------------------------------- unanswered, not unread (2026-11-07)

def test_read_but_unanswered_mail_is_listed_and_marked():
    s = collect_mail(world([msg("opened", is_read=True), msg("new")]), ME, day=DAY)
    assert sorted(ids(s)) == ["new", "opened"]
    by_id = {i["id"]: i for i in s["items"]}
    assert by_id["opened"]["is_read"] is True and by_id["new"]["is_read"] is False


def test_answered_mail_is_not_listed_even_if_unread():
    s = collect_mail(world([msg("done", is_answered=True), msg("open")]), ME, day=DAY)
    assert ids(s) == ["open"]


def test_lookback_window_is_14_days_and_sent_to_server():
    fc = world([msg("old", received_at="2026-10-20T10:00:00+00:00"),
                msg("edge", received_at="2026-10-21T00:00:00+00:00"),
                msg("recent", received_at="2026-11-03T10:00:00+00:00")])
    s = collect_mail(fc, ME, day=DAY, tz=__import__("zoneinfo").ZoneInfo("UTC"))
    assert sorted(ids(s)) == ["edge", "recent"]
    assert all(a.get("received_at") == "gte:2026-10-21T00:00:00+00:00"
               for a in fc.calls_to("EmailMessage.list"))


def test_lookback_rechecked_when_server_ignores_received_filter():
    fc = world([msg("old", received_at="2026-10-01T10:00:00+00:00"), msg("recent")])
    fc.ignored_filters = {"received_at"}
    s = collect_mail(fc, ME, day=DAY)
    assert ids(s) == ["recent"]


def test_markdown_marks_unread_only():
    from ea_briefing.briefing import render_markdown
    fc = world([msg("opened", is_read=True, subject="Opened one"), msg("new", subject="New one")])
    b = build_briefing(fc, ME, DAY, __import__("zoneinfo").ZoneInfo("UTC"))
    lines = [l for l in render_markdown(b).splitlines() if "received" in l]
    assert any("New one" in l and "(unread)" in l for l in lines)
    assert any("Opened one" in l and "(unread)" not in l for l in lines)


# --------------------------------------------------------------------------- model failures are not a clean run

def _boom(system, user):
    raise RuntimeError("model down")


def test_model_failure_adds_warning():
    b = build_briefing(world([msg("a"), msg("b")]), ME, DAY, __import__("zoneinfo").ZoneInfo("UTC"), llm=_boom)
    assert any("2 of 2 emails could not be assessed" in w for w in b["warnings"])


def test_no_model_configured_is_not_a_warning():
    b = build_briefing(world([msg("a")]), ME, DAY, __import__("zoneinfo").ZoneInfo("UTC"), llm=None)
    assert b["warnings"] == []


def test_model_success_is_not_a_warning():
    llm = FakeLLM([json.dumps({"needs_reply": False, "reason": "fyi", "draft": None})])
    b = build_briefing(world([msg("a")]), ME, DAY, __import__("zoneinfo").ZoneInfo("UTC"), llm=llm)
    assert b["warnings"] == []
