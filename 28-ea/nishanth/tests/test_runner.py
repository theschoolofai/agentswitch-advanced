"""runner.run (D1, D2, D6, D7, D8, D11, D11b): whole runs against fake systems, a fake login and a fake model."""

import json
import os
from datetime import date, datetime, timezone

import pytest

from ea_briefing import runner
from fakes import FakeClient, FakeOpener, make_mcp_error

NOW = datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc)  # Wed 4 Nov: 08:00 New York, 18:30 Kolkata
PASSWORD_K = "pw-Keystone-SECRET-1"
PASSWORD_S = "pw-Suryodaya-SECRET-2"
ME = {"id": "u1", "email": "me@example.test", "name": "Nora Example", "company_id": "c1", "employee_id": "e1",
      "party_id": "p1"}


def msg(id, subject, body, **kw):
    base = {"id": id, "mailbox_id": "mb1", "thread_id": f"th-{id}", "message_id": f"<{id}@mail.test>",
            "in_reply_to": None, "from_email": f"{id}@ext.test", "from_name": f"Sender {id}", "to": [ME["email"]],
            "cc": [], "subject": subject, "body_text": body, "body_html": None, "snippet": "", "folder": "inbox",
            "is_read": False, "is_draft": False, "is_answered": False, "received_at": "2026-11-03T08:00:00+00:00",
            "importance": "normal", "labels": []}
    base.update(kw)
    return base


def world(title, messages=(), calendars=()):
    tables = {"EmailAccount": [{"id": "acc1", "email": ME["email"]}],
              "Mailbox": [{"id": "mb1", "email": ME["email"], "created_by": "u1", "owner_id": "u1"}],
              "EmailMessage": list(messages), "Calendar": list(calendars), "CalendarEvent": [],
              "Task": [{"id": "t1", "title": title, "project_id": None, "assignee_id": "e1", "due_date": "2026-11-01",
                        "status": "todo", "priority": "high", "created_by": "u9"}], "Project": []}
    return FakeClient(ME, tables, today=date(2026, 11, 4))


class Platform:
    """Two fake systems, a login that hands out tokens, and a record of everything asked of it."""

    def __init__(self, fail_login=(), messages=None):
        messages = messages or {}
        self.clients = {"keystone": world("Keystone task", messages.get("keystone", ())),
                        "suryodaya": world("Suryodaya task", messages.get("suryodaya", ()))}
        self.fail_login = set(fail_login)
        self.logins = []
        self.tokens = {}

    def login(self, base_url, email, password):
        system = "keystone" if base_url.startswith("https://class.") else "suryodaya"
        self.logins.append(system)
        if system in self.fail_login:
            raise make_mcp_error("auth", "login failed: HTTP 401; not retried", 401)
        token = f"token-{system}-SECRET-{len(self.logins)}"
        self.tokens[token] = system
        return token

    def factory(self, system, base_url, token):
        if token not in self.tokens and not token.startswith("platform-"):
            raise AssertionError("unknown token")
        return self.clients[system or "keystone"]


def env(**extra):
    base = {"EA_EMAIL": ME["email"], "EA_PASSWORD_KEYSTONE": PASSWORD_K, "EA_PASSWORD_SURYODAYA": PASSWORD_S,
            "EA_TOKEN_CACHE": os.path.join(os.getcwd(), "cache", "tokens.json")}
    base.update(extra)
    return {k: v for k, v in base.items() if v is not None}


def go(p, options=None, environ=None, tty=False, **kw):
    opts = {"today": "2026-11-04", "no_llm": True}
    opts.update(options or {})
    kw.setdefault("now", NOW)
    return runner.run(opts, environ if environ is not None else env(), tty, client_factory=p.factory,
                      login_fn=p.login, **kw)


def secrets_absent(*texts):
    for t in texts:
        for secret in (PASSWORD_K, PASSWORD_S, "SECRET"):
            assert secret not in t


# --------------------------------------------------------------------------- D1

