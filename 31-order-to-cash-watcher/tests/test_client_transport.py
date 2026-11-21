"""Bug hunt D1-D3 (19 Nov): retries, one-line errors and robust response parsing.

The network is faked at `Client._post` and sleeping at `Client._sleep`; nothing is sent anywhere.
"""
import contextlib
import io
import json
import socket
import unittest
import urllib.error
from unittest import mock

from o2c import client as C
from o2c.client import Client, McpError, PlatformUnavailable, tool_result

TOKEN = "tok-SECRET-123"


def ok(result, request_id=1):
    return 200, "application/json", json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


def http_error(code, retry_after=None):
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return urllib.error.HTTPError("http://x/api/mcp", code, "reason", headers, None)


PAGE = {"structuredContent": {"data": [{"id": "a"}], "total": 1}}


class Scripted(Client):
    """A client whose transport replays a script: each item is a response tuple or an exception."""

    def __init__(self, script):
        super().__init__("http://x", TOKEN)
        self.script, self.posts, self.slept = list(script), 0, []
        self._sleep = self.slept.append

    def _post(self, body):
        self.posts += 1
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        status, ctype, raw = step
        # Answer with the id of the request actually sent, unless the script pins one.
        return status, ctype, raw.replace('"id": 1,', f'"id": {json.loads(body)["id"]},') if '"id": 1,' in raw else raw


