"""Token cache and login (D11): one login per system per run, a cached token checked first, nothing secret printed."""

import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

from ea_briefing import auth
from fakes import make_mcp_error

NOW = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)
BASE = "https://class.agentswitch.theschoolofai.in"
PASSWORD = "pw-Very-Secret-991"
TOKEN = "tok-cached-SECRET-123"
NEW_TOKEN = "tok-fresh-SECRET-456"
ME = {"id": "u1", "email": "me@example.test", "name": "Nora"}


class Client:
    def __init__(self, token, valid):
        self.token = token
        self.valid = valid
        self.me_calls = 0

    def me(self):
        self.me_calls += 1
        if self.token not in self.valid:
            raise make_mcp_error("auth", "token rejected (HTTP 401); log in again", 401)
        return dict(ME)


class World:
    def __init__(self, valid=(NEW_TOKEN,), login_result=NEW_TOKEN):
        self.valid = set(valid)
        self.login_calls = []
        self.clients = []
        self.login_result = login_result

    def factory(self, system, base_url, token):
        c = Client(token, self.valid)
        self.clients.append(c)
        return c

    def login(self, base_url, email, password):
        self.login_calls.append((base_url, email))
        if isinstance(self.login_result, Exception):
            raise self.login_result
        return self.login_result


def connect(world, cache, env=None, explicit=False, tty=False, prompts=None, logs=None):
    prompts = prompts if prompts is not None else []
    logs = logs if logs is not None else []
    return auth.connect("keystone", BASE, env if env is not None else {"EA_EMAIL": "me@example.test"},
                        cache_file=str(cache), explicit=explicit, stdin_isatty=tty,
                        input_fn=lambda p: prompts.append(p) or "me@example.test",
                        getpass_fn=lambda p: prompts.append(p) or PASSWORD,
                        client_factory=world.factory, login_fn=world.login, now=NOW, log=logs.append)


def seed(cache, token=TOKEN, age=timedelta(days=1), base_url=BASE, email="me@example.test"):
    auth.save(str(cache), "keystone", token, base_url, email, NOW - age)


@pytest.fixture
def cache(tmp_path):
    return tmp_path / "cfg" / "ea-briefing" / "tokens.json"


def test_cache_path_precedence(tmp_path):
    assert auth.cache_path({"EA_TOKEN_CACHE": "/x/t.json", "XDG_CONFIG_HOME": "/y"}) == "/x/t.json"
    assert auth.cache_path({"XDG_CONFIG_HOME": "/y"}) == "/y/ea-briefing/tokens.json"
    assert auth.cache_path({"HOME": "/h"}) == "/h/.config/ea-briefing/tokens.json"


def test_conftest_keeps_real_home_out(tmp_path):
    assert str(tmp_path) in os.environ["HOME"] and str(tmp_path) in os.environ["XDG_CONFIG_HOME"]
    assert auth.cache_path(dict(os.environ)).startswith(str(tmp_path))


def test_save_is_private_and_atomic(cache):
    seed(cache)
    assert stat.S_IMODE(os.stat(cache.parent).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(cache).st_mode) == 0o600
    data = json.loads(cache.read_text())
    assert set(data["keystone"]) == {"token", "base_url", "email", "saved_at"}
    assert data["keystone"]["saved_at"] == (NOW - timedelta(days=1)).isoformat()
    assert sorted(os.listdir(cache.parent)) == ["tokens.json"]  # no temp file left behind


def test_save_keeps_other_systems(cache):
    seed(cache)
    auth.save(str(cache), "suryodaya", "other", "https://s.example", "me@example.test", NOW)
    assert set(json.loads(cache.read_text())) == {"keystone", "suryodaya"}


@pytest.mark.parametrize("age,base,email,fresh", [
    (timedelta(days=6, hours=23), BASE, "me@example.test", True),
    (timedelta(days=7), BASE, "me@example.test", False),
    (timedelta(days=1), "https://other.example", "me@example.test", False),
    (timedelta(days=1), BASE, "someone@else.test", False),
    (timedelta(days=-1), BASE, "me@example.test", False),
])
def test_fresh_entry(cache, age, base, email, fresh):
    seed(cache, age=age, base_url=base, email=email)
    entry = auth.fresh_entry(auth.load(str(cache)), "keystone", BASE, "me@example.test", NOW)
    assert (entry is not None) is fresh


def test_broken_cache_reads_as_empty(cache):
    cache.parent.mkdir(parents=True)
    cache.write_text("{not json")
    assert auth.load(str(cache)) == {}


