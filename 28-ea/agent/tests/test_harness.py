"""The course harness contract, ready per-system tokens, model list settings, secret redaction and output files.

Contract: 34-eval-harness/docs/processed/evaluation/agent-contract.md.
"""
import argparse
import json
import os
import stat

import pytest

from ea_agent import auth, config, redact, runner
from fakes import make_mcp_error
from test_runner import NOW, Platform, env, go, world

HARNESS_TOKEN = "platform-LEAK-harness-777"


def ns(**kw):
    base = {"system": None, "instance": None, "today": None, "tz": None, "env_file": None, "no_llm": False}
    base.update(kw)
    return argparse.Namespace(**base)


def harness(**extra):
    base = {"AGENTSWITCH_TOKEN": HARNESS_TOKEN, "AGENTSWITCH_INSTANCE": "keystone",
            "AGENTSWITCH_BASE_URL": "https://copy.invalid",
            # the course runner always passes the model endpoint; harness mode stops without it
            "OPENAI_BASE_URL": "https://gw.invalid/v1", "OPENAI_API_KEY": "sk-harness-default-1", "OPENAI_MODEL": "gm-0"}
    base.update(extra)
    return {k: v for k, v in base.items() if v is not None}


# --------------------------------------------------------------------------- harness mode settings

@pytest.mark.parametrize("missing", ["AGENTSWITCH_TOKEN", "AGENTSWITCH_INSTANCE", "AGENTSWITCH_BASE_URL"])
def test_harness_needs_all_three(missing):
    with pytest.raises(SystemExit) as exc:
        config.resolve(ns(), harness(**{missing: None}))
    text = str(exc.value.code)
    assert missing in text and HARNESS_TOKEN not in text


def test_harness_rejects_unknown_instance_and_bad_url():
    with pytest.raises(SystemExit, match="AGENTSWITCH_INSTANCE"):
        config.resolve(ns(), harness(AGENTSWITCH_INSTANCE="seat28"))
    with pytest.raises(SystemExit, match="http"):
        config.resolve(ns(), harness(AGENTSWITCH_BASE_URL="ftp://copy.invalid"))


def test_harness_system_flag_must_match_instance():
    assert config.resolve(ns(system=["keystone"]), harness())["systems"] == ["keystone"]
    with pytest.raises(SystemExit, match="conflicts with AGENTSWITCH_INSTANCE=keystone"):
        config.resolve(ns(system=["suryodaya"]), harness())


def test_harness_reads_run_id_and_never_the_env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "load_env_file", lambda *_a, **_k: pytest.fail("env file was read"))
    (tmp_path / ".env").write_text("EA_EMAIL=file@x.test\n")
    out = config.resolve(ns(), harness(AGENTSWITCH_RUN_ID=" run-42 ", AGENTSWITCH_INSTANCE="SURYODAYA"))
    assert out["platform"] is True and out["run_id"] == "run-42"
    assert out["systems"] == ["suryodaya"] and out["instance"] == "suryodaya"
    assert out["base_url"] == "https://copy.invalid" and out["token"] == HARNESS_TOKEN


def test_harness_model_comes_from_openai_vars_only():
    out = config.resolve(ns(), harness(EA_LLM_URL="http://127.0.0.1:8107/v1", OPENAI_BASE_URL="https://gw.invalid/v1",
                                       OPENAI_API_KEY="sk-harness-123456", OPENAI_MODEL="m1, m2 ,"))
    assert out["llm"]["base_url"] == "https://gw.invalid/v1"
    assert out["llm"]["models"] == ["m1", "m2"] and out["llm"]["model"] == "m1"
    # EA_LLM_* never stands in for the runner's endpoint: without OPENAI_* the run stops
    with pytest.raises(SystemExit, match="OPENAI_BASE_URL"):
        config.resolve(ns(), harness(EA_LLM_URL="http://127.0.0.1:8107/v1", OPENAI_BASE_URL=None,
                                     OPENAI_API_KEY=None, OPENAI_MODEL=None))


@pytest.mark.parametrize("missing", ["OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL"])
def test_harness_stops_when_the_model_endpoint_is_incomplete(missing):
    # agent contract section 2: stop with an error if the given endpoint is incomplete; never print a value
    with pytest.raises(SystemExit) as exc:
        config.resolve(ns(), harness(**{missing: None}))
    text = str(exc.value.code)
    assert missing in text and "sk-harness-default-1" not in text and HARNESS_TOKEN not in text


def test_harness_no_llm_skips_the_model_check():
    out = config.resolve(ns(no_llm=True), harness(OPENAI_BASE_URL=None, OPENAI_API_KEY=None, OPENAI_MODEL=None))
    assert out["llm"] is None


