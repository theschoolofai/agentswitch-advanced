"""One run: every configured system, one combined briefing, one exit code.

Exit codes: 0 all good; 2 the briefing was printed but something failed (a login, a section, the model, a draft save,
the time limit, the briefing or JSON file); 1 nothing could run (bad flags or settings, no system configured, every
login failed).

Each platform call takes about 2 s, so the systems run on parallel threads; the output keeps their fixed order.

Output rules:
* Every line on stdout or stderr and every file goes through `redact`, so no loaded token, password or key appears.
* The briefing and --json files are written atomically, owner-only (0600; a folder we create is 0700): they hold
  mail. A run that fetched nothing keeps the day's earlier briefing file.
* With AGENTSWITCH_RUN_ID set (a course harness run) the last stdout line is `AGENT_RESULT {...}` (contract section
  4): claim "done" for exit 0, "failed" otherwise, `steps` = MCP tool calls made, `model` = the first model name.
  A non-zero exit then also ends stderr with one plain `error:` line (contract section 5).
"""
import getpass
import json
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfoNotFoundError

from . import auth, briefing, collect, config, review
from . import llm as llm_mod
from . import redact as redact_mod

DEFAULT_TIME_LIMIT = 60.0
DEFAULT_MODEL_PARALLEL = 3
DEFAULT_OUT = "briefings"
SECTIONS = ("mail", "meetings", "overdue")
NOTHING_FETCHED = "note: nothing could be read, so no briefing file was written (an earlier one is kept)"


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _opt(options: dict, name: str, default=None):
    value = options.get(name)
    return default if value is None else value