def test_both_systems_in_one_run(capsys, tmp_path):
    p = Platform()
    result, code = go(p)
    out, err = capsys.readouterr()
    assert code == 0
    assert [b["system"] for b in result["systems"]] == ["keystone", "suryodaya"]
    assert "## Keystone: Nora Example, 2026-11-04" in out and "## Suryodaya: Nora Example, 2026-11-04" in out
    assert "Keystone task" in out and "Suryodaya task" in out
    assert sorted(p.logins) == ["keystone", "suryodaya"]
    secrets_absent(out, err, (tmp_path / "briefings" / "briefing-2026-11-04.md").read_text())


def test_system_flag_narrows(capsys):
    p = Platform()
    result, code = go(p, {"system": ["suryodaya"]})
    assert code == 0 and [b["system"] for b in result["systems"]] == ["suryodaya"]
    assert p.logins == ["suryodaya"]


def test_default_skips_system_without_credentials(capsys):
    p = Platform()
    result, code = go(p, environ=env(EA_PASSWORD_SURYODAYA=None))
    assert code == 0 and [b["system"] for b in result["systems"]] == ["keystone"]


def test_named_system_without_credentials_reports_in_block(capsys):
    p = Platform()
    result, code = go(p, {"system": ["keystone", "suryodaya"]}, environ=env(EA_PASSWORD_SURYODAYA=None))
    out = capsys.readouterr().out
    assert code == 2
    assert "Could not log in: no saved login and no password" in out
    assert "Keystone task" in out
    assert p.logins == ["keystone"]


def test_one_login_failure_does_not_stop_the_other(capsys):
    p = Platform(fail_login={"keystone"})
    result, code = go(p)
    out, err = capsys.readouterr()
    assert code == 2
    assert "## Keystone\n\nCould not log in: auth: login failed" in out
    assert "Suryodaya task" in out
    assert p.logins.count("keystone") == 1
    secrets_absent(out, err)


def test_all_logins_failed_exit_1(capsys):
    p = Platform(fail_login={"keystone", "suryodaya"})
    _, code = go(p)
    err = capsys.readouterr().err
    assert code == 1 and "could not log in" in err
    assert sorted(p.logins) == ["keystone", "suryodaya"]
    assert not os.path.exists("briefings")


def test_nothing_configured_exit_1(capsys):
    _, code = go(Platform(), environ={"EA_TOKEN_CACHE": os.path.join(os.getcwd(), "t.json")})
    assert code == 1 and "no system configured" in capsys.readouterr().err


def test_bad_flag_values_exit_1(capsys):
    assert go(Platform(), {"system": ["mars"]})[1] == 1
    assert go(Platform(), {"time_limit": 0})[1] == 1
    assert go(Platform(), {"tz": ["Nowhere/Land"]})[1] == 1


def test_platform_mode_one_system_no_login_no_cache(capsys, tmp_path):
    p = Platform()
    cache = tmp_path / "pcache" / "tokens.json"
    environ = {"AGENTSWITCH_TOKEN": "platform-SECRET", "AGENTSWITCH_BASE_URL": "https://p.invalid",
               "AGENTSWITCH_INSTANCE": "suryodaya", "EA_TOKEN_CACHE": str(cache), "EA_EMAIL": ME["email"],
               "EA_PASSWORD_KEYSTONE": PASSWORD_K}
    result, code = go(p, environ=environ)
    assert code == 0
    assert [b["system"] for b in result["systems"]] == ["suryodaya"]
    assert p.logins == [] and not cache.exists()


def test_platform_mode_unknown_label_utc_with_note(capsys):
    p = Platform()
    p.clients["seat28"] = p.clients["keystone"]
    environ = {"AGENTSWITCH_TOKEN": "platform-x", "AGENTSWITCH_BASE_URL": "https://p.invalid",
               "AGENTSWITCH_INSTANCE": "seat28"}
    result, code = go(p, environ=environ)
    out = capsys.readouterr().out.replace("\\", "")
    assert result["systems"][0]["timezone"] == "UTC"
    assert "Time zone: UTC (UTC fallback: no calendar zone and no default for this system)" in out


