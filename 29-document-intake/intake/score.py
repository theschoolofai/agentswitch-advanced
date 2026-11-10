"""Score predictions against an answer key by exact field match.

A person runs this, because the key must stay out of the agent's reach. It reads
the key from the zip in memory, writes nothing, and prints totals and field names
only, never an answer:

    python -m intake.score local/predictions.json --key PATH/TO/adv29_samples.zip
    python -m intake.score --describe --key PATH/TO/adv29_samples.zip
    python -m intake.score --labels --key PATH/TO/adv29_samples.zip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

KEY_FILE = "answer_key.json"
ID_FIELDS = ("source_file", "file", "filename", "file_name", "sample", "document", "id")
# Only these fields hold labels rather than document data.
LABEL_FIELDS = ("doc_type", "tax_type", "flags")
RECORD_LIST_FIELDS = ("lines",)
# A label could hold a date, amount or name. Digits are masked, and long or unusual text is not printed.
SAFE_LABEL = re.compile(r"^[A-Za-z_+/ :=#.-]{1,40}$")


def _printable_label(label: Any) -> Any:
    """Return the label with digits masked, or None if it may hold document data."""
    if not isinstance(label, str):
        return None
    masked = re.sub(r"\d", "#", label)
    return masked if SAFE_LABEL.match(masked) else None


def _stem(name: Any) -> str:
    return Path(str(name)).stem


def load_key(path: Path) -> dict[str, dict[str, Any]]:
    """Return {sample name: fields}, from a zip or a JSON file."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            raw = json.loads(archive.read(KEY_FILE))
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and len(raw) == 1 and isinstance(next(iter(raw.values())), (list, dict)):
        only = next(iter(raw.values()))
        if isinstance(only, list) or all(isinstance(v, dict) for v in only.values()):
            raw = only

    if isinstance(raw, dict):
        rows = dict(raw)
    else:
        rows = {}
        for row in raw:
            id_field = next((f for f in ID_FIELDS if f in row), None)
            if id_field is None:
                raise SystemExit("The key has a row with no recognised name field.")
            rows[row[id_field]] = {k: v for k, v in row.items() if k != id_field}
    key = {}
    for name, row in rows.items():
        nested = row.get("fields")
        flat = {**row, **nested} if isinstance(nested, dict) else dict(row)
        flat.pop("fields", None)
        key[_stem(name)] = flat
    return key


def _same(predicted: Any, expected: Any) -> bool:
    numbers = (int, float)
    if isinstance(predicted, numbers) and isinstance(expected, numbers) \
            and not isinstance(predicted, bool) and not isinstance(expected, bool):
        return float(predicted) == float(expected)
    return predicted == expected


def score(docs: list[dict[str, Any]], key: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare every field the key has, for the documents that were predicted."""
    results: dict[str, list[int]] = {}
    not_predicted = set()
    scored = 0
    flags = {"exact": [0, 0], "labels": {}, "extra": {}}
    for doc in docs:
        expected_row = key.get(_stem(doc.get("source_file", "")))
        if expected_row is None:
            continue
        scored += 1
        for field, expected in expected_row.items():
            if field == "flags":
                _score_flags(flags, doc.get("flags") or [], expected or [])
                continue
            if field not in doc:
                not_predicted.add(field)
            correct, total = results.get(field, [0, 0])
            results[field] = [correct + _same(doc.get(field), expected), total + 1]
    return {"documents": scored, "fields": results, "not_predicted": sorted(not_predicted), "flags": flags}


def _score_flags(flags: dict[str, Any], predicted: list[Any], expected: list[Any]) -> None:
    """Add one document's flags. Names are stored masked, so they are safe to print."""
    wanted, found = {str(item) for item in expected}, {str(item) for item in predicted}
    flags["exact"][0] += wanted == found
    flags["exact"][1] += 1
    for label in wanted:
        name = _printable_label(label) or "(label withheld)"
        hit, total = flags["labels"].get(name, [0, 0])
        flags["labels"][name] = [hit + (label in found), total + 1]
    for label in found - wanted:
        name = _printable_label(label) or "(label withheld)"
        flags["extra"][name] = flags["extra"].get(name, 0) + 1


def describe(key: dict[str, dict[str, Any]]) -> list[str]:
    """Field names and value types only."""
    types: dict[str, set] = {}
    for row in key.values():
        for field, value in row.items():
            types.setdefault(field, set()).add(type(value).__name__)
    lines = [f"documents in key: {len(key)}"]
    lines += [f"  {field}: {'/'.join(sorted(kinds))}" for field, kinds in sorted(types.items())]
    return lines


def labels(key: dict[str, dict[str, Any]]) -> list[str]:
    """The labels a field uses, sorted and without saying which document has which."""
    lines = []
    for field in LABEL_FIELDS:
        found, withheld = set(), 0
        for row in key.values():
            value = row.get(field)
            for item in value if isinstance(value, list) else [value]:
                if isinstance(item, dict):
                    found.update(f"{name} (field)" for name in item)
                elif _printable_label(item):
                    found.add(_printable_label(item))
                elif item is not None:
                    withheld += 1
        lines.append(f"{field}: {', '.join(sorted(found)) or '(none)'}")
        if withheld:
            lines.append(f"  withheld, may hold document data: {withheld}")
    for field in RECORD_LIST_FIELDS:
        types: dict[str, set] = {}
        for row in key.values():
            for record in row.get(field) or []:
                if isinstance(record, dict):
                    for name, value in record.items():
                        types.setdefault(name, set()).add(type(value).__name__)
        fields = ", ".join(f"{name} ({'/'.join(sorted(kinds))})" for name, kinds in sorted(types.items()))
        lines.append(f"fields inside {field}: {fields or '(none)'}")
    return lines


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", nargs="?", type=Path)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--describe", action="store_true", help="print field names and types only")
    parser.add_argument("--labels", action="store_true", help="print the labels used, not per document")
    args = parser.parse_args(argv)

    key = load_key(args.key)
    if args.describe:
        print("\n".join(describe(key)))
        return 0
    if args.labels:
        print("\n".join(labels(key)))
        return 0
    if args.predictions is None:
        parser.error("give a predictions file, or use --describe")

    docs = json.loads(args.predictions.read_text(encoding="utf-8"))
    result = score(docs, key)
    print(f"documents scored: {result['documents']}")
    for field, (correct, total) in sorted(result["fields"].items()):
        print(f"  {field}: {correct}/{total}")
    if result["not_predicted"]:
        print(f"fields the reader does not produce yet: {', '.join(result['not_predicted'])}")
    flags = result["flags"]
    if flags["exact"][1]:
        print(f"flags, documents with exactly the right set: {flags['exact'][0]}/{flags['exact'][1]}")
        for name, (hit, total) in sorted(flags["labels"].items()):
            print(f"  {name}: found {hit} of {total}")
        for name, count in sorted(flags["extra"].items()):
            print(f"  raised but not in the key, {name}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