def test_base_url_alone_is_ignored_with_a_warning():
    out = config.resolve(ns(), {"AGENTSWITCH_BASE_URL": "https://copy.invalid", "EA_EMAIL": "me@x.test"})
    assert out["platform"] is False and out["base_url"] is None
    assert any("AGENTSWITCH_BASE_URL is ignored" in w for w in out["warnings"])
    assert config.resolve(ns(), {"EA_EMAIL": "me@x.test"})["warnings"] == []


def test_runner_prints_settings_warnings(capsys):
    _, code = go(Platform(), environ=env(AGENTSWITCH_BASE_URL="https://copy.invalid"))
    assert code == 0
    assert "warning: AGENTSWITCH_BASE_URL is ignored" in capsys.readouterr().err


def test_local_run_id_is_kept():
    assert config.resolve(ns(), {"AGENTSWITCH_RUN_ID": "r1"})["run_id"] == "r1"
    assert config.resolve(ns(), {})["run_id"] is None


# --------------------------------------------------------------------------- model settings

def test_extra_body_is_parsed():
    out = config.llm_settings({"OPENAI_BASE_URL": "https://x.invalid", "OPENAI_EXTRA_BODY": '{"thinking": false}'})
    assert out["extra_body"] == {"thinking": False}
    out = config.llm_settings({"EA_LLM_URL": "https://x.invalid", "EA_LLM_EXTRA_BODY": '{"a": 1}'})
    assert out["extra_body"] == {"a": 1}


@pytest.mark.parametrize("raw", ['{"secret-value-9": ', '["secret-value-9"]', '"secret-value-9"'])
def test_bad_extra_body_names_the_variable_not_the_value(raw):
    with pytest.raises(SystemExit) as exc:
        config.llm_settings({"OPENAI_BASE_URL": "https://x.invalid", "OPENAI_EXTRA_BODY": raw})
    assert "OPENAI_EXTRA_BODY" in str(exc.value.code) and "secret-value-9" not in str(exc.value.code)


def test_ea_extra_body_without_url_is_an_error():
    with pytest.raises(SystemExit, match="EA_LLM_URL is missing"):
        config.llm_settings({"EA_LLM_EXTRA_BODY": "{}"})


def test_model_list_for_ea_llm_and_openai_api_needs_a_name():
    out = config.llm_settings({"EA_LLM_URL": "https://x.invalid", "EA_LLM_MODEL": "a,b"})
    assert out["models"] == ["a", "b"] and out["model"] == "a"
    with pytest.raises(SystemExit):
        config.llm_settings({"EA_LLM_URL": "https://x.invalid", "EA_LLM_API": "openai", "EA_LLM_MODEL": " , "})


# --------------------------------------------------------------------------- ready per-system tokens (local mode)

def test_ready_token_skips_login_and_cache(capsys, tmp_path):
    p = Platform()
    environ = env(EA_PASSWORD_KEYSTONE=None, EA_PASSWORD_SURYODAYA=None, AGENTSWITCH_KEYSTONE_TOKEN="platform-k-1234567")
    result, code = go(p, environ=environ)
    assert code == 0
    assert [b["system"] for b in result["systems"]] == ["keystone"]
    assert result["systems"][0]["login"] == "token from AGENTSWITCH_KEYSTONE_TOKEN"
    assert p.logins == [] and not (tmp_path / "cache" / "tokens.json").exists()


def test_refused_ready_token_is_an_error_not_a_password_login(tmp_path):
    calls = []

    class Refusing:
        def me(self):
            raise make_mcp_error("auth", "HTTP 401", 401)

    def login(*a):
        calls.append(a)
        return "x"

    with pytest.raises(auth.AuthError) as exc:
        auth.connect("keystone", config.SYSTEMS["keystone"],
                     {"AGENTSWITCH_KEYSTONE_TOKEN": "platform-bad-99999", "EA_EMAIL": "me@x.test",
                      "EA_PASSWORD_KEYSTONE": "pw-123456"},
                     cache_file=str(tmp_path / "c.json"), explicit=True, stdin_isatty=False, input_fn=input,
                     getpass_fn=lambda *_: pytest.fail("prompted"), client_factory=lambda *a: Refusing(),
                     login_fn=login, now=NOW)
    assert "AGENTSWITCH_KEYSTONE_TOKEN was not accepted" in str(exc.value)
    assert "platform-bad-99999" not in str(exc.value) and calls == []


# --------------------------------------------------------------------------- redaction