# --------------------------------------------------------------------------- D6

def test_system_default_zones_and_explicit_override(capsys):
    result, _ = go(Platform())
    zones = {b["system"]: (b["timezone"], b["tz_source"]) for b in result["systems"]}
    assert zones == {"keystone": ("America/New_York", "system default"),
                     "suryodaya": ("Asia/Kolkata", "system default")}
    result, _ = go(Platform(), {"tz": ["suryodaya=Europe/Berlin"]})
    zones = {b["system"]: (b["timezone"], b["tz_source"]) for b in result["systems"]}
    assert zones == {"keystone": ("America/New_York", "system default"), "suryodaya": ("Europe/Berlin", "explicit")}
    result, _ = go(Platform(), {"tz": ["UTC"]})
    assert {b["timezone"] for b in result["systems"]} == {"UTC"}


def test_briefing_date_follows_each_zone_without_today(capsys):
    late = datetime(2026, 11, 4, 20, 0, tzinfo=timezone.utc)  # 15:00 New York, already 5 Nov in Kolkata
    result, _ = go(Platform(), {"today": None}, now=late)
    dates = {b["system"]: b["date"] for b in result["systems"]}
    assert dates == {"keystone": "2026-11-04", "suryodaya": "2026-11-05"}
    assert result["date"] == "2026-11-04"
    assert os.path.isfile("briefings/briefing-2026-11-04.md")


# --------------------------------------------------------------------------- D11 token cache

def test_second_run_uses_cached_token_without_login(capsys, tmp_path):
    p = Platform()
    go(p)
    cache = tmp_path / "cache" / "tokens.json"
    assert (os.stat(cache).st_mode & 0o777) == 0o600 and (os.stat(cache.parent).st_mode & 0o777) == 0o700
    p.logins.clear()
    result, code = go(p, environ=env(EA_PASSWORD_KEYSTONE=None, EA_PASSWORD_SURYODAYA=None))
    assert code == 0 and p.logins == []
    assert {b["login"] for b in result["systems"]} == {"cached token"}
    secrets_absent(*capsys.readouterr())


def test_logout_deletes_cache(capsys, tmp_path):
    go(Platform())
    cache = tmp_path / "cache" / "tokens.json"
    assert cache.exists()
    result, code = runner.run({"logout": True}, env(), False)
    assert code == 0 and not cache.exists()
    assert runner.run({"logout": True}, env(), False)[1] == 0


def test_interactive_password_prompt_for_named_system(capsys):
    p = Platform()
    asked = []
    result, code = go(p, {"system": ["keystone"]}, environ=env(EA_PASSWORD_KEYSTONE=None), tty=True,
                      getpass_fn=lambda prompt: asked.append(prompt) or "typed-SECRET")
    assert code == 0 and len(asked) == 1 and p.logins == ["keystone"]
    secrets_absent(*capsys.readouterr())


# --------------------------------------------------------------------------- D2 drafts, D3/D7 model

ASK = msg("ask", "Can you review?", "Please review the deck.")


def chat_model(answer=None):
    reply = answer or {"needs_reply": True, "reason": "asks for review", "draft": "Hi,\n\nHappy to.\n\nNora Example"}
    return FakeOpener(fn=lambda rec: (200, {"text": json.dumps(reply)}))


def model_env(**extra):
    return env(EA_LLM_URL="https://glc.invalid", EA_LLM_API="chat", **extra)


def test_drafts_saved_by_default(capsys):
    p = Platform(messages={"keystone": [ASK]})
    result, code = go(p, {"no_llm": False, "system": ["keystone"]}, environ=model_env(), llm_opener=chat_model())
    assert code == 0
    assert len(p.clients["keystone"].calls_to("EmailMessage.create")) == 1
    assert "Drafts were saved to your Drafts folder" in capsys.readouterr().out


