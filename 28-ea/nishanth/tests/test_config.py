import argparse

import pytest

from ea_briefing import config

SECRET_PW = "pw-Zebra-778-secret"
SECRET_TOKEN = "platform-token-Q9-secret"
SECRET_KEY = "sk-test-key-0000-secret"


def ns(**kw):
    base = {"instance": None, "today": None, "tz": None, "env_file": None, "json": None, "save_drafts": False,
            "no_llm": False, "mail_cap": 25}
    base.update(kw)
    return argparse.Namespace(**base)


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_instances():
    assert config.INSTANCES["suryodaya"] == "https://agentswitch.theschoolofai.in"
    assert config.INSTANCES["keystone"] == "https://class.agentswitch.theschoolofai.in"


def test_load_env_file_parsing(tmp_path):
    p = write(tmp_path / "e.env", "\n".join([
        "# a comment",
        "",
        "EA_EMAIL=me@x.test",
        "EA_PASSWORD_KEYSTONE=\"quoted value\"",
        "SINGLE='single q'",
        "WITH_EQ=a=b=c",
        "Remember: rotate these every month",
        "this line is just a note",
        "1BAD=nope",
        "BAD-KEY=nope",
        "   # indented comment",
        "_UNDER=ok",
    ]) + "\n")
    env = config.load_env_file(p)
    assert env["EA_EMAIL"] == "me@x.test"
    assert env["EA_PASSWORD_KEYSTONE"] == "quoted value"
    assert env["SINGLE"] == "single q"
    assert env["WITH_EQ"] == "a=b=c"
    assert env["_UNDER"] == "ok"
    assert "1BAD" not in env
    assert "BAD-KEY" not in env
    assert set(env) == {"EA_EMAIL", "EA_PASSWORD_KEYSTONE", "SINGLE", "WITH_EQ", "_UNDER"}


def test_platform_mode_does_not_read_env_file(tmp_path, monkeypatch):
    bad = tmp_path / ".env"
    bad.write_bytes(b"\xff\xfe\x00 not utf8 ===\nEA_EMAIL=file@x.test\n")
    monkeypatch.setattr(config, "load_env_file", lambda *_a, **_k: pytest.fail("env file was read"))
    environ = {"AGENTSWITCH_TOKEN": SECRET_TOKEN, "AGENTSWITCH_BASE_URL": "https://platform.example",
               "AGENTSWITCH_INSTANCE": "seat28", "EA_ENV_FILE": str(bad)}
    out = config.resolve(ns(env_file=str(bad)), environ)
    assert out["token"] == SECRET_TOKEN
    assert out["base_url"] == "https://platform.example"
    assert out["instance"] == "seat28"
    assert out["email"] != "file@x.test"
    assert out["password"] in (None, "")


def test_platform_mode_requires_base_url(capsys):
    with pytest.raises(SystemExit) as exc:
        config.resolve(ns(), {"AGENTSWITCH_TOKEN": SECRET_TOKEN})
    msg = str(exc.value.code) + capsys.readouterr().err
    assert "AGENTSWITCH_BASE_URL" in msg
    assert SECRET_TOKEN not in msg


def test_env_file_mode(tmp_path):
    p = write(tmp_path / "creds", f"EA_EMAIL=me@x.test\nEA_PASSWORD_KEYSTONE='{SECRET_PW}'\n")
    out = config.resolve(ns(instance="keystone", env_file=p), {})
    assert out["instance"] == "keystone"
    assert out["base_url"] == "https://class.agentswitch.theschoolofai.in"
    assert out["email"] == "me@x.test"
    assert out["password"] == SECRET_PW
    assert out["token"] in (None, "")
    assert out["llm"] is None
    assert out["today"] is None
    assert out["tz"] is None


def test_password_variable_is_per_instance(tmp_path):
    p = write(tmp_path / "creds", "EA_EMAIL=me@x.test\nEA_PASSWORD_KEYSTONE=k-pw\nEA_PASSWORD_SURYODAYA=s-pw\n")
    out = config.resolve(ns(instance="suryodaya", env_file=p), {})
    assert out["password"] == "s-pw"
    assert out["base_url"] == "https://agentswitch.theschoolofai.in"


def test_ea_env_file_variable_used(tmp_path):
    p = write(tmp_path / "other.env", "EA_EMAIL=viaenv@x.test\nEA_PASSWORD_KEYSTONE=pw\n")
    out = config.resolve(ns(instance="keystone"), {"EA_ENV_FILE": p})
    assert out["email"] == "viaenv@x.test"