def test_valid_cached_token_means_no_login(cache):
    seed(cache)
    w = World(valid={TOKEN})
    client, me, how = connect(w, cache, env={"EA_EMAIL": "me@example.test", "EA_PASSWORD_KEYSTONE": PASSWORD})
    assert how == "cached token" and me["id"] == "u1"
    assert w.login_calls == []
    assert client.token == TOKEN and client.me_calls == 1


def test_401_on_cached_token_means_exactly_one_login(cache):
    seed(cache)
    w = World(valid={NEW_TOKEN})
    logs = []
    client, _, how = connect(w, cache, env={"EA_EMAIL": "me@example.test", "EA_PASSWORD_KEYSTONE": PASSWORD},
                             logs=logs)
    assert how == "login" and client.token == NEW_TOKEN
    assert len(w.login_calls) == 1
    assert json.loads(cache.read_text())["keystone"]["token"] == NEW_TOKEN
    assert all(TOKEN not in m and NEW_TOKEN not in m and PASSWORD not in m for m in logs)


def test_401_on_cached_token_without_password_no_login(cache):
    seed(cache)
    w = World(valid=set())
    with pytest.raises(auth.AuthError) as exc:
        connect(w, cache)
    assert w.login_calls == []
    assert "EA_PASSWORD_KEYSTONE" in str(exc.value)
    assert "keystone" not in json.loads(cache.read_text())  # the dead token is dropped


def test_expired_cache_is_not_even_tried(cache):
    seed(cache, age=timedelta(days=8))
    w = World()
    connect(w, cache, env={"EA_EMAIL": "me@example.test", "EA_PASSWORD_KEYSTONE": PASSWORD})
    assert [c.token for c in w.clients] == [NEW_TOKEN]


def test_failed_login_is_not_retried_and_saves_nothing(cache):
    w = World(login_result=make_mcp_error("auth", "login failed: HTTP 401; not retried", 401))
    with pytest.raises(auth.AuthError) as exc:
        connect(w, cache, env={"EA_EMAIL": "me@example.test", "EA_PASSWORD_KEYSTONE": PASSWORD})
    assert len(w.login_calls) == 1
    assert PASSWORD not in str(exc.value)
    assert not cache.exists()


def test_failed_cached_token_then_failed_login_is_one_login(cache):
    seed(cache)
    w = World(valid=set(), login_result=make_mcp_error("auth", "login failed: HTTP 401", 401))
    with pytest.raises(auth.AuthError):
        connect(w, cache, env={"EA_EMAIL": "me@example.test", "EA_PASSWORD_KEYSTONE": PASSWORD})
    assert len(w.login_calls) == 1


def test_prompt_only_with_tty_and_named_system(cache):
    w = World()
    prompts = []
    with pytest.raises(auth.AuthError):
        connect(w, cache, env={"EA_EMAIL": "me@example.test"}, explicit=False, tty=True, prompts=prompts)
    with pytest.raises(auth.AuthError):
        connect(w, cache, env={"EA_EMAIL": "me@example.test"}, explicit=True, tty=False, prompts=prompts)
    assert prompts == [] and w.login_calls == []
    connect(w, cache, env={}, explicit=True, tty=True, prompts=prompts)
    assert len(prompts) == 2 and "Password" in prompts[1]
    assert len(w.login_calls) == 1
    stored = cache.read_text()
    assert PASSWORD not in stored  # the password is never stored, only the token


def test_platform_token_never_touches_cache_helpers(cache):
    # connect() is not used in platform mode (see test_runner); delete() of a missing file is harmless
    assert auth.delete(str(cache)) is False
    seed(cache)
    assert auth.delete(str(cache)) is True and not cache.exists()


def test_existing_cache_folder_is_tightened(tmp_path):
    folder = tmp_path / "xdg" / "ea-briefing"
    folder.mkdir(parents=True)
    os.chmod(folder, 0o755)
    auth.save(str(folder / "tokens.json"), "keystone", TOKEN, BASE, "me@example.test", NOW)
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o700


def test_custom_cache_folder_left_alone(tmp_path):
    # EA_TOKEN_CACHE may point into a shared folder (even $HOME); only the file is made private there
    folder = tmp_path / "shared"
    folder.mkdir()
    os.chmod(folder, 0o755)
    auth.save(str(folder / "t.json"), "keystone", TOKEN, BASE, "me@example.test", NOW)
    assert stat.S_IMODE(os.stat(folder).st_mode) == 0o755
    assert stat.S_IMODE(os.stat(folder / "t.json").st_mode) == 0o600


def test_parallel_saves_keep_every_system(cache):
    from concurrent.futures import ThreadPoolExecutor
    systems = [f"s{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda s: auth.save(str(cache), s, TOKEN, BASE, "me@example.test", NOW), systems))
    assert set(json.loads(cache.read_text())) == set(systems)
