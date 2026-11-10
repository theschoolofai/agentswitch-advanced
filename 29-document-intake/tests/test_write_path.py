"""Tests for the write path. Every network call is faked."""
import json
import unittest

from intake.mcp_client import McpClient, Settings
from intake.write_path import ACCEPT, CREATE_PARTY, EXTRACT, TEST_LABEL, ApprovedWrites, WriteRefused

COPY_URL = "https://copy-1234.example.invalid"
COPY = Settings("suryodaya", COPY_URL, "token")
COPY_ENV = {"AGENTSWITCH_RUN_ID": "run-1", "AGENTSWITCH_BASE_URL": COPY_URL}


class Platform:
    def __init__(self, labels=None):
        self.labels = labels or {}
        self.called = []

    def __call__(self, body):
        params = json.loads(body)["params"]
        name = params["name"]
        if name == "tools.describe":
            rows = [{"name": n, "risk_class": self.labels.get(n, "WRITE")} for n in params["arguments"]["names"]]
            payload = {"results": rows}
        else:
            self.called.append(name)
            payload = {"ok": True}
        text = json.dumps(payload)
        return 200, json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}})


def writes(platform=None, settings=COPY, env=COPY_ENV):
    platform = platform or Platform()
    return ApprovedWrites(McpClient(settings, transport=platform), settings, env), platform


class CopyOnlyTests(unittest.TestCase):
    def test_refused_outside_a_harness_run(self):
        with self.assertRaises(WriteRefused):
            writes(env={"AGENTSWITCH_BASE_URL": COPY_URL})

    def test_refused_on_either_live_system(self):
        for url in ("https://agentswitch.theschoolofai.in", "https://class.agentswitch.theschoolofai.in/"):
            settings = Settings("x", url, "token")
            with self.assertRaises(WriteRefused):
                writes(settings=settings, env={"AGENTSWITCH_RUN_ID": "run-1", "AGENTSWITCH_BASE_URL": url})

    def test_refused_when_the_client_is_not_from_the_harness_settings(self):
        with self.assertRaises(WriteRefused):
            writes(env={"AGENTSWITCH_RUN_ID": "run-1", "AGENTSWITCH_BASE_URL": "https://other.example.invalid"})


class CallTests(unittest.TestCase):
    def test_allowed_write_is_sent_and_recorded(self):
        path, platform = writes()
        path.call(EXTRACT, {"document_id": "d"}, approved_by="harness run run-1")
        self.assertEqual(platform.called, [EXTRACT])
        self.assertEqual(path.records[0].approved_by, "harness run run-1")

    def test_posting_and_unlisted_tools_are_refused_unsent(self):
        path, platform = writes(Platform({"Bill.submit": "POSTING"}))
        for name in ("Bill.submit", "Bill.create", "Bill.update", "PaymentMade.create"):
            with self.assertRaises(WriteRefused):
                path.call(name, {}, approved_by="someone")
        self.assertEqual(platform.called, [])

    def test_a_listed_tool_labelled_above_write_is_refused(self):
        path, platform = writes(Platform({ACCEPT: "POSTING"}))
        with self.assertRaises(WriteRefused):
            path.call(ACCEPT, {}, approved_by="someone")
        self.assertEqual(platform.called, [])

    def test_blank_approver_is_refused(self):
        path, platform = writes()
        with self.assertRaises(WriteRefused):
            path.call(EXTRACT, {}, approved_by="  ")
        self.assertEqual(platform.called, [])

    def test_party_must_carry_the_test_label(self):
        path, platform = writes()
        with self.assertRaises(WriteRefused):
            path.call(CREATE_PARTY, {"name": "Real Vendor Ltd"}, approved_by="someone")
        path.call(CREATE_PARTY, {"name": f"{TEST_LABEL} Real Vendor Ltd"}, approved_by="someone")
        self.assertEqual(platform.called, [CREATE_PARTY])

    def test_read_only_client_still_refuses_the_same_tools(self):
        path, platform = writes()
        with self.assertRaises(Exception):
            path._client.call_tool(ACCEPT, {})
        self.assertEqual(platform.called, [])


if __name__ == "__main__":
    unittest.main()
