"""Offline tests for task 8 (Sagar): persona write regression guard.

    cd 33-red-team/suite && python -m unittest discover -s tests -t .

The stub handler sees the JSON-RPC method; task 8 makes one tools/list call (the
write-verb check) and then lists personas. Tool names are resolved from neutral
RT_* fakes in the test base env, so no real identifiers appear here.
"""
from harness.tasks import t08_persona_write_blocked as t08
from tests.test_suite import JSON, Base, GOOD, jr, tool_text

# Resolution settings are passed per test so this file does not depend on the
# shared test base env (keeps the task 7/8 PR independent of the task 6 PR).
ENV = {"RT_PERSONA_LIST_TOOL": "test.persona.list"}


def _denied(code="permission_denied", rpc=-32001):
    return 200, jr(error={"code": rpc, "message": "no", "data": {"code": code}}), JSON


def _personas(*perms):
    rows = [{"id": f"p{i}", "_permissions": {"write": w}} for i, w in enumerate(perms)]
    return 200, tool_text({"data": rows, "total": len(rows)}), JSON


class _H:
    """tools/list returns `tools`; tools/call returns `listed` (or refused)."""

    def __init__(self, tools=(), listed=None, list_refused=False):
        self.tools, self.listed, self.list_refused = list(tools), listed, list_refused

    def __call__(self, method, auth):
        if auth != f"Bearer {GOOD}":
            return 401, "{}", JSON
        if method != "tools/call":
            return 200, jr({"tools": self.tools}), JSON
        if self.list_refused:
            return _denied()
        return self.listed if self.listed is not None else _personas()


class Task8(Base):
    def test_not_copy_only(self):
        self.assertFalse(t08.TASK["copy_only"])

    def test_passes_when_no_write_verb_and_readonly_rows(self):
        self.serve(_H(tools=[{"name": "x.persona.list", "description": "list"},
                             {"name": "x.persona.get", "description": "get"}],
                      listed=_personas(False, False)))
        r = self.run_task(t08.TASK, **ENV)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("write:false", r["evidence"])

    def test_fails_when_write_verb_exposed(self):
        self.serve(_H(tools=[{"name": "x.persona.update", "description": "update a persona"}]))
        r = self.run_task(t08.TASK, **ENV)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("write verb is now exposed", r["evidence"])

    def test_fails_when_a_row_is_writable(self):
        self.serve(_H(listed=_personas(False, True, False)))
        r = self.run_task(t08.TASK, **ENV)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("write:true", r["evidence"])

    def test_list_refused_passes(self):
        self.serve(_H(list_refused=True))
        r = self.run_task(t08.TASK, **ENV)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("list refused", r["evidence"])

    def test_empty_list_passes(self):
        self.serve(_H(listed=_personas()))
        r = self.run_task(t08.TASK, **ENV)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("0 rows", r["evidence"])

    def test_resolves_list_tool_from_tools_list(self):
        self.serve(_H(tools=[{"name": "mock.persona.list", "description": "List personas"}],
                      listed=_personas(False)))
        r = self.run_task(t08.TASK, RT_PERSONA_LIST_TOOL=None)
        self.assertTrue(r["passed"], r["evidence"])
