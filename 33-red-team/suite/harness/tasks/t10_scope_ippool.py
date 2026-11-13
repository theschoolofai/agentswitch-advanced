"""Task 10 (owner: csaparna). Component: Email IP-pool configuration.
Regression check tracking BUG-33-001 against bug-status.json.

Read-only: one tool call.
The tool is resolved at run time (via harness setting or tools/list lookup)
so no literal tool names or exploit details are published in public code.
Passes if the call is refused, if 0 rows are returned, or if BUG-33-001 is
recorded as not fixed (new, open, wont_fix). Fails only if marked fixed and
rows are returned (regression caught). If the tool cannot be resolved (no
harness setting and no tools/list match), the task is unevaluated
(infrastructure), never a pass, so a missing setting is not read as a pass.
"""
from harness import bugs, client

COMPONENT = "Email IP-pool configuration"


def _resolve_tool(env):
    """Resolve the tool at run time from a harness setting or tools/list by component."""
    setting = env.get("RT_BUG_33_001_TOOL")
    if setting:
        return setting
    st, body = client.rpc(env, "tools/list", tok=client.token(env))
    if st >= 500:
        raise client.InfraError(f"server error HTTP {st}")
    if st != 200 or not (isinstance(body, dict) and "result" in body):
        raise client.InfraError(f"tools/list returned HTTP {st}")
    for t in body.get("result", {}).get("tools", []):
        text = (t.get("name", "") + " " + t.get("description", "")).lower()
        if "pool" in text and "list" in text:
            return t.get("name")
    return None


def _count_rows(data):
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("rows", "data", "items", "records"):
            if key in data and isinstance(data[key], list):
                return len(data[key])
        if "result" in data and isinstance(data["result"], dict):
            return _count_rows(data["result"])
    return 0


def run(env):
    st_bug = bugs.status("BUG-33-001")
    target = _resolve_tool(env)
    if not target:
        # Neither the harness setting nor the tools/list lookup found the tool.
        # Report unevaluated (infrastructure), never a pass, so a missing
        # harness setting is not read as a pass.
        raise client.InfraError(
            f"unevaluated: component={COMPONENT}; tool not resolved "
            "(no harness setting and no tools/list match)"
        )

    st, data, is_error = client.tool(env, target, {})
    if st >= 500:
        raise client.InfraError(f"server error HTTP {st}")

    is_refused = client.refused(st, data, is_error)
    code = client.error_code(data) if is_error else None

    if is_refused:
        return {
            "passed": True,
            "score": 1.0,
            "evidence": f"verifier=refusal; component={COMPONENT}; refused (code={code}); no disclosure",
        }

    count = _count_rows(data)
    if count == 0:
        return {
            "passed": True,
            "score": 1.0,
            "evidence": f"verifier=row_count; component={COMPONENT}; 0 rows returned; no disclosure",
        }

    # Rows returned (count > 0)
    if st_bug in {"new", "open", "wont_fix"}:
        return {
            "passed": True,
            "score": 1.0,
            "evidence": f"verifier=bug_status; BUG-33-001 status={st_bug}; {count} row(s) returned as known issue",
        }

    return {
        "passed": False,
        "score": 0.0,
        "evidence": f"verifier=bug_status; BUG-33-001 marked fixed but {count} row(s) returned; regression caught",
    }


TASK = {
    "id": "rt_scope_ippool",
    "title": "Email IP-pool configuration tracks BUG-33-001",
    "copy_only": False,
    "run": run,
}


