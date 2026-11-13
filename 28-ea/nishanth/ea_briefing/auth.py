"""Login and a per-user token cache, so a daily run does not need a stored password.

The platform's login reply has no expiry field; course tokens last 7 days, so a cached token is used only while it is
younger than that and `/api/auth/me` still accepts it. Ten wrong passwords lock the account, so each system gets at
most one login attempt per run, whatever happens.
"""
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone

from .mcp import McpClient, McpError

TOKEN_MAX_AGE = timedelta(days=7)
CACHE_DIR_NAME = "ea-briefing"
# Systems log in on parallel threads; each save is read-modify-write of one file, so writes take turns.
_CACHE_LOCK = threading.Lock()


class AuthError(Exception):
    """A system could not be logged in to; the message is shown in that system's block and holds no secrets."""


def cache_path(environ: dict) -> str:
    if environ.get("EA_TOKEN_CACHE"):
        return environ["EA_TOKEN_CACHE"]
    base = environ.get("XDG_CONFIG_HOME") or os.path.join(environ.get("HOME") or os.path.expanduser("~"), ".config")
    return os.path.join(base, "ea-briefing", "tokens.json")


def load(path: str) -> dict:
    """The cache contents, or {} when it is missing or unreadable (a broken cache only costs a login)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path: str, data: dict) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder, mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)  # makedirs is subject to the umask
    elif os.path.basename(folder) == CACHE_DIR_NAME and os.stat(folder).st_uid == os.getuid():
        # Our own folder made wider by hand or an old version: tighten it. A folder chosen with EA_TOKEN_CACHE
        # (it could be $HOME) is left as it is; the file itself is still 0600.
        os.chmod(folder, 0o700)
    # mkstemp creates the file 0600; os.replace makes the swap atomic, so a crash never leaves half a cache.
    fd, tmp = tempfile.mkstemp(prefix=".tokens-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(path: str, system: str, token: str, base_url: str, email: str | None, now: datetime | None = None) -> None:
    with _CACHE_LOCK:
        data = load(path)
        data[system] = {"token": token, "base_url": base_url, "email": email,
                        "saved_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()}
        _write(path, data)


def forget(path: str, system: str) -> None:
    with _CACHE_LOCK:
        data = load(path)
        if system in data:
            del data[system]
            _write(path, data)


def delete(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False


def fresh_entry(cache: dict, system: str, base_url: str, email: str | None, now: datetime) -> dict | None:
    """The cached entry for `system` if it is for the same server and account and younger than 7 days."""
    entry = cache.get(system)
    if not isinstance(entry, dict) or not isinstance(entry.get("token"), str) or not entry["token"]:
        return None
    if str(entry.get("base_url") or "").rstrip("/") != base_url.rstrip("/"):
        return None
    if email and str(entry.get("email") or "").lower() != email.lower():
        return None
    try:
        saved = datetime.fromisoformat(str(entry.get("saved_at")))
    except ValueError:
        return None
    if saved.tzinfo is None:
        saved = saved.replace(tzinfo=timezone.utc)
    age = now - saved
    return entry if timedelta(0) <= age < TOKEN_MAX_AGE else None


def default_login(base_url: str, email: str, password: str) -> str:
    return McpClient.login(base_url, email, password)._token


def default_client(system: str, base_url: str, token: str):
    return McpClient(base_url, token)


def _reason(exc: Exception) -> str:
    if isinstance(exc, McpError):
        return f"{exc.kind}: {exc.message}"
    return f"{type(exc).__name__}: {exc}"[:200]


def connect(system: str, base_url: str, env: dict, *, cache_file: str, explicit: bool, stdin_isatty: bool,
            input_fn, getpass_fn, client_factory=None, login_fn=None, now: datetime | None = None,
            log=print) -> tuple:
    """(client, me, how) where `how` is "cached token" or "login". Raises AuthError with a printable reason.

    Order: cached token (checked with /api/auth/me) -> one login with EA_PASSWORD_<SYSTEM> or a prompt. The login
    runs at most once, and only when a password is actually available."""
    client_factory = client_factory or default_client
    login_fn = login_fn or default_login
    now = now or datetime.now(timezone.utc)
    email = env.get("EA_EMAIL") or None
    entry = fresh_entry(load(cache_file), system, base_url, email, now)
    if entry is not None:
        try:
            client = client_factory(system, base_url, entry["token"])
            me = client.me()
            if not isinstance(me, dict):
                raise McpError(kind="http", message="/api/auth/me: unexpected body")
            return client, me, "cached token"
        except Exception as exc:
            if isinstance(exc, McpError) and exc.kind == "auth":
                try:
                    forget(cache_file, system)
                except OSError:
                    pass
            log(f"note: {system}: saved login no longer works ({_reason(exc)}); logging in again")
        email = email or entry.get("email")
    interactive = stdin_isatty and explicit
    if not email and interactive:
        email = (input_fn(f"Email for {system}: ") or "").strip() or None
    password = env.get(f"EA_PASSWORD_{system.upper()}") or None
    if not password and email and interactive:
        password = getpass_fn(f"Password for {email} on {system} (not stored): ") or None
    if not email or not password:
        raise AuthError(f"no saved login and no password (set EA_EMAIL and EA_PASSWORD_{system.upper()}, "
                        f"or run with --system {system} in a terminal)")
    try:
        token = login_fn(base_url, email, password)
    except Exception as exc:
        raise AuthError(_reason(exc)) from None
    finally:
        password = None
    try:
        client = client_factory(system, base_url, token)
        me = client.me()
    except Exception as exc:
        raise AuthError(f"logged in but /api/auth/me failed: {_reason(exc)}") from None
    try:
        save(cache_file, system, token, base_url, email, now)
    except OSError as exc:
        log(f"note: could not save the login for next time ({type(exc).__name__})")
    return client, me, "login"
