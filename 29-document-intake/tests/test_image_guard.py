"""Image files built to do harm, and the checks that stop them. Every image here is built in the test."""
import ast
import json
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from intake import extract, image_guard
from intake.extract import extract_files
from intake.image_guard import MAX_FILE_BYTES, MAX_IMAGE_PIXELS, inspect_image, read_image
from intake.reader import mark_duplicates

from .pdf_forge import BILL_LINES, drawn, forge

INTAKE = Path(__file__).resolve().parent.parent / "intake"


def chunk(kind, data=b""):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width=4, height=4, colour_type=2, depth=8, extra=b""):
    rows = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(min(height, 8)))
    return (image_guard.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour_type, 0, 0, 0))
            + extra + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND"))


def jpeg_segment(marker, body=b""):
    return bytes((0xFF, marker)) + struct.pack(">H", len(body) + 2) + body


def frame(width=4, height=4, marker=0xC0):
    return jpeg_segment(marker, b"\x08" + struct.pack(">HH", height, width) + b"\x01\x01\x11\x00")


def jpeg(*segments, picture=b"\x12\x34\x56"):
    parts = segments or (jpeg_segment(0xE0, b"JFIF\x00"), frame())
    return b"\xff\xd8" + b"".join(parts) + jpeg_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00") + picture + b"\xff\xd9"


class ValidImages(unittest.TestCase):
    def test_png_is_read_for_type_and_size(self):
        reading = inspect_image(png(width=30, height=20))
        self.assertEqual((reading.kind, reading.width, reading.height, reading.flags, reading.error),
                         ("png", 30, 20, (), None))

    def test_jpeg_is_read_for_type_and_size(self):
        reading = inspect_image(jpeg(frame(width=640, height=480)))
        self.assertEqual((reading.kind, reading.width, reading.height, reading.flags, reading.error),
                         ("jpeg", 640, 480, (), None))

    def test_a_progressive_jpeg_is_read_too(self):
        self.assertEqual(inspect_image(jpeg(frame(9, 7, marker=0xC2))).width, 9)

    def test_padding_after_the_end_is_harmless(self):
        self.assertEqual(inspect_image(png() + b"\x00" * 64).flags, ())

    def test_a_large_but_allowed_photo_passes(self):
        reading = inspect_image(jpeg(frame(width=10000, height=10000)))
        self.assertIsNone(reading.error)


