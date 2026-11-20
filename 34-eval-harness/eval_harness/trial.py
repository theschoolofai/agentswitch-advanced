"""One trial: one attempt at one task. Everything a grader needs is captured here and saved BEFORE scoring.

Steps: pick targets -> snapshot before -> start the agent (a separate program) -> snapshot after ->
record writes made by the run's login -> save the trial record. Graders later read only this record, so a
scorer change can be re-run from disk with zero model calls and zero platform calls (rescore.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shlex
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from eval_harness.platform import Me, PlatformError, PlatformReader
from eval_harness.rules import RULES, Population, Rule
from eval_harness.settings import MODEL_VARIABLES, OPTIONAL_MODEL_VARIABLES, HarnessSettings
from eval_harness.suite import Suite, Task

SEAT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_TAIL_CHARS = 4000
RESULT_PREFIX = "AGENT_RESULT "
KILL_GRACE_S = 10  # after a time-out: how long to wait for the killed agent's last output
# What a process needs to start and to reach the given endpoints (a proxy, if the runner uses one).
SYSTEM_VARIABLES = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TZ",
    "TMPDIR",
    "SYSTEMROOT",
    "VIRTUAL_ENV",
    "SSL_CERT_FILE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)


class AgentRun(BaseModel):
    """What we observed of the agent process. Its output is kept for people to read; graders never use it."""

    command: list[str]
    exit_code: int | None = None
    timed_out: bool = False
    seconds: float = 0.0
    output_tail: str = ""
    reported: dict[str, Any] | None = None  # the agent's optional AGENT_RESULT line: what it SAYS happened


class TrialRecord(BaseModel):
    run_id: str
    trial: int = 0  # index for repeated trials (pass^k comes in M2)
    instance: str
    task_id: str
    task_version: int
    manifest: dict[str, Any]  # everything that can change a score: commit, versions, model, command, limits
    user_id: str | None = None
    started_at: datetime | None = None  # server clock at the start (HTTP Date header)
    target_entity: str | None = None
    targets: list[str] = []
    before: dict[str, dict[str, Any] | None] = {}  # record id -> row (None: could not read)
    after: dict[str, dict[str, Any] | None] = {}
    writes_since_start: dict[str, list[dict[str, Any]] | None] = {}  # entity -> rows written by our login
    population: dict[str, Population] = {}  # recount answer name -> rows its rule needs (rules.py)
    agent: AgentRun | None = None
    infrastructure: str | None = None  # set when the trial could not run fairly


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=SEAT_DIR, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def manifest_for(suite: Suite, task: Task, settings: HarnessSettings) -> dict[str, Any]:
    return {
        "git_commit": git_commit(),
        "suite": suite.name,
        "suite_graded": suite.graded,
        "task_version": task.version,
        "graders": [g.model_dump() for g in task.graders],
        "agent_command": suite.agent,
        "task_minutes": suite.task_minutes,
        "model": settings.openai_model,
        "instance": settings.agentswitch_instance,
    }


def entities_to_watch(task: Task) -> list[str]:
    """Entities whose writes by our login we record, so the integrity grader can judge them later."""
    names: list[str] = []
    for spec in task.graders:
        names += [str(e) for e in spec.params.get("entities", [])]
    return sorted(set(names))


def answers_to_capture(task: Task) -> list[str]:
    """Answer names of the task's recount graders that have a rule (an unknown name is graded unevaluated)."""
    names = [str(s.params.get("answer", "")) for s in task.graders if s.name == "recount"]
    return sorted({n for n in names if n in RULES})


async def _read_rows(platform: PlatformReader, rule: Rule) -> list[dict[str, Any]] | None:
    try:
        rows = await platform.list_all(rule.entity)
    except PlatformError:
        return None  # could not check; never an empty list, which would look like "no orders"
    return [{f: row.get(f) for f in rule.fields} for row in rows]


async def capture_before(platform: PlatformReader, task: Task, as_of: datetime) -> dict[str, Population]:
    """Rows each recount answer needs, read just before the agent starts (only the rule's fields)."""
    captured: dict[str, Population] = {}
    for name in answers_to_capture(task):
        rule = RULES[name]
        captured[name] = Population(entity=rule.entity, as_of=as_of, before=await _read_rows(platform, rule))
    return captured


async def capture_after(platform: PlatformReader, before: dict[str, Population]) -> dict[str, Population]:
    """The same rows read again after the agent ran (live data can move during a run)."""
    return {
        name: pop.model_copy(update={"after": await _read_rows(platform, RULES[name])})
        for name, pop in before.items()
    }


GONE: dict[str, Any] = {"_harness": "not_found"}  # the platform said 404: the record is gone


async def snapshot(platform: PlatformReader, entity: str, ids: list[str]) -> dict[str, dict[str, Any] | None]:
    """One row per id. A 404 is saved as GONE (a fact); any other failed read as None (could not check)."""
    rows: dict[str, dict[str, Any] | None] = {}
    for record_id in ids:
        try:
            rows[record_id] = await platform.get(entity, record_id)
        except PlatformError as e:
            rows[record_id] = dict(GONE) if e.status == 404 else None
    return rows


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)  # the platform stores naive UTC


async def writes_by(
    platform: PlatformReader, entity: str, user_id: str, since: datetime
) -> list[dict[str, Any]]:
    """Rows of `entity` created or updated by this login at or after `since` (id and audit fields only)."""
    found: dict[str, dict[str, Any]] = {}
    for field in ("created_by", "updated_by"):
        for row in await platform.list_all(entity, **{field: user_id}):
            stamp = _parse_time(row.get("updated_at")) or _parse_time(row.get("created_at"))
            if stamp and stamp >= since:
                found[str(row["id"])] = {
                    k: row.get(k) for k in ("id", "created_at", "created_by", "updated_at", "updated_by")
                }
    return list(found.values())


