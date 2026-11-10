"""Check an image file without decoding it, so a file built to do harm cannot use up memory.

This reads file headers and structure only. It never decompresses pixels, never reads text
from an image and never uses metadata. Reading an image is a separate step, for later. Until
then, every valid image goes to a person with no values proposed.

Only PNG and JPEG are allowed. The type comes from the file's own bytes, never its name.
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 100_000_000  # About 300 MB once decoded, which stays under the parser's memory limit.
MAX_PNG_CHUNKS = 100_000
SNIFF_BYTES = 16

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
# A file can be two things at once. These show another kind of file carried inside an image.
EMBEDDED_FILE_MARKS = (b"%PDF-", b"PK\x03\x04", b"<script")

_PNG_DEPTHS = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
# Start-of-frame markers hold the image size. C4, C8 and CC share the range but mean other things.
_JPEG_FRAME_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_JPEG_NO_LENGTH_MARKERS = frozenset(range(0xD0, 0xD8)) | {0x01}


@dataclass(frozen=True)
class ImageReading:
    sha256: Optional[str] = None
    kind: Optional[str] = None
    width: int = 0
    height: int = 0
    flags: tuple = ()
    error: Optional[str] = None


def image_kind(start: bytes) -> Optional[str]:
    """Name the type from a file's first bytes, or return None if it is not an image we recognise."""
    if start.startswith(PNG_SIGNATURE):
        return "png"
    if start.startswith(JPEG_SIGNATURE):
        return "jpeg"
    if (start.startswith((b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*"))
            or (start[:4] == b"RIFF" and start[8:12] == b"WEBP")
            or start[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypavif")):
        return "unsupported"
    return None


def _inspect_png(data: bytes) -> ImageReading:
    position, chunks, end = len(PNG_SIGNATURE), 0, None
    width = height = 0
    has_pixels = animated = False
    while position + 12 <= len(data):
        length, kind = struct.unpack(">I4s", data[position:position + 8])
        finish = position + 12 + length
        chunks += 1
        if finish > len(data) or chunks > MAX_PNG_CHUNKS:
            return ImageReading(error="image_corrupt")
        stored = struct.unpack(">I", data[finish - 4:finish])[0]
        if zlib.crc32(data[position + 4:finish - 4]) != stored:
            return ImageReading(error="image_corrupt")
        if chunks == 1:
            if kind != b"IHDR" or length != 13:
                return ImageReading(error="image_corrupt")
            width, height, depth, colour = struct.unpack(">IIBB", data[position + 8:position + 18])
            if not width or not height or depth not in _PNG_DEPTHS.get(colour, ()):
                return ImageReading(error="image_corrupt")
        has_pixels = has_pixels or kind == b"IDAT"
        animated = animated or kind == b"acTL"
        position = finish
        if kind == b"IEND":
            end = finish
            break
    if end is None or not has_pixels:
        return ImageReading(error="image_corrupt")
    return _finished("png", width, height, data, end, ("image_animated",) if animated else ())


def _inspect_jpeg(data: bytes) -> ImageReading:
    position = 2
    width = height = 0
    while True:
        if position + 2 > len(data) or data[position] != 0xFF:
            return ImageReading(error="image_corrupt")
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            return ImageReading(error="image_corrupt")
        marker = data[position]
        position += 1
        if marker in _JPEG_NO_LENGTH_MARKERS:
            continue
        if marker == 0xD9:  # The file ended before any picture data.
            return ImageReading(error="image_corrupt")
        if marker == 0xDA:
            break
        if position + 2 > len(data):
            return ImageReading(error="image_corrupt")
        length = struct.unpack(">H", data[position:position + 2])[0]
        if length < 2 or position + length > len(data):
            return ImageReading(error="image_corrupt")
        if marker in _JPEG_FRAME_MARKERS:
            if length < 8:
                return ImageReading(error="image_corrupt")
            frame_height, frame_width = struct.unpack(">HH", data[position + 3:position + 7])
            if not frame_height or not frame_width:
                return ImageReading(error="image_corrupt")
            # A file could state several sizes. Judge it by the largest.
            if frame_width * frame_height > width * height:
                width, height = frame_width, frame_height
        position += length
    end = data.rfind(b"\xff\xd9", position)
    if not width or end < 0:
        return ImageReading(error="image_corrupt")
    return _finished("jpeg", width, height, data, end + 2, ())


def _finished(kind: str, width: int, height: int, data: bytes, end: int, flags: tuple) -> ImageReading:
    if width * height > MAX_IMAGE_PIXELS:
        return ImageReading(kind=kind, width=width, height=height, error="image_too_large")
    found = list(flags)
    if data[end:].strip(b"\x00"):
        found.append("image_trailing_data")
    if any(mark in data for mark in EMBEDDED_FILE_MARKS):
        found.append("image_embedded_file")
    return ImageReading(kind=kind, width=width, height=height, flags=tuple(found))


def inspect_image(data: bytes) -> ImageReading:
    kind = image_kind(data[:SNIFF_BYTES])
    if kind == "png":
        return _inspect_png(data)
    if kind == "jpeg":
        return _inspect_jpeg(data)
    return ImageReading(error="unsupported_image_type")


def read_image(path: Path) -> Optional[ImageReading]:
    """Return a reading if this file is an image, or None so it can go on to the PDF reader."""
    try:
        with path.open("rb") as handle:
            if image_kind(handle.read(SNIFF_BYTES)) is None:
                return None
        if path.stat().st_size > MAX_FILE_BYTES:
            return ImageReading(error="file_too_large")
        # Read once, so the hash always describes the bytes that were checked.
        data = path.read_bytes()
    except OSError:
        return None  # The PDF reader reports an unreadable file in the usual way.
    reading = inspect_image(data)
    return ImageReading(hashlib.sha256(data).hexdigest(), reading.kind, reading.width, reading.height,
                        reading.flags, reading.error)
