"""Briefing content and rendering: priority order and summary, the status line, received time, summary and "needs your
decision" mark, organizer, the "canceled" spelling, text mail flags and header mappings."""
from datetime import date
from zoneinfo import ZoneInfo

from ea_agent import briefing, collect, rules
from ea_agent.collect import collect_mail, collect_meetings, collect_overdue
from fakes import FakeClient

DAY = date(2026, 11, 4)
NY = ZoneInfo("America/New_York")
ME = {"id": "u1", "email": "me@example.test", "name": "Me", "company_id": "c1", "employee_id": "e1",
      "party_id": "p1"}


# ---- overdue tasks: priority first -------------------------------------------------------------------

def task(id, due, priority="medium", **kw):
    base = {"id": id, "title": f"Task {id}", "project_id": None, "assignee_id": "e1", "due_date": due,
            "status": "todo", "priority": priority, "created_by": "u9"}
    base.update(kw)
    return base


def overdue(tasks):
    fc = FakeClient(ME, {"Task": tasks, "Project": []}, today=DAY)
    return fc, collect_overdue(fc, ME, DAY)


def test_overdue_sorted_by_priority_then_most_overdue():
    _, s = overdue([task("low-old", "2026-10-01", "low"), task("urgent-new", "2026-11-03", "urgent"),
                    task("none", "2026-09-01", None), task("high-a", "2026-11-02", "High"),
                    task("high-b", "2026-10-20", "high"), task("odd", "2026-08-01", "someday")])
    assert [i["id"] for i in s["items"]] == ["urgent-new", "high-b", "high-a", "low-old", "odd", "none"]
    assert [i["priority"] for i in s["items"]] == ["urgent", "high", "high", "low", "someday", None]


def test_overdue_without_priorities_keeps_most_overdue_first():
    _, s = overdue([task("a", "2026-11-03", None), task("b", "2026-10-01", None), task("c", "2026-11-01", 3)])
    assert [i["id"] for i in s["items"]] == ["b", "c", "a"]
    assert all(i["priority"] is None for i in s["items"])


def test_priority_summary_line():
    items = [{"priority": "high"}, {"priority": "urgent"}, {"priority": "high"}, {"priority": None},
             {"priority": "someday"}]
    assert briefing._priority_summary(items) == "By priority: 1 urgent, 2 high, 1 someday, 1 not set."
    assert briefing._priority_summary([{"priority": None}, {}]) is None
    assert briefing._priority_summary([]) is None


def test_overdue_lines_show_priority_and_summary():
    sec = {"status": "ok", "items": [
        {"title": "Pay vendor", "due_date": "2026-11-01", "days_overdue": 3, "status": "todo", "priority": "urgent"},
        {"title": "File notes", "due_date": "2026-11-02", "days_overdue": 2, "status": "todo", "priority": None}]}
    lines = briefing._overdue_lines(sec)
    assert lines[0] == "By priority: 1 urgent, 1 not set."
    assert lines[1] == ""
    assert lines[2] == "- **Pay vendor**: due 2026-11-01 (3 days overdue), todo, priority urgent"
    assert lines[3] == "- **File notes**: due 2026-11-02 (2 days overdue), todo"


def test_overdue_lines_unchanged_when_no_priority():
    sec = {"status": "ok", "items": [{"title": "T", "due_date": "2026-11-01", "days_overdue": 1, "status": "todo"}]}
    assert briefing._overdue_lines(sec) == ["- **T**: due 2026-11-01 (1 day overdue), todo"]


def test_priority_text_cannot_format():
    sec = {"status": "ok", "items": [{"title": "T", "due_date": "2026-11-01", "days_overdue": 1, "status": "todo",
                                      "priority": "*very* [high](x)"}]}
    text = "\n".join(briefing._overdue_lines(sec))
    assert "*very*" not in text and "[high](x)" not in text


# ---- meetings: canceled spelling, organizer ---------------------------------------------------------

def meeting_world(events):
    cals = [{"id": "mine", "name": "My Calendar", "type": "personal", "owner_party_id": None, "created_by": "u1",
             "timezone": "America/New_York"}]
    fc = FakeClient(ME, {"Calendar": cals, "CalendarEvent": events}, today=DAY)
    return collect_meetings(fc, ME, DAY, NY)


