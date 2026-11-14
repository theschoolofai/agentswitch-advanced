"""Offline tests for task 7 (Sagar): tool-policy write guard + session policy-bind.

    cd 33-red-team/suite && python -m unittest discover -s tests -t .

Task 7 makes one tools/list call (the write-verb guard), then lists policies, then
creates a session and (if needed) reads it back. Tool names and the policy-binding
field come from neutral RT_* fakes in the test base env, so no real identifiers
appear here. The stub sees only the JSON-RPC method, so tools/call steps are
sequenced with a counter.
"""
from harness.tasks import t07_toolpolicy_write_blocked as t07
from tests.test_suite import JSON, Base, GOOD, jr, tool_text

# Resolution settings are passed per test so this file does not depend on the
# shared test base env (keeps the task 7/8 PR independent of the task 6 PR).
ENV = {"RT_POLICY_LIST_TOOL": "test.policy.list",
       "RT_SESSION_CREATE_TOOL": "test.session.create",
       "RT_SESSION_READ_TOOL": "test.session.get",
       "RT_SESSION_POLICY_FIELD": "policy_ref"}


def _denied(code="permission_denied", rpc=-32001):
    return 200, jr(error={"code": rpc, "message": "no", "data": {"code": code}}), JSON


def _not_available():
    return _denied(code="tool_not_available", rpc=-32602)


def _policies(*rows):
    data = [{"id": rid, "_permissions": {"write": w}, "allowed_actions": acts, "role": role}
            for (rid, w, acts, role) in rows]
    return 200, tool_text({"data": data, "total": len(data)}), JSON


def _session(sid="s1", policy=None):
    body = {"id": sid}
    if policy is not None:
        body["policy_ref"] = policy
    return 200, tool_text(body), JSON


class _H7:
    """tools/list -> self.tools; tools/call -> steps in order (last repeats)."""

    def __init__(self, tools=(), steps=()):
        self.tools, self.steps, self.n = list(tools), list(steps), 0

    def __call__(self, method, auth):
        if auth != f"Bearer {GOOD}":
            return 401, "{}", JSON
        if method != "tools/call":
            return 200, jr({"tools": self.tools}), JSON
        step = self.steps[min(self.n, len(self.steps) - 1)]
        self.n += 1
        return step() if callable(step) else step


# A single foreign policy, read-only, with some scope.
FOREIGN_POLICY = ("p1", False, ["read", "list"], "viewer")


class Task7(Base):
    def test_copy_only_flag(self):
        self.assertTrue(t07.TASK["copy_only"])

    def test_guard_fails_when_write_verb_exposed(self):
        self.serve(_H7(tools=[{"name": "mock.tool_policy.update", "description": "update policy"}]))
        r = self.run_task(t07.TASK, **ENV)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("tool-policy write verb is now exposed", r["evidence"])

    def test_guard_fails_when_policy_row_writable(self):
        self.serve(_H7(steps=[_policies(("p1", True, [], "admin"))]))
        r = self.run_task(t07.TASK, **ENV)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("write:true", r["evidence"])

    def test_bind_refused_passes(self):
        self.serve(_H7(steps=[_policies(FOREIGN_POLICY), _denied()]))
        r = self.run_task(t07.TASK, **ENV)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("bind refused", r["evidence"])

    def test_bind_not_available_passes(self):
        self.serve(_H7(steps=[_policies(FOREIGN_POLICY), _not_available()]))
        r = self.run_task(t07.TASK, **ENV)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("bind refused", r["evidence"])

    def test_foreign_bind_takes_is_finding_fail(self):
        self.serve(_H7(steps=[_policies(FOREIGN_POLICY),
                              _session(policy="p1")]))   # create echoes the foreign policy
        r = self.run_task(t07.TASK, **ENV)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("FINDING: session bound to foreign policy", r["evidence"])
        self.assertIn("allowed_actions=2", r["evidence"])   # counts only, no contents

    def test_bind_ignored_passes(self):
        self.serve(_H7(steps=[_policies(FOREIGN_POLICY),
                              _session(policy=None),       # create: no policy echoed
                              _session(policy=None)]))     # read-back: not bound
        r = self.run_task(t07.TASK, **ENV)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("did not take", r["evidence"])

    def test_readback_resolves_foreign_bind_fail(self):
        self.serve(_H7(steps=[_policies(FOREIGN_POLICY),
                              _session(sid="s2", policy=None),      # create: no echo
                              _session(sid="s2", policy="p1")]))    # read-back: bound
        r = self.run_task(t07.TASK, **ENV)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("FINDING", r["evidence"])

    def test_no_policy_target_passes(self):
        self.serve(_H7(steps=[_policies()]))   # empty policy list
        r = self.run_task(t07.TASK, **ENV)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("no foreign policy", r["evidence"])

    def test_policy_list_server_error_is_infrastructure(self):
        self.serve(_H7(steps=[(200, jr(error={"code": -32000, "message": "boom",
                                               "data": {"code": "server_error"}}), JSON)]))
        r = self.run_task(t07.TASK, **ENV)
        self.assertInfra(r, "list failed")
