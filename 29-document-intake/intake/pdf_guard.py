"""Read a PDF the way a person sees it, and survive a PDF built to do harm.

A PDF can show a person one thing and hand a text reader another. So this module
removes text a person cannot see before the rules read anything, and it raises a
flag for whatever it finds.

The parser runs in its own process, with no tokens in its environment and a time
limit, so a malicious file can only cost that one document.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Optional

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PAGES = 50
MAX_TEXT_CHARS = 500_000
MAX_OPERATIONS = 500_000
MAX_FORM_DEPTH = 5
WORKER_SECONDS = 20
WORKER_MEMORY_BYTES = 1024 * 1024 * 1024

# Below this size, in points, a person cannot read the text.
MIN_VISIBLE_POINTS = 2.0
MIN_VISIBLE_ALPHA = 0.05
SAME_COLOUR = 0.06
# An image this share of the page can show values the text reader never sees.
LARGE_IMAGE_SHARE = 0.3

HIDDEN_TEXT = "pdf_hidden_text"
OVERLAY = "pdf_overlay_content"
ACTIVE = "pdf_active_content"
FONT_REMAP = "pdf_font_remap"
MODIFIED = "pdf_modified_after_creation"
ANOMALY = "pdf_structure_anomaly"
UNREAD_IMAGE = "pdf_unread_image"

ACTIVE_ACTIONS = frozenset({
    "/JavaScript", "/Launch", "/SubmitForm", "/ImportData", "/GoToR", "/GoToE", "/URI",
    "/Rendition", "/Sound", "/Movie",
})
ACTIVE_ANNOTATIONS = frozenset({"/FileAttachment", "/RichMedia", "/Screen", "/Movie", "/Sound", "/3D"})
HARMLESS_ANNOTATIONS = frozenset({"/Link", "/Popup"})

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
PACKAGE_PARENT = Path(__file__).resolve().parent.parent
BFCHAR = re.compile(rb"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{4})>")
BFRANGE = re.compile(rb"<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{2})>\s*<([0-9A-Fa-f]{4})>")


@dataclass(frozen=True)
class PdfReading:
    sha256: Optional[str] = None
    text: str = ""
    flags: tuple = ()
    error: Optional[str] = None


def read_pdf(path: Path, timeout: float = WORKER_SECONDS) -> PdfReading:
    """Read one file. Never raises for a bad file: it reports an error code instead."""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return PdfReading(error="file_too_large")
        # Read once, so the hash always describes the bytes that were parsed.
        data = path.read_bytes()
    except OSError:
        return PdfReading(error="unreadable_file")
    sha256 = hashlib.sha256(data).hexdigest()
    result = _run_worker(data, timeout)
    return PdfReading(sha256, result.get("text", ""), tuple(result.get("flags", ())), result.get("error"))


def _run_worker(data: bytes, timeout: float) -> dict:
    # Only what Python needs to start. Tokens stay out of the parser's reach.
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if key in os.environ}
    try:
        done = subprocess.run(
            [sys.executable, "-m", "intake.pdf_guard", "--worker"],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout, cwd=PACKAGE_PARENT, env=env, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"error": "timed_out"}
    except OSError:
        return {"error": "reader_failed"}
    try:
        result = json.loads(done.stdout)
    except ValueError:
        return {"error": "reader_failed"}
    return result if done.returncode == 0 and isinstance(result, dict) else {"error": "reader_failed"}


def inspect_pdf(data: bytes) -> dict:
    """Return the visible text and flags, or an error code."""
    from pypdf import PdfReader
    from pypdf.errors import FileNotDecryptedError

    if b"%PDF-" not in data[:1024]:
        return {"error": "not_a_pdf"}
    flags = _file_shape_flags(data)
    with _CountPdfWarnings() as warnings:
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                return {"error": "encrypted_pdf"}
            pages = list(reader.pages)
        except FileNotDecryptedError:
            return {"error": "encrypted_pdf"}
        except Exception:  # A broken file can raise nearly anything from inside the parser.
            return {"error": "corrupt_pdf"}
        if warnings.count:
            flags.add(ANOMALY)
        if len(pages) > MAX_PAGES:
            return {"error": "too_many_pages"}
        try:
            flags |= _catalog_flags(reader)
            texts = []
            off_layers = _layers_switched_off(reader)
            budget = _Budget()
            for page in pages:
                flags |= _annotation_flags(page)
                flags |= _strip_hidden_text(page, reader, off_layers, budget)
                texts.append(page.extract_text() or "")
        except _TooComplex:
            return {"error": "too_complex"}
        except Exception:
            return {"error": "corrupt_pdf"}
    text = "\n".join(texts)
    if not text.strip():
        # A plain scan is not suspicious. It simply has nothing to read.
        flags.discard(UNREAD_IMAGE)
    return {"text": text[:MAX_TEXT_CHARS], "flags": sorted(flags)}


class _CountPdfWarnings(logging.Handler):
    """pypdf warns when it had to repair a file. A repair is where readers disagree."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.count = 0
        self._logger = logging.getLogger("pypdf")

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1

    def __enter__(self) -> "_CountPdfWarnings":
        self._propagate = self._logger.propagate
        self._logger.addHandler(self)
        self._logger.propagate = False
        return self

    def __exit__(self, *_: Any) -> None:
        self._logger.removeHandler(self)
        self._logger.propagate = self._propagate