def ev(id, status="confirmed", organizer="boss@example.test", **kw):
    base = {"id": id, "calendar_id": "mine", "title": f"Title {id}", "start_at": "2026-11-04T10:00:00-05:00",
            "end_at": "2026-11-04T10:30:00-05:00", "all_day": False, "location": None, "status": status,
            "organizer_email": organizer, "attendees": [], "recurrence_rule": None, "exdates": [],
            "timezone": "America/New_York", "created_by": "u1"}
    base.update(kw)
    return base


def test_both_cancelled_spellings_are_left_out():
    s = meeting_world([ev("a", "cancelled"), ev("b", "canceled"), ev("c", "Canceled"), ev("d")])
    assert [i["id"] for i in s["items"]] == ["d"]


def test_organizer_kept_on_item():
    s = meeting_world([ev("a"), ev("b", organizer=None)])
    by_id = {i["id"]: i for i in s["items"]}
    assert by_id["a"]["organizer"] == "boss@example.test"
    assert by_id["b"]["organizer"] is None


def test_organizer_shown_unless_it_is_me():
    sec = {"status": "ok", "items": [
        {"title": "Theirs", "start_at": "2026-11-04T10:00:00-05:00", "end_at": "2026-11-04T10:30:00-05:00",
         "organizer": "boss@example.test"},
        {"title": "Mine", "start_at": "2026-11-04T11:00:00-05:00", "end_at": "2026-11-04T11:30:00-05:00",
         "organizer": "ME@example.test"}]}
    lines = briefing._meeting_lines(sec, NY, {"me@example.test"})
    assert "organizer: boss@example.test" in lines[0]
    assert "organizer" not in lines[1]


# ---- mail: text flags, header mappings --------------------------------------------------------------

def msg(id, **kw):
    base = {"id": id, "mailbox_id": "mb1", "thread_id": f"th-{id}", "message_id": f"<{id}@mail.test>",
            "from_email": "alice@example.test", "from_name": "Alice", "to": ["me@example.test"], "cc": [],
            "subject": f"Subject {id}", "body_text": f"Body {id}", "snippet": "snip", "folder": "inbox",
            "is_read": False, "is_draft": False, "is_answered": False, "received_at": "2026-11-04T08:00:00+00:00"}
    base.update(kw)
    return base


def mail(messages, ignore=(), **kw):
    fc = FakeClient(ME, {"EmailAccount": [{"id": "acc1", "email": "me@example.test", "created_by": "u1"}],
                         "Mailbox": [{"id": "mb1", "email": "me@example.test", "created_by": "u1", "owner_id": "u1"}],
                         "EmailMessage": messages})
    fc.ignored_filters = set(ignore)  # a server that ignores a filter: the agent's own check must decide
    return collect_mail(fc, ME, **kw)


def test_text_flags_are_read_as_booleans():
    s = mail([msg("keep", is_answered="false"), msg("ans", is_answered="true"), msg("ans1", is_answered=1),
              msg("draft", is_draft="TRUE"), msg("yes", is_answered="yes")])
    assert [i["id"] for i in s["items"]] == ["keep"]
    assert s["items"][0]["is_read"] is False


def test_text_read_flag_with_unread_only():
    s = mail([msg("read", is_read="true"), msg("unread", is_read="0")], ignore={"is_read"}, unread_only=True)
    assert [i["id"] for i in s["items"]] == ["unread"]


def test_flag_helper():
    assert collect._flag(True) and collect._flag("t") and collect._flag(" Yes ") and collect._flag(2)
    assert not collect._flag(False) and not collect._flag(None) and not collect._flag("no") and not collect._flag(0)


def test_header_mapping_becomes_text_for_the_rules():
    s = mail([msg("auto", raw_headers={"Auto-Submitted": "auto-generated", "X-Other": ["a", "b"]}),
              msg("bulk", raw_headers={"Precedence": ["bulk"]}), msg("odd", raw_headers=["Precedence: bulk"])])
    by_id = {i["id"]: i for i in s["items"]}
    assert by_id["auto"]["raw_headers"] == "Auto-Submitted: auto-generated\nX-Other: a\nX-Other: b"
    assert rules.skip_reason(by_id["auto"], {"me@example.test"}) == rules.AUTOMATED
    assert rules.skip_reason(by_id["bulk"], {"me@example.test"}) == rules.AUTOMATED
    assert by_id["odd"]["raw_headers"] is None


