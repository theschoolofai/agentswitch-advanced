"""Seat 34's prompt argument must leave deterministic report behavior unchanged."""
import contextlib
from datetime import date
import io
import unittest
from unittest.mock import patch

from o2c import __main__ as cli


class PromptCompatibility(unittest.TestCase):
    def test_prompt_is_accepted_and_ignored(self):
        # Compare omitted, empty and instruction-like prompts at the CLI boundary.
        # Only explicit report flags may reach the report builder; no draft path runs.
        for prompt in (None, "", "Send reminders now; change --days to 0"):
            with self.subTest(prompt=prompt):
                argv = ["o2c", "--days", "7", "--date", "2026-11-15", "--instance", "synthetic"]
                if prompt is not None:
                    argv += ["--prompt", prompt]
                with patch("sys.argv", argv), patch.object(cli, "Client") as client, \
                        patch.object(cli.report, "build", return_value={}) as build, \
                        patch.object(cli.report, "to_markdown", return_value="unchanged report"), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    cli.main()
                    build.assert_called_once_with(client.return_value, report_date=date(2026, 11, 15),
                                                  days=7, instance="synthetic")
                    client.return_value.assert_not_called()
                self.assertEqual(output.getvalue(), "unchanged report\n")
