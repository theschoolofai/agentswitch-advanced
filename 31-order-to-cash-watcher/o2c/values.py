"""Strict business-date and finite-money parsing shared by report consumers.

Dates retain the calendar day recorded by the source; no implicit zone conversion.
Money is calculated with Decimal, rounded to cents with half-even rounding, and
only converted to a finite JSON number at the output boundary.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
import math
import re

DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?\Z")
NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
CENT = Decimal("0.01")


def business_date(value):
    """Accept ISO calendar dates/timestamps in full, never a valid-looking prefix."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        if DATE.fullmatch(value):
            return date.fromisoformat(value)
        if TIMESTAMP.fullmatch(value):
            # Python 3.10 accepts only 3/6 fractional digits. Normalize to six
            # after full validation so every supported version parses the same input.
            normalized = re.sub(r"\.(\d{1,6})", lambda m: "." + m[1].ljust(6, "0"), value)
            return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()
    raise ValueError("expected YYYY-MM-DD or a valid ISO timestamp")


def money(value):
    """Missing is unknown, not zero; malformed/nonfinite amounts are rejected."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("expected a finite monetary number")
    text = str(value).strip()
    if not NUMBER.fullmatch(text):
        raise ValueError("expected a finite monetary number")
    try:
        amount = Decimal(text)
        # Keep rounding/JSON conversion bounded for pathological numeric input.
        if not amount.is_finite() or amount.adjusted() > 300 or len(amount.as_tuple().digits) > 1000:
            raise ValueError("monetary value is nonfinite or out of range")
        return amount
    except InvalidOperation:
        raise ValueError("expected a finite monetary number") from None


def cents(amount):
    with localcontext() as ctx:
        ctx.prec = max(28, amount.adjusted() + 5)
        return amount.quantize(CENT, rounding=ROUND_HALF_EVEN)


def money_number(value):
    """Preserve numeric JSON fields while rejecting unrepresentable cent values."""
    amount = money(value)
    if amount is None:
        return None
    rounded = cents(amount)
    number = float(rounded)
    if not math.isfinite(number) or cents(Decimal(str(number))) != rounded:
        raise ValueError("monetary value cannot be represented safely as a JSON number")
    return number


def money_text(value):
    try:
        amount = money(value)
        return "unknown" if amount is None else f"{cents(amount):,.2f}"
    except ValueError:
        return "unknown"


def money_sum(amounts):
    """Sum bounded cent amounts without Decimal's default 28-digit truncation."""
    if not amounts:
        return None
    with localcontext() as ctx:
        ctx.prec = max(28, max(a.adjusted() for a in amounts) + len(str(len(amounts))) + 6)
        return money_number(sum((cents(a) for a in amounts), Decimal(0)))


def currency_code(value):
    if value is None or value == "":
        return None
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z]{3}", value.strip()):
        return value.strip().upper()
    return None