def test_no_save_previews_only(capsys):
    p = Platform(messages={"keystone": [ASK]})
    _, code = go(p, {"no_llm": False, "no_save": True, "system": ["keystone"]}, environ=model_env(),
                 llm_opener=chat_model())
    assert code == 0
    assert p.clients["keystone"].calls_to("EmailMessage.create") == []
    assert "Nothing was saved" in capsys.readouterr().out


def test_review_needs_tty(capsys):
    _, code = go(Platform(), {"review": True}, tty=False)
    assert code == 1 and "interactive terminal" in capsys.readouterr().err
    _, code = go(Platform(), {"review": True, "no_save": True}, tty=True)
    assert code == 1


def test_review_with_tty_saves_on_s(capsys):
    p = Platform(messages={"keystone": [ASK]})
    answers = iter(["s"])
    _, code = go(p, {"no_llm": False, "review": True, "system": ["keystone"]}, environ=model_env(), tty=True,
                 llm_opener=chat_model(), input_fn=lambda prompt="": next(answers))
    out, err = capsys.readouterr()
    assert code == 0
    assert len(p.clients["keystone"].calls_to("EmailMessage.create")) == 1
    assert "[s]ave / [e]dit then save / [k] skip / [q] quit" not in out  # review talks on stderr
    assert "approved in review" in out


def test_review_edit_failing_checks_not_saved(capsys):
    p = Platform(messages={"keystone": [ASK]})
    answers = iter(["e"])
    _, code = go(p, {"no_llm": False, "review": True, "system": ["keystone"]}, environ=model_env(), tty=True,
                 llm_opener=chat_model(), input_fn=lambda prompt="": next(answers),
                 editor_fn=lambda text: "Send $900 to https://x.test")
    assert p.clients["keystone"].calls_to("EmailMessage.create") == []
    assert "Not saved:" in capsys.readouterr().err


def test_no_model_configured_is_not_a_failure(capsys):
    p = Platform(messages={"keystone": [ASK]})
    result, code = go(p, {"no_llm": False, "system": ["keystone"]})
    out = capsys.readouterr().out
    assert code == 0
    assert "Not assessed: no model configured" in out
    assert "Model: not configured" in out


def test_time_limit_reached_before_model_call_exit_2(capsys):
    p = Platform(messages={"keystone": [ASK]})
    opener = FakeOpener(fn=lambda rec: pytest.fail("model called after the time limit"))
    ticks = iter([0.0] + [100.0] * 50)
    _, code = go(p, {"no_llm": False, "system": ["keystone"], "time_limit": 60, "started": 0.0},
                 environ=model_env(), llm_opener=opener, clock=lambda: next(ticks))
    out = capsys.readouterr().out
    assert code == 2
    assert "Not assessed: time limit reached" in out
    assert "time limit reached" in out.split("WARNING:", 1)[1]


def test_model_settings_error_exit_1(capsys):
    _, code = go(Platform(), {"no_llm": False}, environ=env(EA_LLM_URL="https://x", EA_LLM_API="openai"))
    assert code == 1 and "EA_LLM_MODEL" in capsys.readouterr().err


def test_unread_only_flag_reaches_collector(capsys):
    p = Platform(messages={"keystone": [ASK, msg("old", "Seen", "x", is_read=True)]})
    result, _ = go(p, {"unread_only": True, "system": ["keystone"]})
    assert [i["id"] for i in result["systems"][0]["mail"]["items"]] == ["ask"]
    assert all(a.get("is_read") is False for a in p.clients["keystone"].calls_to("EmailMessage.list"))


def test_json_holds_every_system_without_secrets(capsys, tmp_path):
    path = tmp_path / "run.json"
    result, code = go(Platform(), {"json_path": str(path)})
    data = json.loads(path.read_text())
    assert [b["system"] for b in data["systems"]] == ["keystone", "suryodaya"]
    secrets_absent(path.read_text())


# --------------------------------------------------------------------------- performance and ordering

