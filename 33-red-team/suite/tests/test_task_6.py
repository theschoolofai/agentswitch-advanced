"""Offline tests for task 6 (Sagar). Uses the same stub server as test_suite.

    cd 33-red-team/suite && python -m unittest discover -s tests -t .

Tool names and field names are resolved at run time; the base env in test_suite
supplies neutral fakes (test.mem.create, owner_ref, ...) so no real identifiers
appear here. The stub handler sees only the JSON-RPC method, so each test
sequences responses with a counter matching the task's call order:
seat list -> own-create -> own read-back(if needed) -> foreign-create -> foreign read-back.
"""
from harness.tasks import t06_memory_foreign_user as t06
from tests.test_suite import JSON, ME, Base, GOOD, jr, tool_text

FOREIGN = "other-seat-user"
OWN = ME["id"]


def _denied(code="permission_denied", rpc=-32001, message="Permission denied"):
    return 200, jr(error={"code": rpc, "message": message, "data": {"code": code}}), JSON


def _not_available():
    return _denied(code="tool_not_available", rpc=-32602, message="not in your tools/list")


def _seats(*user_ids):
    rows = [{"id": f"seat{i}", "seat_owner_ref": uid} for i, uid in enumerate(user_ids)]
    return 200, tool_text({"data": rows, "total": len(rows)}), JSON


def _rec(owner=None, rid="m1"):
    body = {"id": rid}
    if owner is not None:
        body["owner_ref"] = owner
    return 200, tool_text(body), JSON


class _Seq:
    """Dispatch tools/call responses in order; pass other methods straight through."""

    def __init__(self, *steps):
        self.steps, self.n = list(steps), 0

    def __call__(self, method, auth):
        if auth != f"Bearer {GOOD}":
            return 401, "{}", JSON
        if method != "tools/call":
            return 200, jr({"tools": []}), JSON
        step = self.steps[min(self.n, len(self.steps) - 1)]
        self.n += 1
        return step() if callable(step) else step


class Task6(Base):
    def test_copy_only_flag(self):
        self.assertTrue(t06.TASK["copy_only"])

    def test_seat_list_refused_passes(self):
        self.serve(_Seq(_denied()))
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("seat_list_refused", r["evidence"])

    def test_no_foreign_seat_passes_without_write(self):
        seq = _Seq(_seats(OWN, None))  # only our own user + an unassigned seat
        self.serve(seq)
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("no_other_seat_user", r["evidence"])
        self.assertEqual(seq.n, 1, "must not create when there is no target")

    def test_own_create_refused_passes(self):
        self.serve(_Seq(_seats(FOREIGN), _denied()))  # control create itself refused
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("create refused", r["evidence"])

    def test_control_unreflected_is_infrastructure(self):
        # own-create accepted, echoes no owner, and read-back does not reflect our id
        self.serve(_Seq(_seats(FOREIGN),
                        _rec(owner=None, rid="m1"),            # control create, no owner echoed
                        lambda: _rec(owner=None, rid="m1")))   # read-back: still no owner
        r = self.run_task(t06.TASK)
        self.assertInfra(r, "ownership field unconfirmed")

    def test_foreign_create_refused_passes(self):
        self.serve(_Seq(_seats(FOREIGN),
                        _rec(owner=OWN),      # control create (owner echoed, reflected)
                        _not_available()))    # foreign create refused
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("foreign create refused", r["evidence"])

    def test_foreign_bound_to_own_passes(self):
        self.serve(_Seq(_seats(FOREIGN),
                        _rec(owner=OWN),      # control
                        _rec(owner=OWN)))     # foreign create -> platform bound to caller
        r = self.run_task(t06.TASK)
        self.assertTrue(r["passed"], r["evidence"])
        self.assertIn("owner=own_user", r["evidence"])

    def test_foreign_bound_to_foreign_fails(self):
        self.serve(_Seq(_seats(FOREIGN),
                        _rec(owner=OWN),      # control
                        _rec(owner=FOREIGN))) # foreign create -> bound to the other seat
        r = self.run_task(t06.TASK)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("created_owned_by_foreign_user", r["evidence"])

    def test_foreign_readback_resolves_binding_fails(self):
        # foreign create echoes no owner; read-back shows the foreign id
        self.serve(_Seq(_seats(FOREIGN),
                        _rec(owner=OWN),              # control
                        _rec(owner=None, rid="m2"),   # foreign create, no owner echoed
                        lambda: _rec(owner=FOREIGN, rid="m2")))  # read-back
        r = self.run_task(t06.TASK)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("created_owned_by_foreign_user", r["evidence"])

    def test_seat_list_server_error_is_infrastructure(self):
        self.serve(_Seq(
            (200, jr(error={"code": -32000, "message": "boom", "data": {"code": "server_error"}}), JSON)
        ))
        r = self.run_task(t06.TASK)
        self.assertInfra(r, "list failed")

    def test_resolves_tools_from_tools_list(self):
        # No RT_* settings: names are discovered from tools/list by component.
        tools = [
            {"name": "mock.memory.create", "description": "Create a memory record",
             "inputSchema": {"properties": {"content": {}, "owner_id": {}}}},
            {"name": "mock.memory.get", "description": "Get a memory record"},
            {"name": "mock.seat.list", "description": "List seat records"},
        ]

        class Seq2:
            def __init__(self):
                self.calls = 0

            def __call__(self, method, auth):
                if auth != f"Bearer {GOOD}":
                    return 401, "{}", JSON
                if method == "tools/list":
                    return 200, jr({"tools": tools}), JSON
                self.calls += 1
                if self.calls == 1:
                    return 200, tool_text({"data": [{"id": "s0", "assigned_owner_id": FOREIGN}]}), JSON
                if self.calls == 2:
                    return 200, tool_text({"id": "m1", "owner_id": OWN}), JSON       # control
                return 200, tool_text({"id": "m2", "owner_id": FOREIGN}), JSON       # foreign -> fail

        self.serve(Seq2())
        r = self.run_task(t06.TASK, RT_MEMORY_CREATE_TOOL=None, RT_MEMORY_READ_TOOL=None,
                          RT_SEAT_LIST_TOOL=None, RT_MEMORY_USER_FIELD=None, RT_SEAT_USER_FIELD=None)
        self.assertFalse(r["passed"], r["evidence"])
        self.assertIn("created_owned_by_foreign_user", r["evidence"])
