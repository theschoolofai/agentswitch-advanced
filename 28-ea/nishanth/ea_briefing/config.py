"""Settings from CLI flags, the process environment and an optional KEY=VALUE env file."""
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

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path) -> dict:
    out: dict = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
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


def llm_settings(env: dict) -> dict | None:
    """Model settings, first match wins: EA_LLM_* then OPENAI_*. No default endpoint or model: unset means off."""
    if env.get("EA_LLM_URL"):
        url, api = env["EA_LLM_URL"].strip(), (env.get("EA_LLM_API") or "auto").strip().lower()
        if api not in LLM_APIS:
            raise SystemExit(f"EA_LLM_API must be one of {', '.join(LLM_APIS)}, got {api!r}")
        model = (env.get("EA_LLM_MODEL") or "").strip() or None
        if api == "openai" and not model:
            raise SystemExit("EA_LLM_API=openai needs EA_LLM_MODEL (the model name to request)")
        key, source = env.get("EA_LLM_KEY") or None, "EA_LLM_URL"
    elif any(env.get(k) for k in ("EA_LLM_API", "EA_LLM_MODEL", "EA_LLM_KEY")):
        raise SystemExit("EA_LLM_API / EA_LLM_MODEL / EA_LLM_KEY are set but EA_LLM_URL is missing")
    elif env.get("OPENAI_BASE_URL"):
        url, api = env["OPENAI_BASE_URL"].strip(), "auto"
        model = (env.get("OPENAI_MODEL") or "").strip() or None
        key, source = env.get("OPENAI_API_KEY") or None, "OPENAI_BASE_URL"
    else:
        return None
    if not url.lower().startswith(("https://", "http://")):
        raise SystemExit(f"{source} must start with http:// or https://")
    return {"base_url": url, "api": api, "key": key, "model": model}


def password_var(system: str) -> str:
    return f"EA_PASSWORD_{system.upper()}"


def resolve(args, environ) -> dict:
    environ = dict(environ if environ is not None else os.environ)
    requested = _requested_systems(args)
    if environ.get("AGENTSWITCH_TOKEN"):
        # Platform mode: the runner hands us a token and URL for exactly one system; there is no password, no
        # login, no token cache, and the env file is not read.
        base_url = environ.get("AGENTSWITCH_BASE_URL")
        if not base_url:
            raise SystemExit("AGENTSWITCH_TOKEN is set but AGENTSWITCH_BASE_URL is missing")
        env = environ
        label = (environ.get("AGENTSWITCH_INSTANCE") or (requested[0] if requested else "") or "").strip().lower()
        platform, token, systems = True, environ["AGENTSWITCH_TOKEN"], [label or None]
        tz_all, tz_by = parse_tz(_arg(args, "tz"))
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
        if not requested and env.get("EA_INSTANCE"):
            requested = [str(env["EA_INSTANCE"]).strip().lower()]
        for name in requested:
            if name not in SYSTEMS:
                raise SystemExit(f"unknown system {name!r}; expected one of {', '.join(sorted(SYSTEMS))}")
        platform, token, base_url, label = False, None, None, None
        systems = requested or sorted(SYSTEMS)
        tz_all, tz_by = parse_tz(_arg(args, "tz"), known=set(SYSTEMS))
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
        "email": env.get("EA_EMAIL") or None,
        "tz": tz_all,
        "tz_by_system": tz_by,
        "today": _parse_today(_arg(args, "today") or env.get("EA_TODAY")),
        "llm": None if _arg(args, "no_llm") else llm_settings(env),
    }
