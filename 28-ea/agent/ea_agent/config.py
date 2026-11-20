"""Settings from CLI flags, the process environment and an optional KEY=VALUE env file.

Two modes:
* local: systems from --system (or every system with a login); a password, a ready token or a cached login per
  system (see `auth.connect`); the env file is read.
* harness, for the course's eval runner (34-eval-harness/docs/processed/evaluation/agent-contract.md): it starts when
  AGENTSWITCH_TOKEN or AGENTSWITCH_INSTANCE is set, and then AGENTSWITCH_TOKEN, AGENTSWITCH_INSTANCE and
  AGENTSWITCH_BASE_URL are all required, so a harness token never reaches a system it was not given for. No env
  file, no login, no token cache; the model comes from OPENAI_* only, the endpoint the run must use.
"""
import json
import os
import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

INSTANCES = {
    "suryodaya": "https://agentswitch.theschoolofai.in",
    "keystone": "https://class.agentswitch.theschoolofai.in",
}
SYSTEMS = INSTANCES
LLM_APIS = ("openai", "chat", "auto")
HARNESS_VARS = ("AGENTSWITCH_TOKEN", "AGENTSWITCH_INSTANCE", "AGENTSWITCH_BASE_URL")
RUN_ID_VAR = "AGENTSWITCH_RUN_ID"

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except (OSError, UnicodeDecodeError) as exc:
        # a settings problem, reported in one line like the others, never a traceback
        raise SystemExit(f"could not read the env file {path}: {type(exc).__name__}") from None
    out: dict = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        if not _KEY.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def _arg(args, name: str):
    if args is None:
        return None
    if isinstance(args, dict):
        return args.get(name)
    return getattr(args, name, None)


