# data/

> Platform data that seat 34 collects. It is kept minimal and organised by system.

| Path | What | In git? |
|---|---|---|
| `platform/<system>/rest-me.json` | Who our login is (roles, allowed apps) | No |
| `platform/<system>/rest-schemas.json` | All entity schemas | No (the course forbids committing schemas) |
| `platform/<system>/rest-agent_tools.json` | The 13 agent tools | No |
| `platform/<system>/rest-display_locale.json` | Country, currency and date format | No |
| `platform/<system>/mcp-tools.json` | Our MCP tool list: name, risk, read-only flag, arguments | No |
| `platform/<system>/probe.json` | What each probe read returned: reachable or not, row count, field names (no values) | No |
| `platform/access-summary.md` | A table of the above for both systems | No |
| `platform/<system>/previous/` | The snapshot from the run before, kept by the sync script for comparison | No |
| `platform/<system>/version.json` | The platform version, if the platform reports one | No |
| `platform/changes-<date>.md` | What changed since the previous snapshot (tools, schemas, access, differences between systems) | No |

`<system>` is `suryodaya` or `keystone`.

**To regenerate everything and see what changed:** `uv run python scripts/platform_sync.py`. This needs `.env`; see `.env.example`. It only reads. Run it after every platform release notice.

The checked conclusions from this data live in the local platform notes; see [../docs/processed/platform/README.md](../docs/processed/platform/README.md). Add a new committed data file only when code needs it, and never put customer records in one.
