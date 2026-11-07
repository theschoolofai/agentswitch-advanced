import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
for _p in (ROOT, TESTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ENV_PREFIXES = ("AGENTSWITCH_", "OPENAI_", "EA_")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    # A developer's shell (or a real ./.env next to the cwd) must never leak into a test.
    for key in list(os.environ):
        if key.startswith(ENV_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(time, "sleep", lambda *_a, **_k: None)
    yield
