"""Drives `python -m ea_briefing` in-process.

The spec names no client-factory seam for the CLI, so the fake is wired in by patching the methods of the real
`McpClient` class (platform mode builds it from AGENTSWITCH_* without a login) and the CLI is run as `__main__`.
"""

import json
import runpy
import sys

import pytest

from ea_briefing import mcp
from fakes import FakeClient

ME = {"id": "u1", "email": "me@example.test", "name": "Nora Example", "company_id": "c1", "employee_id": "e1",
      "party_id": "p1"}


def tables():
    return {
        "EmailAccount": [],
        "Mailbox": [],
        "EmailMessage": [],
        "Calendar": [{"id": "mine", "name": "My Calendar", "type": "personal", "owner_party_id": "p1",
                      "created_by": "u1", "timezone": "America/New_York"}],
        "CalendarEvent": [
            {"id": "ev1", "calendar_id": "mine", "title": "Standup", "start_at": "2026-11-04T09:00:00-05:00",
             "end_at": "2026-11-04T09:15:00-05:00", "all_day": False, "location": None, "status": "confirmed",
             "organizer_email": ME["email"], "attendees": [], "recurrence_rule": None, "exdates": [],
             "created_by": "u1"}],
        "Task": [],
        "Project": [],
    }


@pytest.fixture
def fake(monkeypatch):
    fc = FakeClient(ME, tables())
    monkeypatch.setattr(mcp.McpClient, "call", lambda self, name, arguments=None: fc.call(name, arguments))
    monkeypatch.setattr(mcp.McpClient, "me", lambda self: fc.me())

    def no_login(*_a, **_k):
        raise AssertionError("login must not be attempted in platform mode")

    monkeypatch.setattr(mcp.McpClient, "login", classmethod(no_login))
    monkeypatch.setenv("AGENTSWITCH_TOKEN", "platform-token-secret")
    monkeypatch.setenv("AGENTSWITCH_BASE_URL", "https://platform.invalid")
    monkeypatch.setenv("AGENTSWITCH_INSTANCE", "keystone")
    return fc


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["ea_briefing", *argv])
    sys.modules.pop("ea_briefing.__main__", None)
    try:
        runpy.run_module("ea_briefing", run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    return 0


BASE_ARGS = ("--today", "2026-11-04", "--tz", "America/New_York", "--no-llm")


def test_exit_zero_when_all_ok(fake, monkeypatch, capsys):
    code = run_cli(monkeypatch, *BASE_ARGS)
    out = capsys.readouterr().out
    assert code == 0
    assert "Standup" in out
    assert "No mailbox is linked to this login yet." in out
    assert "Nothing overdue." in out
    assert "platform-token-secret" not in out
    assert fake.refused == []


def test_exit_two_when_a_section_errors(fake, monkeypatch, capsys):
    fake.fail("Task.list", kind="forbidden", message="tasks locked")
    code = run_cli(monkeypatch, *BASE_ARGS)
    out = capsys.readouterr().out
    assert code == 2
    assert "Could not load" in out
    assert "Standup" in out
    assert "Nothing overdue" not in out


def test_json_output_written(fake, monkeypatch, capsys, tmp_path):
    path = tmp_path / "out.json"
    code = run_cli(monkeypatch, *BASE_ARGS, "--json", str(path))
    assert code == 0
    data = json.loads(path.read_text())
    assert data["date"] == "2026-11-04"
    assert data["mail"]["status"] == "no_mailbox"
    assert [i["id"] for i in data["meetings"]["items"]] == ["ev1"]
    assert "Standup" in capsys.readouterr().out


def test_no_drafts_saved_without_flag(fake, monkeypatch, capsys):
    run_cli(monkeypatch, *BASE_ARGS)
    assert fake.calls_to("EmailMessage.create") == []
