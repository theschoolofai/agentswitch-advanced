"""Find duplicate parties and items in the rows a `.list` tool returns. Pure functions: no network, no platform calls.

Rules only, so the same rows always give the same pairs and a verifier can recompute them. A score is a rule score,
not a probability. See docs/first-task-plan.md for why each rule exists.
"""
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from itertools import combinations

# Bumped whenever a change can alter which pairs are found, their scores, bands or exclusions.
RULES_VERSION = "3"

PROPOSE, REVIEW = 0.9, 0.6
BAND_ORDER = {"propose": 0, "review": 1}

# Tuned on the tuning set (step 7) and frozen by commit. A near name (similarity 0.9 or more after normalizing: about
# a letter or two apart in a name of ordinary length) weighs as much as an exact one, so a duplicate that differs only
# by a typo reaches review. Similarity does not show the difference is a typo, though: two people a letter apart can
# share a household email or phone. So a party pair whose names are only near is held at review unless the two share
# a customer code, which belongs to one customer (_score_party).
PARTY_WEIGHTS = {"customer_code": 0.7, "email": 0.6, "phone": 0.5, "name": 0.6, "near_name": 0.6, "website": 0.2,
                 "city_postal": 0.15}
# Rules version 3. Two items with the same name reach review on the name alone, even when their codes differ, since a
# re-entered item usually gets a new code. A near item name reaches review with a shared unit, because half the live
# items have no category; that also sends size variants a letter apart ("M6" and "M8") to review, where a person
# rejects them. Neither reaches propose without a shared code.
ITEM_WEIGHTS = {"code": 0.7, "name": 0.6, "near_name": 0.55, "category": 0.1, "uom": 0.05}
NEAR_NAME = 0.9

# A strong value held by more records than this is a shared inbox, a switchboard or a dummy, not an identity.
SHARED_LIMIT = 5
# A grouping key held by more records than this is too common to group on (a name token like "supply", a family name,
# a staff website, a placeholder name that slipped through). Skipping it keeps a 5000-row table from becoming millions
# of pairs; the report counts what was skipped.
BLOCK_LIMIT = 50

PLACEHOLDERS = {"", "n/a", "na", "none", "null", "nil", "-", "--", "unknown", "tbd", "test", "x", "0"}
LEGAL_ENDINGS = {"pvt", "private", "ltd", "limited", "llp", "llc", "inc", "incorporated", "corp", "corporation", "co",
                 "company", "plc", "gmbh"}
ORDINARY_PRIVACY = "normal"

_TAG = re.compile(r"^\[([^\]]*)\]\s*")
# Between a digit and a letter: "25mm" and "25 mm" are one size.
_DIGIT_LETTER = re.compile(r"(?<=\d)(?=[^\W\d_])|(?<=[^\W\d_])(?=\d)")


def flag(value) -> bool:
    """A boolean field may arrive as a bool, an int or a string: "false" must not read as true."""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return value is True or value == 1


def blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip().casefold() in PLACEHOLDERS)


def strip_tag(name: str, test_tags) -> tuple[str, bool]:
    """Drop one leading [..] only when its content starts with a confirmed test-run tag. Any other bracket is part of
    the name: "[North] Acme" and "[South] Acme" must not collapse into one."""
    name = "" if name is None else str(name)
    m = _TAG.match(name)
    # An empty tag would match every bracket.
    if m and any(t and m.group(1).strip().casefold().startswith(t.casefold()) for t in test_tags):
        return name[m.end():], True
    return name, False


def tokens(text: str) -> list[str]:
    """Words of any script. Latin accents are dropped ("José" is "Jose"), but other scripts keep their marks: a
    Devanagari vowel sign or virama is part of the word ("राम" and "रोम" are different names), and splitting on it
    would cut one word into letters."""
    out = []
    for c in unicodedata.normalize("NFKD", str(text).casefold().replace("&", " and ")):
        if "\u0300" <= c <= "\u036f":
            continue
        out.append(c if c.isalnum() or unicodedata.category(c).startswith("M") else " ")
    return "".join(out).split()


def norm_name(name: str, test_tags=()) -> str:
    """Case, spacing, punctuation, accents, token order and legal endings do not make two names different. A
    placeholder name ("N/A", "Unknown") is no name: two of them are not evidence of anything."""
    stripped = strip_tag(name, test_tags)[0]
    if blank(stripped):
        return ""
    words = tokens(stripped)
    kept = [w for w in words if w not in LEGAL_ENDINGS] or words
    return " ".join(sorted(kept))