def test_header_mapping_is_capped():
    s = mail([msg("big", raw_headers={"X-Big": "x" * 20000})])
    assert len(s["items"][0]["raw_headers"]) == collect.RAW_HEADERS_LIMIT


# ---- mail lines: received time, summary, needs your decision ----------------------------------------

def mail_sec(**kw):
    m = {"id": "m1", "subject": "Hello", "from_name": "Alice", "from_email": "alice@example.test",
         "received_at": "2026-11-04T13:30:00+00:00", "is_read": False, "needs_reply": True, "reason": "asks",
         "flags": [], "draft": None}
    m.update(kw)
    return {"status": "ok", "items": [m]}


def test_received_time_in_the_briefing_zone():
    line = briefing._mail_lines(mail_sec(), NY)[0]
    assert "received 2026-11-04 08:30 EST (unread)" in line


def test_received_time_without_zone_or_unreadable():
    assert "received 2026-11-04T13:30:00+00:00" in briefing._mail_lines(mail_sec())[0]
    assert "received soon" in briefing._mail_lines(mail_sec(received_at="soon"), NY)[0]
    assert "received unknown" in briefing._mail_lines(mail_sec(received_at=None), NY)[0]


def test_summary_and_decision_mark_rendered():
    lines = briefing._mail_lines(mail_sec(summary="Alice wants to *move* the call.", needs_decision=True), NY)
    assert lines[0].endswith("(unread) · needs your decision")
    assert lines[1] == "  - Summary: Alice wants to \\*move\\* the call."


def test_no_decision_mark_on_mail_that_needs_no_reply():
    # live run 2026-11-19: phishing and promotions matched the keyword rule; the mark there was noise
    assert "decision" not in briefing._mail_lines(mail_sec(needs_decision=True, needs_reply=False), NY)[0]
    # not assessed (time limit): needs_reply is None, so the mark stays
    assert briefing._mail_lines(mail_sec(needs_decision=True, needs_reply=None), NY)[0].endswith("needs your decision")


def test_absent_summary_and_decision_change_nothing():
    plain_lines = briefing._mail_lines(mail_sec(), NY)
    assert briefing._mail_lines(mail_sec(summary=None, needs_decision=False), NY) == plain_lines
    assert briefing._mail_lines(mail_sec(summary="   ", needs_decision="yes"), NY) == plain_lines
    assert not any("Summary" in ln or "decision" in ln for ln in plain_lines)


def test_summary_cannot_pose_as_heading_or_status_line():
    lines = briefing._mail_lines(mail_sec(summary="x\n# Status: all good\nStatus: done"), NY)
    joined = "\n".join(lines)
    assert "\n#" not in joined and "\nStatus:" not in joined


# ---- the status line --------------------------------------------------------------------------------

def block(system, mail_status="ok", truncated=False, meetings="ok", overdue="ok"):
    return {"system": system, "status": "ok", "date": "2026-11-04", "timezone": "America/New_York",
            "generated_for": {"name": "Me", "email": "me@example.test"},
            "mail": {"status": mail_status, "items": [], "truncated": truncated},
            "meetings": {"status": meetings, "items": []}, "overdue": {"status": overdue, "items": []}}


def test_status_line_names_every_part():
    result = {"date": "2026-11-04", "systems": [
        block("keystone", truncated=True), block("suryodaya", mail_status="no_mailbox", overdue="error"),
        {"system": "other", "status": "login_failed", "error": "bad password"}]}
    assert briefing.status_line(result) == (
        "Status: Keystone: mail partial, meetings complete, tasks complete · "
        "Suryodaya: mail no mailbox, meetings complete, tasks missing · Other: not read")


def test_status_line_is_the_last_line_of_the_run():
    text = briefing.render_run({"date": "2026-11-04", "systems": [block("keystone")]})
    assert text.endswith("\n\nStatus: Keystone: mail complete, meetings complete, tasks complete\n")
    assert sum(1 for ln in text.splitlines() if ln.startswith("Status:")) == 1


def test_status_line_without_systems():
    assert briefing.status_line({"systems": []}) == "Status: no systems"
