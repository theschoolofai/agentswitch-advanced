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
    # v1: the JSON is the combined run, one entry per system under "systems"
    path = tmp_path / "out.json"
    code = run_cli(monkeypatch, *BASE_ARGS, "--json", str(path))
    assert code == 0
    data = json.loads(path.read_text())
    assert data["date"] == "2026-11-04"
    block = data["systems"][0]
    assert block["system"] == "keystone"
    assert block["mail"]["status"] == "no_mailbox"
    assert [i["id"] for i in block["meetings"]["items"]] == ["ev1"]
    assert "Standup" in capsys.readouterr().out
    assert "platform-token-secret" not in path.read_text()


def test_no_save_creates_nothing(fake, monkeypatch, capsys):
    run_cli(monkeypatch, *BASE_ARGS, "--no-save")
    assert fake.calls_to("EmailMessage.create") == []


def test_markdown_file_written_by_default_d8(fake, monkeypatch, capsys, tmp_path):
    assert run_cli(monkeypatch, *BASE_ARGS) == 0
    out = capsys.readouterr().out
    path = tmp_path / "briefings" / "briefing-2026-11-04.md"
    assert path.read_text() + "\n" == out
    assert (path.stat().st_mode & 0o777) == 0o600
    assert [p.name for p in (tmp_path / "briefings").iterdir()] == ["briefing-2026-11-04.md"]
    # same day again: overwritten, still one file
    assert run_cli(monkeypatch, *BASE_ARGS) == 0
    assert [p.name for p in (tmp_path / "briefings").iterdir()] == ["briefing-2026-11-04.md"]


def test_out_dir_and_no_file_d8(fake, monkeypatch, capsys, tmp_path):
    assert run_cli(monkeypatch, *BASE_ARGS, "--out", str(tmp_path / "elsewhere")) == 0
    assert (tmp_path / "elsewhere" / "briefing-2026-11-04.md").is_file()
    assert run_cli(monkeypatch, *BASE_ARGS, "--no-file", "--out", str(tmp_path / "none")) == 0
    assert not (tmp_path / "none").exists()


def test_unwritable_briefing_file_exit_2(fake, monkeypatch, capsys, tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, not a folder")
    assert run_cli(monkeypatch, *BASE_ARGS, "--out", str(blocker)) == 2
    assert "could not write the briefing file" in capsys.readouterr().err


def test_review_without_tty_exits_1(fake, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    code = run_cli(monkeypatch, *BASE_ARGS, "--review")
    err = capsys.readouterr().err
    assert code == 1
    assert "--review needs an interactive terminal" in err


def test_save_drafts_is_accepted_as_alias(fake, monkeypatch, capsys):
    assert run_cli(monkeypatch, *BASE_ARGS, "--save-drafts") == 0


def test_platform_label_sets_system_zone(fake, monkeypatch, capsys):
    code = run_cli(monkeypatch, "--today", "2026-11-04", "--no-llm")
    out = capsys.readouterr().out.replace("\\", "")
    assert code == 0
    assert "Time zone: America/New_York (from your calendar)" in out


@pytest.mark.parametrize("argv", [("--bogus",), ("--mail-cap", "many"), ("--time-limit", "soon"),
                                  ("--model-parallel", "x")])
def test_bad_flags_exit_1(fake, monkeypatch, capsys, argv):
    assert run_cli(monkeypatch, *argv) == 1
    assert "usage:" in capsys.readouterr().err


def test_help_exits_0(fake, monkeypatch, capsys):
    assert run_cli(monkeypatch, "--help") == 0
    out = capsys.readouterr().out
    assert "--model-parallel" in out and "--unread-only" in out


def test_logout_in_platform_mode_touches_nothing(fake, monkeypatch, capsys, tmp_path):
    cache = tmp_path / "c" / "tokens.json"
    cache.parent.mkdir()
    cache.write_text("{}")
    monkeypatch.setenv("EA_TOKEN_CACHE", str(cache))
    assert run_cli(monkeypatch, "--logout") == 0
    assert cache.exists()
    assert "Platform mode has no saved logins" in capsys.readouterr().out
