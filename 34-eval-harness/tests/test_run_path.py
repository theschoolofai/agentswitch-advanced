"""The run path, end to end: settings -> login check -> trial -> agent process -> record -> results.json.

A small fake platform (an httpx2 MockTransport) stands in for AgentSwitch, and tests/fake_agent.py is started
as a real separate process. No live calls: a guard fails any test in which the harness opens a socket.
These tests also back the harness-mode promise: only the injected token, only the given URLs, no password.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx2
import pytest

import eval_harness.__main__ as harness
from eval_harness.platform import PlatformReader
from eval_harness.scorer import row_for, score_trial
from eval_harness.settings import MODEL_VARIABLES, OPTIONAL_MODEL_VARIABLES, SettingsMissing, load_settings
from eval_harness.suite import GraderSpec, Suite, Task, load_suite
from eval_harness.trial import SYSTEM_VARIABLES, TrialRecord, agent_environment, run_agent

SEAT = Path(__file__).resolve().parent.parent
TOKEN = "tok-injected-for-tests"  # the same value as INJECTED_TOKEN in tests/fake_agent.py
API_KEY = "sk-given-key-for-tests"
PLATFORM_URL = "https://copy.platform.test"
MODEL_URL = "https://model.given.test/v1"
RUN_ID = "test-run"
CONTRACT = {
    "AGENTSWITCH_BASE_URL": PLATFORM_URL,
    "AGENTSWITCH_TOKEN": TOKEN,
    "AGENTSWITCH_INSTANCE": "suryodaya",
    "AGENTSWITCH_RUN_ID": RUN_ID,
    "OPENAI_BASE_URL": MODEL_URL,
    "OPENAI_API_KEY": API_KEY,
    "OPENAI_MODEL": "given-model",
}
PASSWORDS = {"AS_EMAIL": "lead@example.test", "AS_KEYSTONE_PASSWORD": "pw-not-for-agents"}


class FakePlatform:
    """Two parties, a login check, and a log of every request the harness sends."""

    def __init__(self, me_status: int = 200, broken_entity: str | None = None) -> None:
        self.me_status, self.broken_entity = me_status, broken_entity
        self.requests: list[httpx2.Request] = []
        self.parties = {
            f"party-{i}": {"id": f"party-{i}", "name": f"Party {i}", "updated_at": "2026-11-01T10:00:00"}
            for i in range(2)
        }

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/auth/me":
            if self.me_status != 200:
                return httpx2.Response(self.me_status, json={"detail": "token expired"})
            return httpx2.Response(
                200, json={"id": "user-34"}, headers={"date": "Tue, 10 Nov 2026 10:00:00 GMT"}
            )
        entity, _, record_id = path.removeprefix("/api/").partition("/")
        if entity == self.broken_entity:
            return httpx2.Response(500, json={"detail": "fake server error"})
        if entity == "SalesOrder" and not record_id:  # rows for the recount capture
            orders = [{"id": "so-1", "docstatus": 1, "invoiced_status": "unbilled", "date": "2026-10-01"}]
            return httpx2.Response(200, json={"data": orders, "total": len(orders)})
        if entity != "Party":
            return httpx2.Response(404, json={"detail": "no such entity"})
        if record_id:
            return httpx2.Response(200, json=self.parties[record_id])
        if "created_by" in request.url.params or "updated_by" in request.url.params:
            return httpx2.Response(200, json={"data": [], "total": 0})  # nothing written by our login
        return httpx2.Response(200, json={"data": list(self.parties.values()), "total": len(self.parties)})


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The harness process may not open any connection of its own: everything goes through the fake."""

    def refuse(*_: object) -> None:
        raise AssertionError("the harness tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakePlatform:
    """Contract variables set, runs saved under tmp_path, and the harness wired to a fake platform."""
    fake = FakePlatform()
    for name, value in CONTRACT.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(harness, "RUNS_DIR", tmp_path / "runs")

    def reader(base_url: str, token: str) -> PlatformReader:
        return PlatformReader(base_url, token, transport=httpx2.MockTransport(fake.handle))

    monkeypatch.setattr(harness, "PlatformReader", reader)
    return fake


def suite_with(mode: str, minutes: float = 1, tasks: list[Task] | None = None) -> Suite:
    example = load_suite(SEAT / "suites" / "example")
    agent = f"{shlex.quote(sys.executable)} tests/fake_agent.py --mode {mode}"
    return example.model_copy(
        update={"agent": agent, "task_minutes": minutes, "tasks": tasks or example.tasks}
    )


def run(suite: Suite, tmp_path: Path) -> list[dict[str, Any]]:
    out = tmp_path / "results.json"
    asyncio.run(harness.run_suite(suite, load_settings(), out))
    rows: list[dict[str, Any]] = json.loads(out.read_text())["tasks"]
    return rows


def saved_record(tmp_path: Path, task_id: str) -> dict[str, Any]:
    record: dict[str, Any] = json.loads(
        (tmp_path / "runs" / RUN_ID / f"suryodaya__{task_id}__t0.json").read_text()
    )
    return record


def test_a_clean_refusal_passes_and_nothing_secret_is_saved(platform: FakePlatform, tmp_path: Path) -> None:
    rows = run(suite_with("ok"), tmp_path)
    assert [r["passed"] for r in rows] == [True]
    assert rows[0]["evidence"].startswith("outcome=approve; integrity=clean")
    saved = [p.read_text() for p in tmp_path.rglob("*.json")]
    assert len(saved) == 2  # the trial record and results.json
    assert not any(TOKEN in text or API_KEY in text for text in saved)


def test_harness_only_reads_the_given_platform_with_the_injected_token(
    platform: FakePlatform, tmp_path: Path
) -> None:
    run(suite_with("ok"), tmp_path)
    assert platform.requests
    for request in platform.requests:
        assert request.method == "GET"
        assert request.url.host == "copy.platform.test"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"


def test_agent_environment_is_the_allowlist_only(
    platform: FakePlatform, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {**PASSWORDS, "OTHER_SERVICE_TOKEN": "other-secret"}.items():
        monkeypatch.setenv(name, value)
    env = agent_environment(load_settings(), RUN_ID)
    allowed = {*SYSTEM_VARIABLES, *MODEL_VARIABLES, *OPTIONAL_MODEL_VARIABLES, *CONTRACT}
    assert set(env) <= allowed
    assert env["AGENTSWITCH_TOKEN"] == TOKEN and env["OPENAI_BASE_URL"] == MODEL_URL


def test_agent_process_gets_no_password_and_the_given_endpoints(
    platform: FakePlatform, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, value in PASSWORDS.items():
        monkeypatch.setenv(name, value)
    run(suite_with("ok"), tmp_path)
    reported = saved_record(tmp_path, "example.merge_two_parties_refused")["agent"]["reported"]
    assert not [k for k in reported["env_keys"] if k.startswith("AS_")]
    assert reported["token_is_injected"] is True and reported["model_url"] == MODEL_URL


def test_dead_token_makes_every_task_infrastructure_and_starts_no_agent(
    platform: FakePlatform, tmp_path: Path
) -> None:
    platform.me_status = 401
    rows = run(suite_with("ok"), tmp_path)
    assert all(
        not r["passed"] and r["evidence"].startswith("infrastructure: login check failed") for r in rows
    )
    assert not (tmp_path / "runs").exists()  # no trial ran, so no record
    assert [r.url.path for r in platform.requests] == ["/api/auth/me"]


@pytest.mark.parametrize(("mode", "reason"), [("crash", "exited with code 3"), ("sleep", "timed out")])
def test_agent_that_cannot_finish_is_infrastructure_never_a_pass(
    platform: FakePlatform, tmp_path: Path, mode: str, reason: str
) -> None:
    rows = run(suite_with(mode, minutes=0.02), tmp_path)
    assert not rows[0]["passed"] and rows[0]["score"] == 0.0
    assert rows[0]["evidence"].startswith("infrastructure:") and reason in rows[0]["evidence"]


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX only")
def test_time_limit_also_stops_the_agents_child_processes() -> None:
    """A wrapper (here `sh -c`) whose child keeps the output pipe open must not stretch the time limit."""
    agent = asyncio.run(run_agent(["sh", "-c", "sleep 30; echo late"], {"PATH": "/usr/bin:/bin"}, 1))
    assert agent.timed_out and agent.seconds < 5
    assert "late" not in agent.output_tail


def test_a_token_the_agent_prints_reaches_neither_results_nor_the_record(
    platform: FakePlatform, tmp_path: Path
) -> None:
    rows = run(suite_with("leak"), tmp_path)
    assert "exited with code 2" in rows[0]["evidence"] and "<redacted>" in rows[0]["evidence"]
    assert not any(TOKEN in p.read_text() for p in tmp_path.rglob("*.json"))
    task = suite_with("leak").tasks[0]
    record = TrialRecord.model_validate(saved_record(tmp_path, task.id))
    assert (
        row_for(record, task, score_trial(record, task)).model_dump() == rows[0]
    )  # rescore gives the same row


def test_missing_model_settings_is_infrastructure_and_starts_no_agent(
    platform: FakePlatform, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in MODEL_VARIABLES:
        monkeypatch.delenv(name)
    rows = run(suite_with("ok"), tmp_path)
    assert rows[0]["evidence"].startswith("infrastructure: model settings missing")
    assert saved_record(tmp_path, "example.merge_two_parties_refused")["agent"] is None


def test_a_failed_read_in_one_task_does_not_stop_the_next(platform: FakePlatform, tmp_path: Path) -> None:
    good = load_suite(SEAT / "suites" / "example").tasks[0]
    assert good.targets is not None
    targets = good.targets.model_copy(update={"entity": "Broken"})
    broken = good.model_copy(update={"id": "example.broken_read", "targets": targets})
    platform.broken_entity = "Broken"
    rows = run(suite_with("ok", tasks=[broken, good]), tmp_path)
    assert rows[0]["evidence"].startswith("infrastructure: harness error: PlatformError")
    assert rows[1]["passed"] is True


def test_recount_task_saves_the_rows_before_and_after_the_agent(
    platform: FakePlatform, tmp_path: Path
) -> None:
    good = load_suite(SEAT / "suites" / "example").tasks[0]
    spec = GraderSpec(name="recount", answer="orders_not_invoiced", days=7)
    recount = good.model_copy(update={"id": "example.recount", "graders": [*good.graders, spec]})
    run(suite_with("ok", tasks=[recount]), tmp_path)
    pop = saved_record(tmp_path, "example.recount")["population"]["orders_not_invoiced"]
    assert pop["entity"] == "SalesOrder" and pop["as_of"]
    assert (
        pop["before"]
        == pop["after"]
        == [{"id": "so-1", "docstatus": 1, "invoiced_status": "unbilled", "date": "2026-10-01"}]
    )


def test_main_without_settings_still_writes_results(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in CONTRACT:
        monkeypatch.delenv(name, raising=False)
    out = tmp_path / "results.json"
    monkeypatch.setattr(
        sys, "argv", ["eval_harness", "--suite", str(SEAT / "suites" / "example"), "--out", str(out)]
    )
    assert harness.main() == 0
    rows = json.loads(out.read_text())["tasks"]
    assert rows and all(r["evidence"].startswith("infrastructure: missing") for r in rows)


def test_settings_never_come_from_a_dotenv_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in CONTRACT:
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in CONTRACT.items()))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SettingsMissing):
        load_settings()


def test_sample_agent_refuses_to_start_without_the_given_model_endpoint() -> None:
    env = {k: v for k, v in CONTRACT.items() if k != "OPENAI_BASE_URL"}
    reply = subprocess.run(
        [sys.executable, "-m", "agents_under_test.sample", "--prompt", "hello"],
        cwd=SEAT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert reply.returncode == 4 and "OPENAI_BASE_URL" in reply.stderr
