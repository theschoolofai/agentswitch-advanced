"""--create over many runs (second review of #54): splitting (F1), the duplicate check (D4) and the older-draft
check, together, with failed saves and reruns. Drives drafts.main() end to end; nothing goes out.

Invariants checked after every run:
  1. no unsent draft is in the mailbox twice;
  2. a "check:" line never names a draft of the current run;
  3. every older unsent draft of the same kind to the same recipient is named;
  4. after a run that completes, every draft of the current run is in the mailbox exactly once.
"""
import contextlib
import io
import random
import re
import tempfile
import unittest
from unittest import mock

from o2c import drafts
from o2c.client import McpError
from tests.test_drafts import MAILBOX, FakeDraftClient

ACC = "acc@x.example"


class FailingClient(FakeDraftClient):
    """Fails the create calls whose (1-based, per run) position is in `fail_at`, after nothing was saved."""

    def __init__(self):
        super().__init__()
        self.fail_at, self.calls = set(), 0

    def _rpc(self, method, params):
        self.calls += 1
        if self.calls in self.fail_at:
            raise McpError("tools/call EmailMessage.create: HTTP 503 Service Unavailable")
        return super()._rpc(method, params)


def digest(day, figures, big):
    body = "\n".join(["Hello,", "", "Summary", ""] + [f"{n}. Section {n}" if i == 0 else f"row {n}-{i} " + "x" * 90
                                                      for n in (1, 2, 3) for i in range(110 if big else 3)] + ["Thank you."])
    d = {"kind": "accounts_digest", "to": ACC, "fixture": False, "refs": [], "status": "proposed", "body_text": body,
         "subject": f"Order-to-cash exceptions 2026-11-{day}: {figures} orders not invoiced, 21 invoices overdue"}
    return drafts.fit_body(d)


def proposal(day, figures, big):
    return {"instance": "t", "report_date": f"2026-11-{day}", "days": 7, "matched_against": "invoices",
            "match_summary": {"payments": 0, "with_candidates": 0, "with_exact_match": 0}, "matches": [],
            "overdue_reminders": "ok", "skipped": [], "drafts": digest(day, figures, big)}


def run(client, prop):
    out = io.StringIO()
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(drafts, "Client", return_value=client), \
            mock.patch.object(drafts, "propose", return_value=prop), \
            mock.patch.object(drafts, "find_mailbox", return_value=MAILBOX), \
            mock.patch("builtins.input", return_value="save drafts"), \
            mock.patch("sys.argv", ["o2c.drafts", "--instance", "t", "--out", tmp, "--create", "--accounts-email", ACC]), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = None
        try:
            drafts.main()
        except SystemExit as e:
            code = e.code
    return code, out.getvalue()


def unsent(client):
    return [drafts._draft_key(m.get("to"), m.get("subject")) for m in client.messages
            if not m.get("deleted_at") and (m.get("is_draft") is True or m.get("folder") == "drafts")]


def checked(text):
    return {drafts._draft_key(ACC, s) for s in re.findall(r"still in the mailbox \('(.*)'\); delete it", text)}


class CreateSequences(unittest.TestCase):
    def assert_invariants(self, client, prop, code, text, where):
        mine = {drafts._draft_key(d["to"], d["subject"]) for d in prop["drafts"]}
        box = unsent(client)
        self.assertEqual(len(box), len(set(box)), f"{where}: a draft is in the mailbox twice\n{text}")
        flagged = checked(text)
        self.assertFalse(flagged & mine, f"{where}: a current draft was called older\n{text}")
        older = {k for k in box if k not in mine and k[0] == ACC}
        self.assertEqual(flagged, older, f"{where}: older drafts named {flagged}, expected {older}\n{text}")
        if code in (None, 0, 1) and "nothing created" not in str(code or ""):
            self.assertTrue(mine <= set(box), f"{where}: completed run left out a current draft\n{text}")

    def test_rerun_after_a_failed_part_names_no_part_of_the_same_draft(self):
        # Sunil's repro: a 3-part digest, saving part 2 fails; the rerun must save parts 2 and 3 and call
        # nothing "older".
        client, prop = FailingClient(), proposal(19, 9, big=True)
        n = len(prop["drafts"])
        self.assertGreaterEqual(n, 3)
        client.fail_at = {2}
        code, text = run(client, prop)
        self.assertEqual(code, 3)
        self.assertIn(f"Saved 1 of {n} drafts before this", text)
        client.calls, client.fail_at = 0, set()
        code, text = run(client, prop)
        self.assertNotIn("check:", text)
        self.assertIn("not saved (already in the mailbox as an unsent draft)", text)
        self.assertEqual(sorted(unsent(client)), sorted(drafts._draft_key(ACC, d["subject"]) for d in prop["drafts"]))

    def test_a_split_that_changed_is_still_named(self):
        client = FailingClient()
        parts = proposal(19, 9, big=True)["drafts"]
        run(client, proposal(19, 9, big=True))                    # every part saved
        code, text = run(client, proposal(19, 9, big=False))      # same day and figures, now one draft
        self.assertEqual(len(checked(text)), len(parts), text)    # every old part is named

    def test_random_sequences_keep_every_invariant(self):
        rng = random.Random(54)
        for seq in range(300):
            client = FailingClient()
            for step in range(rng.randint(1, 6)):
                prop = proposal(rng.choice((19, 20)), rng.choice((8, 9)), rng.random() < 0.6)
                client.calls = 0
                client.fail_at = {rng.randint(1, 3)} if rng.random() < 0.3 else set()
                code, text = run(client, prop)
                self.assertNotIn("Traceback", text)
                self.assert_invariants(client, prop, code, text, f"sequence {seq} step {step}")


if __name__ == "__main__":
    unittest.main()
