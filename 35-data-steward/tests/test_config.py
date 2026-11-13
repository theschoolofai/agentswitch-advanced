import pytest

from data_steward import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("AGENTSWITCH_TOKEN", "AGENTSWITCH_BASE_URL", "AGENTSWITCH_INSTANCE",
                 "SEAT35_EMAIL", "SEAT35_PASSWORD_SURYODAYA", "SEAT35_PASSWORD_KEYSTONE"):
        monkeypatch.delenv(name, raising=False)


def test_dotenv_wins_over_shell_but_skips_platform_lines(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SEAT35_PASSWORD_KEYSTONE=from-file\nAGENTSWITCH_TOKEN=stray\n# comment\nEMPTY=\n")
    monkeypatch.setenv("SEAT35_PASSWORD_KEYSTONE", "from-shell")
    config.load_dotenv(env_file)
    assert config.os.environ["SEAT35_PASSWORD_KEYSTONE"] == "from-file"
    # A token line in .env must never switch a local run into platform mode.
    assert not config.on_platform()


def test_dotenv_is_ignored_on_platform(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_MODEL=ours\n")
    monkeypatch.setenv("AGENTSWITCH_TOKEN", "t")
    monkeypatch.setenv("OPENAI_MODEL", "runners")
    config.load_dotenv(env_file)
    assert config.os.environ["OPENAI_MODEL"] == "runners"


def test_missing_password_names_the_variable(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("SEAT35_EMAIL", "seat@example.test")
    with pytest.raises(RuntimeError, match="SEAT35_PASSWORD_SURYODAYA"):
        config.credentials("suryodaya")


def test_login_comes_from_the_environment(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("SEAT35_EMAIL", "seat@example.test")
    monkeypatch.setenv("SEAT35_PASSWORD_KEYSTONE", "x")
    assert config.credentials("keystone") == ("seat@example.test", "x")


def test_missing_login_names_the_variable(monkeypatch):
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("SEAT35_PASSWORD_KEYSTONE", "x")
    with pytest.raises(RuntimeError, match="SEAT35_EMAIL"):
        config.credentials("keystone")


def test_half_set_platform_environment_raises(monkeypatch):
    monkeypatch.setenv("AGENTSWITCH_TOKEN", "t")
    monkeypatch.setenv("AGENTSWITCH_INSTANCE", "keystone")
    with pytest.raises(RuntimeError, match="AGENTSWITCH_BASE_URL"):
        config.platform()


def test_platform_rejects_unknown_instance(monkeypatch):
    monkeypatch.setenv("AGENTSWITCH_TOKEN", "t")
    monkeypatch.setenv("AGENTSWITCH_BASE_URL", "https://copy.example/")
    monkeypatch.setenv("AGENTSWITCH_INSTANCE", "nowhere")
    with pytest.raises(RuntimeError, match="nowhere"):
        config.platform()


def test_dotenv_removes_one_matching_quote_pair_only(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SEAT35_PASSWORD_KEYSTONE=\"ab'c#d=e'\"\nSEAT35_PASSWORD_SURYODAYA='x\"\n")
    config.load_dotenv(env_file)
    assert config.os.environ["SEAT35_PASSWORD_KEYSTONE"] == "ab'c#d=e'"
    # Unmatched quotes are part of the password, not wrapping.
    assert config.os.environ["SEAT35_PASSWORD_SURYODAYA"] == "'x\""