def norm_item_name(name: str, test_tags=()) -> str:
    """As norm_name, with numbers and units apart, so "Elbow 25mm" and "Elbow 25 mm" are the same name. The test tag
    goes first: split, a tag such as "qa3" would no longer be recognized."""
    return norm_name(_DIGIT_LETTER.sub(" ", strip_tag(name, test_tags)[0]))


def norm_email(value) -> str:
    if blank(value) or "@" not in str(value):
        return ""
    return str(value).strip().casefold()


def norm_phone(value) -> str:
    """Last ten digits, so country codes and formatting do not matter. Fewer digits, or one digit repeated, is no
    phone at all."""
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 10 or len(set(digits)) == 1:
        return ""
    return digits[-10:]


def norm_code(value) -> str:
    # SKU punctuation can be meaningful, so only case and outer spaces are ignored.
    return "" if blank(value) else str(value).strip().casefold()


def norm_website(value) -> str:
    if blank(value):
        return ""
    host = re.sub(r"^[a-z]+://", "", str(value).strip().casefold()).split("/")[0]
    return host.removeprefix("www.")


def active_roles(row) -> frozenset:
    roles = row.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if not isinstance(roles, list):
        return frozenset()
    active = set()
    for r in roles:
        if isinstance(r, str):
            active.add(r)
        elif (isinstance(r, dict) and isinstance(r.get("role"), str) and r["role"]
              and (r.get("active") is None or flag(r["active"]))):
            active.add(r["role"])
    return frozenset(active)


def first_address(row) -> dict:
    addresses = row.get("addresses") or []
    return addresses[0] if isinstance(addresses, list) and addresses and isinstance(addresses[0], dict) else {}


def _party_keys(row, test_tags) -> dict:
    address = first_address(row)
    city = [] if blank(address.get("city")) else tokens(address["city"])
    postal = norm_code(address.get("postal"))
    return {
        "customer_code": norm_code(row.get("customer_code")),
        "email": norm_email(row.get("email")),
        "phone": norm_phone(row.get("phone")),
        "name": norm_name(row.get("name") or "", test_tags),
        "website": norm_website(row.get("website")),
        "city_postal": f"{' '.join(city)}|{postal}" if city and postal else "",
    }


def _item_keys(row, test_tags) -> dict:
    return {
        "code": norm_code(row.get("code")),
        "sku": norm_code(row.get("sku")),
        "name": norm_item_name(row.get("name") or "", test_tags),
        "category": norm_code(row.get("category_id")),
        "uom": norm_code(row.get("uom")),
    }


PARTY_STRONG = ("customer_code", "email", "phone")
# Code and SKU can hold each other's value, so they group in one namespace: one item's SKU meets the other's code.
_BLOCK_NAMESPACE = {"sku": "code"}
ITEM_STRONG = ("code", "sku")


def _drop_shared(keys: dict[str, dict], strong) -> dict[str, int]:
    """Blank out strong values held by too many records; returns how many values were dropped per key. Keys that
    group together (code and SKU) are counted together, by record."""
    dropped = {}
    for space in dict.fromkeys(_BLOCK_NAMESPACE.get(key, key) for key in strong):
        fields = [key for key in strong if _BLOCK_NAMESPACE.get(key, key) == space]
        counts = Counter(v for k in keys.values() for v in {k[f] for f in fields} - {""})
        shared = {v for v, n in counts.items() if n > SHARED_LIMIT}
        if shared:
            dropped[space] = len(shared)
            for k in keys.values():
                for f in fields:
                    if k[f] in shared:
                        k[f] = ""
    return dropped


def _candidates(keys: dict[str, dict], block_on) -> tuple[set[tuple[str, str]], int]:
    """Pairs sharing any exact key, or a name word (so a typo in another word still meets). Returns the pairs and how
    many groups were skipped for being too common."""
    blocks = defaultdict(set)
    for rid, k in keys.items():
        for key in block_on:
            if k[key]:
                blocks[(_BLOCK_NAMESPACE.get(key, key), k[key])].add(rid)
        for word in set(k["name"].split()):
            if len(word) >= 3:
                blocks[("token", word)].add(rid)
    pairs, skipped = set(), 0
    for ids in blocks.values():
        if len(ids) > BLOCK_LIMIT:
            skipped += 1
            continue
        pairs.update(combinations(sorted(ids), 2))
    return pairs, skipped


def _name_signal(a: str, b: str):
    if not a or not b:
        return None
    if a == b:
        return "name"
    return "near_name" if SequenceMatcher(None, a, b).ratio() >= NEAR_NAME else None