def test_redact_basics():
    assert redact.redact("a abcdefg-long b abcdefg", {"abcdefg", "abcdefg-long", "x", None}) == "a *** b ***"
    assert redact.redact_value({"k-secret-1": ["v k-secret-1", 3]}, {"k-secret-1"}) == {"***": ["v ***", 3]}
    assert redact.secrets_from_env({"EA_PASSWORD_KEYSTONE": "p", "AGENTSWITCH_SURYODAYA_TOKEN": "t",
                                    "AGENTSWITCH_RUN_ID": "r", "AGENTSWITCH_BASE_URL": "u", "OPENAI_API_KEY": "k",
                                    "EA_LLM_KEY": "e", "AGENTSWITCH_TOKEN": "a", "EA_EMAIL": "m"}) == {
        "p", "t", "k", "e", "a"}


def test_secret_in_mail_never_reaches_screen_or_files(capsys, tmp_path):
    p = Platform()
    p.clients["keystone"] = world(f"Rotate {HARNESS_TOKEN} and sk-model-key-0001 today")
    json_path = tmp_path / "out.json"
    result, code = go(p, {"json_path": str(json_path)},
                      environ=harness(OPENAI_API_KEY="sk-model-key-0001"))
    out, err = capsys.readouterr()
    md = (tmp_path / "briefings" / "briefing-2026-11-04.md").read_text()
    js = json_path.read_text()
    assert code == 0
    for text in (out, err, md, js):
        assert HARNESS_TOKEN not in text and "sk-model-key-0001" not in text
    assert "Rotate *** and *** today" in out.replace("\\", "")
    assert json.loads(js)["systems"][0]["status"] == "ok"


def test_token_from_a_login_is_redacted_too(capsys, tmp_path):
    p = Platform()
    p.clients["keystone"] = world("leaked token-keystone-SECRET-1 here")
    result, code = go(p, {"system": ["keystone"]})
    out, err = capsys.readouterr()
    assert code == 0 and p.logins == ["keystone"]
    assert "token-keystone-SECRET-1" not in out + (tmp_path / "briefings" / "briefing-2026-11-04.md").read_text()


# --------------------------------------------------------------------------- output files

def test_briefing_and_json_files_are_private(tmp_path, capsys):
    out_dir = tmp_path / "new" / "briefings"
    json_path = tmp_path / "out.json"
    _, code = go(Platform(), {"out": str(out_dir), "json_path": str(json_path)})
    assert code == 0
    assert stat.S_IMODE(os.stat(out_dir / "briefing-2026-11-04.md").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(out_dir).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(json_path).st_mode) == 0o600


def test_existing_output_folder_keeps_its_mode(tmp_path, capsys):
    out_dir = tmp_path / "shared"
    out_dir.mkdir()
    os.chmod(out_dir, 0o755)
    go(Platform(), {"out": str(out_dir)})
    assert stat.S_IMODE(os.stat(out_dir).st_mode) == 0o755


def test_nothing_fetched_keeps_the_earlier_file(tmp_path, capsys):
    earlier = tmp_path / "briefings" / "briefing-2026-11-04.md"
    earlier.parent.mkdir()
    earlier.write_text("earlier briefing")
    p = Platform()
    for fc in p.clients.values():
        for tool in ("EmailAccount.list", "Mailbox.list", "Calendar.list", "CalendarEvent.list", "Task.list"):
            fc.fail(tool, kind="network", message="down")
    result, code = go(p)
    err = capsys.readouterr().err
    assert code == 2 and result["file"] is None
    assert earlier.read_text() == "earlier briefing"
    assert runner.NOTHING_FETCHED in err
    assert runner.fetched_anything(result["systems"]) is False


# --------------------------------------------------------------------------- AGENT_RESULT (contract sections 4 and 5)

def test_agent_result_is_the_last_line_with_run_id(capsys):
    # The model is on; this world has no mail, so no model call is made (the opener would fail the test).
    _, code = go(Platform(), {"no_llm": False},
                 environ=harness(AGENTSWITCH_RUN_ID="run-1", OPENAI_BASE_URL="https://gw.invalid",
                                 OPENAI_MODEL="gm-1,gm-2"),
                 llm_opener=lambda *a, **k: pytest.fail("model called"))
    out = capsys.readouterr().out
    last = out.rstrip("\n").splitlines()[-1]
    assert code == 0 and last.startswith("AGENT_RESULT ")
    data = json.loads(last[len("AGENT_RESULT "):])
    assert data["claim"] == "done" and data["model"] == "gm-1"
    assert HARNESS_TOKEN not in out


def test_no_agent_result_without_run_id(capsys):
    go(Platform(), environ=harness())
    assert "AGENT_RESULT" not in capsys.readouterr().out


