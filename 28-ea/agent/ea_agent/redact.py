"""Keep secrets out of everything the run shows or writes.

Every loaded secret (platform tokens, passwords, model keys) is replaced by *** in stdout, stderr, the briefing file
and the --json file. Mail and model text are third-party content and could quote a secret back, so redaction runs at
the final write, not where the secret is used.

A value shorter than MIN_SECRET_LENGTH is not treated as a secret: replacing every "ab" in a briefing would garble it,
and no real token, key or course password is that short.
"""
STARS = "***"
MIN_SECRET_LENGTH = 6
# Variables whose values are secrets wherever they are set (process environment or the env file).
SECRET_VARS = ("AGENTSWITCH_TOKEN", "EA_LLM_KEY", "OPENAI_API_KEY")
SECRET_PATTERNS = (("EA_PASSWORD_", ""), ("AGENTSWITCH_", "_TOKEN"))


def is_secret_var(name: str) -> bool:
    if name in SECRET_VARS:
        return True
    return any(name.startswith(head) and name.endswith(tail) and len(name) > len(head) + len(tail)
               for head, tail in SECRET_PATTERNS)


def secrets_from_env(env: dict) -> set[str]:
    """The values of every secret variable in `env`, OPENAI_API_KEY included even when it is not used."""
    return {str(v) for k, v in (env or {}).items() if is_secret_var(str(k)) and v}


def _ordered(secrets) -> list[str]:
    usable = set()
    for s in secrets or ():
        if isinstance(s, str):
            # the stripped form too: a value read with a stray space or newline is used stripped elsewhere
            usable.update(v for v in (s, s.strip()) if len(v.strip()) >= MIN_SECRET_LENGTH)
    # Longest first, so a secret that contains another is replaced whole.
    return sorted(usable, key=len, reverse=True)


def redact(text, secrets) -> str:
    """`text` with every secret replaced by ***."""
    text = "" if text is None else str(text)
    for secret in _ordered(secrets):
        text = text.replace(secret, STARS)
    return text


def redact_value(value, secrets):
    """The same for a JSON-like value: every string (and dict key) inside it."""
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, dict):
        return {redact(str(k), secrets): redact_value(v, secrets) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v, secrets) for v in value]
    return value
