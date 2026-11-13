"""`--review`: show each clean draft in the terminal and let the user save, edit, skip or stop.

Only drafts that passed every check are offered; an edited draft goes through the same checks again, because the
edit could add exactly what the checks exist to stop (a link, an amount, a time that is not free)."""
import os
import re
import shlex
import subprocess
import tempfile

from . import drafts

PROMPT = "[s]ave / [e]dit then save / [k] skip / [q] quit: "
_CONTROL = re.compile("[\\x00-\\x08\\x0b-\\x1f\\x7f-\\x9f]")


def _safe(text) -> str:
    # Drafts and subjects come from mail and the model; escape sequences must not reach the terminal.
    return drafts._INVISIBLE.sub("", _CONTROL.sub("", str(text or "").replace("\r\n", "\n").replace("\t", "    ")))


def typed_editor(text: str, input_fn, print_fn) -> str | None:
    print_fn("Type the new draft. End with a line containing only \".\" (an empty draft skips it).")
    lines = []
    while True:
        try:
            line = input_fn("")
        except EOFError:
            return None
        if line == ".":
            break
        lines.append(line)
    return "\n".join(lines)


def external_editor(command: str, text: str) -> str | None:
    fd, path = tempfile.mkstemp(prefix="ea-draft-", suffix=".txt")  # 0600: the draft may be private
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        result = subprocess.run([*shlex.split(command), path], check=False)
        if result.returncode != 0:
            return None
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class Reviewer:
    """Callable `(item, original, slots) -> (action, detail)`: ("save", text), ("skip", reason) or ("quit", None).

    After "q" every later draft is answered ("quit", None) without asking."""

    def __init__(self, input_fn=input, print_fn=print, editor_fn=None, environ=None):
        self.input_fn = input_fn
        self.print_fn = print_fn
        environ = os.environ if environ is None else environ
        if editor_fn is None:
            command = (environ.get("VISUAL") or environ.get("EDITOR") or "").strip()
            if command:
                editor_fn = lambda text: external_editor(command, text)  # noqa: E731
            else:
                editor_fn = lambda text: typed_editor(text, self.input_fn, self.print_fn)  # noqa: E731
        self.editor_fn = editor_fn
        self.stopped = False

    def _ask(self) -> str:
        while True:
            try:
                answer = (self.input_fn(PROMPT) or "").strip().lower()
            except EOFError:
                return "q"
            if answer in ("s", "e", "k", "q"):
                return answer
            self.print_fn("Please answer s, e, k or q.")

    def __call__(self, item: dict, original: dict, slots=None) -> tuple:
        if self.stopped:
            return "quit", None
        sender = item.get("from_name") or item.get("from_email") or "unknown sender"
        self.print_fn("")
        self.print_fn(f"Reply to: {_safe(item.get('subject') or '(no subject)')} — from {_safe(sender)}")
        self.print_fn("-" * 60)
        self.print_fn(_safe(item.get("draft")))
        self.print_fn("-" * 60)
        answer = self._ask()
        if answer == "q":
            self.stopped = True
            return "quit", None
        if answer == "k":
            return "skip", "skipped in review"
        text = item.get("draft") or ""
        if answer == "e":
            edited = self.editor_fn(text)
            if edited is None or not edited.strip():
                self.print_fn("Empty or cancelled edit: not saved.")
                return "skip", "edit cancelled"
            text = edited.strip()
            problems = recheck(text, original, slots)
            if problems:
                self.print_fn(f"Not saved: {problems}.")
                return "skip", f"edited draft not saved: {problems}"
        return "save", text


def recheck(text: str, original: dict, slots=None) -> str | None:
    """Why `text` may not be saved, or None. Same checks as a model-written draft (risk and time)."""
    if len(text) > drafts.MAX_DRAFT:
        return f"draft is longer than {drafts.MAX_DRAFT} characters"
    kinds = drafts.check_draft(text, original, slots)
    if not kinds:
        return None
    why = drafts.review_reason(kinds) or "failed the draft checks"
    times = drafts.unverified_times(text, original, slots)
    return f"{why} ({', '.join(times)})" if times else why
