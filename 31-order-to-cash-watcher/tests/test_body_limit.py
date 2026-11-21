"""Live test F1 (20 Nov): the platform refuses a message body over 10,000 characters."""
import unittest

from o2c import drafts
from o2c.client import WriteBlocked


def digest_like(rows_per_section=120):
    lines = ["Hello,", "", "This is the report.", "", "Summary", "- a", ""]
    for n, title in ((1, "Orders not invoiced"), (2, "Invoices overdue"), (3, "Payments not applied")):
        lines += [f"{n}. {title} ({rows_per_section})", "", "Number      Customer              Amount",
                  "----------  --------------------  ----------"]
        lines += [f"N-{n}-{i:05d}  Customer {i:<11}  {i:>10}.00" for i in range(rows_per_section)]
        lines += ["", "Please act on these.", ""]
    lines += ["Thank you."]
    return {"kind": "accounts_digest", "to": "a@example.com", "subject": "Digest", "body_text": "\n".join(lines),
            "fixture": False, "status": "proposed"}


class BodyLimit(unittest.TestCase):
    def test_short_draft_is_unchanged(self):
        d = digest_like(5)
        self.assertEqual(drafts.fit_body(d), [d])

    def test_long_draft_splits_into_numbered_parts_that_fit_and_lose_nothing(self):
        d = digest_like(400)
        self.assertGreater(len(d["body_text"]), drafts.BODY_MAX)
        parts = drafts.fit_body(d)
        n = len(parts)
        self.assertGreater(n, 1)
        for i, p in enumerate(parts, 1):
            self.assertLessEqual(len(p["body_text"]), drafts.BODY_MAX)
            self.assertTrue(p["subject"].endswith(f"(part {i} of {n})"))
            self.assertTrue(p["body_text"].startswith(f"(Part {i} of {n}.)"))
            self.assertEqual(p["to"], d["to"])
        text = "\n".join(p["body_text"] for p in parts)
        for line in d["body_text"].split("\n"):
            self.assertIn(line, text)
        self.assertEqual(len({p["subject"] for p in parts}), n)   # D4 keys each part separately

    def test_a_table_cut_mid_way_repeats_its_header(self):
        parts = drafts.fit_body(digest_like(400))
        for p in parts[1:]:
            body = p["body_text"].split("\n")
            if body[2].startswith("N-"):
                self.fail("a part starts with table rows and no header")

    def test_parts_prefer_section_boundaries(self):
        parts = drafts.fit_body(digest_like(130))
        starts = [p["body_text"].split("\n")[2] for p in parts[1:]]
        self.assertTrue(all(s[:2] in ("2.", "3.") or "(continued)" in s for s in starts), starts)

    def test_writer_refuses_an_oversized_body_before_any_request(self):
        class NoNetwork:
            def _rpc(self, *a):
                raise AssertionError("no request may be sent")

        w = drafts.DraftWriter(NoNetwork(), {"id": "M", "email": "me@example.com", "company_id": "C"})
        with self.assertRaises(WriteBlocked):
            w.create(digest_like(400))


if __name__ == "__main__":
    unittest.main()
