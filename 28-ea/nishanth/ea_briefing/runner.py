"""One run: every configured system, one combined briefing, one exit code.

Exit codes: 0 all good; 2 the briefing was printed but something failed (a login, a section, the model, a draft save,
the time limit, the briefing or JSON file); 1 nothing could run (bad flags or settings, no system configured, every
login failed).

Each platform call takes about 2 s, so the systems run on parallel threads; the output keeps their fixed order.
"""
import getpass
import json
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfoNotFoundError

from . import auth, briefing, collect, config, review
from . import llm as llm_mod

DEFAULT_TIME_LIMIT = 60.0
DEFAULT_MODEL_PARALLEL = 3
DEFAULT_OUT = "briefings"


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _opt(options: dict, name: str, default=None):
    value = options.get(name)
    return default if value is None else value


def write_atomic(path: str, text: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
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


def _targets(cfg: dict, cache_file: str, now: datetime) -> list[str]:
    """Systems to run. Named ones always run (a missing login shows in their block); otherwise only systems with a
    saved login or a password, so an unused system is not reported as a failure every day."""
    if cfg["explicit"]:
        return list(cfg["systems"])
    env, email, cache = cfg["env"], cfg["email"], auth.load(cache_file)
    out = []
    for system in cfg["systems"]:
        has_password = bool(email and env.get(config.password_var(system)))
        if has_password or auth.fresh_entry(cache, system, config.SYSTEMS[system], email, now):
            out.append(system)
    return out


def _block_failed(b: dict) -> bool:
    if b.get("status") != "ok":
        return True
    if any((b.get(k) or {}).get("status") == "error" for k in ("mail", "meetings", "overdue")):
        return True
    return bool(b.get("warnings")) or bool(briefing.draft_errors(b))


def run(options: dict, environ: dict, stdin_isatty: bool, input_fn=input, getpass_fn=getpass.getpass,
        client_factory=None, now=None, *, login_fn=None, llm_opener=None, editor_fn=None, clock=time.monotonic):
    options = dict(options or {})
    environ = dict(environ if environ is not None else os.environ)
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
        _err("error: --review and --no-save cannot be used together")
        return {}, 1
    if want_review and not stdin_isatty:
        _err("error: --review needs an interactive terminal (stdin is not a TTY); run without --review to save "
             "clean drafts, or with --no-save to preview them")
        return {}, 1
    time_limit = _opt(options, "time_limit", DEFAULT_TIME_LIMIT)
    if not isinstance(time_limit, (int, float)) or isinstance(time_limit, bool) or time_limit <= 0:
        _err("error: --time-limit must be a positive number of seconds")
        return {}, 1
    parallel = _opt(options, "model_parallel", DEFAULT_MODEL_PARALLEL)
    if not isinstance(parallel, int) or isinstance(parallel, bool) or parallel < 1:
        _err("error: --model-parallel must be a whole number of at least 1")
        return {}, 1
    try:
        cfg = config.resolve(options, environ)
    except SystemExit as exc:
        _err(f"error: {exc.code}")
        return {}, 1
    started = _opt(options, "started", clock())
    deadline = started + float(time_limit)
    now = now or datetime.now(timezone.utc)

    llm = None
    if cfg["llm"]:
        try:
            llm = llm_mod.make_llm(cfg["llm"], deadline=deadline, opener=llm_opener, clock=clock, parallel=parallel)
        except ValueError as exc:
            _err(f"error: {exc}")
            return {}, 1
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
            _err("error: no system configured. Set EA_EMAIL and EA_PASSWORD_KEYSTONE or EA_PASSWORD_SURYODAYA, "
                 "or run with --system NAME in a terminal to log in.")
            return {}, 1

    save = not no_save
    reviewer = review.Reviewer(input_fn=input_fn, print_fn=_err, editor_fn=editor_fn, environ=environ) \
        if want_review else None

    def connect(system):
        return _connect_system(system, cfg, environ, stdin_isatty, input_fn, getpass_fn, client_factory, login_fn,
                               cache_file, now)

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
            _err(f"error: {b.get('system') or 'system'}: {what}: {b.get('error')}")
        return result, 1

    text = briefing.render_run(result)
    print(text)
    failed = any(_block_failed(b) for b in blocks)
    for b in ran:
        errors = briefing.draft_errors(b)
        if errors:
            _err(f"note: {b.get('system')}: {len(errors)} draft(s) could not be saved")
    if not options.get("no_file"):
        path = os.path.join(_opt(options, "out", DEFAULT_OUT), f"briefing-{result['date']}.md")
        try:
            write_atomic(path, text)
            result["file"] = path
            _err(f"note: briefing written to {path}")
        except OSError as exc:
            _err(f"error: could not write the briefing file {path}: {type(exc).__name__}")
            failed = True
    if options.get("json_path"):
        try:
            with open(options["json_path"], "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=2, default=str, ensure_ascii=False)
        except (OSError, TypeError, ValueError) as exc:
            _err(f"error: could not write JSON to {options['json_path']}: {type(exc).__name__}: {exc}")
            failed = True  # the briefing is already printed, so this is "something failed", not "nothing ran"
    return result, 2 if failed else 0


def _connect_system(system, cfg, environ, stdin_isatty, input_fn, getpass_fn, client_factory, login_fn,
                    cache_file, now) -> dict:
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
                                           now=now, log=_err)
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
