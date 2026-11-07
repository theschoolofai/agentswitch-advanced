# 0004 uv, Python 3.11, maintained libraries, ruff and mypy

- **Status:** Accepted, 7 Nov 2026
- **Context:** The course runner has Python 3.11. It installs packages with internet first, then runs offline. Earlier harnesses wasted effort on hand-written protocol code.
- **Decision:**
  - Install and run everything with **uv**. The lock file is committed. People run `uv sync`; the course runner's install step uses `uv sync --frozen`, so it installs exactly what is in the lock file.
  - Use maintained libraries rather than writing our own:
    - the official `mcp` SDK (MCP);
    - `httpx2` (REST; it is what the `mcp` SDK itself uses);
    - `pydantic` and `pydantic-settings`;
    - the `openai` SDK, added only when we first need a model.
  - Use `asyncio` where calls can run side by side, keeping concurrency low because the platform is slow.
  - Quality checks: `ruff format`, `ruff check`, `mypy --strict`, `pytest`.
- **Consequences:** One HTTP library, not two. The mcp SDK checks reply shapes strictly, so our client logs and tolerates a reply that breaks its own declared schema, instead of failing the whole call.
