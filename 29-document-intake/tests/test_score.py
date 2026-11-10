"""Tests for the scorer, using a made-up key. The output must never show an answer."""
import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from intake.score import labels, load_key, main, score

SECRET_NAME = "Secret Vendor Name"
ROWS = [
    {"file": "sample_01.pdf", "seller_name": SECRET_NAME, "grand_total": 590, "due_date": None,
     "flags": ["some_flag"]},
    {"file": "sample_02.pdf", "seller_name": "Another Secret", "grand_total": 10.5, "due_date": "2026-01-02"},
]
DOCS = [
    {"source_file": "sample_01.pdf", "seller_name": SECRET_NAME, "grand_total": 590.0, "due_date": None},
    {"source_file": "sample_02.pdf", "seller_name": "Wrong", "grand_total": 10.5, "due_date": "2026-01-03"},
]


class KeyShapeTests(unittest.TestCase):
    def write(self, folder, data):
        path = Path(folder) / "key.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_key_shapes_load_the_same(self):
        by_name = {row["file"]: {k: v for k, v in row.items() if k != "file"} for row in ROWS}
        nested = {name: {"fields": row} for name, row in by_name.items()}
        with tempfile.TemporaryDirectory() as folder:
            for data in (ROWS, {"documents": ROWS}, by_name, {"samples": by_name}, nested):
                key = load_key(self.write(folder, data))
                self.assertEqual(set(key), {"sample_01", "sample_02"})
                self.assertEqual(key["sample_01"]["grand_total"], 590)

    def test_key_is_read_from_a_zip_without_extracting(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "set.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("answer_key.json", json.dumps(ROWS))
            self.assertEqual(len(load_key(path)), 2)
            self.assertEqual([p.name for p in Path(folder).iterdir()], ["set.zip"])


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.key = {row["file"].split(".")[0]: {k: v for k, v in row.items() if k != "file"} for row in ROWS}

    def test_exact_match_per_field(self):
        result = score(DOCS, self.key)
        self.assertEqual(result["documents"], 2)
        self.assertEqual(result["fields"]["seller_name"], [1, 2])
        self.assertEqual(result["fields"]["grand_total"], [2, 2])
        self.assertEqual(result["fields"]["due_date"], [1, 2])

    def test_flags_are_not_scored_as_a_field(self):
        self.assertNotIn("flags", score(DOCS, self.key)["fields"])

    def test_field_the_reader_lacks_counts_as_wrong(self):
        docs = [{"source_file": "sample_02.pdf"}]
        result = score(docs, self.key)
        self.assertEqual(result["fields"]["seller_name"], [0, 1])
        self.assertIn("seller_name", result["not_predicted"])

    def test_documents_outside_the_predictions_are_not_counted(self):
        self.assertEqual(score(DOCS[:1], self.key)["documents"], 1)

    def test_output_never_shows_an_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            key_path = Path(folder) / "key.json"
            key_path.write_text(json.dumps(ROWS), encoding="utf-8")
            docs_path = Path(folder) / "docs.json"
            docs_path.write_text(json.dumps(DOCS), encoding="utf-8")
            for args in ([str(docs_path), "--key", str(key_path)], ["--describe", "--key", str(key_path)]):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    main(args)
                for answer in (SECRET_NAME, "Another Secret", "2026-01-02", "590", "10.5"):
                    self.assertNotIn(answer, output.getvalue())


class FlagScoreTests(unittest.TestCase):
    KEY = {
        "sample_01": {"flags": ["no_due_date", "duplicate_of:sample_03"]},
        "sample_02": {"flags": []},
        "sample_03": {"flags": ["no_due_date"]},
    }

    def test_exact_sets_found_labels_and_extras_are_counted(self):
        docs = [
            {"source_file": "sample_01.pdf", "flags": ["no_due_date", "duplicate_of:sample_03"]},
            {"source_file": "sample_02.pdf", "flags": ["our_extra"]},
            {"source_file": "sample_03.pdf", "flags": []},
        ]
        flags = score(docs, self.KEY)["flags"]
        self.assertEqual(flags["exact"], [1, 3])
        self.assertEqual(flags["labels"]["no_due_date"], [1, 2])
        self.assertEqual(flags["labels"]["duplicate_of:sample_##"], [1, 1])
        self.assertEqual(flags["extra"], {"our_extra": 1})

    def test_flag_output_masks_which_document_is_meant(self):
        with tempfile.TemporaryDirectory() as folder:
            key_path = Path(folder) / "key.json"
            key_path.write_text(json.dumps(self.KEY), encoding="utf-8")
            docs_path = Path(folder) / "docs.json"
            docs_path.write_text(json.dumps([{"source_file": "sample_01.pdf", "flags": []}]), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                main([str(docs_path), "--key", str(key_path)])
            self.assertIn("flags, documents with exactly the right set: 0/1", output.getvalue())
            self.assertNotIn("sample_03", output.getvalue())


class LabelTests(unittest.TestCase):
    KEY = {
        "sample_01": {"doc_type": "bill", "tax_type": "IGST", "flags": ["duplicate"], "seller": SECRET_NAME,
                      "invoice_number": "AB/001", "total_stated": 590.0,
                      "lines": [{"description": "Secret line text", "qty": 2, "rate": 295.0}]},
        "sample_02": {"doc_type": "credit_note", "tax_type": None,
                      "flags": ["total off by 100", "due on 2026-01-02", "x" * 41, {"kind": "Secret flag text"}]},
    }

    def output(self):
        return "\n".join(labels(self.KEY))

    def test_labels_and_inner_field_names_are_listed(self):
        output = self.output()
        self.assertIn("doc_type: bill, credit_note", output)
        self.assertIn("tax_type: IGST", output)
        self.assertIn("duplicate", output)
        self.assertIn("description (str), qty (int), rate (float)", output)

    def test_digits_are_masked_and_long_labels_are_withheld(self):
        output = self.output()
        for hidden in ("total off by 100", "2026-01-02", "x" * 41):
            self.assertNotIn(hidden, output)
        self.assertIn("total off by ###", output)
        self.assertIn("due on ####-##-##", output)
        self.assertIn("withheld, may hold document data: 1", output)

    def test_flag_records_show_field_names_only(self):
        output = self.output()
        self.assertIn("kind (field)", output)
        self.assertNotIn("Secret flag text", output)

    def test_document_data_and_which_document_never_appear(self):
        output = self.output()
        for hidden in (SECRET_NAME, "AB/001", "590", "295", "Secret line text", "sample_01", "sample_02"):
            self.assertNotIn(hidden, output)


if __name__ == "__main__":
    unittest.main()
