"""Hand-builds small PDFs for the attack tests. Everything in them is made up."""
from __future__ import annotations

import zlib
from typing import Iterable

OWN_BUYER = "29AAAAA1111A1Z1"
OWN_SELLER = "29BBBBB2222B1Z2"
OWN = frozenset({OWN_BUYER, OWN_SELLER})
CUSTOMER = "07EEEEE5555E1Z5"
VENDOR = "27DDDDD4444D1Z4"

BILL_LINES = (
    "Teal Paper Mills", f"GSTIN: {VENDOR}", "Some City", "TAX INVOICE", "Invoice No: TP/001",
    "Date: 25 Sep 2026", "Due date: 25 Oct 2026", "Bill to", "Our Buying Co", f"GSTIN: {OWN_BUYER}",
    "Other City", "Description", "Qty", "Rate", "Amount", "Paper", "2", "100.00", "200.00", "Ink", "1",
    "300.00", "300.00", "Subtotal", "Rs. 500.00", "IGST @ 18%", "Rs. 90.00", "TOTAL", "Rs. 590.00", "Thank you.",
)
# An attacker's total, drawn after the real one, in whatever way each test hides it.
FAKE_TOTAL = "(TOTAL) Tj 0 -14 Td (Rs. 1.00) Tj ET"


def replaced(old: str, new: str, lines: Iterable[str] = BILL_LINES) -> list[str]:
    return [new if line == old else line for line in lines]


def bill_text(lines: Iterable[str] = BILL_LINES) -> str:
    return "\n".join(lines)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def drawn(lines: Iterable[str] = BILL_LINES, x: int = 50, top: int = 780, step: int = 14) -> str:
    """The drawing commands for visible black text, one line at a time."""
    return "\n".join(
        f"BT /F1 10 Tf {x} {top - index * step} Td ({_escape(line)}) Tj ET" for index, line in enumerate(lines)
    )


HELVETICA = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


def forge(content: str = "", catalog: str = "", page: str = "", resources: str = "", objects: Iterable = (),
          after_end: bytes = b"", before_header: bytes = b"", compress: bool = False, font: str = HELVETICA) -> bytes:
    """Objects 1 to 5 are always catalog, pages, page, font, contents. Extra objects start at 6."""
    data = content.encode("latin-1") if isinstance(content, str) else content
    if compress:
        data = zlib.compress(data)
        stream = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data)
    else:
        stream = b"<< /Length %d >>\nstream\n" % len(data)
    built = [
        f"<< /Type /Catalog /Pages 2 0 R {catalog} >>".encode(),
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> {resources} >> "
         f"/Contents 5 0 R {page} >>").encode(),
        font.encode(),
        stream + data + b"\nendstream",
        *(item if isinstance(item, bytes) else item.encode() for item in objects),
    ]
    out = bytearray(before_header + b"%PDF-1.7\n")
    offsets = []
    for number, item in enumerate(built, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + item + b"\nendobj\n"
    table = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(built) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(built) + 1, table)
    return bytes(out) + after_end


def stream_object(data: str, dictionary: str = "") -> bytes:
    body = data.encode("latin-1")
    return b"<< %s /Length %d >>\nstream\n" % (dictionary.encode(), len(body)) + body + b"\nendstream"
