"""Re-read the platform and report what changed since the last run. Read-only.

Run it after every platform release notice:
    uv run python scripts/platform_sync.py          (needs .env, see .env.example)

It runs the access probe (which keeps the last snapshot in data/platform/<system>/previous/),
compares previous and current for each system, compares the two systems with each other, and writes
data/platform/changes-<date>.md (git-ignored). Review that file: new gaps become instructor
questions or bug drafts, and changed access updates the local platform notes.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import probe_access
from platform_diff import Snapshot, compare_systems, diff_snapshots, load_snapshot

IST = ZoneInfo("Asia/Kolkata")


def system_section(name: str, folder: Path) -> tuple[list[str], Snapshot | None, int]:
    """The report lines for one system, its current snapshot (None if none), and its change count."""
    current = load_snapshot(folder)
    previous = load_snapshot(folder / "previous")
    if current is None:
        return [f"## {name}", "", "- no current snapshot (the probe failed for this system)", ""], None, 0
    if previous is None:
        return [f"## {name}", "", "- first snapshot: nothing to compare yet", ""], current, 0
    changes = diff_snapshots(previous, current)
    body = [f"- {c}" for c in changes] or ["- no changes"]
    return [f"## {name} (version {current.version})", "", *body, ""], current, len(changes)


def build_report(out_dir: Path, systems: tuple[str, ...]) -> tuple[str, int]:
    """The markdown report and the number of change lines in it."""
    stamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M IST")
    lines = [f"# Platform changes ({stamp})", ""]
    snapshots: dict[str, Snapshot] = {}
    changes = 0
    for name in systems:
        section, snap, count = system_section(name, out_dir / name)
        lines += section
        changes += count
        if snap is not None:
            snapshots[name] = snap
    if len(snapshots) == 2:
        (a, sa), (b, sb) = snapshots.items()
        diffs = compare_systems(sa, sb, a, b)
        lines += ["## Differences between systems", "", *([f"- {d}" for d in diffs] or ["- none"]), ""]
    return "\n".join(lines), changes


def main() -> int:
    settings = probe_access.load_settings()
    if settings is None:
        return 2
    results, failures = asyncio.run(probe_access.probe_all(settings))
    read_now = tuple(r["instance"] for r in results)  # report only on systems read in this run
    if not read_now:
        print("No system could be read, so no change report was written.", file=sys.stderr)
        return 1
    report, changes = build_report(probe_access.OUT_DIR, read_now)
    path = probe_access.OUT_DIR / f"changes-{datetime.now(IST):%Y-%m-%d-%H%M}.md"
    path.write_text(report)
    print(f"{changes} change(s) found; report: {path.relative_to(probe_access.SEAT_DIR)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
