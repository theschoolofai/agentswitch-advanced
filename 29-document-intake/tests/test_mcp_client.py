"""Tests for the client and write guard. Every network call is faked."""
import http.client
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from intake.mcp_client import (
    AuthError,
    ConfigError,
    GuardRefused,
    McpClient,
    Settings,
    ToolError,
    TransportError,
    _http_transport,
    load_settings,
)

FAKE_TOKEN = "fake-token-value"
SETTINGS = Settings("suryodaya", "https://example.invalid", FAKE_TOKEN)


def tool_reply(payload, is_error=False):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    result = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})


class FakePlatform:
    """Answers tools.describe from a table and records every call it receives."""

    def __init__(self, risk_classes=None, reply=None, status=200):
        self.risk_classes = risk_classes or {}
        self.reply = reply if reply is not None else tool_reply({"ok": True})
        self.status = status
        self.described = []
        self.called = []

    def __call__(self, body):
        params = json.loads(body)["params"]
        if params["name"] == "tools.describe":
            self.described.extend(params["arguments"]["names"])
            rows = [
                {"name": name, "risk_class": self.risk_classes[name]}
                for name in params["arguments"]["names"]
                if name in self.risk_classes
            ]
            return 200, tool_reply({"results": rows})
        self.called.append(params["name"])
        return self.status, self.reply


class GuardTests(unittest.TestCase):
    def assert_refused(self, platform, name):
        client = McpClient(SETTINGS, transport=platform)
        with self.assertRaises(GuardRefused):
            client.call_tool(name, {})
        self.assertEqual(platform.called, [], "a refused call must never be sent")

    def test_read_tool_is_sent(self):
        platform = FakePlatform({"Bill.list": "READ"})
        McpClient(SETTINGS, transport=platform).call_tool("Bill.list")
        self.assertEqual(platform.called, ["Bill.list"])

    def test_risk_class_case_does_not_matter(self):
        platform = FakePlatform({"Bill.list": "read"})
        McpClient(SETTINGS, transport=platform).call_tool("Bill.list")
        self.assertEqual(platform.called, ["Bill.list"])

    def test_posting_tools_are_refused(self):
        for name in ("Bill.submit", "Bill.open"):
            self.assert_refused(FakePlatform({name: "POSTING"}), name)

    def test_write_tools_are_refused(self):
        for name in (
            "Bill.create",
            "Bill.update",
            "Bill.approval.submit",
            "AcctDocument.create",
            "endpoint.accounting.bill_intake.extract",
            "endpoint.accounting.bill_intake.accept",
            "endpoint.accounting.bill_intake.reject",
        ):
            self.assert_refused(FakePlatform({name: "WRITE"}), name)

    def test_read_name_is_not_enough(self):
        self.assert_refused(FakePlatform({"Bill.list": "WRITE"}), "Bill.list")

    def test_unknown_risk_class_is_refused(self):
        self.assert_refused(FakePlatform({"Odd.tool": "SOMETHING_NEW"}), "Odd.tool")

    def test_tool_the_platform_does_not_describe_is_refused(self):
        self.assert_refused(FakePlatform(), "No.such_tool")

    def test_failed_risk_lookup_is_refused(self):
        calls = []

        def failing(body):
            calls.append(json.loads(body)["params"]["name"])
            reply = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "down"}}
            return 500, json.dumps(reply)

        client = McpClient(SETTINGS, transport=failing)
        with self.assertRaises(GuardRefused):
            client.call_tool("Bill.list")
        self.assertEqual(calls, ["tools.describe"])

    def test_each_tool_is_looked_up_once(self):
        platform = FakePlatform({"Bill.list": "READ"})
        client = McpClient(SETTINGS, transport=platform)
        client.call_tool("Bill.list")
        client.call_tool("Bill.list")
        self.assertEqual(platform.described, ["Bill.list"])
        self.assertEqual(platform.called, ["Bill.list", "Bill.list"])


