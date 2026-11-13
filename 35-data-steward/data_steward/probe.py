"""Log in and list the MCP tools this seat can see. Read-only: initialize and tools/list, nothing else.

    uv run python -m data_steward.probe                      # both instances
    uv run python -m data_steward.probe --instance keystone

Prints tool counts per module. The full tool list (names, descriptions, input schemas) is platform-derived, so it
goes to local/tools-<instance>.json, which is git-ignored, never into the repository.
"""
import argparse
import json
from collections import Counter

from . import config
from .mcp_client import McpClient, Session
from .report import _write_private


def probe(instance: str) -> dict[str, dict]:
    tools = McpClient(Session(instance)).tools()
    config.LOCAL_DIR.mkdir(exist_ok=True)
    _write_private(config.LOCAL_DIR / f"tools-{instance}.json", json.dumps(tools, indent=2, sort_keys=True))
    return tools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instance", choices=sorted(config.INSTANCES), action="append")
    args = parser.parse_args(argv)
    failed = 0
    for instance in args.instance or sorted(config.INSTANCES):
        try:
            tools = probe(instance)
        except Exception as e:  # one system failing (network, bad reply) must not stop the probe of the other
            print(f"{instance}: FAILED {type(e).__name__}: {e}")
            failed += 1
            continue
        modules = Counter(name.split(".", 1)[0] for name in tools)
        print(f"{instance}: {len(tools)} tools -> local/tools-{instance}.json")
        for module, count in sorted(modules.items()):
            print(f"  {module}: {count}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
