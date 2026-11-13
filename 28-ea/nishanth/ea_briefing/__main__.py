"""CLI: python -m ea_briefing [--system keystone|suryodaya ...] [options]."""
import argparse
import os
import sys
import time

STARTED = time.monotonic()  # the run time limit counts from process start

from . import runner  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ea_briefing",
                                description="Daily briefing: mail to answer, meetings, overdue tasks.")
    p.add_argument("--system", "--instance", dest="system", action="append", metavar="NAME",
                   help="keystone or suryodaya; repeatable (default: every system with a saved login or password)")
    p.add_argument("--today", help="YYYY-MM-DD (default: today in the user's time zone)")
    p.add_argument("--tz", action="append", metavar="ZONE|SYSTEM=ZONE",
                   help="IANA zone for all systems, or SYSTEM=ZONE for one (repeatable)")
    p.add_argument("--env-file", dest="env_file", help="KEY=VALUE file (default: EA_ENV_FILE or ./.env)")
    p.add_argument("--json", dest="json_path", metavar="PATH", help="also write the briefing as JSON")
    p.add_argument("--out", metavar="DIR", help="folder for briefing-YYYY-MM-DD.md (default ./briefings)")
    p.add_argument("--no-file", action="store_true", help="do not write the Markdown briefing file")
    p.add_argument("--no-save", action="store_true", help="preview drafts; save nothing")
    p.add_argument("--review", action="store_true", help="ask before saving each draft (needs a terminal)")
    p.add_argument("--save-drafts", action="store_true", help=argparse.SUPPRESS)  # old flag; saving is the default
    p.add_argument("--no-llm", action="store_true", help="skip the model; mail is listed unassessed")
    p.add_argument("--mail-cap", type=int, default=25, metavar="N", help="max messages to read (default 25)")
    p.add_argument("--unread-only", action="store_true", help="only unread mail (default: unanswered, read or not)")
    p.add_argument("--time-limit", type=float, default=runner.DEFAULT_TIME_LIMIT, metavar="SECONDS",
                   help="limit for all model calls, from start (default 60)")
    p.add_argument("--model-parallel", type=int, default=runner.DEFAULT_MODEL_PARALLEL, metavar="N",
                   help="model calls at once (default 3; 1 = one after another)")
    p.add_argument("--logout", action="store_true", help="delete saved logins and exit")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        options = vars(parse_args(argv))
    except SystemExit as exc:
        # argparse exits 2 on a bad flag, but 2 means "briefing printed, something failed" here; --help stays 0.
        return 0 if exc.code in (0, None) else 1
    options["started"] = STARTED
    try:
        isatty = sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        isatty = False
    _, code = runner.run(options, os.environ, isatty)
    return code


if __name__ == "__main__":
    sys.exit(main())
