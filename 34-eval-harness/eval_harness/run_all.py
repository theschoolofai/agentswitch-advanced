"""Run several suites one after another on one system, and write one results.json for all of them.

    python -m eval_harness.run_all --suite suites/seat35 --suite suites/seat31 --out ../results.json

The course runner reads one results.json per run, and the harness runs one suite per call, so for the
15 Nov run (instructor, 13 Nov: "start the seat 35 suite and then the seat 31 suite and write one report")
this starts `python -m eval_harness` once per suite, in order, and joins the rows. Each suite runs in its own
process, so one suite crashing cannot stop the next. A suite that left no results file becomes one
infrastructure row, never a silent gap. Exit code is always 0: the runner scores the file.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from eval_harness.results import ResultRow, ResultsFile, ResultsWriter


def rows_from(path: Path, suite: Path, instance: str) -> list[ResultRow]:
    """The rows one suite run wrote, or one infrastructure row if it wrote nothing readable."""
    try:
        return ResultsFile.model_validate_json(path.read_text()).tasks
    except (OSError, ValueError) as e:
        return [
            ResultRow(
                id=f"{instance}:{suite.name}",
                title=f"suite {suite.name}",
                passed=False,
                score=0.0,
                evidence=f"infrastructure: suite run left no readable results ({type(e).__name__})"[:500],
            )
        ]


def join_results(parts: list[tuple[Path, Path]], instance: str, out: Path) -> ResultsWriter:
    """Write every suite's rows, in suite order, into one results file at `out`."""
    writer = ResultsWriter(out, instance)
    for suite, path in parts:
        writer.rows.extend(rows_from(path, suite, instance))
    writer.write()  # once, not per row: add() rewrites the whole file each time
    return writer


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m eval_harness.run_all", description=__doc__.split("\n")[0]
    )
    parser.add_argument("--suite", type=Path, action="append", required=True, help="repeat, in run order")
    parser.add_argument("--out", type=Path, default=Path("results.json"))
    args = parser.parse_args()
    instance = os.environ.get("AGENTSWITCH_INSTANCE", "setup")
    with tempfile.TemporaryDirectory(prefix="run_all-") as tmp:
        parts = []
        for i, suite in enumerate(args.suite):
            part = Path(tmp) / f"{i}-{suite.name}.json"
            subprocess.run([sys.executable, "-m", "eval_harness", "--suite", str(suite), "--out", str(part)])
            parts.append((suite, part))
        writer = join_results(parts, instance, args.out)
    passed = sum(r.passed for r in writer.rows)
    print(
        f"{instance}: {passed}/{len(writer.rows)} passed across {len(args.suite)} suite(s); wrote {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