def test_default_dot_env_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / ".env", "EA_EMAIL=cwd@x.test\nEA_PASSWORD_KEYSTONE=pw\n")
    out = config.resolve(ns(instance="keystone"), {})
    assert out["email"] == "cwd@x.test"


def test_process_env_beats_file(tmp_path):
    p = write(tmp_path / "creds", "EA_EMAIL=file@x.test\nEA_PASSWORD_KEYSTONE=file-pw\nEA_TZ=Europe/London\n")
    environ = {"EA_EMAIL": "env@x.test", "EA_PASSWORD_KEYSTONE": "env-pw", "EA_TZ": "Asia/Kolkata",
               "EA_TODAY": "2026-11-04"}
    out = config.resolve(ns(instance="keystone", env_file=p), environ)
    assert out["email"] == "env@x.test"
    assert out["password"] == "env-pw"
    assert out["tz"] == "Asia/Kolkata"
    assert str(out["today"]) == "2026-11-04"


def test_cli_flags_beat_env_for_today_and_tz(tmp_path):
    p = write(tmp_path / "creds", "EA_EMAIL=me@x.test\nEA_PASSWORD_KEYSTONE=pw\n")
    out = config.resolve(ns(instance="keystone", env_file=p, today="2026-12-01", tz="America/New_York"),
                         {"EA_TODAY": "2026-11-04", "EA_TZ": "Asia/Kolkata"})
    assert str(out["today"]) == "2026-12-01"
    assert out["tz"] == "America/New_York"


def test_missing_password_exits_naming_variable(tmp_path, capsys):
    p = write(tmp_path / "creds", f"EA_EMAIL=me@x.test\nOPENAI_API_KEY={SECRET_KEY}\nEA_PASSWORD_SURYODAYA={SECRET_PW}\n")
    with pytest.raises(SystemExit) as exc:
        config.resolve(ns(instance="keystone", env_file=p), {})
    captured = capsys.readouterr()
    msg = str(exc.value.code) + captured.out + captured.err
    assert "EA_PASSWORD_KEYSTONE" in msg
    assert SECRET_PW not in msg
    assert SECRET_KEY not in msg


def test_missing_email_exits_naming_variable(tmp_path, capsys):
    p = write(tmp_path / "creds", f"EA_PASSWORD_KEYSTONE={SECRET_PW}\n")
    with pytest.raises(SystemExit) as exc:
        config.resolve(ns(instance="keystone", env_file=p), {})
    captured = capsys.readouterr()
    msg = str(exc.value.code) + captured.out + captured.err
    assert "EA_EMAIL" in msg
    assert SECRET_PW not in msg


def test_llm_none_without_api_key(tmp_path):
    p = write(tmp_path / "creds", "EA_EMAIL=me@x.test\nEA_PASSWORD_KEYSTONE=pw\nOPENAI_MODEL=gpt-4.1\n")
    out = config.resolve(ns(instance="keystone", env_file=p), {})
    assert out["llm"] is None


def test_llm_defaults_with_api_key(tmp_path):
    p = write(tmp_path / "creds", f"EA_EMAIL=me@x.test\nEA_PASSWORD_KEYSTONE=pw\nOPENAI_API_KEY={SECRET_KEY}\n")
    out = config.resolve(ns(instance="keystone", env_file=p), {})
    assert out["llm"] == {"base_url": "https://api.openai.com/v1", "api_key": SECRET_KEY, "model": "gpt-4.1-mini"}


def test_llm_overrides_from_env(tmp_path):
    p = write(tmp_path / "creds", "EA_EMAIL=me@x.test\nEA_PASSWORD_KEYSTONE=pw\n")
    out = config.resolve(ns(instance="keystone", env_file=p),
                         {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "https://llm.example/v1", "OPENAI_MODEL": "o4"})
    assert out["llm"] == {"base_url": "https://llm.example/v1", "api_key": "k", "model": "o4"}


def test_platform_mode_llm_from_process_env():
    out = config.resolve(ns(), {"AGENTSWITCH_TOKEN": "t", "AGENTSWITCH_BASE_URL": "https://p.example",
                                "OPENAI_API_KEY": "k2"})
    assert out["llm"]["api_key"] == "k2"
    assert out["llm"]["model"] == "gpt-4.1-mini"