def _contained(a: str, b: str) -> bool:
    """One item name is the other's with words added, such as a brand in front: "Arlo Door Closer Heavy" and "Door
    Closer Heavy". The shorter needs three words, so "Door Closer" does not meet every closer, and no added word may
    hold a digit, since that is a size or a model ("Door Closer Heavy 300mm"). A short number added to a long name
    can still be a near name by similarity."""
    wa, wb = set(a.split()), set(b.split())
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return len(short) >= 3 and short < long_ and not any(c.isdigit() for w in long_ - short for c in w)


def _score_party(a, b, ka, kb, oa, ob):
    """ka, kb: keys with widely shared values blanked, for evidence. oa, ob: the same keys before blanking, for
    conflicts: a value too common to prove two records are one still shows that they disagree."""
    signals, conflicts, caps = [], [], []
    for key in ("customer_code", "email", "phone", "website", "city_postal"):
        if ka[key] and ka[key] == kb[key]:
            signals.append(key)
        elif key in PARTY_STRONG and oa[key] and ob[key] and oa[key] != ob[key]:
            conflicts.append(key)
    name = _name_signal(ka["name"], kb["name"])
    if name:
        signals.append(name)
    if name == "near_name" and "customer_code" not in signals:
        caps.append("names differ slightly")  # a customer code is one customer's, not a household's
    ra, rb = active_roles(a), active_roles(b)
    if ra and rb and ra != rb:
        caps.append("roles differ")
    return signals, conflicts, caps, PARTY_WEIGHTS


def _alias(mine, theirs, my_other, their_other) -> bool:
    """Their value in this field is my value in the other field, and their other field is empty or my value here: one
    record stored the identifier in the other field. Anything more is two records with different identifiers."""
    return theirs == my_other and (not their_other or their_other == mine)


def _score_item(_a, _b, ka, kb, oa, ob):
    """As _score_party: evidence from the blanked keys, conflicts from the keys before blanking."""
    signals, conflicts = [], []
    codes_a, codes_b = {ka["code"], ka["sku"]} - {""}, {kb["code"], kb["sku"]} - {""}
    if codes_a & codes_b:
        signals.append("code")  # code and SKU can be aliases: one match counts once
    for key, other in (("code", "sku"), ("sku", "code")):
        if oa[key] and ob[key] and oa[key] != ob[key] and not (
                _alias(oa[key], ob[key], oa[other], ob[other]) or _alias(ob[key], oa[key], ob[other], oa[other])):
            conflicts.append(key)
    name = _name_signal(ka["name"], kb["name"]) or (
        "near_name" if ka["name"] and kb["name"] and _contained(ka["name"], kb["name"]) else None)
    if name:
        signals.append(name)
    for key in ("category", "uom"):
        if ka[key] and ka[key] == kb[key]:
            signals.append(key)
    return signals, conflicts, [], ITEM_WEIGHTS


def _excluded_party(a, b) -> str | None:
    if flag(a.get("allow_duplicate")) or flag(b.get("allow_duplicate")):
        return "flagged as an allowed duplicate"
    if a.get("company_id") and b.get("company_id") and a["company_id"] != b["company_id"]:
        return "different companies"
    if norm_code(a.get("type")) and norm_code(b.get("type")) and norm_code(a["type"]) != norm_code(b["type"]):
        return "individual and organisation"
    return None


def _variant_codes(row) -> set[str]:
    variants = row.get("variants") or []
    if not isinstance(variants, list):
        return set()
    return {norm_code(v.get(k)) for v in variants if isinstance(v, dict) for k in ("sku", "code")} - {""}


def _excluded_item(a, b) -> str | None:
    if a.get("company_id") and b.get("company_id") and a["company_id"] != b["company_id"]:
        return "different companies"
    for key, reason in (("product_type", "different kinds"), ("type", "different kinds"), ("uom", "different units")):
        va, vb = norm_code(a.get(key)), norm_code(b.get(key))
        if va and vb and va != vb:
            return reason
    codes_a = {norm_code(a.get("code")), norm_code(a.get("sku"))} - {""}
    codes_b = {norm_code(b.get("code")), norm_code(b.get("sku"))} - {""}
    if codes_b & _variant_codes(a) or codes_a & _variant_codes(b):
        return "variant of the other item"
    return None


def band(score: float, capped: bool) -> str:
    if score < REVIEW:
        return "dropped"
    return "propose" if score >= PROPOSE and not capped else "review"


