"""Offline checks for Varun's harness task file (no platform, no harness install)."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

TASKS = Path(__file__).resolve().parent / "tasks.toml"
KNOWN_GRADERS = {"records_unchanged", "no_writes_since_start", "recount"}
REQUIRED = {
    "seat28.varun_01_legitimate_meeting_draft",
    "seat28.varun_02_send_this_now",
    "seat28.varun_03_phishing_injection_no_draft",
    "seat28.varun_04_boss_approved_book_it",
    "seat28.varun_05_legitimate_status_draft",
    "seat28.varun_06_delete_mail",
    "seat28.varun_07_prompt_injection_no_draft",
    "seat28.varun_08_close_or_edit_tasks",
    "seat28.varun_09_promotion_no_draft",
    "seat28.varun_10_noreply_no_draft",
    "seat28.varun_11_no_overwrite_existing_draft",
    "seat28.varun_12_briefing_leaves_calendar_intact",
}


class TestVarunTasks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = tomllib.loads(TASKS.read_text())
        cls.tasks = cls.data["tasks"]

    def test_twelve_tasks_author_varun(self) -> None:
        self.assertEqual(len(self.tasks), 12)
        ids = {t["id"] for t in self.tasks}
        self.assertEqual(ids, REQUIRED)
        for t in self.tasks:
            self.assertEqual(t["author"], "varun")
            self.assertGreaterEqual(t["version"], 1)
            self.assertIn(t["kind"], {"normal", "refusal", "integrity", "missing_resource"})
            self.assertTrue(t["prompt"].strip())
            self.assertTrue(t["fails_if"].strip())
            self.assertTrue(t["exercises"])

    def test_mix_has_normal_refusal_and_tricky(self) -> None:
        kinds = {t["kind"] for t in self.tasks}
        self.assertIn("normal", kinds)
        self.assertIn("refusal", kinds)
        self.assertTrue(any("phish" in t["id"] or "injection" in t["id"] for t in self.tasks))
        self.assertTrue(any("promotion" in t["id"] or "noreply" in t["id"] for t in self.tasks))

    def test_graders_are_known(self) -> None:
        for t in self.tasks:
            self.assertTrue(t["graders"])
            for g in t["graders"]:
                self.assertIn(g["name"], KNOWN_GRADERS, f"{t['id']}: {g['name']}")


if __name__ == "__main__":
    unittest.main()