class ReplyTests(unittest.TestCase):
    def call(self, reply, status=200):
        platform = FakePlatform({"Bill.list": "READ"}, reply=reply, status=status)
        return McpClient(SETTINGS, transport=platform).call_tool("Bill.list")

    def test_json_content_is_decoded(self):
        self.assertEqual(self.call(tool_reply({"total": 3})), {"total": 3})

    def test_event_stream_reply_is_decoded(self):
        self.assertEqual(self.call("event: message\ndata: " + tool_reply({"total": 3})), {"total": 3})

    def test_event_data_on_several_lines_is_joined(self):
        pretty = json.dumps(json.loads(tool_reply({"total": 3})), indent=1)
        stream = "event: message\n" + "".join(f"data: {line}\n" for line in pretty.splitlines()) + "\n"
        self.assertEqual(self.call(stream), {"total": 3})

    def test_last_event_is_used(self):
        stream = f"data: {tool_reply({'total': 1})}\n\ndata: {tool_reply({'total': 2})}\n\n"
        self.assertEqual(self.call(stream), {"total": 2})

    def test_event_stream_with_no_data_raises(self):
        with self.assertRaises(TransportError):
            self.call("event: message\n\n")

    def test_platform_error_keeps_its_code(self):
        reply = json.dumps({"error": {"code": -32004, "message": "Bill not found.",
                                      "data": {"code": "not_found"}}})
        with self.assertRaises(ToolError) as caught:
            self.call(reply)
        self.assertEqual(caught.exception.code, "not_found")

    def test_tool_marked_as_error_raises(self):
        with self.assertRaises(ToolError):
            self.call(tool_reply("refused", is_error=True))

    def test_reply_that_is_not_json_raises(self):
        with self.assertRaises(TransportError):
            self.call("<html>bad gateway</html>", status=502)


class TransportTests(unittest.TestCase):
    def test_connection_failures_become_transport_errors(self):
        failures = (
            urllib.error.URLError("no route"),
            TimeoutError("timed out"),
            ConnectionResetError("reset"),
            http.client.IncompleteRead(b"partial"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with mock.patch("urllib.request.urlopen", side_effect=failure):
                    with self.assertRaises(TransportError) as caught:
                        _http_transport(SETTINGS)(b"{}")
                self.assertNotIn(FAKE_TOKEN, str(caught.exception))

    def test_connection_dropped_while_reading_becomes_a_transport_error(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = http.client.IncompleteRead(b"partial")
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaises(TransportError):
                _http_transport(SETTINGS)(b"{}")

    def test_http_error_status_is_returned_for_the_client_to_read(self):
        error = urllib.error.HTTPError("https://example.invalid", 401, "no", None, None)
        with mock.patch.object(error, "read", return_value=b"{}"):
            with mock.patch("urllib.request.urlopen", side_effect=error):
                self.assertEqual(_http_transport(SETTINGS)(b"{}"), (401, "{}"))


class AuthTests(unittest.TestCase):
    def test_rejected_token_stops_after_one_call_and_hides_the_token(self):
        bodies = []

        def rejecting(body):
            bodies.append(body)
            return 401, "{}"

        client = McpClient(SETTINGS, transport=rejecting)
        with self.assertRaises(AuthError) as caught:
            client.call_tool("Bill.list")
        self.assertEqual(len(bodies), 1)
        self.assertNotIn(FAKE_TOKEN, str(caught.exception))

    def test_settings_repr_hides_the_token(self):
        self.assertNotIn(FAKE_TOKEN, repr(SETTINGS))


class SettingsTests(unittest.TestCase):
    NO_FILE = Path("does-not-exist.env")

    def test_harness_variables_win(self):
        env = {"AGENTSWITCH_TOKEN": "t", "AGENTSWITCH_BASE_URL": "https://copy.invalid",
               "AGENTSWITCH_INSTANCE": "keystone", "AGENTSWITCH_KEYSTONE_TOKEN": "other"}
        settings = load_settings(env=env, env_file=self.NO_FILE)
        self.assertEqual((settings.system, settings.base_url, settings.token),
                         ("keystone", "https://copy.invalid", "t"))

    def test_local_token_comes_from_the_environment(self):
        settings = load_settings("keystone", {"AGENTSWITCH_KEYSTONE_TOKEN": "t"}, self.NO_FILE)
        self.assertEqual(settings.token, "t")
        self.assertIn("class.", settings.base_url)

    def test_local_token_comes_from_the_env_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("# comment\nAGENTSWITCH_SURYODAYA_TOKEN=abc=def\n", encoding="utf-8")
            self.assertEqual(load_settings("suryodaya", {}, path).token, "abc=def")

    def test_missing_token_is_a_config_error(self):
        with self.assertRaises(ConfigError):
            load_settings("suryodaya", {}, self.NO_FILE)

    def test_unknown_system_is_a_config_error(self):
        with self.assertRaises(ConfigError):
            load_settings("elsewhere", {}, self.NO_FILE)


if __name__ == "__main__":
    unittest.main()
