from datetime import date

from ea_briefing.collect import collect_overdue
from fakes import FakeClient

DAY = date(2026, 11, 4)
ME = {"id": "u1", "email": "me@example.test", "name": "Me", "company_id": "c1", "employee_id": "e1",
      "party_id": "p1"}
ITEM_KEYS = {"id", "title", "due_date", "days_overdue", "status", "project"}


def task(id, due, assignee="e1", status="todo", created_by="u9", project_id=None, title=None):
    return {"id": id, "title": title or f"Task {id}", "project_id": project_id, "assignee_id": assignee,
            "due_date": due, "status": status, "priority": "medium", "created_by": created_by}


PROJECTS = [{"id": "pa", "name": "Apollo", "status": "active"}, {"id": "pb", "name": "Borealis", "status": "active"}]


def run(tasks, me=ME, ignore=(), projects=None):
    fc = FakeClient(me, {"Task": tasks, "Project": PROJECTS if projects is None else projects}, today=DAY)
    fc.ignored_filters = set(ignore)
    return fc, collect_overdue(fc, me, DAY)


def ids(s):
    return [i["id"] for i in s["items"]]


def test_due_boundaries():
    tasks = [task("yesterday", "2026-11-03"), task("today", "2026-11-04"), task("tomorrow", "2026-11-05"),
             task("nodue", None)]
    fc, s = run(tasks)
    assert s["status"] == "ok"
    assert ids(s) == ["yesterday"]
    assert s["items"][0]["days_overdue"] == 1
    assert ITEM_KEYS <= set(s["items"][0])
    assert fc.refused == []


def test_due_boundaries_even_if_server_ignores_due_filter():
    tasks = [task("yesterday", "2026-11-03"), task("today", "2026-11-04"), task("tomorrow", "2026-11-05"),
             task("nodue", None)]
    _, s = run(tasks, ignore={"due_date"})
    assert ids(s) == ["yesterday"]


def test_query_filters():
    fc, _ = run([])
    calls = fc.calls_to("Task.list")
    assert calls
    for a in calls:
        assert a["due_date"] == "lt:2026-11-04"
        assert set(a["status"].split(",")) == {"todo", "in_progress", "in_review"}
    assert any(a.get("assignee_id") == "e1" for a in calls)
    assert any(a.get("created_by") == "u1" for a in calls)


def test_closed_statuses_excluded_even_if_server_ignores_status():
    tasks = [task("open", "2026-11-01"), task("ip", "2026-11-01", status="in_progress"),
             task("rev", "2026-11-01", status="in_review"), task("done", "2026-10-01", status="done"),
             task("completed", "2026-10-01", status="completed"), task("cancelled", "2026-10-01", status="cancelled")]
    _, s = run(tasks, ignore={"status"})
    assert set(ids(s)) == {"open", "ip", "rev"}


def test_ownership():
    tasks = [
        task("assigned_me", "2026-11-01", assignee="e1"),
        task("created_unassigned", "2026-11-01", assignee=None, created_by="u1"),
        task("created_assigned_other", "2026-11-01", assignee="e7", created_by="u1"),
        task("other", "2026-11-01", assignee="e7", created_by="u9"),
        task("other_unassigned", "2026-11-01", assignee=None, created_by="u9"),
    ]
    _, s = run(tasks)
    assert set(ids(s)) == {"assigned_me", "created_unassigned"}


def test_ownership_rechecked_when_server_ignores_owner_filters():
    tasks = [
        task("assigned_me", "2026-11-01", assignee="e1"),
        task("created_unassigned", "2026-11-01", assignee=None, created_by="u1"),
        task("created_assigned_other", "2026-11-01", assignee="e7", created_by="u1"),
        task("other", "2026-11-01", assignee="e7", created_by="u9"),
        task("other_unassigned", "2026-11-01", assignee=None, created_by="u9"),
        task("done_mine", "2026-11-01", status="done"),
        task("future_mine", "2026-11-09"),
    ]
    _, s = run(tasks, ignore={"assignee_id", "created_by", "status", "due_date"})
    assert set(ids(s)) == {"assigned_me", "created_unassigned"}


def test_null_employee_id_does_not_match_unassigned_tasks():
    me = dict(ME, employee_id=None)
    tasks = [
        task("other_unassigned", "2026-11-01", assignee=None, created_by="u9"),
        task("created_unassigned", "2026-11-01", assignee=None, created_by="u1"),
        task("assigned_someone", "2026-11-01", assignee="e1", created_by="u9"),
    ]
    fc, s = run(tasks, me=me)
    assert ids(s) == ["created_unassigned"]
    for a in fc.calls_to("Task.list"):
        assert not ("assignee_id" in a and a["assignee_id"] is None)
        assert a.get("assignee_id") not in ("", "null", "None")


def test_no_duplicates_when_both_queries_match():
    tasks = [task("both", "2026-11-01", assignee="e1", created_by="u1")]
    _, s = run(tasks)
    assert ids(s) == ["both"]


def test_days_overdue_and_sort_order():
    tasks = [
        task("t1", "2026-11-03", title="Zebra"),
        task("t2", "2026-10-25", title="Mango"),
        task("t3", "2026-11-03", title="Apple"),
        task("t4", "2026-10-04", title="Kiwi", assignee=None, created_by="u1"),
    ]
    _, s = run(tasks)
    assert [(i["title"], i["days_overdue"]) for i in s["items"]] == [
        ("Kiwi", 31), ("Mango", 10), ("Apple", 1), ("Zebra", 1)]
    assert s["items"][0]["due_date"] == "2026-10-04"
    assert s["items"][0]["status"] == "todo"


def test_project_names_cached_per_id():
    tasks = [task("a1", "2026-11-01", project_id="pa"), task("a2", "2026-11-02", project_id="pa"),
             task("a3", "2026-11-03", project_id="pa"), task("b1", "2026-11-01", project_id="pb"),
             task("none", "2026-11-01", project_id=None)]
    fc, s = run(tasks)
    by_id = {i["id"]: i["project"] for i in s["items"]}
    assert by_id == {"a1": "Apollo", "a2": "Apollo", "a3": "Apollo", "b1": "Borealis", "none": None}
    gets = fc.calls_to("Project.get")
    assert len(gets) == 2
    assert fc.names().count("Project.get") == 2


def test_project_get_failure_gives_none_but_section_ok():
    tasks = [task("a1", "2026-11-01", project_id="pa"), task("a2", "2026-11-02", project_id="pa")]
    fc = FakeClient(ME, {"Task": tasks, "Project": PROJECTS}, today=DAY)
    fc.fail("Project.get", kind="forbidden", message="no project access")
    s = collect_overdue(fc, ME, DAY)
    assert s["status"] == "ok"
    assert {i["id"]: i["project"] for i in s["items"]} == {"a1": None, "a2": None}


def test_missing_project_gives_none():
    _, s = run([task("x", "2026-11-01", project_id="ghost")])
    assert s["status"] == "ok"
    assert s["items"][0]["project"] is None


def test_task_list_failure_is_error_section():
    fc = FakeClient(ME, {"Task": [task("x", "2026-11-01")]}, today=DAY)
    fc.fail("Task.list", kind="http", message="server exploded")
    s = collect_overdue(fc, ME, DAY)
    assert s["status"] == "error"
    assert s["error"]
    assert s["items"] == []