def _file_shape_flags(data: bytes) -> set:
    flags = set()
    if not data.startswith(b"%PDF-"):
        flags.add(ANOMALY)
    # A linearized PDF has two end markers. More than expected means something was added later.
    expected = 2 if b"/Linearized" in data[:2048] else 1
    if data.count(b"%%EOF") > expected:
        flags.add(MODIFIED)
    end = data.rfind(b"%%EOF")
    if end != -1 and data[end + 5:].strip():
        flags.add(ANOMALY)
    return flags


def _resolved(value: Any) -> Any:
    return value.get_object() if hasattr(value, "get_object") else value


def _is_active_action(action: Any, depth: int = 0) -> bool:
    action = _resolved(action)
    if not isinstance(action, dict) or depth > 5:
        return False
    return action.get("/S") in ACTIVE_ACTIONS or _is_active_action(action.get("/Next"), depth + 1)


def _catalog_flags(reader: Any) -> set:
    root = _resolved(reader.trailer["/Root"])
    names = _resolved(root.get("/Names")) or {}
    form = _resolved(root.get("/AcroForm")) or {}
    active = (
        _is_active_action(root.get("/OpenAction")) or "/AA" in root
        or "/JavaScript" in names or "/EmbeddedFiles" in names or "/XFA" in form
    )
    return {ACTIVE} if active else set()


def _annotation_flags(page: Any) -> set:
    flags = set()
    if "/AA" in page:
        flags.add(ACTIVE)
    annotations = _resolved(page.get("/Annots")) or []
    for item in annotations:
        annotation = _resolved(item)
        if not isinstance(annotation, dict):
            continue
        kind = annotation.get("/Subtype")
        if kind in ACTIVE_ANNOTATIONS or "/AA" in annotation or _is_active_action(annotation.get("/A")):
            flags.add(ACTIVE)
        # A person sees these on the page, and the text reader never reads them.
        if kind not in HARMLESS_ANNOTATIONS:
            flags.add(OVERLAY)
    return flags


def _reference_id(value: Any) -> Optional[int]:
    return getattr(value, "idnum", None)


def _layers_switched_off(reader: Any) -> set:
    root = _resolved(reader.trailer["/Root"])
    properties = _resolved(root.get("/OCProperties"))
    if not isinstance(properties, dict):
        return set()
    default = _resolved(properties.get("/D")) or {}
    switched_off = {_reference_id(ref) for ref in _resolved(default.get("/OFF")) or []}
    if default.get("/BaseState") == "/OFF":
        switched_on = {_reference_id(ref) for ref in _resolved(default.get("/ON")) or []}
        switched_off |= {_reference_id(ref) for ref in _resolved(properties.get("/OCGs")) or []} - switched_on
    return switched_off - {None}


def _layer_is_off(reference: Any, off_layers: set) -> bool:
    if _reference_id(reference) in off_layers:
        return True
    target = _resolved(reference)
    if not isinstance(target, dict):
        return False
    if "/OCGs" not in target:
        return False
    groups = target.raw_get("/OCGs")
    if _reference_id(groups) in off_layers:
        return True
    groups = _resolved(groups)
    return isinstance(groups, list) and any(_reference_id(ref) in off_layers for ref in groups)


class _TooComplex(Exception):
    pass


class _Budget:
    def __init__(self) -> None:
        self.left = MAX_OPERATIONS

    def spend(self, count: int) -> None:
        self.left -= count
        if self.left < 0:
            raise _TooComplex