def _parse_today(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise SystemExit(f"--today / EA_TODAY must be YYYY-MM-DD, got {value!r}") from None




def _as_list(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [v for v in value if v not in (None, "")]
    return [value]


def _requested_systems(args) -> list[str]:
    # --instance is kept as an alias of --system; both may be repeated.
    out: list[str] = []
    for value in _as_list(_arg(args, "system")) + _as_list(_arg(args, "instance")):
        name = str(value).strip().lower()
        if name and name not in out:
            out.append(name)
    return out


def _zone(name: str, flag: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise SystemExit(f"unknown time zone {name!r} in {flag}") from None
    return name


def parse_tz(values, known: set | None = None) -> tuple[str | None, dict]:
    """`--tz ZONE` (all systems) or `--tz system=ZONE` (repeatable). Returns (zone for all, {system: zone})."""
    everywhere, per_system = None, {}
    for raw in _as_list(values):
        text = str(raw).strip()
        if "=" in text:
            system, zone = (part.strip() for part in text.split("=", 1))
            system = system.lower()
            if known is not None and system not in known:
                raise SystemExit(f"--tz {text}: unknown system {system!r}")
            per_system[system] = _zone(zone, f"--tz {text}")
        else:
            if everywhere is not None and everywhere != text:
                raise SystemExit("--tz ZONE was given twice; use --tz system=ZONE for different zones")
            everywhere = _zone(text, "--tz")
    return everywhere, per_system


def _models(value) -> list[str]:
    """One model name, or a comma-separated list to try in order (the course contract allows both)."""
    return [m.strip() for m in str(value or "").split(",") if m.strip()]


def _extra_body(env: dict, name: str) -> dict | None:
    """A JSON object sent with every model request (provider quirks). Errors name the variable, never its value."""
    raw = (env.get(name) or "").strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} is not valid JSON ({getattr(exc, 'msg', 'parse error')})") from None
    if not isinstance(value, dict):
        raise SystemExit(f'{name} must be a JSON object, like {{"key": "value"}}')
    return value


def llm_settings(env: dict) -> dict | None:
    """Model settings, first match wins: EA_LLM_* then OPENAI_*. No default endpoint or model: unset means off.

    Keys: base_url, api, key, model (the first name or None), models (every name, in order) and extra_body (a dict
    or None)."""
    if env.get("EA_LLM_URL"):
        url, api = env["EA_LLM_URL"].strip(), (env.get("EA_LLM_API") or "auto").strip().lower()
        if api not in LLM_APIS:
            raise SystemExit(f"EA_LLM_API must be one of {', '.join(LLM_APIS)}, got {api!r}")
        models = _models(env.get("EA_LLM_MODEL"))
        if api == "openai" and not models:
            raise SystemExit("EA_LLM_API=openai needs EA_LLM_MODEL (the model name to request)")
        key, source = (env.get("EA_LLM_KEY") or "").strip() or None, "EA_LLM_URL"  # a stray newline breaks the header
        extra = _extra_body(env, "EA_LLM_EXTRA_BODY")
    elif any(env.get(k) for k in ("EA_LLM_API", "EA_LLM_MODEL", "EA_LLM_KEY", "EA_LLM_EXTRA_BODY")):
        raise SystemExit("EA_LLM_API / EA_LLM_MODEL / EA_LLM_KEY / EA_LLM_EXTRA_BODY are set but EA_LLM_URL "
                         "is missing")
    elif env.get("OPENAI_BASE_URL"):
        url, api = env["OPENAI_BASE_URL"].strip(), "auto"
        models = _models(env.get("OPENAI_MODEL"))
        key, source = (env.get("OPENAI_API_KEY") or "").strip() or None, "OPENAI_BASE_URL"
        extra = _extra_body(env, "OPENAI_EXTRA_BODY")
    else:
        return None
    if not url.lower().startswith(("https://", "http://")):
        raise SystemExit(f"{source} must start with http:// or https://")
    return {"base_url": url, "api": api, "key": key, "model": models[0] if models else None, "models": models,
            "extra_body": extra}


def password_var(system: str) -> str:
    return f"EA_PASSWORD_{system.upper()}"


def token_var(system: str) -> str:
    """A ready token for one system in local mode: no password and no login."""
    return f"AGENTSWITCH_{system.upper()}_TOKEN"


HARNESS_LLM_VARS = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_MODEL")


def _harness(environ: dict, requested: list[str]) -> tuple[str, str, str]:
    """(token, instance, base_url) of a harness run, or SystemExit with one plain line that holds no value."""
    token, instance, base_url = ((environ.get(v) or "").strip() for v in HARNESS_VARS)
    missing = [v for v, value in zip(HARNESS_VARS, (token, instance, base_url)) if not value]
    if missing:
        raise SystemExit("harness mode needs AGENTSWITCH_TOKEN, AGENTSWITCH_INSTANCE and AGENTSWITCH_BASE_URL "
                         "together; missing: " + ", ".join(missing))
    if not base_url.lower().startswith(("https://", "http://")):
        raise SystemExit("AGENTSWITCH_BASE_URL must start with http:// or https://")
    instance = instance.lower()
    if instance not in SYSTEMS:
        raise SystemExit(f"AGENTSWITCH_INSTANCE must be one of {', '.join(sorted(SYSTEMS))}, got {instance!r}")
    others = [name for name in requested if name != instance]
    if others:
        raise SystemExit(f"--system {others[0]} conflicts with AGENTSWITCH_INSTANCE={instance}")
    return token, instance, base_url.rstrip("/")


def resolve(args, environ) -> dict:
    environ = dict(environ if environ is not None else os.environ)
    requested = _requested_systems(args)
    warnings: list[str] = []
    if environ.get("AGENTSWITCH_TOKEN") or environ.get("AGENTSWITCH_INSTANCE"):
        # Harness mode: the runner hands us a token and URL for exactly one system; there is no password, no
        # login, no token cache, and the env file is not read.
        token, label, base_url = _harness(environ, requested)
        env, platform, systems = environ, True, [label]
        # The contract: local runs use the live shared data, so they must be read-only; only a harness copy may be
        # written to. A live URL here means a local run, so drafts are previewed and never saved.
        read_only = base_url in {url.rstrip("/") for url in SYSTEMS.values()}
        if read_only:
            warnings.append("AGENTSWITCH_BASE_URL is a live system, not a harness copy: drafts are previewed, "
                            "not saved")
        tz_all, tz_by = parse_tz(_arg(args, "tz"), known=set(SYSTEMS))
        # The contract names OPENAI_* as the endpoint the run must use: an EA_LLM_* left in a shell must not win.
        llm_env = {k: v for k, v in environ.items() if k.startswith("OPENAI_")}
        # The contract says to stop with an error when the given endpoint is incomplete: a harness run grades the
        # drafts that land on the platform, so a run without a model would pass silently with nothing to grade.
        # --no-llm is an explicit choice and skips the check.
        if not _arg(args, "no_llm"):
            missing = [v for v in HARNESS_LLM_VARS if not (environ.get(v) or "").strip()]
            if missing:
                raise SystemExit("harness mode needs the model endpoint the run gives; missing: " + ", ".join(missing))
    else:
        explicit = _arg(args, "env_file") or environ.get("EA_ENV_FILE")
        path = explicit or os.path.join(os.getcwd(), ".env")
        if os.path.isfile(path):
            file_env = load_env_file(path)
        elif explicit:
            raise SystemExit(f"env file not found: {path}")
        else:
            file_env = {}
        env = {**file_env, **environ}
        if env.get("AGENTSWITCH_BASE_URL"):
            warnings.append("AGENTSWITCH_BASE_URL is ignored unless AGENTSWITCH_TOKEN and AGENTSWITCH_INSTANCE are "
                            "set too")
        if not requested and env.get("EA_INSTANCE"):
            requested = [str(env["EA_INSTANCE"]).strip().lower()]
        for name in requested:
            if name not in SYSTEMS:
                raise SystemExit(f"unknown system {name!r}; expected one of {', '.join(sorted(SYSTEMS))}")
        platform, token, base_url, label, read_only = False, None, None, None, False
        systems = requested or sorted(SYSTEMS)
        tz_all, tz_by = parse_tz(_arg(args, "tz"), known=set(SYSTEMS))
        llm_env = env
    if tz_all is None and env.get("EA_TZ"):
        tz_all = _zone(env["EA_TZ"].strip(), "EA_TZ")
    return {
        "platform": platform,
        "env": env,
        "systems": systems,
        "explicit": bool(requested),
        "instance": label if platform else (requested[0] if len(requested) == 1 else None),
        "base_url": base_url,
        "token": token,
        "run_id": (environ.get(RUN_ID_VAR) or "").strip() or None,
        "read_only": read_only,
        "warnings": warnings,
        "email": env.get("EA_EMAIL") or None,
        "tz": tz_all,
        "tz_by_system": tz_by,
        "today": _parse_today(_arg(args, "today") or env.get("EA_TODAY")),
        "llm": None if _arg(args, "no_llm") else llm_settings(llm_env),
    }