class ImagesBuiltToDoHarm(unittest.TestCase):
    def assert_error(self, data, code):
        self.assertEqual(inspect_image(data).error, code)

    def test_png_claiming_billions_of_pixels_is_refused(self):
        self.assert_error(png(width=60000, height=60000), "image_too_large")

    def test_jpeg_claiming_billions_of_pixels_is_refused(self):
        self.assert_error(jpeg(frame(width=65000, height=65000)), "image_too_large")

    def test_the_pixel_limit_is_exact(self):
        side = int(MAX_IMAGE_PIXELS ** 0.5)
        self.assertIsNone(inspect_image(png(width=side, height=side)).error)
        self.assert_error(png(width=side + 1, height=side + 1), "image_too_large")

    def test_a_jpeg_cannot_hide_a_huge_frame_behind_a_small_one(self):
        self.assert_error(jpeg(frame(width=2, height=2), frame(width=65000, height=65000)), "image_too_large")

    def test_a_compression_bomb_is_refused_without_decoding(self):
        small_file = png(width=30000, height=30000)
        self.assertLess(len(small_file), 2000)
        self.assert_error(small_file, "image_too_large")

    def test_zero_sizes_are_corrupt(self):
        self.assert_error(png(width=0), "image_corrupt")
        self.assert_error(png(height=0), "image_corrupt")
        self.assert_error(jpeg(frame(width=0, height=9)), "image_corrupt")

    def test_a_bad_colour_setting_is_corrupt(self):
        self.assert_error(png(colour_type=9), "image_corrupt")
        self.assert_error(png(colour_type=2, depth=3), "image_corrupt")

    def test_a_changed_byte_is_caught_by_the_png_checksum(self):
        damaged = bytearray(png())
        damaged[20] ^= 0xFF
        self.assert_error(bytes(damaged), "image_corrupt")

    def test_a_truncated_file_is_corrupt(self):
        whole = png()
        for cut in (9, 20, len(whole) - 1, len(whole) - 12):
            self.assert_error(whole[:cut], "image_corrupt")
        self.assert_error(jpeg()[:-2], "image_corrupt")
        self.assert_error(jpeg()[:6], "image_corrupt")

    def test_a_chunk_length_past_the_end_is_corrupt(self):
        head = image_guard.PNG_SIGNATURE + struct.pack(">I", 0xFFFFFFF0) + b"IHDR" + b"\x00" * 13
        self.assert_error(head, "image_corrupt")

    def test_a_png_with_no_pixels_is_corrupt(self):
        header = chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
        self.assert_error(image_guard.PNG_SIGNATURE + header + chunk(b"IEND"), "image_corrupt")

    def test_the_header_must_come_first(self):
        rows = zlib.compress(b"\x00")
        self.assert_error(image_guard.PNG_SIGNATURE + chunk(b"IDAT", rows) + chunk(b"IEND"), "image_corrupt")

    def test_too_many_chunks_is_corrupt(self):
        limit = image_guard.MAX_PNG_CHUNKS
        image_guard.MAX_PNG_CHUNKS = 5
        self.addCleanup(setattr, image_guard, "MAX_PNG_CHUNKS", limit)
        self.assert_error(png(extra=chunk(b"tEXt", b"x") * 10), "image_corrupt")

    def test_a_jpeg_with_a_broken_segment_is_corrupt(self):
        self.assert_error(b"\xff\xd8\xff\xe0\x00\x01" + b"\x00" * 10, "image_corrupt")
        self.assert_error(b"\xff\xd8\xff\xe0\xff\xff", "image_corrupt")
        self.assert_error(b"\xff\xd8\xff\xd9", "image_corrupt")

    def test_a_jpeg_with_no_frame_is_corrupt(self):
        self.assert_error(jpeg(jpeg_segment(0xE0, b"JFIF\x00")), "image_corrupt")

    def test_random_bytes_after_a_signature_do_not_crash(self):
        for tail in (b"", b"\xff", b"\xff" * 500, b"\x00" * 500, bytes(range(256)) * 4):
            self.assertIsNotNone(inspect_image(image_guard.JPEG_SIGNATURE + tail).error)
            self.assertIsNotNone(inspect_image(image_guard.PNG_SIGNATURE + tail).error)


class FilesThatAreTwoThings(unittest.TestCase):
    def test_data_after_the_end_of_a_png_is_flagged(self):
        self.assertIn("image_trailing_data", inspect_image(png() + b"anything else").flags)

    def test_data_after_the_end_of_a_jpeg_is_flagged(self):
        self.assertIn("image_trailing_data", inspect_image(jpeg() + b"anything else").flags)

    def test_a_pdf_inside_an_image_is_flagged(self):
        flags = inspect_image(png() + forge(drawn())).flags
        self.assertIn("image_embedded_file", flags)

    def test_a_pdf_hidden_in_a_png_chunk_is_flagged(self):
        reading = inspect_image(png(extra=chunk(b"tEXt", b"note\x00%PDF-1.7 hidden")))
        self.assertEqual(reading.flags, ("image_embedded_file",))

    def test_a_zip_or_script_inside_an_image_is_flagged(self):
        self.assertIn("image_embedded_file", inspect_image(png() + b"PK\x03\x04rest").flags)
        self.assertIn("image_embedded_file", inspect_image(jpeg(picture=b"<script>x")).flags)

    def test_an_animated_png_is_flagged(self):
        self.assertIn("image_animated", inspect_image(png(extra=chunk(b"acTL", b"\x00" * 8))).flags)


