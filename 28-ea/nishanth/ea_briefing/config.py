"""Settings from CLI flags, the process environment and an optional KEY=VALUE env file."""
import os
import re
from datetime import date

INSTANCES = {
    "suryodaya": "https://agentswitch.theschoolofai.in",
    "keystone": "https://class.agentswitch.theschoolofai.in",
}
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LLM_MODEL = "gpt-4.1-mini"

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


def _llm(env: dict, args) -> dict | None:
    if _arg(args, "no_llm"):
        return None
    key = env.get("OPENAI_API_KEY")
    if not key:
        return None
    return {"base_url": env.get("OPENAI_BASE_URL") or DEFAULT_LLM_BASE_URL, "api_key": key,
            "model": env.get("OPENAI_MODEL") or DEFAULT_LLM_MODEL}


def resolve(args, environ) -> dict:
    environ = dict(environ if environ is not None else os.environ)
    if environ.get("AGENTSWITCH_TOKEN"):
        # Platform mode: the runner hands us a token and URL; there is no password and the env file is not read.
        base_url = environ.get("AGENTSWITCH_BASE_URL")
        if not base_url:
            raise SystemExit("AGENTSWITCH_TOKEN is set but AGENTSWITCH_BASE_URL is missing")
        env = environ
        instance = environ.get("AGENTSWITCH_INSTANCE") or _arg(args, "instance")
        token, email, password = environ["AGENTSWITCH_TOKEN"], None, None
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
        instance = _arg(args, "instance") or env.get("EA_INSTANCE")
        if not instance:
            raise SystemExit("--instance is required (keystone or suryodaya)")
        instance = str(instance).lower()
        if instance not in INSTANCES:
            raise SystemExit(f"unknown instance {instance!r}; expected one of {', '.join(sorted(INSTANCES))}")
        base_url = INSTANCES[instance]
        token = None
        email = env.get("EA_EMAIL")
        if not email:
            raise SystemExit("missing EA_EMAIL (set it in the environment or the env file)")
        pw_var = f"EA_PASSWORD_{instance.upper()}"
        password = env.get(pw_var)
        if not password:
            raise SystemExit(f"missing {pw_var} (set it in the environment or the env file)")
    return {
        "instance": instance,
        "base_url": base_url,
        "token": token,
        "email": email,
        "password": password,
        "tz": _arg(args, "tz") or env.get("EA_TZ") or None,
        "today": _parse_today(_arg(args, "today") or env.get("EA_TODAY")),
        "llm": _llm(env, args),
    }
