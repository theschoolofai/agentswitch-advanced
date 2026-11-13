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
    assert out["platform"] is True
    assert out["token"] == SECRET_TOKEN
    assert out["base_url"] == "https://platform.example"
    assert out["instance"] == "seat28"
    assert out["systems"] == ["seat28"]
    assert out["email"] != "file@x.test"


def test_platform_mode_is_exactly_one_system():
    environ = {"AGENTSWITCH_TOKEN": "t", "AGENTSWITCH_BASE_URL": "https://p.example"}
    assert config.resolve(ns(), environ)["systems"] == [None]
    assert config.resolve(ns(system=["keystone"]), environ)["systems"] == ["keystone"]


def test_platform_mode_requires_base_url(capsys):
    with pytest.raises(SystemExit) as exc:
        config.resolve(ns(), {"AGENTSWITCH_TOKEN": SECRET_TOKEN})
    msg = str(exc.value.code) + capsys.readouterr().err
    assert "AGENTSWITCH_BASE_URL" in msg
    assert SECRET_TOKEN not in msg


def test_env_file_mode(tmp_path):
    p = write(tmp_path / "creds", f"EA_EMAIL=me@x.test\nEA_PASSWORD_KEYSTONE='{SECRET_PW}'\n")
    out = config.resolve(ns(instance="keystone", env_file=p), {})
    assert out["platform"] is False
    assert out["systems"] == ["keystone"] and out["explicit"] is True
    assert out["email"] == "me@x.test"
    assert out["env"][config.password_var("keystone")] == SECRET_PW
    assert out["token"] in (None, "")
    assert out["llm"] is None
    assert out["today"] is None
    assert out["tz"] is None


def test_default_is_every_system_d1(tmp_path):
    out = config.resolve(ns(), {"EA_EMAIL": "me@x.test"})
    assert out["systems"] == ["keystone", "suryodaya"]
    assert out["explicit"] is False


def test_system_flag_repeatable_and_instance_alias():
    out = config.resolve(ns(system=["Suryodaya"], instance=["keystone"]), {})
    assert out["systems"] == ["suryodaya", "keystone"]


def test_unknown_system_is_config_error():
    with pytest.raises(SystemExit) as exc:
        config.resolve(ns(system=["mars"]), {})
    assert "mars" in str(exc.value.code)


def test_password_variable_is_per_instance():
    assert config.password_var("suryodaya") == "EA_PASSWORD_SURYODAYA"
    assert config.password_var("keystone") == "EA_PASSWORD_KEYSTONE"


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
    assert out["env"]["EA_PASSWORD_KEYSTONE"] == "env-pw"
    assert out["tz"] == "Asia/Kolkata"
    assert str(out["today"]) == "2026-11-04"


def test_cli_flags_beat_env_for_today_and_tz(tmp_path):
    p = write(tmp_path / "creds", "EA_EMAIL=me@x.test\nEA_PASSWORD_KEYSTONE=pw\n")
    out = config.resolve(ns(instance="keystone", env_file=p, today="2026-12-01", tz=["America/New_York"]),
                         {"EA_TODAY": "2026-11-04", "EA_TZ": "Asia/Kolkata"})
    assert str(out["today"]) == "2026-12-01"
    assert out["tz"] == "America/New_York"


def test_tz_per_system_d6():
    out = config.resolve(ns(tz=["keystone=Europe/Berlin", "suryodaya=Asia/Tokyo"]), {})
    assert out["tz"] is None
    assert out["tz_by_system"] == {"keystone": "Europe/Berlin", "suryodaya": "Asia/Tokyo"}
    both = config.resolve(ns(tz=["UTC", "keystone=Europe/Berlin"]), {})
    assert both["tz"] == "UTC" and both["tz_by_system"] == {"keystone": "Europe/Berlin"}