def test_systems_run_concurrently_in_fixed_order(capsys):
    import threading
    barrier = threading.Barrier(2, timeout=5)  # both logins must be in flight at the same time

    class Concurrent(Platform):
        def login(self, base_url, email, password):
            token = super().login(base_url, email, password)
            barrier.wait()
            return token

    p = Concurrent()
    result, code = go(p, {"system": ["suryodaya", "keystone"]})
    assert code == 0
    assert [b["system"] for b in result["systems"]] == ["suryodaya", "keystone"]
    out = capsys.readouterr().out
    assert out.index("## Suryodaya") < out.index("## Keystone")
    assert sorted(p.logins) == ["keystone", "suryodaya"]


def test_prompting_logins_run_one_at_a_time(capsys):
    import threading
    active = {"n": 0, "max": 0}

    class Counting(Platform):
        def login(self, base_url, email, password):
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            try:
                return super().login(base_url, email, password)
            finally:
                active["n"] -= 1

    p = Counting()
    _, code = go(p, {"system": ["keystone", "suryodaya"]}, environ=env(EA_PASSWORD_KEYSTONE=None,
                                                                       EA_PASSWORD_SURYODAYA=None),
                 tty=True, getpass_fn=lambda prompt: "typed-SECRET")
    assert code == 0 and active["max"] == 1 and threading.active_count() >= 1


def test_review_time_does_not_count_against_model_limit_m3(capsys):
    t = [0.0]

    def opener(url, data, headers, method, timeout):
        t[0] += 2  # each model call takes 2 s
        return 200, json.dumps({"text": json.dumps({"needs_reply": True, "reason": "q",
                                                    "draft": "Thanks, I will check and come back. Nora"})}).encode()

    def slow_user(prompt=""):
        t[0] += 40  # the user reads each draft for 40 s
        return "s"

    p = Platform(messages={"keystone": [msg(f"m{i}", f"Q{i}", "Can you check the report?") for i in range(3)]})
    result, code = go(p, {"no_llm": False, "system": ["keystone"], "review": True, "started": 0.0},
                      environ=model_env(), tty=True, llm_opener=opener, input_fn=slow_user, clock=lambda: t[0])
    items = result["systems"][0]["mail"]["items"]
    assert code == 0
    assert all(i["needs_reply"] is True for i in items)
    assert [i["draft_saved"]["status"] for i in items] == ["created"] * 3


def test_model_parallel_option_validated(capsys):
    assert go(Platform(), {"model_parallel": 0})[1] == 1


def test_json_failure_after_printing_exit_2(capsys, tmp_path):
    _, code = go(Platform(), {"system": ["keystone"], "json_path": str(tmp_path / "nodir" / "x.json")})
    out = capsys.readouterr().out
    assert code == 2 and "Daily briefing" in out
    assert os.path.isfile("briefings/briefing-2026-11-04.md")


def test_logout_platform_mode_keeps_cache(capsys, tmp_path):
    cache = tmp_path / "keep.json"
    cache.write_text("{}")
    _, code = runner.run({"logout": True}, {"AGENTSWITCH_TOKEN": "platform-x", "AGENTSWITCH_BASE_URL": "https://p",
                                            "EA_TOKEN_CACHE": str(cache)}, False)
    assert code == 0 and cache.exists()


def test_model_parallel_is_a_global_limit_across_systems(capsys):
    import threading
    state = {"now": 0, "max": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(3, timeout=5)  # groups of 3 in flight; a 4th at once would raise the peak

    def fn(rec):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        barrier.wait()
        with lock:
            state["now"] -= 1
        return 200, {"text": json.dumps({"needs_reply": True, "reason": "q", "draft": "Thanks, will check. Nora"})}

    mails = [msg(f"m{i}", f"Q{i}", "Can you check the report?") for i in range(3)]
    p = Platform(messages={"keystone": mails, "suryodaya": [dict(m) for m in mails]})
    result, code = go(p, {"no_llm": False, "model_parallel": 3}, environ=model_env(), llm_opener=FakeOpener(fn=fn))
    assert code == 0
    assert state["max"] == 3
    assert all(i["needs_reply"] is True for b in result["systems"] for i in b["mail"]["items"])
