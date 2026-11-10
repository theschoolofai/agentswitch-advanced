"""Turn the text of a document into proposed fields, flags and a confidence.

Rules only: the same text always gives the same result, it uses no tokens, and
the text is only ever parsed, so nothing written in a document can act as an
instruction. Everything here is a proposal for a person to review.

All document text is written by whoever sent the document. Other people and agents
will read the fields we propose, so text that looks like an instruction or markup
is withheld from them and flagged. Nothing here can call a tool.

Confidence is a rule score from 0 to 1, not a probability.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

# The two made-up companies in the course sample set. A live run will take the
# company from the platform instead.
SAMPLE_OWN_GSTINS = frozenset({"29AAACD0000A1Z5", "29AAACS0000B1Z7"})

# The same threshold the platform's bill intake uses.
REVIEW_THRESHOLD = 0.85
TOLERANCE = Decimal("0.01")

GSTIN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z])\b")
PARTY_LABEL = re.compile(
    r"^(?:bill(?:ed)?\s+to|buyer|customer|credit(?:ed)?\s+to|issued\s+to)\s*:?\s*$", re.I
)
TABLE_HEADER = re.compile(r"^amount$|\bqty\b.*\bamount\b", re.I)
AMOUNT_TEXT = r"\(?-?\d(?:[\d,.]*\d)?\)?"
AMOUNT_SEARCH = re.compile(AMOUNT_TEXT)
AMOUNT_ONLY = re.compile(rf"^{AMOUNT_TEXT}$")
LINE_ON_ONE_ROW = re.compile(rf"^(.+?)\s+({AMOUNT_TEXT})\s+({AMOUNT_TEXT})\s+({AMOUNT_TEXT})$")

NUMBER_LABELS = (
    r"credit\s*note\s*(?:#|no\.?|number)",
    r"cn\s*(?:#|no\.?)",
    r"note\s*(?:#|no\.?)",
    r"bill\s*(?:#|no\.?|number)",
    r"inv(?:oice)?\.?\s*(?:#|no\.?|number)",
    r"document\s*(?:#|no\.?)",
    r"ref(?:erence)?(?:\s*no\.?)?",
)
DUE_LABEL = re.compile(r"^(?:pay\s*by|payment\s*due|due\s*on|due\s*date|due)\s*:\s*(.+)$", re.I)
DATE_LABEL = re.compile(
    r"^(?:bill\s*date|invoice\s*date|credit\s*note\s*date|note\s*date|issued(?:\s*on)?|dt\.?|date)"
    r"\s*:\s*(.+)$",
    re.I,
)
ORIGINAL_LABEL = re.compile(
    r"^(?:against(?:\s*(?:invoice|inv\.?|bill))?|original\s*(?:invoice|bill)(?:\s*no\.?)?|"
    r"ref(?:erence)?\.?\s*(?:invoice|inv\.?|bill)(?:\s*no\.?)?)\s*:?\s*(\S.*)$",
    re.I,
)
SUBTOTAL_LABEL = re.compile(r"^(?:sub\s*-?\s*total|taxable\s+(?:value|amount)|net\s+total)\b", re.I)
TOTAL_LABEL = re.compile(r"^(?:(?:grand|credit)\s+)?total(?:\s+(?:amount|payable|due|credit))?\b", re.I)
TAX_LABEL = re.compile(r"^(CGST|SGST|UTGST|IGST|VAT|GST|Tax|Cess)\b(?:\s*@\s*(\d{1,3}(?:\.\d{1,4})?)\s*%)?", re.I)
NO_TAX = re.compile(r"\b(?:exempt|no\s+tax|not\s+applicable|nil[\s-]rated|zero[\s-]rated)\b", re.I)
CURRENCIES = (
    ("INR", re.compile(r"₹|\bRs\.?|\bINR\b", re.I)),
    ("USD", re.compile(r"US\$|\$|\bUSD\b", re.I)),
    ("EUR", re.compile(r"€|\bEUR\b", re.I)),
    ("GBP", re.compile(r"£|\bGBP\b", re.I)),
)
DATE_FORMATS = ("%d %b %Y", "%d %B %Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y")
NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")
TITLES = frozenset({"CREDIT NOTE", "DEBIT NOTE", "TAX INVOICE", "INVOICE", "BILL", "PURCHASE ORDER", "RECEIPT"})

INDIA_ADDRESS = re.compile(r"\bIndia\b")
US_ADDRESS = re.compile(
    r"\bUnited States\b|(?<![A-Za-z])U\.?S\.?A?\.?(?![A-Za-z])|\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b|"
    r"\b(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|"
    r"Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|"
    r"Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|"
    r"North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|"
    r"Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming)\b"
)
DAY_FIRST_BY_COUNTRY = {"IN": True, "US": False}
DAY_FIRST_BY_CURRENCY = {"INR": True, "USD": False}
# How much each clue to the date order is trusted. Below the review threshold, a person looks first.
DATE_CONFIDENCE = {"document": 0.95, "not_needed": 0.95, "vendor": 0.9, "company": 0.7, "currency": 0.7, "none": 0.0}

# Limits on what one document may contain. Beyond these, a person reads it.
MAX_TEXT_CHARS = 200_000
MAX_LINE_CHARS = 2_000
MAX_NAME_CHARS = 120
MAX_DESCRIPTION_CHARS = 300
MAX_AMOUNT_DIGITS = 18
MAX_PLAUSIBLE_AMOUNT = Decimal(10) ** 12
MAX_TAX_RATE = Decimal(100)
EARLIEST_YEAR, LATEST_YEAR = 2000, 2099
NEAR_DUPLICATE_DAYS = 7
WITHHELD = "[withheld: suspicious text]"

DOCUMENT_NUMBER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 /_.\-#:]{0,39}$")
COMMA_DECIMAL = re.compile(r"\d,\d{2}\)?(?=\s|$)")
DOT_DECIMAL = re.compile(r"\d\.\d{2}\)?(?=\s|$)")
# Instructions aimed at an AI model or a hurried reader. Kept narrow, because "please pay this
# invoice" is normal on a bill.
INSTRUCTION_TEXT = re.compile(
    r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,40}\b(?:instructions?|prompts?|rules?|guidelines?|"
    r"checks?|validation|policy|policies)\b|"
    r"\byou\s+are\s+now\b|\bact\s+as\s+(?:an?\s+)?(?:admin|system|assistant|agent)\b|\bpretend\s+to\s+be\b|"
    r"\b(?:new|updated|hidden)\s+instructions?\b|\bsystem\s+(?:prompt|message|override)\b|"
    r"(?:^|\s)(?:system|assistant|developer)\s*:\s|\b(?:admin|developer|debug|god)\s+mode\b|\bjailbreak\b|"
    r"\b(?:call|use|run|invoke|execute)\s+(?:the\s+)?(?:\w+\s+)?tool\b|tools/call|\bendpoint\.\w+|"
    r"\b(?:Bill|Invoice|FundTransfer|PaymentMade|VendorCredit|CreditNote)\.(?!pdf\b|docx?\b|xlsx?\b|png\b|jpe?g\b)"
    r"[a-z_]+\b|"
    r"\b(?:auto[-\s]?approve|pre[-\s]?approved|already\s+approved)\b|"
    r"\b(?:approve|post|submit|accept)\s+(?:this|these|the|all)\s+(?:\w+\s+)?(?:bills?|invoices?|documents?)\b|"
    r"\b(?:skip|no|without)\s+(?:the\s+|any\s+)?(?:human\s+)?(?:review|approval)\b|"
    r"\b(?:mark|set)\s+(?:this\s+|it\s+)?(?:as\s+)?(?:paid|approved|needs_review|confidence)\b|"
    r"<\|[a-z_]+\|>|\[/?INST\]|<<\s*/?SYS\s*>>|#{2,}\s*(?:system|instruction)|"
    r"(?:निर्देशों|निर्देश)\s*(?:को)?\s*(?:अनदेखा|नज़रअंदाज़)",
    re.I,
)
MARKUP_TEXT = re.compile(
    r"<\s*/?\s*(?:script|img|iframe|svg|object|embed|a|style|link|meta|form)\b|\bjavascript:|\bon\w+\s*=|"
    r"!?\[[^\]]{0,200}\]\([^)]{0,500}\)|=\s*[A-Z]{2,}\(",
    re.I,
)
# Stricter, for values that will sit in a record or a spreadsheet cell.
UNSAFE_FIELD = re.compile(r"^[=+@\t]|https?://|\bdata:[a-z]+/", re.I)
ENCODED_BLOB = re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")

# Flags that always send a document to a person first, whatever its score.
REVIEW_FLAGS = frozenset({
    "total_mismatch",
    "lines_do_not_match_subtotal",
    "line_amount_mismatch",
    "tax_rate_mismatch",
    "tax_type_state_mismatch",
    "due_before_bill_date",
    "unknown_counterparty",
    "unknown_document_type",
    "no_text_layer",
    "unparsed_date",
    "ambiguous_date_order",
    "mixed_currencies",
    "possible_duplicate",
    "totals_not_verifiable",
    "no_line_items",
    "non_positive_total",
    "implausible_amount",
    "invalid_document_number",
    "instruction_like_text",
    "unsafe_markup",
})
# Signs that the values themselves cannot be trusted. No draft is proposed for these.
# Instruction-like text is not here: the values are unaffected and the text is withheld.
TAMPER_FLAGS = frozenset({
    "conflicting_values",
    "own_gstin_on_both_sides",
    "mixed_number_formats",
    "hidden_characters",
    "lookalike_characters",
    "text_too_long",
    "pdf_hidden_text",
    "pdf_overlay_content",
    "pdf_active_content",
    "pdf_font_remap",
    "pdf_modified_after_creation",
    "pdf_structure_anomaly",
    "pdf_unread_image",
})


def error_document(code: str) -> dict[str, Any]:
    """The result for a file that could not be read. It creates no record."""
    return {"doc_type": "unknown", "error": code, "flags": [code], "confidence": 0.0, "field_confidence": {},
            "needs_review": True, "proposed_action": "report_error"}


def _clean_text(text: str) -> "tuple[str, list[str]]":
    """Remove characters a person cannot see, so the rules read what a person reads."""
    flags = []
    if len(text) > MAX_TEXT_CHARS:
        text, flags = text[:MAX_TEXT_CHARS], ["text_too_long"]
    kept, hidden = [], False
    for char in text:
        if char in "\n\r\t ":
            kept.append(char)
        elif char == "\f":
            kept.append("\n")
        else:
            category = unicodedata.category(char)
            if category in {"Cc", "Cf", "Cs", "Cn"}:
                hidden = True
            elif category != "Co":  # Private-use characters are usually bullets from a symbol font.
                kept.append(char)
    if hidden:
        flags.append("hidden_characters")
    return "".join(kept), flags


def _has_lookalike_characters(text: str) -> bool:
    """Catch words that mix alphabets, like a Cyrillic letter inside a Latin word."""
    if text.isascii():
        return False
    for word in re.findall(r"\w+", text):
        if word.isascii():
            continue
        scripts = set()
        for char in word:
            if unicodedata.category(char) == "Nd" and not char.isascii():
                return True
            name = unicodedata.name(char, "")
            if name.startswith(("FULLWIDTH", "MATHEMATICAL")):
                return True
            scripts.add(name.split(" ")[0])
        if "LATIN" in scripts and scripts & {"CYRILLIC", "GREEK"}:
            return True
    return False


def _text_flags(text: str) -> list[str]:
    flags = []
    flat = " ".join(text.split())
    if INSTRUCTION_TEXT.search(flat) or ENCODED_BLOB.search(flat):
        flags.append("instruction_like_text")
    if MARKUP_TEXT.search(flat):
        flags.append("unsafe_markup")
    if _has_lookalike_characters(text):
        flags.append("lookalike_characters")
    return flags


def _is_unsafe_field(value: str, limit: int = MAX_NAME_CHARS) -> bool:
    return len(value) > limit or any(
        pattern.search(value) for pattern in (INSTRUCTION_TEXT, MARKUP_TEXT, UNSAFE_FIELD, ENCODED_BLOB)
    )


def _withhold_unsafe_fields(doc: dict[str, Any], flags: list[str]) -> None:
    """Keep attacker-written text out of fields that others will read."""
    found = False
    for key in ("seller_name", "buyer_name", "counterparty_name", "original_invoice"):
        if doc[key] and _is_unsafe_field(doc[key]):
            doc[key], found = None, True
    for row in doc["lines"]:
        if _is_unsafe_field(row["description"], MAX_DESCRIPTION_CHARS):
            row["description"], found = WITHHELD, True
    number = doc["invoice_number"]
    if number and (not DOCUMENT_NUMBER.match(number) or _is_unsafe_field(number)):
        doc["invoice_number"] = None
        flags.append("invalid_document_number")
    if found and not {"instruction_like_text", "unsafe_markup"} & set(flags):
        flags.append("unsafe_markup")


def parse_amount(text: str, decimal_comma: bool = False) -> Optional[Decimal]:
    """Parse 24,000.00 or 1,13,067.60, or 1.094,37 when decimal_comma is set."""
    # Find the number first: the dot in "Rs." must not become part of it.
    match = AMOUNT_SEARCH.search(text)
    if not match:
        return None
    cleaned = match.group(0)
    negative = cleaned.startswith(("-", "(")) or cleaned.endswith(")")
    cleaned = cleaned.strip("()-")
    if sum(char.isdigit() for char in cleaned) > MAX_AMOUNT_DIGITS:
        return None
    if decimal_comma:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -value if negative else value


def _number_style(lines: list[str]) -> "tuple[bool, list[str]]":
    """Decide how decimals are written, from the amounts themselves.

    One stray "1,50" must not change how every other amount reads: under a decimal
    comma, 500.00 becomes 50000 and the sums still agree. So mixed writing stays
    on the usual style and goes to a person.
    """
    comma = any(COMMA_DECIMAL.search(line) for line in lines)
    dot = any(DOT_DECIMAL.search(line) for line in lines)
    if comma and dot:
        return False, ["mixed_number_formats"]
    return comma, []


def _day_first(raw_dates: list[str]) -> Optional[bool]:
    """Use any date in the document that can only be read one way."""
    for raw in raw_dates:
        match = NUMERIC_DATE.match(raw.strip())
        if match:
            if int(match.group(1)) > 12:
                return True
            if int(match.group(2)) > 12:
                return False
    return None


def parse_date(text: str, day_first: bool = True) -> Optional[date]:
    cleaned = text.strip()
    match = NUMERIC_DATE.match(cleaned)
    if match:
        first, second, year = (int(part) for part in match.groups())
        day, month = (first, second) if day_first else (second, first)
        try:
            return _plausible_date(date(year, month, day))
        except ValueError:
            return None
    for pattern in DATE_FORMATS:
        try:
            return _plausible_date(datetime.strptime(cleaned, pattern).date())
        except ValueError:
            continue
    return None


def _plausible_date(value: date) -> Optional[date]:
    return value if EARLIEST_YEAR <= value.year <= LATEST_YEAR else None


def _is_ambiguous_numeric_date(text: str) -> bool:
    match = NUMERIC_DATE.match(text.strip())
    return bool(match) and int(match.group(1)) <= 12 and int(match.group(2)) <= 12 \
        and int(match.group(1)) != int(match.group(2))


def _issuer_lines(lines: list[str]) -> list[str]:
    """The issuer's address block, which sits between its name and the document's title."""
    block = []
    for line in lines[1:]:
        if line.upper() in TITLES or PARTY_LABEL.match(line):
            break
        block.append(line)
    return block


def _date_order(raw_dates: list[str], seller_gstin: Optional[str], issuer_lines: list[str],
                own_country: Optional[str], currency: Optional[str]) -> "tuple[Optional[bool], str]":
    """Return whether dates are day-first, and which clue said so.

    The issuer wrote the date, so its country comes before ours. Currency comes
    last, because an Indian vendor can bill in dollars. With no clue, the answer
    is None and the date stays empty.
    """
    settled = _day_first(raw_dates)
    if settled is not None:
        return settled, "document"
    if not any(_is_ambiguous_numeric_date(raw) for raw in raw_dates):
        return True, "not_needed"
    address = "\n".join(issuer_lines)
    if seller_gstin or INDIA_ADDRESS.search(address):
        return True, "vendor"
    if US_ADDRESS.search(address):
        return False, "vendor"
    if own_country in DAY_FIRST_BY_COUNTRY:
        return DAY_FIRST_BY_COUNTRY[own_country], "company"
    if currency in DAY_FIRST_BY_CURRENCY:
        return DAY_FIRST_BY_CURRENCY[currency], "currency"
    return None, "none"


def _read_date(raw: Optional[str], day_first: Optional[bool]) -> Optional[date]:
    if not raw or (day_first is None and _is_ambiguous_numeric_date(raw)):
        return None
    return parse_date(raw, day_first is not False)


def _first_labelled(lines: list[str], label: re.Pattern) -> Optional[str]:
    for line in lines:
        match = label.match(line)
        if match:
            return match.group(1).strip()
    return None


def _document_number(lines: list[str]) -> Optional[str]:
    for label in NUMBER_LABELS:
        pattern = re.compile(rf"^{label}\s*:?\s*(\S.*)$", re.I)
        for line in lines:
            if ORIGINAL_LABEL.match(line):
                continue
            match = pattern.match(line)
            if match:
                return match.group(1).strip()
    return None


def _distinct_document_numbers(lines: list[str]) -> set[str]:
    """Numbers under a label that means this document. A reference can differ, so it is left out."""
    found = set()
    for label in NUMBER_LABELS[:-1]:
        pattern = re.compile(rf"^{label}\s*:?\s*(\S.*)$", re.I)
        for line in lines:
            match = pattern.match(line)
            if match and not ORIGINAL_LABEL.match(line):
                found.add(_number_key(match.group(1)))
    return found


def _all_labelled(lines: list[str], label: re.Pattern) -> list[str]:
    return [match.group(1).strip() for match in map(label.match, lines) if match]


def _has_conflicts(lines: list[str], parties: dict[str, Optional[str]], day_first: Optional[bool]) -> bool:
    """A value stated twice with different answers means someone has to decide which is real."""
    titles = {line.upper() for line in lines if line.upper() in TITLES}
    party_labels = sum(1 for line in lines if PARTY_LABEL.match(line))
    dates_differ = any(
        len({_read_date(raw, day_first) or raw for raw in _all_labelled(lines, label)}) > 1
        for label in (DATE_LABEL, DUE_LABEL)
    )
    return (
        len(titles) > 1 or party_labels > 1 or dates_differ
        or len(_distinct_document_numbers(lines)) > 1
        or len(parties["seller_gstins"]) > 1 or len(parties["buyer_gstins"]) > 1
    )


def _title(lines: list[str]) -> str:
    for line in lines[:12]:
        upper = line.upper().strip()
        if upper in TITLES:
            return upper
    return ""


def _classify(title: str, seller_gstin: Optional[str], buyer_gstin: Optional[str],
              own_gstins: frozenset[str]) -> "tuple[str, list[str]]":
    if title == "CREDIT NOTE":
        return "credit_note", []
    if title == "PURCHASE ORDER":
        return "purchase_order", []
    if title == "RECEIPT":
        return "receipt", []
    if title not in {"TAX INVOICE", "INVOICE", "BILL"}:
        return "unknown", ["unknown_document_type"]
    # The title cannot decide this: bills and our own sales invoices can both
    # say TAX INVOICE. What matters is which side of the document we are on.
    if buyer_gstin in own_gstins:
        return "vendor_bill", []
    if seller_gstin in own_gstins:
        return "sales_invoice", []
    return "unknown", ["unknown_counterparty"]


def _party_details(lines: list[str]) -> dict[str, Optional[str]]:
    party_index = next((i for i, line in enumerate(lines) if PARTY_LABEL.match(line)), None)
    header = lines if party_index is None else lines[:party_index]
    block = [] if party_index is None else lines[party_index + 1:party_index + 5]
    seller_gstins = [m.group(1) for m in map(GSTIN.search, header) if m]
    buyer_gstins = [m.group(1) for m in map(GSTIN.search, block) if m]
    return {
        "seller_name": lines[0] if lines else None,
        "seller_gstin": seller_gstins[0] if seller_gstins else None,
        "buyer_name": block[0] if block else None,
        "buyer_gstin": buyer_gstins[0] if buyer_gstins else None,
        "seller_gstins": set(seller_gstins),
        "buyer_gstins": set(buyer_gstins),
    }


def _line_items(table: list[str], decimal_comma: bool) -> list[dict[str, Any]]:
    items, description, numbers = [], [], []
    for line in table:
        one_row = LINE_ON_ONE_ROW.match(line)
        if one_row and not description:
            values = [parse_amount(part, decimal_comma) for part in one_row.groups()[1:]]
            if None not in values:
                items.append({"description": one_row.group(1), "qty": values[0],
                              "rate": values[1], "amount": values[2]})
                continue
        if AMOUNT_ONLY.match(line) and description:
            numbers.append(parse_amount(line, decimal_comma))
            if len(numbers) == 3:
                if None not in numbers:
                    items.append({"description": " ".join(description), "qty": numbers[0],
                                  "rate": numbers[1], "amount": numbers[2]})
                description, numbers = [], []
        else:
            description.append(line)
    return items


def _labelled_amount(lines: list[str], index: int, label: re.Pattern, decimal_comma: bool
                     ) -> "tuple[Optional[Decimal], str]":
    """Return the amount for a label on the same line or the next one, and its text."""
    remainder = label.sub("", lines[index], count=1).strip()
    text = remainder if re.search(r"\d", remainder) else ""
    if not text and index + 1 < len(lines) and re.search(r"\d", lines[index + 1]):
        text = lines[index + 1]
    return (parse_amount(text, decimal_comma) if text else None), text


def _currency(money_texts: list[str]) -> "tuple[Optional[str], list[str]]":
    found = []
    for text in money_texts:
        for code, pattern in CURRENCIES:
            if pattern.search(text) and code not in found:
                found.append(code)
    flags = ["mixed_currencies"] if len(found) > 1 else []
    return (found[0] if found else None), flags


def _read_totals(lines: list[str], decimal_comma: bool) -> dict[str, Any]:
    totals: dict[str, Any] = {"net": None, "total": None, "tax": None, "taxes": [],
                              "no_tax": False, "exempt": False, "money_texts": [], "conflict": False}
    tax_sum = Decimal(0)

    def record(key: str, amount: Optional[Decimal]) -> None:
        # Two different answers for one value: leave it empty rather than pick one.
        if amount is None:
            return
        if totals.get(key + "_seen") not in (None, amount):
            totals["conflict"] = True
        totals[key + "_seen"] = amount
        totals[key] = None if totals["conflict"] else amount

    for index, line in enumerate(lines):
        if SUBTOTAL_LABEL.match(line):
            amount, text = _labelled_amount(lines, index, SUBTOTAL_LABEL, decimal_comma)
            record("net", amount)
        elif TOTAL_LABEL.match(line):
            amount, text = _labelled_amount(lines, index, TOTAL_LABEL, decimal_comma)
            record("total", amount)
        elif NO_TAX.search(line):
            totals["no_tax"] = True
            totals["exempt"] = totals["exempt"] or "exempt" in line.lower()
            continue
        elif TAX_LABEL.match(line):
            match = TAX_LABEL.match(line)
            amount, text = _labelled_amount(lines, index, TAX_LABEL, decimal_comma)
            if amount is not None:
                tax_sum += amount
                rate = Decimal(match.group(2)) if match.group(2) else None
                totals["taxes"].append({"type": match.group(1).upper(), "rate": rate, "amount": amount})
        else:
            continue
        if text:
            totals["money_texts"].append(text)
    if totals["taxes"]:
        totals["tax"] = tax_sum
    elif totals["no_tax"]:
        totals["tax"] = Decimal(0)
    if totals["conflict"]:
        totals["net"] = totals["total"] = None
    return totals


def _check_amounts(items: list[dict[str, Any]], totals: dict[str, Any],
                   seller_gstin: Optional[str], buyer_gstin: Optional[str]) -> list[str]:
    flags = []
    net, tax, total = totals["net"], totals["tax"], totals["total"]
    if any(abs(row["qty"] * row["rate"] - row["amount"]) > TOLERANCE for row in items):
        flags.append("line_amount_mismatch")
    if items and net is not None and abs(sum(row["amount"] for row in items) - net) > TOLERANCE:
        flags.append("lines_do_not_match_subtotal")
    if None not in (net, tax, total) and abs(net + tax - total) > TOLERANCE:
        flags.append("total_mismatch")
    if total is not None and None in (net, tax):
        # Without both parts, nothing checks the total, so a person has to.
        flags.append("totals_not_verifiable")
    if total is not None and not items:
        flags.append("no_line_items")
    amounts = [net, total, *(row["amount"] for row in items)]
    if any(value is not None and abs(value) >= MAX_PLAUSIBLE_AMOUNT for value in amounts) or any(
        row["rate"] is not None and row["rate"] > MAX_TAX_RATE for row in totals["taxes"]
    ):
        flags.append("implausible_amount")
    if net is not None and any(
        row["rate"] is not None and abs(net * row["rate"] / 100 - row["amount"]) > TOLERANCE
        for row in totals["taxes"]
    ):
        flags.append("tax_rate_mismatch")
    kinds = {row["type"] for row in totals["taxes"]}
    if seller_gstin and buyer_gstin and kinds:
        same_state = seller_gstin[:2] == buyer_gstin[:2]
        if ("IGST" in kinds and same_state) or (kinds & {"CGST", "SGST"} and not same_state):
            flags.append("tax_type_state_mismatch")
    if totals["exempt"]:
        flags.append("tax_exempt")
    if any(row["amount"] < 0 for row in items):
        flags.append("has_discount_line")
    return flags


def _confidence(doc: dict[str, Any], flags: list[str], date_confidence: float) -> dict[str, float]:
    reconciled = not {"total_mismatch", "lines_do_not_match_subtotal", "totals_not_verifiable"} & set(flags)
    return {
        "vendor": 0.0 if not doc["seller_name"] else (0.95 if doc["seller_gstin"] else 0.7),
        "invoice_number": 0.95 if doc["invoice_number"] else 0.0,
        "invoice_date": date_confidence if doc["invoice_date"] else 0.0,
        "currency": 0.95 if doc["currency"] else 0.0,
        "total_stated": 0.0 if doc["total_stated"] is None else (0.98 if reconciled else 0.5),
    }


def _proposed_action(doc_type: str) -> str:
    return {
        "vendor_bill": "draft_bill",
        "sales_invoice": "reject_not_a_bill",
        "credit_note": "review_credit_note",
    }.get(doc_type, "review")


def _as_output(value: Optional[Decimal]) -> Optional[float]:
    return None if value is None else float(value)


def _counterparty(doc_type: str, parties: dict[str, Optional[str]], own_gstins: frozenset[str]
                  ) -> "tuple[Optional[str], Optional[str]]":
    """The other company on the document. Unknown stays empty rather than guessed."""
    seller = (parties["seller_name"], parties["seller_gstin"])
    buyer = (parties["buyer_name"], parties["buyer_gstin"])
    if doc_type == "vendor_bill":
        return seller
    if doc_type == "sales_invoice":
        return buyer
    if parties["seller_gstin"] in own_gstins:
        return buyer
    if parties["buyer_gstin"] in own_gstins:
        return seller
    return None, None


def _tax_type(totals: dict[str, Any]) -> Optional[str]:
    """Unknown stays empty: "no tax" is only for a document that says so."""
    taxes = totals["taxes"]
    kinds = {row["type"] for row in taxes}
    if not kinds:
        return "NONE" if totals["no_tax"] else None
    if kinds == {"CGST", "SGST"}:
        return "CGST_SGST"
    return "_".join(sorted(kinds))


def _tax_rate_percent(totals: dict[str, Any]) -> Optional[Any]:
    """The combined rate, so CGST 9% plus SGST 9% is 18. A document that says no tax is 0."""
    taxes = totals["taxes"]
    if not taxes:
        return 0 if totals["no_tax"] else None
    if any(row["rate"] is None for row in taxes):
        return None
    total = sum(row["rate"] for row in taxes)
    return int(total) if total == int(total) else float(total)


def parse_document(text: str, own_gstins: frozenset[str] = SAMPLE_OWN_GSTINS,
                   base_currency: str = "INR", own_country: Optional[str] = None,
                   pdf_flags: "tuple[str, ...]" = ()) -> dict[str, Any]:
    """Parse one document's text into proposed fields, flags and a confidence.

    own_country ("IN" or "US") is a clue to how dates are written. pdf_flags are
    findings about the file itself, from pdf_guard.
    """
    text, safety_flags = _clean_text(text)
    safety_flags = [*pdf_flags, *safety_flags]
    all_lines = [line.strip() for line in text.splitlines() if line.strip()]
    lines = [line for line in all_lines if len(line) <= MAX_LINE_CHARS]
    if len(lines) != len(all_lines) and "text_too_long" not in safety_flags:
        safety_flags.append("text_too_long")
    if not lines:
        return {"doc_type": "unknown", "flags": [*safety_flags, "no_text_layer"], "confidence": 0.0,
                "field_confidence": {}, "needs_review": True, "proposed_action": "review"}
    safety_flags += _text_flags(text)

    header_end = next((i for i, line in enumerate(lines) if TABLE_HEADER.search(line)), len(lines))
    subtotal_at = next((i for i, line in enumerate(lines) if SUBTOTAL_LABEL.match(line)), len(lines))
    header, table, footer = lines[:header_end], lines[header_end + 1:subtotal_at], lines[subtotal_at:]
    decimal_comma, style_flags = _number_style(table + footer)

    parties = _party_details(lines)
    doc_type, flags = _classify(_title(header), parties["seller_gstin"], parties["buyer_gstin"], own_gstins)
    flags += style_flags
    if parties["seller_gstin"] and parties["seller_gstin"] == parties["buyer_gstin"]:
        flags.append("own_gstin_on_both_sides")

    items = _line_items(table, decimal_comma)
    totals = _read_totals(footer, decimal_comma)
    currency, currency_flags = _currency(totals["money_texts"])

    raw_date, raw_due = _first_labelled(header, DATE_LABEL), _first_labelled(header, DUE_LABEL)
    known_dates = [raw for raw in (raw_date, raw_due) if raw]
    day_first, date_clue = _date_order(known_dates, parties["seller_gstin"], _issuer_lines(lines),
                                       own_country, currency)
    bill_date, due_date = _read_date(raw_date, day_first), _read_date(raw_due, day_first)
    conflict = totals["conflict"] or _has_conflicts(lines, parties, day_first)
    if conflict:
        flags.append("conflicting_values")
    if date_clue in {"company", "currency", "none"}:
        flags.append("ambiguous_date_order")
    if date_clue != "none" and ((raw_date and not bill_date) or (raw_due and not due_date)):
        flags.append("unparsed_date")
    if not raw_due:
        flags.append("no_due_date")
    if bill_date and due_date and due_date < bill_date:
        flags.append("due_before_bill_date")

    flags += currency_flags
    if currency and currency != base_currency:
        flags.append("foreign_currency")
    flags += _check_amounts(items, totals, parties["seller_gstin"], parties["buyer_gstin"])
    if totals["total"] is not None and totals["total"] <= 0 and doc_type != "credit_note":
        flags.append("non_positive_total")

    counterparty_name, counterparty_gstin = _counterparty(doc_type, parties, own_gstins)
    doc = {
        "doc_type": doc_type,
        "seller_name": parties["seller_name"],
        "seller_gstin": parties["seller_gstin"],
        "buyer_name": parties["buyer_name"],
        "buyer_gstin": parties["buyer_gstin"],
        "counterparty_name": counterparty_name,
        "counterparty_gstin": counterparty_gstin,
        "tax_type": _tax_type(totals),
        "tax_rate_percent": _tax_rate_percent(totals),
        "invoice_number": _document_number(header),
        "original_invoice": _first_labelled(header, ORIGINAL_LABEL),
        "invoice_date": bill_date.isoformat() if bill_date else None,
        "due_date": due_date.isoformat() if due_date else None,
        "currency": currency,
        "subtotal": _as_output(totals["net"]),
        "tax_total": _as_output(totals["tax"]),
        "total_stated": _as_output(totals["total"]),
        "lines": [{key: (float(v) if isinstance(v, Decimal) else v) for key, v in row.items()}
                       for row in items],
    }
    # These lines change output only when a safety check found something.
    if conflict and len(_distinct_document_numbers(lines)) > 1:
        doc["invoice_number"] = None
    if conflict and len({_read_date(raw, day_first) or raw for raw in _all_labelled(lines, DATE_LABEL)}) > 1:
        doc["invoice_date"] = None
    flags += safety_flags
    _withhold_unsafe_fields(doc, flags)
    field_confidence = _confidence(doc, flags, DATE_CONFIDENCE[date_clue])
    confidence = min(field_confidence.values())
    found = set(flags)
    doc.update({
        "flags": flags,
        "field_confidence": field_confidence,
        "confidence": confidence,
        "needs_review": confidence < REVIEW_THRESHOLD or bool((REVIEW_FLAGS | TAMPER_FLAGS) & found),
        "proposed_action": "review" if TAMPER_FLAGS & found else _proposed_action(doc_type),
    })
    return doc


def _number_key(number: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", number)).upper()


def _loose_number_key(number: str) -> str:
    """Treat TP/001, TP-001 and TP/OO1 as the same, to catch a number altered on purpose."""
    letters = re.sub(r"[^A-Z0-9]", "", _number_key(number))
    return letters.translate(str.maketrans("OIL", "011"))


def _close_in_time(first: Optional[str], second: Optional[str]) -> bool:
    if not first or not second:
        return False
    gap = date.fromisoformat(first) - date.fromisoformat(second)
    return abs(gap.days) <= NEAR_DUPLICATE_DAYS


def _flag_duplicate(doc: dict[str, Any], duplicate_of: str) -> None:
    doc["duplicate_of"] = duplicate_of
    doc["flags"].append("duplicate_of_" + duplicate_of.rsplit(".", 1)[0])
    doc["needs_review"] = True
    doc["proposed_action"] = "reject_duplicate"


def _flag_possible_duplicate(doc: dict[str, Any], duplicate_of: str) -> None:
    doc["duplicate_of"] = duplicate_of
    doc["flags"].append("possible_duplicate")
    doc["needs_review"] = True


def mark_duplicates(docs: list[dict[str, Any]]) -> None:
    """Flag later documents that repeat an earlier one. Docs need a source_file.

    Only a sure match is proposed for rejection. An altered number or a close date
    is a possible duplicate for a person to judge, so a real bill is never rejected.
    """
    by_bytes: dict[str, str] = {}
    by_number: dict[tuple, str] = {}
    by_loose_number: dict[tuple, str] = {}
    by_amount: dict[tuple, list] = {}
    for doc in docs:
        if doc.get("error"):
            continue
        seller = doc.get("seller_gstin") or doc.get("seller_name")
        number = doc.get("invoice_number")
        number_key = (seller, _number_key(number)) if number else None
        loose_key = (seller, _loose_number_key(number)) if number else None
        amount_key = (seller, doc.get("total_stated"))
        invoice_date = doc.get("invoice_date")
        same_bytes = by_bytes.get(doc.get("source_sha256") or "")
        near = next((name for other_date, name in by_amount.get(amount_key, ())
                     if _close_in_time(invoice_date, other_date)), None)
        if same_bytes:
            _flag_duplicate(doc, same_bytes)
        elif number_key and number_key in by_number:
            _flag_duplicate(doc, by_number[number_key])
        elif loose_key and loose_key in by_loose_number:
            _flag_possible_duplicate(doc, by_loose_number[loose_key])
        elif doc.get("total_stated") is not None and near:
            _flag_possible_duplicate(doc, near)
        if doc.get("source_sha256"):
            by_bytes.setdefault(doc["source_sha256"], doc["source_file"])
        if number_key:
            by_number.setdefault(number_key, doc["source_file"])
            by_loose_number.setdefault(loose_key, doc["source_file"])
        by_amount.setdefault(amount_key, []).append((invoice_date, doc["source_file"]))