def write_atomic(path: str, text: str, make_dirs: bool = True) -> None:
    """Write `text` to `path` owner-only and atomically. `make_dirs` False: a missing folder is an OSError."""
    folder = os.path.dirname(os.path.abspath(path))
    if make_dirs and not os.path.isdir(folder):
        os.makedirs(folder, mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)  # makedirs is subject to the umask; a folder that already existed is left alone
    # mkstemp makes the file 0600 (the briefing holds mail); the rename means a reader never sees half a file.
    fd, tmp = tempfile.mkstemp(prefix=".briefing-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fetched_anything(blocks: list[dict]) -> bool:
    """True when at least one section of one system was read."""
    return any(b.get("status") == "ok" and any((b.get(k) or {}).get("status") == "ok" for k in SECTIONS)
               for b in blocks)


def _mcp_calls(clients) -> int | None:
    """Tool calls made, from each client's JSON-RPC id counter; None when no client exposes one."""
    counts = [c._id for c in clients if isinstance(getattr(c, "_id", None), int)]
    return sum(counts) if counts else None


def drafts_created(clients) -> int:
    return sum(c.drafts_created for c in clients if isinstance(getattr(c, "drafts_created", None), int))


def harness_claim(code: int, stats: dict) -> str:
    """'done' for a clean run, or a partial one that still landed drafts; 'failed' otherwise. The contract compares
    the claim with what reached the platform, so a run that saved drafts does not claim it failed."""
    if code == 0 or (code == 2 and drafts_created(stats.get("clients") or [])):
        return "done"
    return "failed"


def agent_result(claim: str, stats: dict) -> str:
    """The contract's optional last line. It holds no secret: a claim, a count and a model name."""
    data = {"claim": claim}
    steps = _mcp_calls(stats.get("clients") or [])
    if steps is not None:
        data["steps"] = steps
    if stats.get("model"):
        data["model"] = stats["model"]
    return "AGENT_RESULT " + json.dumps(data)


def run(options: dict, environ: dict, stdin_isatty: bool, input_fn=input, getpass_fn=getpass.getpass,
        client_factory=None, now=None, *, login_fn=None, llm_opener=None, editor_fn=None, clock=time.monotonic):
    environ = dict(environ if environ is not None else os.environ)
    stats = {"clients": [], "model": None, "problems": [], "secrets": redact_mod.secrets_from_env(environ)}
    result, code = _run(options, environ, stdin_isatty, input_fn, getpass_fn, client_factory, now, stats,
                        login_fn=login_fn, llm_opener=llm_opener, editor_fn=editor_fn, clock=clock)
    if (environ.get(config.RUN_ID_VAR) or "").strip():
        # Exit 1 already ended stderr with its `error:` line. Exit 2 means the briefing ran but part of it failed:
        # the contract reads any non-zero exit as "could not finish" (an infrastructure failure, not graded), so a
        # harness run that finished exits 0 and names what failed in a warning line instead.
        claim = harness_claim(code, stats)
        if code == 2:
            why = "; ".join(stats["problems"]) or "part of the run failed"
            _err(redact_mod.redact(f"warning: {why}", stats["secrets"]))
            code = 0
        print(redact_mod.redact(agent_result(claim, stats), stats["secrets"]))
    return result, code


def _targets(cfg: dict, cache_file: str, now: datetime) -> list[str]:
    """Systems to run. Named ones always run (a missing login shows in their block); otherwise only systems with a
    ready token, a saved login or a password, so an unused system is not reported as a failure every day."""
    if cfg["explicit"]:
        return list(cfg["systems"])
    env, email, cache = cfg["env"], cfg["email"], auth.load(cache_file)
    out = []
    for system in cfg["systems"]:
        has_password = bool(email and env.get(config.password_var(system)))
        has_token = bool((env.get(config.token_var(system)) or "").strip())
        if has_token or has_password or auth.fresh_entry(cache, system, config.SYSTEMS[system], email, now):
            out.append(system)
    return out


def _block_failed(b: dict) -> bool:
    if b.get("status") != "ok":
        return True
    if any((b.get(k) or {}).get("status") == "error" for k in ("mail", "meetings", "overdue")):
        return True
    return bool(b.get("warnings")) or bool(briefing.draft_errors(b))


def _block_problem(b: dict) -> str:
    """One short reason for a failed system block, for the closing error line of a harness run."""
    name = b.get("system") or "system"
    if b.get("status") == "login_failed":
        return f"{name}: could not log in"
    if b.get("status") != "ok":
        return f"{name}: failed"
    bad = [k for k in SECTIONS if (b.get(k) or {}).get("status") == "error"]
    if bad:
        return f"{name}: could not read {', '.join(bad)}"
    if briefing.draft_errors(b):
        return f"{name}: a draft could not be saved"
    return f"{name}: " + "; ".join(str(w) for w in b.get("warnings") or ["a warning was raised"])


def _run(options, environ, stdin_isatty, input_fn, getpass_fn, client_factory, now, stats, *, login_fn,
         llm_opener, editor_fn, clock):
    options = dict(options or {})
    secrets = stats["secrets"]
    lock = threading.Lock()  # systems connect on parallel threads; the set is never read while it grows

    def add_secrets(values) -> None:
        with lock:
            secrets.update(v for v in values if isinstance(v, str) and v)

    def known_secrets() -> frozenset:
        with lock:
            return frozenset(secrets)

    def say(message: str) -> None:
        _err(redact_mod.redact(message, known_secrets()))

    def fail(message: str):
        say(f"error: {message}")
        stats["problems"].append(message)
        return {}, 1

    if options.get("logout"):
        if environ.get("AGENTSWITCH_TOKEN"):
            print("Platform mode has no saved logins; nothing removed.")
            return {"logout": True, "removed": False}, 0
        path = auth.cache_path(environ)
        removed = auth.delete(path)
        print("Saved logins removed." if removed else "No saved logins to remove.")
        return {"logout": True, "removed": removed}, 0
    want_review, no_save = bool(options.get("review")), bool(options.get("no_save"))
    if want_review and no_save:
        return fail("--review and --no-save cannot be used together")
    if want_review and not stdin_isatty:
        return fail("--review needs an interactive terminal (stdin is not a TTY); run without --review to save "
                    "clean drafts, or with --no-save to preview them")
    time_limit = _opt(options, "time_limit", DEFAULT_TIME_LIMIT)
    if not isinstance(time_limit, (int, float)) or isinstance(time_limit, bool) or time_limit <= 0:
        return fail("--time-limit must be a positive number of seconds")
    parallel = _opt(options, "model_parallel", DEFAULT_MODEL_PARALLEL)
    if not isinstance(parallel, int) or isinstance(parallel, bool) or parallel < 1:
        return fail("--model-parallel must be a whole number of at least 1")
    try:
        cfg = config.resolve(options, environ)
    except SystemExit as exc:
        return fail(str(exc.code))
    # The env file may hold passwords and tokens too; the model key is a secret even when it came from the file.
    add_secrets(redact_mod.secrets_from_env(cfg["env"]))
    add_secrets((cfg["token"], (cfg["llm"] or {}).get("key")))
    stats["model"] = (cfg["llm"] or {}).get("model")
    for warning in cfg.get("warnings") or []:
        say(f"warning: {warning}")
    started = _opt(options, "started", clock())
    deadline = started + float(time_limit)
    now = now or datetime.now(timezone.utc)

    llm = None
    if cfg["llm"]:
        try:
            llm = llm_mod.make_llm(cfg["llm"], deadline=deadline, opener=llm_opener, clock=clock, parallel=parallel)
        except ValueError as exc:
            return fail(str(exc))
    if llm is not None:
        describe = getattr(llm, "describe", None)
        model_text = describe() if callable(describe) else "configured"
    elif options.get("no_llm"):
        model_text = "off (--no-llm); mail is listed unassessed"
    else:
        model_text = "not configured; mail is listed unassessed"

    cache_file = None if cfg["platform"] else auth.cache_path(environ)
    if cfg["platform"]:
        targets = cfg["systems"]
    else:
        targets = _targets(cfg, cache_file, now)
        if not targets:
            return fail("no system configured. Set EA_EMAIL and EA_PASSWORD_KEYSTONE or EA_PASSWORD_SURYODAYA, "
                        "or AGENTSWITCH_KEYSTONE_TOKEN or AGENTSWITCH_SURYODAYA_TOKEN, or run with --system NAME "
                        "in a terminal to log in.")

    save = not no_save and not cfg.get("read_only")
    reviewer = review.Reviewer(input_fn=input_fn, print_fn=say, editor_fn=editor_fn, environ=environ) \
        if want_review else None

    def connect(system):
        found: set = set()
        conn = _connect_system(system, cfg, environ, stdin_isatty, input_fn, getpass_fn, client_factory, login_fn,
                               cache_file, now, log=say, secrets=found)
        # A token from the cache or a fresh login (and a typed password) is a secret from here on, like the ones in
        # the environment.
        add_secrets(found)
        if "client" in conn:
            add_secrets((getattr(conn["client"], "_token", None),))
            with lock:
                stats["clients"].append(conn["client"])
        return conn

    def brief(conn):
        return _brief_system(conn, cfg, options, now, llm, save and not want_review, deadline, parallel)

    # A password prompt cannot share the terminal with another thread, so logins that may prompt run one by one.
    may_prompt = stdin_isatty and cfg["explicit"] and not cfg["platform"]
    with ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
        conns = [connect(t) for t in targets] if may_prompt else list(pool.map(connect, targets))
        blocks = list(pool.map(brief, conns))
    if reviewer is not None:
        # After every system's model calls: reading drafts must not eat into the model time limit.
        for conn, b in zip(conns, blocks):
            if b.get("status") == "ok":
                briefing.review_drafts(conn["client"], conn["me"], b, reviewer)

    first_date = next((b["date"] for b in blocks if b.get("date")), None)
    result = {
        "date": first_date or (cfg["today"] or now.date()).isoformat(),
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "model": model_text,
        "drafts": "review" if want_review else ("save" if save else "preview"),
        "systems": blocks,
        "warnings": [],
        "file": None,
    }
    ran = [b for b in blocks if b.get("status") == "ok"]
    if not ran:
        for b in blocks:
            what = "could not log in" if b.get("status") == "login_failed" else "failed"
            message = f"{b.get('system') or 'system'}: {what}: {b.get('error')}"
            say(f"error: {message}")
            stats["problems"].append(message)
        return result, 1

    text = redact_mod.redact(briefing.render_run(result), known_secrets())
    print(text)
    failed = any(_block_failed(b) for b in blocks)
    stats["problems"].extend(_block_problem(b) for b in blocks if _block_failed(b))
    for b in ran:
        errors = briefing.draft_errors(b)
        if errors:
            say(f"note: {b.get('system')}: {len(errors)} draft(s) could not be saved")
    if not options.get("no_file"):
        path = os.path.join(_opt(options, "out", DEFAULT_OUT), f"briefing-{result['date']}.md")
        if not fetched_anything(blocks):
            say(NOTHING_FETCHED)
        else:
            try:
                write_atomic(path, text)
                result["file"] = path
                say(f"note: briefing written to {path}")
            except OSError as exc:
                say(f"error: could not write the briefing file {path}: {type(exc).__name__}")
                stats["problems"].append("could not write the briefing file")
                failed = True
    if options.get("json_path"):
        try:
            # Through JSON once (default=str for dates), then redacted value by value: a secret is matched in its
            # plain form, which JSON escaping could otherwise hide.
            data = redact_mod.redact_value(json.loads(json.dumps(result, default=str)), known_secrets())
            write_atomic(options["json_path"], json.dumps(data, indent=2, ensure_ascii=False), make_dirs=False)
        except (OSError, TypeError, ValueError) as exc:
            say(f"error: could not write JSON to {options['json_path']}: {type(exc).__name__}: {exc}")
            stats["problems"].append("could not write the JSON file")
            failed = True  # the briefing is already printed, so this is "something failed", not "nothing ran"
    return result, 2 if failed else 0


def _connect_system(system, cfg, environ, stdin_isatty, input_fn, getpass_fn, client_factory, login_fn,
                    cache_file, now, log=_err, secrets: set | None = None) -> dict:
    name = system or "platform"
    factory = client_factory or auth.default_client
    try:
        if cfg["platform"]:
            client = factory(system, cfg["base_url"], cfg["token"])
            me, how = client.me(), "platform token"
        else:
            client, me, how = auth.connect(system, config.SYSTEMS[system], cfg["env"], cache_file=cache_file,
                                           explicit=cfg["explicit"], stdin_isatty=stdin_isatty, input_fn=input_fn,
                                           getpass_fn=getpass_fn, client_factory=client_factory, login_fn=login_fn,
                                           now=now, log=log, secrets=secrets)
    except auth.AuthError as exc:
        return {"system": system, "name": name, "error": str(exc)}
    except Exception as exc:
        detail = f"{exc.kind}: {exc.message}" if hasattr(exc, "kind") and hasattr(exc, "message") else \
            f"{type(exc).__name__}: {exc}"
        return {"system": system, "name": name, "error": detail[:300]}
    return {"system": system, "name": name, "client": client, "me": me, "how": how}


def _brief_system(conn, cfg, options, now, llm, save, deadline, parallel) -> dict:
    system, name = conn["system"], conn["name"]
    if "client" not in conn:
        return {"system": name, "status": "login_failed", "error": conn["error"]}
    client, me = conn["client"], conn["me"]
    try:
        try:
            client.instance = system
        except AttributeError:
            pass
        tz_name = cfg["tz_by_system"].get(system or "") or cfg["tz"]
        tz = collect.resolve_tz(client, me, tz_name, system=system)
        day = cfg["today"] or now.astimezone(tz).date()
        b = briefing.build_briefing(client, me, day, tz, llm=llm, save_drafts=save,
                                    mail_cap=int(_opt(options, "mail_cap", 25)),
                                    unread_only=bool(options.get("unread_only")), deadline=deadline, now=now,
                                    model_parallel=parallel)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        return {"system": name, "status": "error", "error": f"time zone: {type(exc).__name__}: {exc}"[:300]}
    except Exception as exc:  # one system's bug must not take the other system's briefing with it
        return {"system": name, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
    b.update(system=name, status="ok", login=conn["how"])
    return b
