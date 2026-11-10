"""Check a bill's vendor against a saved copy of the Party records.

This module reads document fields and a local file. It has no platform client and
makes no network call, so nothing a document says can become a platform query.
intake/fetch_parties.py saves the copy.

Only an exact name match can make a vendor known. A close name goes to a person,
because a small difference is how a fake vendor would look. A match never removes
a flag or lowers a review.
"""
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

MAX_RECORDS_AGE = timedelta(hours=24)
# Only decides whether the reviewer is shown a likely match. Either way the bill goes to a person.
LOOKALIKE_SIMILARITY = 0.86
UNCHECKED_VENDOR_CONFIDENCE = 0.5

KNOWN_BY_NAME = "known_name_only"
KNOWN_BY_TAX_ID = "known_tax_id_confirmed"
NOT_CHECKED = "not_checked"
NOT_APPLICABLE = "not_applicable"
# Each result here sends the bill to a person, with no draft proposed.
FLAG_FOR_RESULT = {
    "unknown": "unknown_vendor",
    "lookalike": "vendor_name_lookalike",
    "ambiguous": "vendor_ambiguous",
    "not_a_supplier": "vendor_not_a_supplier",
    "tax_id_mismatch": "vendor_tax_id_mismatch",
}

_WORD_FORMS = {"pvt": "private", "ltd": "limited", "co": "company", "corp": "corporation", "inc": "incorporated"}
_LEGAL_WORDS = frozenset({"private", "limited", "company", "corporation", "incorporated", "llp", "llc"})


class VendorRecordsError(Exception):
    """The saved Party records cannot be trusted for a check."""


@dataclass(frozen=True)
class Party:
    id: str
    names: tuple[str, ...]
    is_vendor: bool  # An active supplier role, or Bills already on record.
    tax_ids: frozenset[str]


@dataclass(frozen=True)
class VendorRecords:
    system: str
    fetched_at: datetime
    parties: tuple[Party, ...]


def name_key(name: str) -> str:
    """Fold case, punctuation and common spellings. Letters from other scripts stay different."""
    words = re.findall(r"\w+", unicodedata.normalize("NFKC", name).casefold().replace("&", " and "))
    if words[:2] == ["m", "s"]:  # "M/s", a common courtesy prefix on Indian invoices.
        words = words[2:]
    if words[:1] == ["the"]:
        words = words[1:]
    return " ".join(_WORD_FORMS.get(word, word) for word in words)


def _without_legal_words(key: str) -> str:
    words = key.split()
    while words and words[-1] in _LEGAL_WORDS:
        words.pop()
    return " ".join(words)


def load_records(path: Path, now: Optional[datetime] = None) -> VendorRecords:
    """Load the saved copy. An old, empty or damaged copy is refused, not used."""
    now = now or datetime.now(timezone.utc)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(saved["fetched_at"])
        parties = tuple(
            Party(row["id"], tuple(row["names"]), bool(row["is_supplier"] or row["bill_count"]),
                  frozenset(row.get("tax_ids", ())))
            for row in saved["parties"]
        )
        age = now - fetched_at
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise VendorRecordsError(f"{path.name}: cannot read the saved Party records ({type(error).__name__}).") from None
    if not parties:
        raise VendorRecordsError(f"{path.name}: holds no Party records.")
    if age < timedelta(0) or age > MAX_RECORDS_AGE:
        raise VendorRecordsError(f"{path.name}: saved at {saved['fetched_at']}, outside the "
                                 f"{MAX_RECORDS_AGE.total_seconds() / 3600:.0f}-hour limit. Fetch them again.")
    return VendorRecords(str(saved.get("system", "")), fetched_at, parties)


def _with_name(parties: tuple[Party, ...], key: str) -> list[Party]:
    return [party for party in parties if key in {name_key(name) for name in party.names}]


def _closest_vendor(parties: tuple[Party, ...], key: str) -> Optional[dict[str, str]]:
    best, best_score = None, 0.0
    core = _without_legal_words(key)
    for party in parties:
        if not party.is_vendor:
            continue
        for name in party.names:
            other = name_key(name)
            same_core = bool(core) and core == _without_legal_words(other)
            score = 1.0 if same_core else difflib.SequenceMatcher(None, key, other).ratio()
            if score >= LOOKALIKE_SIMILARITY and score > best_score:
                best, best_score = {"id": party.id, "name": name}, score
    return best


def _as_candidates(parties: list[Party]) -> list[dict[str, str]]:
    """Names from our records, never from the document, for a reviewer to compare."""
    return [{"id": party.id, "name": party.names[0] if party.names else ""} for party in parties]


def _decide(name: Optional[str], tax_id: Optional[str], records: VendorRecords
            ) -> "tuple[str, Optional[str], list[dict[str, str]]]":
    """Return (result, vendor id if known, parties a reviewer should compare with)."""
    key = name_key(name or "")
    if not key:
        return "unknown", None, []
    named = _with_name(records.parties, key)
    vendors = [party for party in named if party.is_vendor]
    if len(vendors) > 1:
        return "ambiguous", None, _as_candidates(vendors)
    if vendors:
        vendor = vendors[0]
        if not vendor.tax_ids:
            return KNOWN_BY_NAME, vendor.id, []
        if tax_id in vendor.tax_ids:
            return KNOWN_BY_TAX_ID, vendor.id, []
        return "tax_id_mismatch", None, _as_candidates(vendors)
    if named:
        return "not_a_supplier", None, _as_candidates(named)
    closest = _closest_vendor(records.parties, key)
    return ("lookalike", None, [closest]) if closest else ("unknown", None, [])


def check_vendors(docs: list[dict[str, Any]], records: Optional[VendorRecords]) -> None:
    """Add the result to each document. Run this after mark_duplicates.

    Without records every vendor bill says not_checked. Anything that creates a
    draft must require a known_ result, because not_checked proves nothing.
    """
    for doc in docs:
        if doc.get("doc_type") != "vendor_bill":
            doc["vendor_check"] = NOT_APPLICABLE
            continue
        if records is None:
            doc["vendor_check"] = NOT_CHECKED
            continue
        result, vendor_id, candidates = _decide(doc.get("counterparty_name"), doc.get("counterparty_gstin"), records)
        doc["vendor_check"] = result
        if vendor_id:
            doc["vendor_id"] = vendor_id
        if candidates:
            doc["vendor_candidates"] = candidates
        flag = FLAG_FOR_RESULT.get(result)
        if flag:
            _send_to_a_person(doc, flag)


def _send_to_a_person(doc: dict[str, Any], flag: str) -> None:
    doc["flags"].append(flag)
    doc["needs_review"] = True
    confidence = doc["field_confidence"]
    confidence["vendor"] = min(confidence["vendor"], UNCHECKED_VENDOR_CONFIDENCE)
    doc["confidence"] = min(doc["confidence"], confidence["vendor"])
    if doc["proposed_action"] == "draft_bill":  # A sure duplicate stays a duplicate.
        doc["proposed_action"] = "review"