class TheFileNameCannotDecideTheType(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)

    def run_one(self, name, data):
        path = self.folder / name
        path.write_bytes(data)
        return extract_files([path])[0]

    def test_a_photo_goes_to_a_person_with_no_values(self):
        doc = self.run_one("photo.png", png(width=30, height=20))
        self.assertEqual(doc["flags"], ["image_not_read"])
        self.assertEqual(doc["image"], {"kind": "png", "width": 30, "height": 20})
        self.assertEqual(doc["proposed_action"], "review")
        self.assertTrue(doc["needs_review"])
        self.assertEqual(doc["confidence"], 0.0)
        self.assertIsNone(doc.get("total_stated"))
        self.assertIsNone(doc.get("error"))
        self.assertEqual(doc["vendor_check"], "not_applicable")

    def test_a_jpeg_goes_to_a_person_too(self):
        doc = self.run_one("photo.jpeg", jpeg())
        self.assertEqual(doc["flags"], ["image_not_read"])
        self.assertEqual(doc["image"]["kind"], "jpeg")

    def test_a_capital_extension_is_fine(self):
        self.assertEqual(self.run_one("PHOTO.JPG", jpeg())["flags"], ["image_not_read"])

    def test_a_file_with_no_extension_is_judged_by_its_bytes(self):
        self.assertEqual(self.run_one("attachment", png())["flags"], ["image_not_read"])

    def test_an_image_named_pdf_is_flagged(self):
        doc = self.run_one("bill.pdf", png())
        self.assertIn("file_type_mismatch", doc["flags"])
        self.assertEqual(doc["image"]["kind"], "png")

    def test_a_png_named_jpg_is_flagged(self):
        self.assertIn("file_type_mismatch", self.run_one("photo.jpg", png())["flags"])

    def test_a_pdf_named_png_is_read_but_sent_to_a_person(self):
        doc = self.run_one("photo.png", forge(drawn(BILL_LINES)))
        self.assertIn("file_type_mismatch", doc["flags"])
        self.assertTrue(doc["needs_review"])
        self.assertNotEqual(doc["proposed_action"], "draft_bill")

    def test_a_normal_pdf_gets_no_new_flag(self):
        doc = self.run_one("bill.pdf", forge(drawn(BILL_LINES)))
        self.assertNotIn("file_type_mismatch", doc["flags"])

    def test_a_refused_image_is_an_error_and_creates_nothing(self):
        for name, data, code in (("huge.png", png(width=60000, height=60000), "image_too_large"),
                                 ("bad.png", png()[:20], "image_corrupt"),
                                 ("anim.gif", b"GIF89a" + b"\x00" * 50, "unsupported_image_type"),
                                 ("phone.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 50, "unsupported_image_type"),
                                 ("scan.tiff", b"II*\x00" + b"\x00" * 50, "unsupported_image_type"),
                                 ("photo.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 50, "unsupported_image_type"),
                                 ("old.bmp", b"BM" + b"\x00" * 50, "unsupported_image_type")):
            doc = self.run_one(name, data)
            self.assertEqual(doc["error"], code, name)
            self.assertEqual(doc["proposed_action"], "report_error", name)
            self.assertTrue(doc["source_sha256"], name)

    def test_an_oversized_image_is_refused_before_it_is_read(self):
        path = self.folder / "big.png"
        with path.open("wb") as handle:
            handle.write(png())
            handle.truncate(MAX_FILE_BYTES + 1)
        self.assertEqual(read_image(path).error, "file_too_large")

    def test_other_files_still_go_to_the_pdf_reader(self):
        self.assertEqual(self.run_one("note.txt", b"just text")["error"], "not_a_pdf")

    def test_a_file_that_vanished_is_reported_as_before(self):
        doc = extract.extract_file(self.folder / "missing.png")
        self.assertEqual(doc["error"], "unreadable_file")


class ImagesInABatch(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder)

    def test_the_same_photo_twice_is_a_duplicate(self):
        for name in ("a.png", "b.png"):
            (self.folder / name).write_bytes(png())
        first, second = extract_files(sorted(self.folder.iterdir()))
        self.assertEqual(second["proposed_action"], "reject_duplicate")
        self.assertEqual(first["proposed_action"], "review")

    def test_a_bad_image_does_not_stop_the_others(self):
        (self.folder / "a.png").write_bytes(png()[:20])
        (self.folder / "b.pdf").write_bytes(forge(drawn(BILL_LINES)))
        (self.folder / "c.png").write_bytes(png())
        docs = extract_files(sorted(self.folder.iterdir()))
        self.assertEqual(len(docs), 3)
        self.assertEqual(docs[0]["error"], "image_corrupt")
        self.assertEqual(docs[2]["flags"], ["image_not_read"])

    def test_results_stay_valid_json(self):
        (self.folder / "a.png").write_bytes(png())
        json.dumps(extract_files(sorted(self.folder.iterdir())), allow_nan=False)


class TheGuardNeverDecodes(unittest.TestCase):
    def test_it_imports_no_image_library_network_or_platform_client(self):
        tree = ast.parse((INTAKE / "image_guard.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        self.assertEqual(names, {"__future__", "hashlib", "struct", "zlib", "dataclasses", "pathlib", "typing"})

    def test_it_never_decompresses(self):
        tree = ast.parse((INTAKE / "image_guard.py").read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == "zlib"}
        self.assertEqual(used, {"crc32"})


if __name__ == "__main__":
    unittest.main()
