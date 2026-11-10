"""Read PDFs and write proposed fields to a JSON file, without using the platform.

Run from 29-document-intake:
    python -m intake.fetch_parties suryodaya
    python -m intake.extract local/samples/sample_01.pdf --out local/predictions.json --parties local/parties_suryodaya.json

Use --no-vendor-check instead of --parties only for runs that create nothing, such as scoring.

The output holds document data, so keep it in the git-ignored local/ folder.
Standard output is counts only.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Optional

from .image_guard import ImageReading, read_image
from .pdf_guard import read_pdf
from .reader import error_document, mark_duplicates, parse_document
from .vendors import VendorRecords, VendorRecordsError, check_vendors, load_records


def safe_file_name(name: str) -> str:
    """A sender chooses the file name, so it gets no more trust than the file."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]


SUFFIXES_FOR = {"png": {".png"}, "jpeg": {".jpg", ".jpeg"}, "pdf": {".pdf"}}


def _image_document(image: ImageReading) -> dict:
    """A valid image goes to a person. Its pixels are not read, so it has no values to propose."""
    if image.error:
        return error_document(image.error)
    doc = parse_document("", pdf_flags=("image_not_read", *image.flags))
    doc["flags"] = [flag for flag in doc["flags"] if flag != "no_text_layer"]
    doc["image"] = {"kind": image.kind, "width": image.width, "height": image.height}
    return doc


def _flag_misleading_name(doc: dict, path: Path, kind: Optional[str]) -> None:
    """A sender chooses the name, so one that disagrees with the file's bytes is a warning sign."""
    suffix = path.suffix.lower()
    if not kind or not suffix or suffix in SUFFIXES_FOR.get(kind, ()):
        return
    doc["flags"].append("file_type_mismatch")
    doc["needs_review"] = True
    if doc["proposed_action"] == "draft_bill":
        doc["proposed_action"] = "review"


def extract_file(path: Path, own_country: Optional[str] = None) -> dict:
    """Read one file. A bad file gets an error result and never stops the batch."""
    image = read_image(path)
    if image is not None:
        doc = _image_document(image)
        _flag_misleading_name(doc, path, image.kind)
        doc["source_file"] = safe_file_name(path.name)
        doc["source_sha256"] = image.sha256
        return doc
    reading = read_pdf(path)
    if reading.error:
        doc = error_document(reading.error)
    else:
        try:
            doc = parse_document(reading.text, own_country=own_country, pdf_flags=reading.flags)
        except Exception:  # A rule bug on one strange document must not lose the others.
            doc = error_document("reader_failed")
    if not reading.error:
        _flag_misleading_name(doc, path, "pdf")
    doc["source_file"] = safe_file_name(path.name)
    doc["source_sha256"] = reading.sha256
    return doc


def extract_files(paths: list[Path], own_country: Optional[str] = None,
                  records: Optional[VendorRecords] = None) -> list[dict]:
    docs = [extract_file(path, own_country) for path in sorted(paths)]
    mark_duplicates(docs)
    check_vendors(docs, records)
    return docs


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--own-country", choices=("IN", "US"), help="our company's country, a clue to date order")
    vendor_source = parser.add_mutually_exclusive_group(required=True)
    vendor_source.add_argument("--parties", type=Path, help="saved Party records from intake.fetch_parties")
    vendor_source.add_argument("--no-vendor-check", action="store_true", help="leave vendors marked not_checked")
    args = parser.parse_args(argv)

    try:
        records = load_records(args.parties) if args.parties else None
    except VendorRecordsError as error:
        print(f"Vendor check not possible: {error}", file=sys.stderr)
        return 2

    docs = extract_files(args.pdfs, args.own_country, records)
    args.out.write_text(json.dumps(docs, indent=1, ensure_ascii=False, allow_nan=False), encoding="utf-8")

    print(f"documents: {len(docs)}")
    print(f"could not be read: {sum(bool(d.get('error')) for d in docs)}")
    print(f"types: {dict(sorted(collections.Counter(d['doc_type'] for d in docs).items()))}")
    print(f"sent to a person first: {sum(d['needs_review'] for d in docs)}")
    flags = collections.Counter(flag for d in docs for flag in d["flags"])
    print(f"flags: {dict(sorted(flags.items()))}")
    print(f"vendor check: {dict(sorted(collections.Counter(d['vendor_check'] for d in docs).items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