def agent_environment(settings: HarnessSettings, run_id: str) -> dict[str, str]:
    """The contract variables and a few operating-system basics, nothing else.

    An allowlist, so no password, token or key that happens to be in our environment can reach the agent.
    """
    allowed = (*SYSTEM_VARIABLES, *MODEL_VARIABLES, *OPTIONAL_MODEL_VARIABLES)
    env = {name: os.environ[name] for name in allowed if name in os.environ}
    env.update(
        {
            "AGENTSWITCH_BASE_URL": settings.base_url,
            "AGENTSWITCH_TOKEN": settings.agentswitch_token.get_secret_value(),
            "AGENTSWITCH_INSTANCE": settings.agentswitch_instance,
            "AGENTSWITCH_RUN_ID": run_id,
        }
    )
    return env


def parse_reported(output: str) -> dict[str, Any] | None:
    for line in reversed(output.splitlines()):
        if line.startswith(RESULT_PREFIX):
            try:
                value = json.loads(line[len(RESULT_PREFIX) :])
            except ValueError:
                return None
            return value if isinstance(value, dict) else None
    return None


async def run_agent(command: list[str], env: dict[str, str], timeout_s: float) -> AgentRun:
    """Start the agent in its own process group, so the time limit also stops what it starts.

    An agent command is often a wrapper (`uv run`, `sh -c`) whose child keeps the output pipe open after the
    wrapper is killed. Killing the whole group closes the pipe, and the final read is bounded as well, so the
    time limit always holds. POSIX only; the course runner is Linux.
    """
    started = time.monotonic()
    run = AgentRun(command=command)
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=SEAT_DIR,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as e:
        run.output_tail = f"could not start the agent: {e}"
        return run
    note = ""
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except TimeoutError:
        run.timed_out = True
        _kill_group(process.pid)
        try:
            out, _ = await asyncio.wait_for(process.communicate(), timeout=KILL_GRACE_S)
        except TimeoutError:
            out = b""  # a process outside the group still holds the pipe: stop waiting for it
            note = "\n[harness: output not collected; a process outside the agent's group kept it open]"
    run.exit_code = process.returncode
    run.seconds = round(time.monotonic() - started, 1)
    text = (out or b"").decode("utf-8", "replace") + note
    run.output_tail = text[-OUTPUT_TAIL_CHARS:]
    run.reported = parse_reported(text)
    return run


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):  # the group has already exited: nothing left to stop
        os.killpg(pid, signal.SIGKILL)


def infrastructure_problem(agent: AgentRun) -> str | None:
    """Course rule: a task that could not run (time-out, model error, crash) is an infrastructure failure."""
    if agent.timed_out:
        return f"agent timed out after {agent.seconds:.0f}s"
    if agent.exit_code != 0:
        last = next(
            (ln.strip() for ln in reversed(agent.output_tail.splitlines()) if any(c.isalpha() for c in ln)),
            "",
        )
        return f"agent exited with code {agent.exit_code}: {last[:200]}"
    return None


async def run_trial(
    suite: Suite, task: Task, settings: HarnessSettings, platform: PlatformReader, me: Me, run_id: str
) -> TrialRecord:
    record = TrialRecord(
        run_id=run_id,
        instance=settings.agentswitch_instance,
        task_id=task.id,
        task_version=task.version,
        manifest=manifest_for(suite, task, settings),
        user_id=me.user_id,
    )
    missing = settings.missing_model_variables()
    if missing:
        record.infrastructure = f"model settings missing: {', '.join(missing)}"
        return record
    if task.targets:
        record.target_entity = task.targets.entity
        rows = await platform.list_page(task.targets.entity, task.targets.limit)
        record.targets = [str(r["id"]) for r in rows]
        if len(record.targets) < task.targets.limit:
            record.infrastructure = (
                f"needed {task.targets.limit} {task.targets.entity} records, found {len(record.targets)}"
            )
            return record
        record.before = await snapshot(platform, task.targets.entity, record.targets)
    record.started_at = (await platform.whoami()).server_time
    record.population = await capture_before(platform, task, record.started_at)
    command = [*shlex.split(suite.agent), "--prompt", task.render_prompt(record.targets)]
    record.agent = await run_agent(command, agent_environment(settings, run_id), suite.task_minutes * 60)
    record.infrastructure = infrastructure_problem(record.agent)
    if task.targets:
        record.after = await snapshot(platform, task.targets.entity, record.targets)
    record.population = await capture_after(platform, record.population)
    for entity in entities_to_watch(task):
        try:
            record.writes_since_start[entity] = await writes_by(
                platform, entity, me.user_id, record.started_at
            )
        except PlatformError:
            record.writes_since_start[entity] = None
    return record


def scrub(text: str, secrets: list[str]) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "<redacted>")
    return text


def save_record(record: TrialRecord, run_dir: Path, secrets: list[str]) -> TrialRecord:
    """Write the trial record atomically, secrets removed, and return exactly what was written.

    Called before any grading; the caller scores the returned record. So a token the agent printed reaches
    neither the saved record nor results.json, and a rescore of the file gives the same row.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / f"{record.instance}__{record.task_id}__t{record.trial}.json"
    text = scrub(record.model_dump_json(indent=1), secrets)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
    return TrialRecord.model_validate_json(text)
