"""Minimal read-only client for the AgentSwitch REST API.

Read-only on purpose. This seat proposes and drafts; a person approves
anything that changes a record. Nothing here issues a POST, PUT or DELETE,
so the calendar cannot alter the data it reports on even by accident.

Exactly one request in this file can send a POST: the login, at
LOGIN_PATH. Every other request is a GET, and `_send` raises `Refused`
if anything tries to attach a body to a non-login path. There is no
other HTTP anywhere in the package.

Credentials come from the environment and never from this repository.
Set AS_EMAIL and AS_PASSWORD_SURYODAYA / AS_PASSWORD_KEYSTONE, or point
AS_ENV_FILE at a file outside the repo holding them.
"""
import json
import os
import urllib.error
import urllib.request

HOSTS = {
    "suryodaya": "https://agentswitch.theschoolofai.in",
    "keystone": "https://class.agentswitch.theschoolofai.in",
}

PAGE = 500
HARD_CAP = 20000

# The ONLY path this client may POST to. Everything else is GET.
#
# The seat rule is that the agent proposes and a person approves anything
# that changes a record, so this tool must not be able to write at all.
# Leaving that to call-site discipline is not good enough: _send issues a
# POST whenever it is handed a payload, so one future caller passing a body
# by mistake turns a read-only tool into a writing one, silently.
#
# The guard in _send refuses that. A reviewer can confirm the whole
# read-only claim by reading one function rather than auditing every call
# site now and forever after.
LOGIN_PATH = "/api/auth/login"


class Refused(RuntimeError):
    """A write was attempted. This client cannot write, by construction."""


class Unreachable(RuntimeError):
    """The platform did not answer. Distinct from 'answered, and said no'."""


def load_credentials():
    """Environment first, then AS_ENV_FILE if one is named."""
    env = dict(os.environ)
    path = env.get("AS_ENV_FILE")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


class Client:
    def __init__(self, instance, env=None):
        if instance not in HOSTS:
            raise ValueError("unknown instance %r" % instance)
        self.instance = instance
        self.base = HOSTS[instance]
        self.env = env or load_credentials()
        self._token = None

    def login(self):
        if self._token:
            return self._token
        email = self.env.get("AS_EMAIL_32") or self.env.get("AS_EMAIL")
        key = "AS_PASSWORD_32_%s" % self.instance.upper()
        password = self.env.get(key) or self.env.get(
            "AS_PASSWORD_%s" % self.instance.upper())
        if not email or not password:
            raise Unreachable(
                "no credentials for %s: set AS_EMAIL_32 and %s in the "
                "environment, or point AS_ENV_FILE at a file outside this "
                "repository that holds them" % (self.instance, key))
        status, body = self._send("/api/auth/login",
                                  {"email": email, "password": password})
        if status != 200:
            raise Unreachable("login to %s returned HTTP %s" % (self.instance, status))
        self._token = json.loads(body).get("token")
        if not self._token:
            raise Unreachable("login to %s returned no token" % self.instance)
        return self._token

    def list(self, entity):
        """Every row of an entity, paged.

        403 returns [] - "this seat may not read it" is a real answer.
        Any other non-200 raises. A caller must never be unable to tell an
        empty table from a failed request; reading one as the other is how
        a broken run comes to look like a clean one.
        """
        self.login()
        rows, offset = [], 0
        while True:
            status, body = self._send(
                "/api/%s?limit=%d&offset=%d" % (entity, PAGE, offset), None)
            if status == 403:
                return []
            if status != 200:
                raise Unreachable(
                    "GET /api/%s on %s returned HTTP %s, so this run cannot "
                    "see the rows it reports on" % (entity, self.instance, status))
            data = json.loads(body)
            page = data.get("data") or []
            rows.extend(page)
            total = data.get("total")
            offset += len(page)
            if not page or total is None or offset >= int(total):
                break
            if offset >= HARD_CAP:
                raise Unreachable(
                    "GET /api/%s has served %d rows and reports %s; refusing "
                    "to page further rather than loop" % (entity, offset, total))
        return rows

    def _send(self, path, payload):
        if payload is not None and path != LOGIN_PATH:
            raise Refused(
                "refusing to POST to %s. This client is read-only: the only "
                "request that may carry a body is the login at %s. If a "
                "change to a record is genuinely needed, a person makes it - "
                "that is the seat rule, and this guard is what makes the "
                "read-only claim checkable rather than merely intended."
                % (path, LOGIN_PATH))
        url = self.base + path
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data,
                                     method="POST" if data else "GET")
        req.add_header("Content-Type", "application/json")
        if self._token:
            req.add_header("Authorization", "Bearer " + self._token)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")
        except Exception as exc:
            raise Unreachable("%s %s: %s" % (self.instance, path, exc))