@pytest.mark.parametrize("tz", [["Mars/Base"], ["keystone=Mars/Base"], ["mars=UTC"], ["UTC", "Asia/Tokyo"]])
def test_bad_tz_is_config_error(tz):
    with pytest.raises(SystemExit):
        config.resolve(ns(tz=tz), {})


def test_missing_credentials_are_not_a_config_error_anymore(tmp_path, capsys):
    # v1: a system without credentials is reported in its own block by the runner, so resolve no longer exits.
    p = write(tmp_path / "creds", f"OPENAI_API_KEY={SECRET_KEY}\nEA_PASSWORD_SURYODAYA={SECRET_PW}\n")
    out = config.resolve(ns(instance="keystone", env_file=p), {})
    assert out["email"] is None
    captured = capsys.readouterr()
    assert SECRET_PW not in captured.out + captured.err


# --------------------------------------------------------------------------- model settings (D3)

def test_llm_none_without_url(tmp_path):
    p = write(tmp_path / "creds", f"EA_EMAIL=me@x.test\nOPENAI_MODEL=gpt-4.1\nOPENAI_API_KEY={SECRET_KEY}\n")
    out = config.resolve(ns(instance="keystone", env_file=p), {})
    assert out["llm"] is None


def test_openai_variables_mean_auto_without_defaults(tmp_path):
    out = config.resolve(ns(), {"OPENAI_BASE_URL": "https://llm.example/v1"})
    assert out["llm"] == {"base_url": "https://llm.example/v1", "api": "auto", "key": None, "model": None}


def test_llm_overrides_from_env():
    out = config.resolve(ns(), {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "https://llm.example/v1",
                                "OPENAI_MODEL": "o4"})
    assert out["llm"] == {"base_url": "https://llm.example/v1", "api": "auto", "key": "k", "model": "o4"}


def test_ea_llm_settings_win_over_openai():
    out = config.resolve(ns(), {"EA_LLM_URL": "http://gateway.local:9000", "EA_LLM_API": "chat",
                                "OPENAI_BASE_URL": "https://api.example/v1", "OPENAI_API_KEY": "k"})
    assert out["llm"] == {"base_url": "http://gateway.local:9000", "api": "chat", "key": None, "model": None}


def test_ea_llm_api_defaults_to_auto():
    out = config.resolve(ns(), {"EA_LLM_URL": "https://x.example", "EA_LLM_MODEL": "m", "EA_LLM_KEY": "kk"})
    assert out["llm"] == {"base_url": "https://x.example", "api": "auto", "key": "kk", "model": "m"}


@pytest.mark.parametrize("env", [
    {"EA_LLM_URL": "https://x.example", "EA_LLM_API": "openai"},           # openai needs a model
    {"EA_LLM_URL": "https://x.example", "EA_LLM_API": "grpc"},             # unknown API
    {"EA_LLM_URL": "ftp://x.example"},                                     # not http(s)
    {"EA_LLM_MODEL": "m"},                                                 # EA_LLM_* without the URL
])
def test_llm_config_errors(env):
    with pytest.raises(SystemExit):
        config.resolve(ns(), {**env, "EA_LLM_KEY": SECRET_KEY} if "EA_LLM_URL" in env else env)


def test_llm_config_error_hides_key():
    with pytest.raises(SystemExit) as exc:
        config.resolve(ns(), {"EA_LLM_URL": "https://x.example", "EA_LLM_API": "openai", "EA_LLM_KEY": SECRET_KEY})
    assert SECRET_KEY not in str(exc.value.code)


def test_no_llm_flag_turns_model_off():
    assert config.resolve(ns(no_llm=True), {"OPENAI_BASE_URL": "https://x.example"})["llm"] is None


def test_platform_mode_llm_from_process_env():
    out = config.resolve(ns(), {"AGENTSWITCH_TOKEN": "t", "AGENTSWITCH_BASE_URL": "https://p.example",
                                "OPENAI_API_KEY": "k2", "OPENAI_BASE_URL": "https://glc.example"})
    assert out["llm"]["key"] == "k2"
    assert out["llm"]["model"] is None
