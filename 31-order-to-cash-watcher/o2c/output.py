"""Safe filenames and staged publication for JSON/Markdown report pairs."""
import os
from pathlib import Path
import re
import shutil
import tempfile

from .values import business_date, DATE


def instance_label(value):
    """An omitted instance uses 'report'; explicitly blank/unsafe values fail."""
    if value is None:
        return "report"
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError("instance must be 1-64 letters, digits, underscores or hyphens, starting with a letter/digit")
    return value


def report_stem(instance, report_date, suffix=""):
    label = instance_label(instance)
    if not isinstance(report_date, str) or not DATE.fullmatch(report_date):
        raise ValueError("report_date must be YYYY-MM-DD")
    day = business_date(report_date)  # Calendar validation, not just a filename pattern.
    if suffix not in ("", "-drafts"):
        raise ValueError("unsupported report suffix")
    return f"{label}-{day.isoformat()}{suffix}"


def write_pair(directory, stem, json_text, markdown_text):
    """Stage both files before publishing, and roll back handled replace failures.

    Two filenames cannot be replaced atomically together. This protects against
    ordinary write/replace errors, not a power failure or concurrent readers
    between replacements. A versioned-directory/manifest protocol would be
    needed for that stronger guarantee.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", stem):
        raise ValueError("unsafe report stem")
    directory = Path(directory)
    targets = [directory / (stem + ".json"), directory / (stem + ".md")]
    # Do not follow a pre-existing report symlink when backing up old contents.
    if any(p.is_symlink() for p in targets):
        raise ValueError("report output must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".o2c-", dir=directory) as temporary:
        staging = Path(temporary)
        staged, backups = [], {}
        for target, content in zip(targets, (json_text, markdown_text)):
            path = staging / (target.name + ".new")
            path.write_text(content, encoding="utf-8")
            staged.append(path)
            if target.exists():
                backup = staging / (target.name + ".old")
                shutil.copyfile(target, backup)
                backups[target] = backup
        published = []
        try:
            for source, target in zip(staged, targets):
                os.replace(source, target)
                published.append(target)
        except Exception:
            # A second replace may fail after JSON was published. Restore the
            # old JSON (or remove the new one) before propagating that failure.
            for target in reversed(published):
                if target in backups:
                    os.replace(backups[target], target)
                else:
                    target.unlink()
            raise