def _multiply(first: tuple, second: tuple) -> tuple:
    a, b, c, d, e, f = first
    g, h, i, j, k, l = second
    return (a * g + b * i, a * h + b * j, c * g + d * i, c * h + d * j, e * g + f * i + k, e * h + f * j + l)


def _apply(matrix: tuple, x: float, y: float) -> tuple:
    return matrix[0] * x + matrix[2] * y + matrix[4], matrix[1] * x + matrix[3] * y + matrix[5]


def _box_on_page(matrix: tuple, x0: float, y0: float, x1: float, y1: float) -> tuple:
    corners = [_apply(matrix, x, y) for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))]
    xs, ys = [corner[0] for corner in corners], [corner[1] for corner in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _inside(box: tuple, x: float, y: float, margin: float = 0.0) -> bool:
    # Written so that a NaN position counts as outside.
    return box[0] - margin <= x <= box[2] + margin and box[1] - margin <= y <= box[3] + margin


def _intersect(first: Optional[tuple], second: tuple) -> tuple:
    if first is None:
        return second
    return max(first[0], second[0]), max(first[1], second[1]), min(first[2], second[2]), min(first[3], second[3])


def _colour_from(values: list) -> Optional[tuple]:
    """An RGB colour from 1, 3 or 4 numbers. Anything else is unknown."""
    if len(values) == 1:
        return values[0], values[0], values[0]
    if len(values) == 3:
        return tuple(values)
    if len(values) == 4:
        c, m, y, k = values
        return (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    return None


def _set_colour(operands: list, space_is_known: bool) -> Optional[tuple]:
    """Three or four numbers read as RGB or CMYK in nearly any colour space, ICC included.

    One number in a special colour space can mean anything, so it stays unknown.
    """
    if not all(isinstance(value, (int, float)) for value in operands):
        return None
    return _colour_from(_numbers(operands)) if space_is_known or len(operands) in (3, 4) else None


WHITE = (1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class _Graphics:
    ctm: tuple = IDENTITY
    fill: Optional[tuple] = BLACK
    stroke: Optional[tuple] = BLACK
    fill_space_known: bool = True
    stroke_space_known: bool = True
    fill_alpha: float = 1.0
    clip: Optional[tuple] = None
    render_mode: int = 0
    size: float = 0.0
    scale: float = 1.0
    rise: float = 0.0
    leading: float = 0.0
    char_space: float = 0.0
    word_space: float = 0.0


def _numbers(operands: list) -> list:
    return [float(value) for value in operands]


class _ContentWalker:
    """Follow one page's drawing commands and find text a person cannot see."""

    def __init__(self, reader: Any, page_box: tuple, off_layers: set, budget: _Budget):
        self.reader = reader
        self.page_box = page_box
        self.off_layers = off_layers
        self.budget = budget
        self.flags: set = set()
        self.painted: list = []
        self.shown: list = []
        self.fonts_checked: set = set()
        self.text_matrix = IDENTITY
        self.line_matrix = IDENTITY

    def walk(self, operations: list, resources: Any, graphics: _Graphics, depth: int,
             drop: Callable[[int], None]) -> None:
        self.budget.spend(len(operations))
        resources = _resolved(resources) or {}
        self._check_fonts(resources)
        stack: list = []
        path: list = []
        pending_clip = False
        marked: list = []

        for index, (operands, operator) in enumerate(operations):
            drop_this = (lambda i=index: drop(i))
            try:
                if operator == b"q":
                    stack.append(graphics)
                elif operator == b"Q":
                    if stack:
                        graphics = stack.pop()
                elif operator == b"cm":
                    graphics = replace(graphics, ctm=_multiply(tuple(_numbers(operands)), graphics.ctm))
                elif operator == b"gs":
                    graphics = self._apply_ext_state(operands, resources, graphics)
                elif operator in (b"g", b"rg", b"k"):
                    graphics = replace(graphics, fill=_colour_from(_numbers(operands)), fill_space_known=True)
                elif operator in (b"G", b"RG", b"K"):
                    graphics = replace(graphics, stroke=_colour_from(_numbers(operands)), stroke_space_known=True)
                elif operator == b"cs":
                    known = operands[0] in ("/DeviceGray", "/DeviceRGB", "/DeviceCMYK")
                    graphics = replace(graphics, fill=BLACK if known else None, fill_space_known=known)
                elif operator == b"CS":
                    known = operands[0] in ("/DeviceGray", "/DeviceRGB", "/DeviceCMYK")
                    graphics = replace(graphics, stroke=BLACK if known else None, stroke_space_known=known)
                elif operator in (b"sc", b"scn"):
                    graphics = replace(graphics, fill=_set_colour(operands, graphics.fill_space_known))
                elif operator in (b"SC", b"SCN"):
                    graphics = replace(graphics, stroke=_set_colour(operands, graphics.stroke_space_known))
                elif operator == b"re":
                    x, y, width, height = _numbers(operands)
                    path.extend(((x, y), (x + width, y + height)))
                elif operator in (b"m", b"l"):
                    path.append(tuple(_numbers(operands)))
                elif operator in (b"c", b"v", b"y"):
                    values = _numbers(operands)
                    path.extend(zip(values[0::2], values[1::2]))
                elif operator in (b"W", b"W*"):
                    pending_clip = True
                elif operator in (b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*", b"S", b"s", b"n"):
                    box = self._path_box(path, graphics)
                    if box is not None and operator not in (b"S", b"s", b"n"):
                        self._paint(graphics, box)
                    if box is not None and pending_clip:
                        graphics = replace(graphics, clip=_intersect(graphics.clip, box))
                    path, pending_clip = [], False
                elif operator == b"sh":
                    if graphics.clip is not None:
                        self._paint(replace(graphics, fill=None), graphics.clip)
                elif operator == b"BT":
                    self.text_matrix = self.line_matrix = IDENTITY
                elif operator == b"Tf":
                    graphics = replace(graphics, size=float(operands[1]))
                elif operator == b"Tr":
                    graphics = replace(graphics, render_mode=int(operands[0]))
                elif operator == b"Tz":
                    graphics = replace(graphics, scale=float(operands[0]) / 100)
                elif operator == b"Ts":
                    graphics = replace(graphics, rise=float(operands[0]))
                elif operator == b"Tc":
                    graphics = replace(graphics, char_space=float(operands[0]))
                elif operator == b"Tw":
                    graphics = replace(graphics, word_space=float(operands[0]))
                elif operator == b"Tm":
                    self.text_matrix = self.line_matrix = tuple(_numbers(operands))
                elif operator == b"TL":
                    graphics = replace(graphics, leading=float(operands[0]))
                elif operator in (b"Td", b"TD"):
                    x, y = _numbers(operands)
                    if operator == b"TD":
                        graphics = replace(graphics, leading=-y)
                    self.text_matrix = self.line_matrix = _multiply((1, 0, 0, 1, x, y), self.line_matrix)
                elif operator == b"T*":
                    self._next_line(graphics)
                elif operator == b"Tj":
                    self._show(graphics, [operands[0]], bool(marked and any(marked)), drop_this)
                elif operator == b"TJ":
                    self._show(graphics, list(operands[0]), bool(marked and any(marked)), drop_this)
                elif operator == b"'":
                    self._next_line(graphics)
                    self._show(graphics, [operands[0]], bool(marked and any(marked)), drop_this)
                elif operator == b'"':
                    graphics = replace(graphics, word_space=float(operands[0]), char_space=float(operands[1]))
                    self._next_line(graphics)
                    self._show(graphics, [operands[2]], bool(marked and any(marked)), drop_this)
                elif operator == b"BDC":
                    marked.append(self._marked_layer_is_off(operands, resources))
                elif operator == b"BMC":
                    marked.append(False)
                elif operator == b"EMC":
                    if marked:
                        marked.pop()
                elif operator == b"Do":
                    self._draw_object(operands[0], resources, graphics, depth, drop_this)
                elif operator == b"INLINE IMAGE":
                    self._draw_image(graphics, covers=True)
            except (TypeError, ValueError, IndexError, KeyError, AttributeError):
                continue  # A malformed command draws nothing we can reason about.

    def _next_line(self, graphics: _Graphics) -> None:
        self.text_matrix = self.line_matrix = _multiply((1, 0, 0, 1, 0, -graphics.leading), self.line_matrix)

    def _apply_ext_state(self, operands: list, resources: Any, graphics: _Graphics) -> _Graphics:
        states = _resolved(resources.get("/ExtGState")) or {}
        state = _resolved(states.get(operands[0])) or {}
        if "/ca" in state:
            return replace(graphics, fill_alpha=float(state["/ca"]))
        return graphics

    def _marked_layer_is_off(self, operands: list, resources: Any) -> bool:
        if not operands or operands[0] != "/OC" or len(operands) < 2:
            return False
        properties = _resolved(resources.get("/Properties")) or {}
        return operands[1] in properties and _layer_is_off(properties.raw_get(operands[1]), self.off_layers)

    def _path_box(self, path: list, graphics: _Graphics) -> Optional[tuple]:
        if not path:
            return None
        xs, ys = [point[0] for point in path], [point[1] for point in path]
        return _box_on_page(graphics.ctm, min(xs), min(ys), max(xs), max(ys))

    def _paint(self, graphics: _Graphics, box: tuple, colour: Any = "fill") -> None:
        if graphics.clip is not None:
            box = _intersect(graphics.clip, box)
        if box[0] > box[2] or box[1] > box[3]:
            return
        solid = graphics.fill_alpha >= 0.5
        painted = (graphics.fill if colour == "fill" else None) if graphics.fill_alpha >= 0.95 else None
        if solid:
            self._cover_shown_text(box)
        self.painted.append((box, painted))

    def _cover_shown_text(self, box: tuple) -> None:
        remaining = []
        for x, y, top, drop in self.shown:
            # Both points must be under the shape, so an underline does not count as cover.
            if _inside(box, x, y) and _inside(box, x, top):
                drop()
                self.flags.add(HIDDEN_TEXT)
            else:
                remaining.append((x, y, top, drop))
        self.shown = remaining

    def _background_at(self, x: float, y: float) -> Optional[tuple]:
        for box, colour in reversed(self.painted):
            if _inside(box, x, y):
                return colour
        return WHITE

    def _show(self, graphics: _Graphics, pieces: list, in_hidden_layer: bool, drop: Callable[[], None]) -> None:
        hidden = False
        pending = []
        for piece in pieces:
            if isinstance(piece, (int, float)):
                shift = -float(piece) / 1000 * graphics.size * graphics.scale
                self.text_matrix = _multiply((1, 0, 0, 1, shift, 0), self.text_matrix)
                continue
            text = piece.decode("latin-1") if isinstance(piece, bytes) else str(piece)
            placed = _multiply(self.text_matrix, graphics.ctm)
            x, y = _apply(placed, 0, graphics.rise)
            size = graphics.size * math.sqrt(abs(placed[0] * placed[3] - placed[1] * placed[2]))
            if text.strip():
                if in_hidden_layer or self._cannot_be_seen(graphics, x, y, size):
                    hidden = True
                else:
                    pending.append((x, y, y + 0.3 * size))
            advance = (graphics.size * 0.5 + graphics.char_space) * len(text)
            advance = (advance + graphics.word_space * text.count(" ")) * graphics.scale
            self.text_matrix = _multiply((1, 0, 0, 1, advance, 0), self.text_matrix)
        if hidden:
            drop()
            self.flags.add(HIDDEN_TEXT)
        else:
            self.shown.extend((x, y, top, drop) for x, y, top in pending)

    def _cannot_be_seen(self, graphics: _Graphics, x: float, y: float, size: float) -> bool:
        if graphics.render_mode in (3, 7) or graphics.fill_alpha < MIN_VISIBLE_ALPHA:
            return True
        if not size >= MIN_VISIBLE_POINTS or not abs(graphics.scale) >= 0.05:
            return True
        if not _inside(self.page_box, x, y, margin=1.0):
            return True
        if graphics.clip is not None and not _inside(graphics.clip, x, y, margin=1.0):
            return True
        colour = graphics.stroke if graphics.render_mode == 1 else graphics.fill
        background = self._background_at(x, y)
        if colour is None or background is None:
            return False
        return all(abs(first - second) < SAME_COLOUR for first, second in zip(colour, background))

    def _draw_object(self, name: Any, resources: Any, graphics: _Graphics, depth: int,
                     drop: Callable[[], None]) -> None:
        objects = _resolved(resources.get("/XObject")) or {}
        target = _resolved(objects.get(name))
        if target is None:
            return
        if "/OC" in target and _layer_is_off(target.raw_get("/OC"), self.off_layers):
            drop()
            self.flags.add(HIDDEN_TEXT)
            return
        kind = target.get("/Subtype")
        if kind == "/Image":
            self._draw_image(graphics, covers="/SMask" not in target and not target.get("/ImageMask"))
        elif kind == "/Form":
            self._draw_form(target, resources, graphics, depth, drop)

    def _draw_image(self, graphics: _Graphics, covers: bool) -> None:
        box = _box_on_page(graphics.ctm, 0, 0, 1, 1)
        if graphics.clip is not None:
            box = _intersect(graphics.clip, box)
        page = self.page_box
        page_area = max((page[2] - page[0]) * (page[3] - page[1]), 1.0)
        if max(box[2] - box[0], 0) * max(box[3] - box[1], 0) / page_area >= LARGE_IMAGE_SHARE:
            self.flags.add(UNREAD_IMAGE)
        if covers:
            self._paint(graphics, box, colour="image")

    def _draw_form(self, form: Any, resources: Any, graphics: _Graphics, depth: int,
                   drop: Callable[[], None]) -> None:
        from pypdf.generic import ContentStream

        if depth >= MAX_FORM_DEPTH:
            drop()
            self.flags.add(HIDDEN_TEXT)
            return
        matrix = tuple(float(value) for value in _resolved(form.get("/Matrix")) or IDENTITY)
        inner = replace(graphics, ctm=_multiply(matrix, graphics.ctm))
        box = _resolved(form.get("/BBox"))
        if box is not None:
            x0, y0, x1, y1 = (float(value) for value in box)
            inner = replace(inner, clip=_intersect(inner.clip, _box_on_page(inner.ctm, x0, y0, x1, y1)))
        saved = self.text_matrix, self.line_matrix
        # Hidden text inside a form removes the whole form. The document goes to a person anyway.
        self.walk(ContentStream(form, self.reader, "bytes").operations, form.get("/Resources") or resources,
                  inner, depth + 1, lambda _index: drop())
        self.text_matrix, self.line_matrix = saved

    def _check_fonts(self, resources: Any) -> None:
        fonts = _resolved(resources.get("/Font")) or {}
        for name in fonts:
            font = _resolved(fonts[name])
            if not isinstance(font, dict) or id(font) in self.fonts_checked:
                continue
            self.fonts_checked.add(id(font))
            if font.get("/Subtype") != "/Type0" and "/ToUnicode" in font and _remaps_digits(font):
                self.flags.add(FONT_REMAP)


def _remaps_digits(font: Any) -> bool:
    """True if a one-byte code for a digit is reported as a different digit.

    The page draws "9" and the text layer says "1". This only catches simple fonts:
    fonts using two-byte codes have no fixed meaning to compare against.
    """
    data = _resolved(font["/ToUnicode"]).get_data()
    pairs = [(int(code, 16), int(value, 16)) for code, value in BFCHAR.findall(data)]
    for start, end, value in BFRANGE.findall(data):
        first, last, base = int(start, 16), int(end, 16), int(value, 16)
        pairs.extend((code, base + code - first) for code in range(first, min(last, 255) + 1))
    digits = range(0x30, 0x3A)
    return any(code in digits and value != code and value in digits for code, value in pairs)


def _strip_hidden_text(page: Any, reader: Any, off_layers: set, budget: _Budget) -> set:
    """Find text nobody can see and take it out of the page before it is read."""
    from pypdf.generic import NameObject

    contents = page.get_contents()
    if contents is None:
        return set()
    operations = contents.operations
    crop = page.cropbox
    media = page.mediabox
    box = _intersect((float(media.left), float(media.bottom), float(media.right), float(media.top)),
                     (float(crop.left), float(crop.bottom), float(crop.right), float(crop.top)))
    walker = _ContentWalker(reader, box, off_layers, budget)
    dropped: set = set()
    walker.walk(operations, page.get("/Resources"), _Graphics(), 0, dropped.add)
    if dropped:
        contents.operations = [op for index, op in enumerate(operations) if index not in dropped]
        page[NameObject("/Contents")] = contents
    return walker.flags


def _limit_memory() -> None:
    """Cap the worker's memory where the system allows it. Windows relies on pypdf's own limits."""
    try:
        import resource
    except ImportError:
        return
    resource.setrlimit(resource.RLIMIT_AS, (WORKER_MEMORY_BYTES, WORKER_MEMORY_BYTES))


def _worker_main() -> int:
    _limit_memory()
    data = sys.stdin.buffer.read()
    try:
        result = inspect_pdf(data)
    except Exception:  # Includes MemoryError and RecursionError. One file must not stop the batch.
        result = {"error": "corrupt_pdf"}
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(_worker_main() if sys.argv[1:] == ["--worker"] else 2)