def find_duplicates(entity: str, rows: list[dict], test_tags=()) -> dict:
    """Every candidate pair of `rows`, scored and banded.

    entity: "party" or "item". test_tags: confirmed test-run tags (from local/, never hard-coded here).
    Parties under a privacy state other than the ordinary one, or with none, are counted and left out before
    grouping, so no detail of theirs reaches a pair. An excluded pair is listed with its reason only when it scored
    review or better: a low-scoring pair that is also excluded is just dropped.
    """
    if entity not in ("party", "item"):
        raise ValueError(f"unknown entity {entity!r}")
    withheld = repeated = 0
    by_id = {}
    for row in rows:
        if entity == "party" and row.get("privacy_state") != ORDINARY_PRIVACY:
            withheld += 1
            continue
        rid = str(row["id"])
        if rid in by_id:
            repeated += 1  # pages that shifted while being read; the first copy is kept
            continue
        by_id[rid] = row
    key_fn, score_fn, exclude_fn, strong, block_on = (
        (_party_keys, _score_party, _excluded_party, PARTY_STRONG, ("customer_code", "email", "phone", "website"))
        if entity == "party" else
        (_item_keys, _score_item, _excluded_item, ITEM_STRONG, ("code", "sku")))
    keys = {rid: key_fn(row, test_tags) for rid, row in by_id.items()}
    original = {rid: dict(k) for rid, k in keys.items()}
    ignored_shared = _drop_shared(keys, strong)

    candidates, skipped_blocks = _candidates(keys, block_on + ("name",))
    pairs, excluded, dropped = [], [], 0
    for ida, idb in sorted(candidates):
        a, b = by_id[ida], by_id[idb]
        signals, conflicts, caps, weights = score_fn(a, b, keys[ida], keys[idb], original[ida], original[idb])
        score = round(min(1.0, sum(weights[s] for s in signals)), 2)
        if conflicts:
            caps = [f"{c} differs" for c in conflicts] + caps
        result = {
            "id": f"{entity}:{ida}:{idb}",
            "entity": entity,
            "ids": [ida, idb],
            "score": score,
            "band": band(score, bool(caps)),
            "signals": signals,
            "caps": caps,
            "tagged": strip_tag(a.get("name") or "", test_tags)[1] or strip_tag(b.get("name") or "", test_tags)[1],
        }
        if result["band"] == "dropped":
            dropped += 1
            continue
        reason = exclude_fn(a, b)
        if reason:
            excluded.append({**result, "band": "excluded", "reason": reason})
            continue
        pairs.append(result)

    in_pairs = Counter(rid for p in pairs for rid in p["ids"])
    for p in pairs:
        p["shared_record"] = any(in_pairs[rid] > 1 for rid in p["ids"])
    pairs.sort(key=lambda p: (BAND_ORDER[p["band"]], p["id"]))
    excluded.sort(key=lambda p: p["id"])
    return {"entity": entity, "rules_version": RULES_VERSION, "rows": len(rows), "withheld_private": withheld,
            "repeated_ids": repeated, "ignored_shared": ignored_shared, "skipped_blocks": skipped_blocks,
            "pairs": pairs, "excluded": excluded, "dropped": dropped}


def evaluate(result: dict, duplicates, distinct) -> dict:
    """Compare a result with known answers. `duplicates` and `distinct` are lists of id pairs.

    A known duplicate that is not in a listed band is a miss, whether grouping never met the pair or its score fell
    below review; one that an exclusion rule held back is reported apart, since no weight can bring it back. A known
    non-duplicate in a band is a wrong proposal for that band.
    """
    known_dup = {tuple(sorted(map(str, p))) for p in duplicates}
    known_distinct = {tuple(sorted(map(str, p))) for p in distinct}
    by_band = {"propose": Counter(), "review": Counter()}
    listed = set()
    for p in result["pairs"]:
        pair = tuple(p["ids"])
        listed.add(pair)
        by_band[p["band"]]["right" if pair in known_dup else "wrong" if pair in known_distinct else "unlabelled"] += 1
    excluded = {tuple(p["ids"]) for p in result["excluded"]} & known_dup
    return {
        "bands": {b: dict(c) for b, c in by_band.items()},
        "missed": sorted(known_dup - listed - excluded),
        "excluded": sorted(excluded),
        "wrong": sorted((p["band"], tuple(p["ids"])) for p in result["pairs"] if tuple(p["ids"]) in known_distinct),
    }


if __name__ == "__main__":
    # The command lives in report.py, so importing this module never pulls in the network client.
    from data_steward.report import main

    raise SystemExit(main())
