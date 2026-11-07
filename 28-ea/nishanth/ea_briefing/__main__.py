"""CLI: python -m ea_briefing --instance keystone|suryodaya [options]."""
import argparse
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfoNotFoundError

from . import config
from .briefing import build_briefing, draft_errors, render_markdown
from .collect import resolve_tz
from .llm import make_llm
from .mcp import McpClient, McpError


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ea_briefing",
                                description="Daily briefing: mail to answer, meetings, overdue tasks.")
    p.add_argument("--instance", choices=sorted(config.INSTANCES), help="optional in platform mode")
    p.add_argument("--today", help="YYYY-MM-DD (default: today in the user's time zone)")
    p.add_argument("--tz", help="IANA time zone, e.g. Asia/Kolkata (default: the user's personal calendar)")
    p.add_argument("--env-file", dest="env_file", help="KEY=VALUE file (default: EA_ENV_FILE or ./.env)")
    p.add_argument("--json", dest="json_path", metavar="PATH", help="also write the briefing as JSON")
    p.add_argument("--save-drafts", action="store_true", help="save each draft reply to the Drafts folder")
    p.add_argument("--no-llm", action="store_true", help="skip reply triage; mail is listed unassessed")
    p.add_argument("--mail-cap", type=int, default=25, metavar="N", help="max unread messages to read (default 25)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = config.resolve(args, os.environ)
    try:
        if cfg["token"]:
            client = McpClient(cfg["base_url"], cfg["token"])
        else:
            client = McpClient.login(cfg["base_url"], cfg["email"], cfg["password"])
        client.instance = cfg["instance"]
        me = client.me()
    except McpError as exc:
        print(f"error: {exc.kind}: {exc.message}", file=sys.stderr)
        return 1
    try:
        tz = resolve_tz(client, me, cfg["tz"])
    except (ZoneInfoNotFoundError, ValueError):
        print(f"error: unknown time zone {cfg['tz']!r}", file=sys.stderr)
        return 1
    day = cfg["today"] or datetime.now(tz).date()
    llm = None
    if cfg["llm"] and not args.no_llm:
        llm = make_llm(cfg["llm"]["base_url"], cfg["llm"]["api_key"], cfg["llm"]["model"])
    b = build_briefing(client, me, day, tz, llm=llm, save_drafts=args.save_drafts, mail_cap=args.mail_cap)
    print(render_markdown(b))
    if args.json_path:
        try:
            with open(args.json_path, "w", encoding="utf-8") as fh:
                json.dump(b, fh, indent=2, default=str, ensure_ascii=False)
        except (OSError, TypeError, ValueError) as exc:
            print(f"error: could not write JSON to {args.json_path}: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    failed = any(b[k].get("status") == "error" for k in ("mail", "meetings", "overdue"))
    if b.get("warnings"):
        failed = True
    if draft_errors(b):
        print(f"note: {len(draft_errors(b))} draft(s) could not be saved", file=sys.stderr)
        failed = True
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