class Retries(unittest.TestCase):
    """D1: reads are retried after transient failures, with backoff; writes never are."""

    def test_transient_status_is_retried_then_succeeds(self):
        for code in (429, 500, 502, 503, 504):
            with self.subTest(code=code):
                c = Scripted([http_error(code), http_error(code), ok(PAGE)])
                self.assertEqual(c.call("SalesOrder.list"), PAGE["structuredContent"])
                self.assertEqual((c.posts, c.slept), (3, [1, 2]))

    def test_gives_up_after_four_tries_with_a_short_reason(self):
        c = Scripted([http_error(503)] * 4)
        with self.assertRaises(PlatformUnavailable) as e:
            c.call("Invoice.list")
        self.assertEqual(str(e.exception), "tools/call Invoice.list: HTTP 503 reason after 4 tries")
        self.assertEqual((c.posts, c.slept), (4, [1, 2, 4]))

    def test_retry_after_is_honoured_and_capped(self):
        c = Scripted([http_error(429, retry_after=7), http_error(429, retry_after=500), ok(PAGE)])
        c.call("Payment.list")
        self.assertEqual(c.slept, [7, C.RETRY_AFTER_MAX])

    def test_connection_errors_and_timeouts_are_retried(self):
        for exc in (urllib.error.URLError(ConnectionRefusedError(111, "refused")), ConnectionResetError(),
                    socket.timeout("timed out"), TimeoutError()):
            with self.subTest(exc=type(exc).__name__):
                c = Scripted([exc, ok(PAGE)])
                self.assertEqual(c.call("Party.list"), PAGE["structuredContent"])
                self.assertEqual(c.posts, 2)

    def test_timeout_reason_is_plain(self):
        c = Scripted([socket.timeout("timed out")] * 4)
        with self.assertRaisesRegex(PlatformUnavailable, r"^tools/call Party.list: no answer before the timeout after 4 tries$"):
            c.call("Party.list")

    def test_client_errors_are_not_retried(self):
        c = Scripted([http_error(400)])
        with self.assertRaisesRegex(McpError, "HTTP 400"):
            c.call("SalesOrder.list")
        self.assertEqual(c.posts, 1)

    def test_rejected_token_is_not_retried_and_never_printed(self):
        for code in (401, 403):
            with self.subTest(code=code):
                c = Scripted([http_error(code)])
                with self.assertRaises(McpError) as e:
                    c.call("SalesOrder.list")
                self.assertIn(f"HTTP {code}, the token was rejected (check AGENTSWITCH_TOKEN)", str(e.exception))
                self.assertNotIn(TOKEN, str(e.exception))
                self.assertEqual(c.posts, 1)

    def test_writes_are_never_retried(self):
        # The draft writer goes through _rpc directly: a retried create could save the draft twice.
        for failure in (http_error(503), socket.timeout("timed out")):
            with self.subTest(failure=type(failure).__name__):
                c = Scripted([failure, ok({"structuredContent": {"id": "m1"}})])
                with self.assertRaises(McpError):
                    c._rpc("tools/call", {"name": "EmailMessage.create", "arguments": {}})
                self.assertEqual((c.posts, c.slept), (1, []))

    def test_tools_list_is_retried(self):
        c = Scripted([http_error(502), ok({"tools": [{"name": "SalesOrder.list"}]})])
        self.assertEqual(c.tool_names(), {"SalesOrder.list"})

    def test_retry_budget_stops_long_waits(self):
        c = Scripted([http_error(503)] * 4)
        clock = iter([0, 0, C.RETRY_BUDGET + 1])
        with mock.patch.object(C.time, "monotonic", lambda: next(clock)), self.assertRaisesRegex(PlatformUnavailable, "after 2 tries"):
            c.call("Invoice.list")
        self.assertEqual(c.posts, 2)

    def test_missing_settings_are_a_plain_error(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(McpError, "^AGENTSWITCH_BASE_URL is not set$"):
                Client()
            with self.assertRaisesRegex(McpError, "^AGENTSWITCH_TOKEN is not set$"):
                Client("http://x")


class ResponseParsing(unittest.TestCase):
    """D3: the reply to this request is found, and odd replies become a short McpError."""

    def sse(self, *messages):
        return 200, "text/event-stream", "".join(f"event: message\ndata: {json.dumps(m)}\n\n" for m in messages)

    def test_notification_after_or_before_the_response_is_skipped(self):
        note = {"jsonrpc": "2.0", "method": "notifications/message", "params": {}}
        for order in ("after", "before"):
            with self.subTest(order=order):
                reply = {"jsonrpc": "2.0", "id": 1, "result": PAGE}
                c = Scripted([self.sse(*((reply, note) if order == "after" else (note, reply)))])
                self.assertEqual(c.call("SalesOrder.list"), PAGE["structuredContent"])

    def test_reply_to_another_request_is_not_used(self):
        c = Scripted([self.sse({"jsonrpc": "2.0", "id": 99, "result": PAGE})])
        with self.assertRaisesRegex(McpError, "no reply to this request"):
            c.call("SalesOrder.list")

    def test_html_page_is_a_plain_error(self):
        c = Scripted([(200, "text/html; charset=utf-8", "<html>maintenance</html>")])
        with self.assertRaisesRegex(McpError, r"the reply was not JSON \(HTTP 200, text/html\)"):
            c.call("SalesOrder.list")

    def test_reply_without_result_is_a_plain_error(self):
        c = Scripted([(200, "application/json", json.dumps({"jsonrpc": "2.0", "id": 1}))])
        with self.assertRaisesRegex(McpError, "no reply to this request"):
            c.call("SalesOrder.list")

    def test_json_rpc_error_uses_its_message(self):
        c = Scripted([(200, "application/json", json.dumps({"jsonrpc": "2.0", "id": 1,
                                                            "error": {"code": -32000, "message": "boom"}}))])
        with self.assertRaisesRegex(McpError, r"^tools/call SalesOrder.list: boom$"):
            c.call("SalesOrder.list")

    def test_tool_results(self):
        with self.assertRaisesRegex(McpError, "the server reported an error with no message"):
            tool_result({"isError": True, "content": []}, "X.list")
        with self.assertRaisesRegex(McpError, "^X.list: not allowed$"):
            tool_result({"isError": True, "content": [{"type": "text", "text": "not allowed"}]}, "X.list")
        self.assertEqual(tool_result({"structuredContent": {}}), {})
        self.assertEqual(tool_result({"content": [{"type": "text", "text": '{"a": 1}'}]}), {"a": 1})
        with self.assertRaisesRegex(McpError, "is not JSON"):
            tool_result({"content": [{"type": "text", "text": "hello"}]})
        with self.assertRaisesRegex(McpError, "has no data"):
            tool_result({})


class OneLineErrors(unittest.TestCase):
    """D2: both commands stop with one line on stderr and exit 3, never a traceback."""

    def run_main(self, module, argv, client):
        err = io.StringIO()
        with mock.patch.object(module, "Client", client), mock.patch("sys.argv", argv), \
                contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stop:
            module.main()
        return stop.exception.code, err.getvalue()

    def test_report_command(self):
        from o2c import __main__ as M

        def unavailable():
            raise PlatformUnavailable("tools/call SalesOrder.list: HTTP 503 reason after 4 tries")
        code, err = self.run_main(M, ["o2c", "--date", "2026-11-19"], unavailable)
        self.assertEqual(code, 3)
        self.assertEqual(err, "o2c: could not complete: tools/call SalesOrder.list: HTTP 503 reason after 4 tries\n")

    def test_drafts_command(self):
        from o2c import drafts

        def missing():
            raise McpError("AGENTSWITCH_TOKEN is not set")
        code, err = self.run_main(drafts, ["o2c.drafts", "--out", "/nonexistent-never-written"], missing)
        self.assertEqual((code, err), (3, "o2c.drafts: could not complete: AGENTSWITCH_TOKEN is not set\n"))

    def test_failed_draft_save_says_how_many_were_saved(self):
        import tempfile
        from o2c import drafts

        class Flaky:
            def __init__(self):
                self.n = 0

            def _rpc(self, method, params):
                self.n += 1
                if self.n == 2:
                    raise PlatformUnavailable("tools/call EmailMessage.create: no answer before the timeout")
                return {"structuredContent": {"id": f"m{self.n}"}}

            def list_all(self, entity, filters=None):
                return []   # an empty mailbox: no duplicate drafts (D4)
        prop = {"instance": "t", "report_date": "2026-11-19", "matched_against": "invoices", "matches": [],
                "match_summary": {"payments": 0, "with_candidates": 0, "with_exact_match": 0},
                "overdue_reminders": "ok", "skipped": [],
                "drafts": [{"kind": "overdue_reminder", "to": f"ap@{x}.example", "subject": x, "body_text": "b",
                            "fixture": False, "refs": [], "status": "proposed"} for x in ("acme", "beta", "gamma")]}
        flaky, err, out = Flaky(), io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(drafts, "Client", lambda: flaky), \
                mock.patch.object(drafts, "propose", return_value=prop), \
                mock.patch.object(drafts, "find_mailbox", return_value={"id": "MB", "company_id": "CO", "email": "me@x.example"}), \
                mock.patch("builtins.input", lambda _: "save drafts"), \
                mock.patch("sys.argv", ["o2c.drafts", "--out", tmp, "--create", "--only", "overdue_reminder"]), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stop:
            drafts.main()
        self.assertEqual(stop.exception.code, 3)
        self.assertEqual(flaky.n, 2)   # the third draft is not attempted, the second is not retried
        self.assertIn("saved draft m1: acme", out.getvalue())
        self.assertIn("Saved 1 of 3 drafts before this. The failed one may still have been created: "
                      "check the mailbox before running --create again", err.getvalue())


if __name__ == "__main__":
    unittest.main()
