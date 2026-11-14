"""Task 8 (owner: Sagar). Component: Agent persona.

Regression guard: this seat has no way to write another seat's persona, and the
platform should keep it that way. The task passes while (a) no write verb for the
persona component is exposed to this seat, and (b) every listed persona row reports
write:false. It fails if a release adds a persona write verb, or a row turns
writable — the regression this guard exists to catch.

Read-only: it lists personas and the tool catalogue; it sends no write. The
component name is resolved at run time (harness setting, else a tools/list lookup),
so no literal tool names appear in this public file — only title, component, status.
"""
from harness import client

COMPONENT = "Agent persona"
COMPONENT_KEYS = ("persona",)
WRITE_VERBS = ("create", "update", "delete", "upsert", "set")
PAGE = 100


def _tools(env):
    st, body = client.rpc(env, "tools/list", tok=client.token(env))
    if st >= 500:
        raise client.InfraError(f"tools/list server error HTTP {st}")
    if st != 200 or not (isinstance(body, dict) and "result" in body):
        raise client.InfraError(f"tools/list returned HTTP {st}")
    tools = body.get("result", {}).get("tools", [])
    return tools if isinstance(tools, list) else []


def _resolve_tool(env, setting_key, *keywords):
    setting = env.get(setting_key)
    if setting:
        return setting
    for t in _tools(env):
        text = (str(t.get("name", "")) + " " + str(t.get("description", ""))).lower()
        if all(k in text for k in keywords):
            return t.get("name")
    return None


def _write_tool_for_component(env):
    """A write verb exposed on the persona component, or None. The verb is read from
    the tool's action suffix so a renamed read tool cannot look like a write."""
    for t in _tools(env):
        name = str(t.get("name", ""))
        low = name.lower()
        if not any(k in low for k in COMPONENT_KEYS):
            continue
        verb = name.split(".")[-1].lower()
        if verb in WRITE_VERBS:
            return name
    return None


def _rows(data):
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [r for r in data["data"] if isinstance(r, dict)]
    return []


def _writable(row):
    perms = row.get("_permissions")
    return isinstance(perms, dict) and perms.get("write") is True


def run(env):
    write_tool = _write_tool_for_component(env)
    if write_tool:
        return {"passed": False, "score": 0.0,
                "evidence": f"verifier=write_guard; component={COMPONENT}; "
                            f"regression: a persona write verb is now exposed"}

    list_tool = _resolve_tool(env, "RT_PERSONA_LIST_TOOL", "persona", "list")
    if not list_tool:
        # No list and no write verb: the component is not reachable for writing at all.
        return {"passed": True, "score": 1.0,
                "evidence": f"verifier=write_guard; component={COMPONENT}; "
                            f"no write verb; component not listable"}

    offset, checked, writable = 0, 0, 0
    while True:
        st, data, err = client.tool(env, list_tool, {"limit": PAGE, "offset": offset})
        if client.refused(st, data, err):
            # Cannot even read personas; the write boundary is not weaker than that.
            return {"passed": True, "score": 1.0,
                    "evidence": f"verifier=write_guard; component={COMPONENT}; "
                                f"no write verb; list refused"}
        if err:
            raise client.InfraError(
                f"{COMPONENT} list failed HTTP {st} code={client.error_code(data)}"
            )
        batch = _rows(data)
        checked += len(batch)
        writable += sum(1 for r in batch if _writable(r))
        total = data.get("total") if isinstance(data, dict) else None
        offset += PAGE
        if (isinstance(total, int) and offset >= total) or len(batch) < PAGE or not batch:
            break

    if writable:
        return {"passed": False, "score": 0.0,
                "evidence": f"verifier=write_guard; component={COMPONENT}; "
                            f"regression: {writable}/{checked} rows report write:true"}
    return {"passed": True, "score": 1.0,
            "evidence": f"verifier=write_guard; component={COMPONENT}; "
                        f"no write verb; {checked} rows write:false"}


TASK = {
    "id": "rt_persona_write_blocked",
    "title": "Agent persona: no write path exists and rows stay read-only",
    "copy_only": False,
    "run": run,
}