def test_partial_run_exits_0_claims_failed_and_ends_with_a_warning_line(capsys):
    # contract section 5: any non-zero exit is "could not finish"; a briefing that ran finished, so it exits 0
    p = Platform()
    p.clients["keystone"].fail("Task.list", kind="network", message="down")
    _, code = go(p, environ=harness(AGENTSWITCH_RUN_ID="run-2"))
    out, err = capsys.readouterr()
    assert code == 0
    assert json.loads(out.rstrip("\n").splitlines()[-1][len("AGENT_RESULT "):])["claim"] == "failed"
    assert err.rstrip("\n").splitlines()[-1] == "warning: keystone: could not read overdue"


def test_harness_claim_is_done_when_a_partial_run_landed_drafts():
    class C:
        def __init__(self, n):
            self.drafts_created = n

    assert runner.harness_claim(0, {"clients": []}) == "done"
    assert runner.harness_claim(2, {"clients": [C(1)]}) == "done"
    assert runner.harness_claim(2, {"clients": [C(0), object()]}) == "failed"
    assert runner.harness_claim(1, {"clients": [C(3)]}) == "failed"


def test_settings_error_with_run_id(capsys):
    _, code = go(Platform(), environ=harness(AGENTSWITCH_INSTANCE="nope", AGENTSWITCH_RUN_ID="run-3"))
    out, err = capsys.readouterr()
    assert code == 1
    assert err.rstrip("\n").splitlines()[-1].startswith("error: AGENTSWITCH_INSTANCE must be one of")
    assert json.loads(out.strip().splitlines()[-1][len("AGENT_RESULT "):]) == {"claim": "failed"}


def test_agent_result_counts_mcp_calls():
    class C:
        def __init__(self, n):
            self._id = n

    assert json.loads(runner.agent_result("done", {"clients": [C(3), C(4), object()], "model": None})[13:]) == {
        "claim": "done", "steps": 7}
    assert json.loads(runner.agent_result("failed", {"clients": [object()], "model": "m"})[13:]) == {
        "claim": "failed", "model": "m"}


# --------------------------------------------------------------------------- contract edge cases

LIVE_KEYSTONE = "https://class.agentswitch.theschoolofai.in"


def test_prompt_flag_from_the_eval_runner_is_accepted():
    # contract section 1: the runner always appends --prompt "<request>"; an unknown flag used to stop every run
    from ea_agent import __main__ as cli_main
    assert cli_main.parse_args(["--prompt", "write my briefing"]).prompt == "write my briefing"


@pytest.mark.parametrize("url", [LIVE_KEYSTONE, LIVE_KEYSTONE + "/", "https://agentswitch.theschoolofai.in"])
def test_harness_on_a_live_url_is_read_only(url):
    # contract section 7: local runs use the live shared data, so they must not write
    out = config.resolve(ns(), harness(AGENTSWITCH_BASE_URL=url))
    assert out["read_only"] is True
    assert any("live system" in w for w in out["warnings"])


def test_harness_on_a_copy_may_save():
    out = config.resolve(ns(), harness())
    assert out["read_only"] is False and not any("live system" in w for w in out["warnings"])


def test_harness_live_run_previews_drafts(capsys):
    result, _ = go(Platform(), environ=harness(AGENTSWITCH_BASE_URL=LIVE_KEYSTONE))
    assert result["drafts"] == "preview"


def test_local_mode_is_never_read_only(tmp_path):
    assert config.resolve(ns(), env())["read_only"] is False


def test_unreadable_env_file_is_one_settings_line(tmp_path):
    bad = tmp_path / "bad.env"
    bad.write_bytes(b"EA_EMAIL=a\xff\xfe@x\n")
    with pytest.raises(SystemExit) as exc:
        config.load_env_file(str(bad))
    assert "could not read the env file" in str(exc.value.code) and "UnicodeDecodeError" in str(exc.value.code)


def test_model_key_with_a_newline_is_stripped_and_redacted():
    out = config.llm_settings({"OPENAI_BASE_URL": "https://gw.invalid/v1", "OPENAI_API_KEY": " sk-key-123456\n"})
    assert out["key"] == "sk-key-123456"
    # the raw value from the environment, newline included, still hides its stripped form
    assert redact.redact("seen sk-key-123456 here", {"sk-key-123456\n"}) == "seen *** here"


def test_bad_header_never_puts_the_key_in_the_reason():
    from ea_agent import llm as llm_mod

    def opener(url, data, headers, method, timeout):
        raise ValueError(f"Invalid header value b'{headers['Authorization']}\\n'")

    model = llm_mod.Llm({"base_url": "https://gw.invalid/v1", "api": "openai", "key": "sk-SECRET-123456",
                         "model": "m"}, opener=opener)
    with pytest.raises(llm_mod.LlmError) as exc:
        model("system", "user")
    assert exc.value.kind == "settings" and "sk-SECRET" not in str(exc.value)
